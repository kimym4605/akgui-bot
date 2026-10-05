"""`/도박` - 악귀코인을 태우는 게임 3종 (🎰 슬롯 · 🎲 하이로우 · 🃏 블랙잭).

## 이게 왜 '소비처'인가

공정한 도박은 소비처가 **아니에요**. 사람끼리 걸면 코인이 옮겨다닐 뿐 총량은 그대로예요
(`/내전베팅`이 그래요). 여기서는 **하우스 몫(엣지)** 이 있어서 돌릴수록 코인이 줄어요.
배당·확률은 `utils/casino_games.py`에 있고, 거기 머리말에 왜 그 숫자인지 적어뒀어요.

## 안전장치

지갑 **중앙값이 3코인**인 서버라 변동성이 그대로 사고가 돼요. 그래서:
  - 1회 최대 5코인 · 하루 총 20코인 (출석·미션으로 하루면 회복되는 수준)
  - 환수율을 `/도박 현황`에 **그대로 공개**해요. 숨기면 "따려고" 하게 돼요
  - 잃은 걸 만회하라고 부추기는 문구는 쓰지 않아요

⚠️ 코인은 **베팅 시점에 바로 차감**하고, 결과가 나오면 돌려받을 몫만 다시 넣어요.
   반대로 하면(이기면 주고 지면 빼기) 중간에 봇이 죽었을 때 공짜 판이 돼요.
"""
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import casino_games as games
from utils import casino_store, coin_wallet
from utils.casino_store import DAILY_LIMIT, MAX_BET, MIN_BET
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

HOUSE_COLOR = 0x8B5CF6
WIN_COLOR = 0x57F287
LOSE_COLOR = 0x95A5A6

# 블랙잭 버튼이 살아있는 시간. 지나면 자동으로 '스탠드'로 정산해요
# (그냥 꺼지면 차감된 코인이 허공에 떠요).
BJ_TIMEOUT = 120


async def take_bet(interaction: discord.Interaction, amount: int) -> tuple[bool, str]:
    """한도 확인 → 코인 차감까지. (성공여부, 실패 사유 문구)."""
    if not (MIN_BET <= amount <= MAX_BET):
        return False, f"한 판에 걸 수 있는 건 **{MIN_BET}~{MAX_BET}코인**이에요."

    ok, wagered = await casino_store.try_wager(interaction.user.id, amount)
    if not ok:
        return False, (
            f"오늘 베팅 한도를 다 썼어요. (하루 **{DAILY_LIMIT}코인**, 지금까지 {wagered}코인)\n"
            "-# 한도는 매일 자정(한국시간)에 다시 차요."
        )

    if not await coin_wallet.spend(interaction.user.id, amount, reason="도박"):
        # 한도만 기록되고 판은 안 열렸으니 한도를 되돌려줘요.
        await casino_store.refund_wager(interaction.user.id, amount)
        balance = await coin_wallet.get_balance(interaction.user.id)
        return False, f"악귀코인이 부족해요. **{amount}개**가 필요한데 지금 **{balance}개** 갖고 있어요."

    return True, ""


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
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        # 버튼만 꺼버리면 차감된 코인이 허공에 떠요. 자동으로 스탠드 처리해서 정산해요.
        await self.finish(None)

    @discord.ui.button(label="히트", emoji="🂠", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.append(self.deck.pop())
        if games.hand_value(self.player) >= 21:
            await self.finish(interaction)
            return
        await interaction.response.edit_message(embed=self.table_embed(reveal=False), view=self)

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finish(interaction)


class Casino(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(name="도박", description="악귀코인을 걸고 하는 게임이에요. (하우스 몫이 있어요)")

    # ------------------------------------------------------------------
    @group.command(name="슬롯", description="릴 3개를 돌려요. 두 개 일치=본전, 세 개 일치=4~7배")
    @app_commands.describe(금액=f"{MIN_BET}~{MAX_BET}코인")
    @restrict_to_channel("casino")
    async def slot(self, interaction: discord.Interaction, 금액: int):
        await interaction.response.defer()
        ok, error = await take_bet(interaction, 금액)
        if not ok:
            await interaction.followup.send(error, ephemeral=True)
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
    async def highlow(self, interaction: discord.Interaction, 금액: int, 선택: str):
        await interaction.response.defer()
        ok, error = await take_bet(interaction, 금액)
        if not ok:
            await interaction.followup.send(error, ephemeral=True)
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
    async def blackjack(self, interaction: discord.Interaction, 금액: int):
        await interaction.response.defer()
        ok, error = await take_bet(interaction, 금액)
        if not ok:
            await interaction.followup.send(error, ephemeral=True)
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

        view.message = await interaction.followup.send(embed=view.table_embed(reveal=False),
                                                       view=view, wait=True)

    # ------------------------------------------------------------------
    @group.command(name="현황", description="오늘 남은 베팅 한도와 각 게임의 환수율을 봐요.")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wagered = await casino_store.wagered_today(interaction.user.id)
        balance = await coin_wallet.get_balance(interaction.user.id)

        embed = discord.Embed(
            title="🎲 도박 현황",
            description=(
                f"오늘 건 금액: **{wagered}/{DAILY_LIMIT}코인** "
                f"(남은 한도 **{max(0, DAILY_LIMIT - wagered)}코인**)\n"
                f"내 악귀코인: **{balance}개** · 한 판 {MIN_BET}~{MAX_BET}코인"
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
            text="오래 하면 잃는 쪽이 정상이에요. 한도는 매일 자정(한국시간)에 다시 차요."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Casino(bot))
