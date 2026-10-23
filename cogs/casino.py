"""`/도박` - 악귀코인을 태우는 게임 3종 (🎰 슬롯 · 🎲 하이로우 · 🃏 블랙잭).

## 이게 왜 '소비처'인가

공정한 도박은 소비처가 **아니에요**. 사람끼리 걸면 코인이 옮겨다닐 뿐 총량은 그대로예요
(`/내전베팅`이 그래요). 여기서는 **하우스 몫(엣지)** 이 있어서 돌릴수록 코인이 줄어요.
배당·확률은 `utils/casino_games.py`에 있고, 거기 머리말에 왜 그 숫자인지 적어뒀어요.

## 안전장치

지갑 **중앙값이 3코인**인 서버라 변동성이 그대로 사고가 돼요. 그래서:
  - 1회 최대 5코인 · 하루 총 20코인 (출석·미션으로 하루면 회복되는 수준)
  - 🔓 더 걸고 싶으면 코인을 내고 **+10코인**씩 늘릴 수 있는데, **살수록 값이 올라가요**
    (5 → 10 → 15 …). 값이 오르는 것 자체가 제동이에요 — `casino_store.extend_price` 참고.
    한도에 막힌 **그 자리에서** 버튼으로 파는 게 핵심이에요 — `send_bet_error` 주석 참고.
    🚨 **몇 번째 연장인지·이번 값·누적 지출을 반드시 같이 보여줘요.**
  - 환수율을 `/도박 현황`에 **그대로 공개**해요. 숨기면 "따려고" 하게 돼요
  - 잃은 걸 만회하라고 부추기는 문구는 쓰지 않아요

⚠️ 코인은 **베팅 시점에 바로 차감**하고, 결과가 나오면 돌려받을 몫만 다시 넣어요.
   반대로 하면(이기면 주고 지면 빼기) 중간에 봇이 죽었을 때 공짜 판이 돼요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs import mission
from utils import adult_check
from utils import casino_games as games
from utils import casino_store, coin_wallet
from utils.casino_store import DAILY_LIMIT, EXTEND_BONUS, MAX_BET, MIN_BET
from utils.channel_check import restrict_to_channel
from utils.interaction_ack import ack

log = logging.getLogger(__name__)

HOUSE_COLOR = 0x8B5CF6
WIN_COLOR = 0x57F287
LOSE_COLOR = 0x95A5A6

# 블랙잭 버튼이 살아있는 시간. 지나면 자동으로 '스탠드'로 정산해요
# (그냥 꺼지면 차감된 코인이 허공에 떠요).
BJ_TIMEOUT = 120

# 🔓 한도 연장권 버튼이 살아있는 시간. 막힌 자리에서 바로 누르는 거라 짧아도 돼요.
EXTEND_VIEW_TIMEOUT = 120

# 🚨 `coin_log`에 남는 이름. **"도박"으로 시작하면 안 돼요.**
#    `scripts/report_economy.py`가 `도박`으로 시작하는 spend를 **베팅액**으로 세서,
#    "도박한도연장"이라고 쓰면 베팅총액에 섞이고 환급과의 차액(=실제 소각)이 틀어져요.
#    연장권은 돌아오지 않는 **순수 소각**이라 따로 잡혀야 해요.
EXTEND_NOTE = "한도연장"
# 🚨 🔓(하루 총액)와 🎲(1회)를 **구분**해요. 같은 note를 쓰면 경제 리포트에서 어느 쪽이
#    팔리는지 알 수 없어요. 둘 다 "도박"으로 시작하지 않는 것도 위와 같은 이유예요.
BET_EXTEND_NOTE = "베팅한도연장"

# 🔞 성인만 쓸 수 있어요. `/채널설정`으로 도박장 채널에 묶더라도 **명령어 자체를 막지 않으면
# 다른 채널에서 그냥 쓸 수 있어요.** 채널을 가리는 것만으로는 잠금이 안 돼요.
#
# ⭐ 판정은 `utils/adult_check.py`로 옮겼어요(2026-10-23). 🎰 도박 미션 배정도 **같은
#    기준**을 봐야 하는데, `mission_store`가 여기서 가져오면 순환 import가 돼요.
#    "미션은 받았는데 명령어가 막힌다"가 제일 나쁜 조합이라 기준은 꼭 한 벌이어야 해요.
_is_adult = adult_check.is_adult


def adult_only():
    """성인 역할이 없으면 조용히 거절해요. 거절 안내는 본인에게만 보여요.

    `bot.tree.error`가 CheckFailure를 '이미 안내한 의도된 거절'로 보고 넘겨요
    (채널 제한·운영진 제한과 같은 방식이에요)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if _is_adult(interaction.user):
            return True
        log.info("🔞 도박 사용을 막았어요(성인 역할 없음): user=%s", interaction.user)
        await interaction.response.send_message(
            "🔞 `/도박`은 **성인 인증을 받은 분**만 쓸 수 있어요.\n"
            "-# `/성인인증`으로 신청하면 관리진 승인 후 역할이 붙어요.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)


async def take_bet(interaction: discord.Interaction, amount: int) -> tuple[bool, str, bool]:
    """한도 확인 → 코인 차감까지. (성공여부, 실패 사유 문구, 한도에 막혔는지).

    세 번째 값이 True면 호출부가 🔓 연장권 버튼을 같이 띄워요. "코인이 부족해서" 실패한
    경우와 구분해야 해요 - 코인이 없는 사람에게 5코인짜리 연장권을 권하면 안 되니까요.

    ⚠️ 1회 한도는 **사람마다 달라요**(2026-10-17, 🎲 베팅 한도 연장). 상수 `MAX_BET`을
    그대로 쓰면 연장권을 산 사람도 5코인에 막혀요 - 반드시 `bet_limit_today`로 읽어요."""
    bet_limit, bet_times = await casino_store.bet_limit_today(interaction.user.id)
    if not (MIN_BET <= amount <= bet_limit):
        tail = ""
        if amount > bet_limit and bet_times < casino_store.BET_EXTEND_MAX:
            tail = (f"\n-# 🎲 한 판 한도를 늘리려면 "
                    f"**{casino_store.bet_extend_price(bet_times)}코인** "
                    f"(+{casino_store.BET_EXTEND_BONUS}코인 · 영구 · `/도박 한도늘리기`)")
        return False, (
            f"한 판에 걸 수 있는 건 **{MIN_BET}~{bet_limit}코인**이에요.{tail}"
        ), False

    ok, wagered = await casino_store.try_wager(interaction.user.id, amount)
    if not ok:
        _, limit = await casino_store.state_today(interaction.user.id)
        return False, (
            f"오늘 베팅 한도를 다 썼어요. (하루 **{limit}코인**, 지금까지 {wagered}코인)\n"
            "-# 건 금액은 매일 자정(한국시간)에 0으로 돌아가요."
        ), True

    if not await coin_wallet.spend(interaction.user.id, amount, reason="도박"):
        # 한도만 기록되고 판은 안 열렸으니 한도를 되돌려줘요.
        await casino_store.refund_wager(interaction.user.id, amount)
        balance = await coin_wallet.get_balance(interaction.user.id)
        return False, (
            f"악귀코인이 부족해요. **{amount}개**가 필요한데 지금 **{balance}개** 갖고 있어요."
        ), False

    # 🎯 🎰 "한 판 걸어보기" 미션 (2026-10-23). **차감까지 끝난 뒤**에 불러요.
    #
    # ⭐ 게임이 4종(`/도박` 슬롯·블랙잭·하이로우…)인데 베팅은 전부 이 함수를 지나요.
    #    그래서 훅이 여기 하나만 있으면 돼요.
    # 🚨 `COMMAND_MISSIONS`로는 못 해요 - 한도 초과나 잔액 부족으로 **위에서 return된
    #    경우에도** 명령어 자체는 정상 종료되니까요(= 안 걸고 공짜로 깸).
    await mission.on_action(
        interaction.user.id, "play_gamble", interaction.channel, interaction.user
    )

    return True, "", False


async def send_bet_error(interaction: discord.Interaction, error: str, limit_reached: bool) -> None:
    """베팅을 못 받은 이유를 본인에게만 알려요. 한도 때문이면 🔓 연장권 버튼을 같이 붙여요.

    🚨 연장권은 `/악귀상점`에 두지 않았어요. 2026-10-06 측정에서 상점에 넣은 소비처 3종이
    **살 수 있는 사람이 18~37명인데도 구매 0건**이었어요 - 구매력이 아니라 발견이 문제였죠.
    그래서 **막힌 바로 그 자리**에서 권해요."""
    if not limit_reached:
        await interaction.followup.send(error, ephemeral=True)
        return
    # 값이 살수록 오르니, 버튼에 **다음 값**을 찍으려면 지금까지 몇 번 샀는지 알아야 해요.
    times = await casino_store.extend_count(interaction.user.id)
    view = ExtendLimitView(interaction.user.id, times)
    error += (f"\n-# 🔓 한도를 늘리려면 **{casino_store.extend_price(times)}코인** "
              "(한 번 늘리면 계속 유지돼요 · 살수록 5코인씩 비싸져요)")
    view.message = await interaction.followup.send(error, view=view, ephemeral=True, wait=True)


class ExtendLimitView(discord.ui.View):
    """🔓 한도 연장권 버튼. 본인에게만 보이는(ephemeral) 거절 메시지에 붙어요.

    ⚠️ 이건 **영속 뷰가 아니에요**(`timeout` 있음). 누를 사람이 바로 앞에 있는 상황이라
    짧게 살아도 되고, 영속으로 만들면 봇 재시작 뒤에 "어제의 거절 메시지"로 막히지도 않은
    한도를 미리 쌓아둘 수 있게 돼요(2026-10-14부터 한도가 영구로 남으니 더 그래요)."""

    def __init__(self, user_id: int, times_so_far: int = 0):
        super().__init__(timeout=EXTEND_VIEW_TIMEOUT)
        self.user_id = user_id
        self.times_so_far = times_so_far
        self.message: discord.Message | None = None
        # 🚨 값이 살수록 올라가니(5 → 10 → 15 …) **라벨도 그때그때 바꿔야** 해요. 데코레이터에
        #    박아두면 몇 번째든 "5코인"으로 보여서, 실제로 빠지는 금액과 어긋나요.
        self.extend.label = (f"🔓 한도 +{EXTEND_BONUS} 늘리기 "
                             f"({casino_store.extend_price(times_so_far)}코인)")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ephemeral이라 사실 본인만 보이지만, 뷰 하나가 한 사람 것임을 여기서 못 박아둬요.
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 누를 수 있어요.", ephemeral=True)
            return False
        return True

    async def _disable(self) -> None:
        """한 번 쓰면 버튼을 꺼요(두 번 눌러도 거절되지만, 눌리는 자체가 헷갈려요)."""
        for item in self.children:
            item.disabled = True
        self.stop()
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass          # 메시지가 이미 사라졌어도 한도 연장 자체는 끝난 상태예요

    async def on_timeout(self) -> None:
        await self._disable()

    @discord.ui.button(style=discord.ButtonStyle.primary)   # label은 __init__에서 값에 맞춰 넣어요
    async def extend(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        # 🚨 **자리를 먼저 선점**해요. 코인은 그다음에 빼고, 결제가 실패하면 되돌려요.
        ok, limit, times = await casino_store.extend_limit(self.user_id)
        if not ok:
            await interaction.followup.send(
                "한도를 늘리지 못했어요. 잠시 뒤 다시 해주세요.", ephemeral=True
            )
            await self._disable()
            return

        # ⚠️ 값은 **선점 결과(= 실제 몇 번째인지)** 로 정해요. 버튼을 띄운 뒤에 다른 창에서
        #    한 번 더 샀다면 라벨보다 비쌀 수 있는데, 그래도 "실제 N번째 값"이 맞는 금액이에요.
        #    그래서 아래 안내에 **이번에 낸 값**을 분명히 적어요.
        price = casino_store.extend_price(times - 1)

        if not await coin_wallet.spend(self.user_id, price, reason=EXTEND_NOTE):
            # 선점만 되고 결제가 안 됐으니 **되돌려요**. 안 그러면 공짜로 한도가 늘어나요.
            await casino_store.undo_extend(self.user_id)
            balance = await coin_wallet.get_balance(self.user_id)
            await interaction.followup.send(
                f"악귀코인이 부족해요. **통산 {times}번째 연장은 {price}코인**인데 지금 "
                f"**{balance}개** 갖고 있어요.\n"
                "-# 연장은 살수록 5코인씩 비싸져요 · 출석·미션으로 모을 수 있어요.",
                ephemeral=True,
            )
            await self._disable()
            return

        wagered, limit = await casino_store.state_today(self.user_id)
        balance = await coin_wallet.get_balance(self.user_id)
        log.info("🔓 도박 한도 연장: %s %d코인 → 한도 %d코인 (통산 %d번째)",
                 self.user_id, price, limit, times)
        await interaction.followup.send(
            f"🔓 하루 한도를 **{limit}코인**으로 늘렸어요. **다음 날에도 그대로예요.**\n"
            f"(오늘 {wagered}코인 걸었고 / 남은 한도 **{max(0, limit - wagered)}코인**)\n"
            # 🚨 상한이 코드에 없으니 **숫자로 보여주는 게 제동**이에요. 이 두 줄을 빼면
            #    자기도 모르게 지갑을 비우게 돼요.
            f"통산 **{times}번째** 연장 · 이번에 **{price}코인** · "
            f"연장에만 쓴 코인 **{casino_store.extend_spent(times)}개**\n"
            f"남은 악귀코인 **{balance}개** · 다음 연장은 "
            f"**{casino_store.extend_price(times)}코인**이에요\n"
            "-# 쓴 코인은 돌아오지 않아요. 값은 살수록 5코인씩 올라가요.",
            ephemeral=True,
        )
        await self._disable()


async def refund_bet(user_id: int, amount: int) -> None:
    """게임이 시작도 못 했을 때 **코인과 하루 한도를 둘 다** 되돌려요.

    둘 중 하나만 돌려주면 "코인은 돌아왔는데 한도는 줄어든 채"가 돼요(2026-10-05 신고 내용이
    정확히 그거였어요 — 15코인만 썼는데 한도는 20으로 찍힘)."""
    await coin_wallet.add(user_id, amount, reason="도박 환불")
    await casino_store.refund_wager(user_id, amount)


async def pay_out(user_id: int, bet: int, multiplier: int) -> tuple[int, int]:
    """돌려받을 금액을 넣고 (받은 금액, 잔액). multiplier는 **총 반환 배수**예요(0이면 꽝)."""
    payout = bet * multiplier
    if payout > 0:
        balance = await coin_wallet.add(user_id, payout, reason="도박 당첨")
    else:
        balance = await coin_wallet.get_balance(user_id)
    return payout, balance


def result_line(bet: int, payout: int, balance: int) -> str:
    net = payout - bet
    if net > 0:
        head = f"🟢 **+{net}코인**"
    elif net == 0:
        head = "⚪ **본전**"
    else:
        head = f"🔴 **{net}코인**"
    return f"{head}  (건 돈 {bet} · 받은 돈 {payout} · 남은 코인 **{balance}개**)"


class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Casino", user_id: int, bet: int, deck: list[int],
                 player: list[int], dealer: list[int]):
        super().__init__(timeout=BJ_TIMEOUT)
        self.cog = cog
        self.user_id = user_id
        self.bet = bet
        self.deck = deck
        self.player = player
        self.dealer = dealer
        self.message: discord.Message | None = None
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인 판만 만질 수 있어요.", ephemeral=True)
            return False
        return True

    def table_embed(self, *, reveal: bool, note: str = "", color: int = HOUSE_COLOR) -> discord.Embed:
        dealer_line = (
            f"{games.hand_label(self.dealer)}  (**{games.hand_value(self.dealer)}**)"
            if reveal else
            f"{games.hand_label(self.dealer[:1])} `?`"
        )
        embed = discord.Embed(title="🃏 블랙잭", color=color)
        embed.add_field(name="딜러", value=dealer_line, inline=False)
        embed.add_field(
            name="나",
            value=f"{games.hand_label(self.player)}  (**{games.hand_value(self.player)}**)",
            inline=False,
        )
        if note:
            embed.description = note
        embed.set_footer(text=f"베팅 {self.bet}코인 · 딜러는 {games.BJ_DEALER_STANDS_AT} 이상이면 멈춰요")
        return embed

    async def finish(self, interaction: discord.Interaction | None):
        """딜러를 돌리고 정산해요. interaction이 None이면 타임아웃 자동 정산이에요."""
        if self.done:
            return
        self.done = True
        self.stop()

        if games.hand_value(self.player) <= 21:
            games.dealer_play(self.dealer, self.deck)
        multiplier, note = games.settle_blackjack(self.player, self.dealer)
        payout, balance = await pay_out(self.user_id, self.bet, multiplier)

        color = WIN_COLOR if payout > self.bet else (HOUSE_COLOR if payout == self.bet else LOSE_COLOR)
        embed = self.table_embed(reveal=True, note=note, color=color)
        embed.add_field(name="결과", value=result_line(self.bet, payout, balance), inline=False)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        log.info("🃏 블랙잭: %s %d코인 → %d코인", self.user_id, self.bet, payout)
        if interaction is not None:
            # 🚨 `edit_original_response`예요. 부르는 쪽(`hit`·`stand`)이 **이미 `ack`로
            #    받아둔** 상호작용이라 `response.*`를 다시 쓸 수 없어요.
            #
            #    왜 받아두나: 바로 위 `pay_out()`이 Atlas를 다녀와요. 3초를 넘기면
            #    배당은 들어갔는데 **화면이 안 바뀌고**, `self.done`이 True라 다시
            #    눌러도 아무 일이 없어서 **이겼는지 졌는지 영구히 못 봐요.**
            await interaction.edit_original_response(embed=embed, view=self)
        elif self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        # 버튼만 꺼버리면 차감된 코인이 허공에 떠요. 자동으로 스탠드 처리해서 정산해요.
        await self.finish(None)

    # ⚠️ 여기 이모지로 `🂠`(U+1F0A0 카드 뒷면)을 썼다가 **블랙잭이 통째로 터졌어요**
    # (2026-10-05). 유니코드 '카드' 블록 문자는 생긴 건 이모지 같아도 디스코드가
    # 이모지로 안 받아줘요 → `400 Invalid Form Body: components.0.components.0.emoji.name`.
    # 버튼이 필요 없는 '처음부터 21' 판만 성공해서 더 늦게 발견됐어요.
    @discord.ui.button(label="히트", emoji="➕", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🚨 **카드를 뽑기 전에** 받아둬요. 못 받으면 덱만 소모되고 유저는 그 카드를
        #    영원히 못 봐요(판은 계속 돌아가는데 화면이 한 장 뒤처져요).
        #    인자 없는 `ack`라 화면은 그대로 있어요. -> utils/interaction_ack.py
        if not await ack(interaction):
            return

        self.player.append(self.deck.pop())
        if games.hand_value(self.player) >= 21:
            await self.finish(interaction)
            return
        await interaction.edit_original_response(embed=self.table_embed(reveal=False), view=self)

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🚨 `finish`가 `pay_out()`으로 Atlas를 다녀와요. 먼저 받아둬야 해요.
        #    ⚠️ 못 받았으면 정산하지 말고 빠져나와요 - `on_timeout`이 자동 정산하니
        #    코인이 허공에 뜨지 않아요.
        if not await ack(interaction):
            return
        await self.finish(interaction)


class Casino(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(name="도박", description="악귀코인을 걸고 하는 게임이에요. (하우스 몫이 있어요)")

    # ------------------------------------------------------------------
    @group.command(name="슬롯", description="릴 3개를 돌려요. 두 개 일치=본전, 세 개 일치=4~7배")
    @app_commands.describe(금액=f"{MIN_BET}~{MAX_BET}코인")
    @restrict_to_channel("casino")
    @adult_only()
    async def slot(self, interaction: discord.Interaction, 금액: int):
        await interaction.response.defer()
        ok, error, limit_reached = await take_bet(interaction, 금액)
        if not ok:
            await send_bet_error(interaction, error, limit_reached)
            return

        symbols, multiplier, note = games.spin_slot()
        payout, balance = await pay_out(interaction.user.id, 금액, multiplier)

        embed = discord.Embed(
            title="🎰 슬롯",
            description=f"# {'  '.join(symbols)}\n{note}",
            color=WIN_COLOR if payout > 금액 else (HOUSE_COLOR if payout == 금액 else LOSE_COLOR),
        )
        embed.add_field(name="결과", value=result_line(금액, payout, balance), inline=False)
        await interaction.followup.send(embed=embed)
        log.info("🎰 슬롯: %s %d코인 → %d코인", interaction.user.id, 금액, payout)

    # ------------------------------------------------------------------
    @group.command(name="하이로우", description="1~100 중 하나를 굴려요. 높다(56↑) / 낮다(45↓) 맞히면 2배")
    @app_commands.describe(금액=f"{MIN_BET}~{MAX_BET}코인", 선택="높다 또는 낮다")
    @app_commands.choices(선택=[
        app_commands.Choice(name="⬆️ 높다 (56~100)", value="high"),
        app_commands.Choice(name="⬇️ 낮다 (1~45)", value="low"),
    ])
    @restrict_to_channel("casino")
    @adult_only()
    async def highlow(self, interaction: discord.Interaction, 금액: int, 선택: str):
        await interaction.response.defer()
        ok, error, limit_reached = await take_bet(interaction, 금액)
        if not ok:
            await send_bet_error(interaction, error, limit_reached)
            return

        number, multiplier, note = games.roll_highlow(선택)
        payout, balance = await pay_out(interaction.user.id, 금액, multiplier)

        picked = "⬆️ 높다" if 선택 == "high" else "⬇️ 낮다"
        embed = discord.Embed(
            title="🎲 하이로우",
            description=f"고른 쪽: {picked}\n# {number}\n{note}",
            color=WIN_COLOR if payout > 금액 else LOSE_COLOR,
        )
        embed.add_field(name="결과", value=result_line(금액, payout, balance), inline=False)
        embed.set_footer(
            text=f"{games.HIGHLOW_LOW_MAX + 1}~{games.HIGHLOW_HIGH_MIN - 1}은 하우스 몫이에요"
        )
        await interaction.followup.send(embed=embed)
        log.info("🎲 하이로우: %s %d코인 → %d코인", interaction.user.id, 금액, payout)

    # ------------------------------------------------------------------
    @group.command(name="블랙잭", description="딜러와 21 승부. 무승부는 돌려드려요")
    @app_commands.describe(금액=f"{MIN_BET}~{MAX_BET}코인")
    @restrict_to_channel("casino")
    @adult_only()
    async def blackjack(self, interaction: discord.Interaction, 금액: int):
        await interaction.response.defer()
        ok, error, limit_reached = await take_bet(interaction, 금액)
        if not ok:
            await send_bet_error(interaction, error, limit_reached)
            return

        deck = games.new_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        view = BlackjackView(self, interaction.user.id, 금액, deck, player, dealer)

        # 처음부터 21이면 버튼을 띄울 이유가 없어요. 바로 정산해요.
        if games.hand_value(player) == 21:
            view.done = True
            games.dealer_play(dealer, deck)
            multiplier, note = games.settle_blackjack(player, dealer)
            payout, balance = await pay_out(interaction.user.id, 금액, multiplier)
            embed = view.table_embed(reveal=True, note=note,
                                     color=WIN_COLOR if payout > 금액 else HOUSE_COLOR)
            embed.add_field(name="결과", value=result_line(금액, payout, balance), inline=False)
            await interaction.followup.send(embed=embed)
            log.info("🃏 블랙잭(즉시): %s %d코인 → %d코인", interaction.user.id, 금액, payout)
            return

        # 🚨 판을 띄우지 못하면 **코인과 한도를 반드시 돌려줘야** 해요. 코인은 이미 빠진
        # 뒤라, 여기서 터지면 유저는 하지도 않은 판에 돈을 낸 셈이 돼요.
        # 2026-10-05에 실제로 그랬어요 — 버튼 이모지가 잘못돼서 디스코드가 400을 냈고,
        # 한 사람이 5코인과 하루 한도 5를 날렸어요(그걸로 이 버그를 발견했어요).
        try:
            view.message = await interaction.followup.send(
                embed=view.table_embed(reveal=False), view=view, wait=True
            )
        except discord.HTTPException:
            view.done = True
            view.stop()
            await refund_bet(interaction.user.id, 금액)
            log.exception("🃏 블랙잭 판을 띄우지 못했어요 — 코인·한도를 돌려줬어요 (user=%s)",
                          interaction.user.id)
            await interaction.followup.send(
                "⚠️ 판을 여는 데 실패했어요. **건 코인과 오늘 한도는 돌려드렸어요.** 다시 시도해주세요.",
                ephemeral=True,
            )

    # ------------------------------------------------------------------
    @group.command(name="한도늘리기",
                   description="한 판에 걸 수 있는 금액을 코인으로 올려요. (영구)")
    @adult_only()
    async def extend_bet(self, interaction: discord.Interaction):
        """🎲 **1회** 베팅 한도를 올려요. 🔓 하루 한도 연장권과는 다른 상품이에요.

        ⭐ 이건 **발행에 영향이 없는 순수 소각**이에요. 하루 총액은 그대로라 걸 수 있는
        돈의 총량이 안 늘고 한 판의 크기만 커져요. 기본 한도를 그냥 올렸다면 🔓 연장권
        수요가 죽었을 텐데(2026-10-17 실측으로 도박 소각의 9할이 거기예요 - 연장권
        175코인 vs 게임 순소각 19코인), 이 방식은 소각처를 **없애지 않고 하나 더** 만들어요.
        """
        await interaction.response.defer(ephemeral=True)
        uid = interaction.user.id
        bet_limit, times = await casino_store.bet_limit_today(uid)

        if times >= casino_store.BET_EXTEND_MAX:
            await interaction.followup.send(
                f"이미 최대예요. 한 판 **{bet_limit}코인**까지 걸 수 있어요.\n"
                f"-# 통산 {times}번 늘렸고 연장에만 "
                f"**{casino_store.bet_extend_spent(times)}코인** 썼어요.",
                ephemeral=True)
            return

        # 🚨 **하루 총 한도를 넘는 1회 한도는 팔지 않아요.**
        #
        # 한 판에 걸 수 있는 돈이 하루치보다 커지면 그 초과분은 영원히 못 써요(하루 한도가
        # 먼저 막으니까요). 그대로 뒀다면 4·5번째 연장(40+50=90코인)을 사고도 체감이
        # 전혀 없어서 "돈만 받고 아무것도 안 해줬다"가 돼요. 테스트가 이걸 잡았어요.
        #
        # 대신 🔓로 하루 한도를 먼저 올리라고 안내해요 - 두 상품이 서로를 끌어주는
        # 구조가 돼서 소각처가 둘 다 살아요.
        _, daily_limit = await casino_store.state_today(uid)
        if casino_store.bet_limit_of(times + 1) > daily_limit:
            ext_times = await casino_store.extend_count(uid)
            await interaction.followup.send(
                f"하루 총 한도(**{daily_limit}코인**)보다 큰 한 판 한도는 살 수 없어요.\n"
                f"한 판을 **{casino_store.bet_limit_of(times + 1)}코인**까지 올리려면 "
                f"하루 한도를 먼저 늘려주세요.\n"
                f"-# 🔓 하루 한도 +{casino_store.EXTEND_BONUS}는 "
                f"**{casino_store.extend_price(ext_times)}코인** "
                f"(`/도박 현황`에서 한도를 다 쓰면 버튼이 떠요)",
                ephemeral=True)
            return

        price = casino_store.bet_extend_price(times)

        # 🚨 자리를 **먼저** 잡고 코인을 빼요. 반대로 하면 차감은 됐는데 증가가 실패했을 때
        #    코인만 사라져요. 차감이 실패하면 undo로 되돌려서 공짜 연장을 막아요.
        ok, new_limit, new_times = await casino_store.extend_bet_limit(uid)
        if not ok:
            await interaction.followup.send(
                "지금은 늘릴 수 없어요. 잠시 후 다시 시도해주세요.", ephemeral=True)
            return

        if not await coin_wallet.spend(uid, price, reason=BET_EXTEND_NOTE):
            await casino_store.undo_bet_extend(uid)
            balance = await coin_wallet.get_balance(uid)
            await interaction.followup.send(
                f"악귀코인이 부족해요. **통산 {new_times}번째 연장은 {price}코인**인데 "
                f"지금 **{balance}개** 있어요.\n"
                f"-# 연장은 살수록 {casino_store.BET_EXTEND_BASE_PRICE}코인씩 비싸져요.",
                ephemeral=True)
            return

        balance = await coin_wallet.get_balance(uid)
        log.info("🎲 1회 베팅 한도 연장: %s %d코인 → 한 판 %d코인 (통산 %d번째)",
                 uid, price, new_limit, new_times)

        # 🚨 몇 번째인지·이번 값·누적 지출을 **반드시** 같이 보여줘요. 값이 오르는 게
        #    유일한 제동이라, 사는 사람이 얼마를 쓰고 있는지 알아야 해요(🔓와 같은 규칙).
        nxt = (f"다음 연장은 **{casino_store.bet_extend_price(new_times)}코인**이에요"
               if new_times < casino_store.BET_EXTEND_MAX else "**이제 최대예요**")
        await interaction.followup.send(
            f"🎲 한 판 한도를 **{new_limit}코인**으로 늘렸어요! (영구)\n"
            f"통산 **{new_times}번째** 연장 · 이번에 **{price}코인** · "
            f"연장에만 쓴 코인 **{casino_store.bet_extend_spent(new_times)}개**\n"
            f"남은 악귀코인 **{balance}개** · {nxt}\n"
            f"-# 하루 **총** 한도는 그대로예요 — 그쪽은 🔓 로 늘려요.",
            ephemeral=True)

    @group.command(name="현황", description="오늘 남은 베팅 한도와 각 게임의 환수율을 봐요.")
    @adult_only()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wagered, limit = await casino_store.state_today(interaction.user.id)
        balance = await coin_wallet.get_balance(interaction.user.id)
        times = await casino_store.extend_count(interaction.user.id)
        bet_limit, bet_times = await casino_store.bet_limit_today(interaction.user.id)

        embed = discord.Embed(
            title="🎲 도박 현황",
            description=(
                f"오늘 건 금액: **{wagered}/{limit}코인** "
                f"(남은 한도 **{max(0, limit - wagered)}코인**)"
                + (f"  🔓 통산 {times}번 연장 ({casino_store.extend_spent(times)}코인)"
                   if times else "")
                + f"\n내 악귀코인: **{balance}개** · 한 판 **{MIN_BET}~{bet_limit}코인**"
                + (f"  🎲 통산 {bet_times}번 연장 "
                   f"({casino_store.bet_extend_spent(bet_times)}코인)" if bet_times else "")
            ),
            color=HOUSE_COLOR,
        )
        # 환수율을 숨기지 않고 그대로 보여줘요. 기대값이 마이너스라는 걸 알고 하는 게 맞아요.
        embed.add_field(
            name="환수율 (건 돈 대비 평균 돌려받는 비율)",
            value=(
                f"🎰 슬롯 **{games.slot_rtp() * 100:.0f}%** — "
                f"두 개 일치 본전 · 세 개 일치 {games.SLOT_SYMBOLS[0][1]}~{games.SLOT_SYMBOLS[-1][1]}배\n"
                f"🎲 하이로우 **{games.highlow_rtp() * 100:.0f}%** — "
                f"{games.HIGHLOW_LOW_MAX + 1}~{games.HIGHLOW_HIGH_MIN - 1}은 하우스 몫\n"
                f"🃏 블랙잭 **약 92%** — 무승부는 반환, 블랙잭은 {games.BJ_BLACKJACK_PAYOUT}배"
            ),
            inline=False,
        )
        embed.set_footer(
            text="오래 하면 잃는 쪽이 정상이에요. 건 금액은 매일 자정(한국시간)에 0으로 돌아가고, "
                 "🔓로 늘린 한도는 다음 날에도 유지돼요."
        )

        # 한도를 다 썼으면 여기서도 바로 늘릴 수 있게 해요.
        if wagered >= limit:
            view = ExtendLimitView(interaction.user.id, times)
            view.message = await interaction.followup.send(
                embed=embed, view=view, ephemeral=True, wait=True
            )
            return
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Casino(bot))
