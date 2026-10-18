"""🎣 낚시 - 찌를 던져 물고기를 낚고, 어항에 모았다가 팔아 코인을 벌어요.

## 🚨 발행 상한이 **없어요** (2026-10-17 5차)

낚시하려면 `/악귀상점`에서 **낚시대**를 사야 해요(`ROD_PRICE`코인 · 내구도 10회).
**몇 개든 살 수 있어요** - 하루 제한을 풀었거든요(4차, 사용자 결정).

    낚시대 1개: 수입 14.13코인 − 값 10코인 = 순이익 **+4.13**

4차까지는 무제한을 **"1개당 순이익 ≈ 0"**(+0.21)으로 버텼어요. 5차에서 사용자가
"가격이 짜다"고 해서 일반 0.5~1.0 → **0.8~1.5**, 희귀 1.5~3.0 → **2.0~3.8**로
올렸고, 그 결과 **안전장치가 없어졌어요.** 실측 기준 9명이 하루 1개씩만 써도
+37코인/일이고 상한은 "쓸 수 있는 시간"뿐이에요.

⚠️ **이건 숫자를 보여드리고 사용자가 고른 거예요** — 발행 증가를 수용하고 보상 체감을
택했어요. 그러니 "0으로 되돌리는 게 맞다"고 판단해 조용히 깎지 말고 **먼저 물어보세요.**

### 설계가 다섯 번 바뀐 이유 (같은 실수를 반복하지 않게)

1. **상한 없음 + 꽝 60%** → 꽝 확률은 1회당 수익만 낮출 뿐 **총 발행량을 못 막아요**
   (작정하면 하루 189코인). 출석 3~5코인이 무의미해졌어요.
2. **낚시대 하루 1개(+8.8/일)** → 상한은 잡혔지만 "더 하고 싶다"는 요구가 남았어요.
3. **치수 시스템** → 고정가를 범위로. 같은 어종도 큰 놈이 비싸요.
4. **제한 해제 + 순이익 ≈ 0** → 무제한이어도 안전했지만, 평균이 본전이라 **"벌이가
   안 된다"**는 체감이 남았어요. 그게 5차를 부른 이유예요.
5. **값 인상(+4.13/개)** ← 지금. 보상 체감을 택하고 발행 증가를 받아들였어요.

🚨 발행을 잡아야 하면 손잡이는 둘이에요: `ROD_PRICE`를 14로 올리면 순이익이 -0.29로
4차 수준으로 돌아가고, `ROD_PER_DAY`를 1로 되살리면 1인 하루 +4.13이 상한이 돼요.

📉 ⚠️ **소각은 안 늘었어요.** 낚시대값(10코인)이 유일한 소각인데 수입만 40% 늘었어요.
경제 소각률이 6.5%였으니, 다음에 손댈 건 가격이 아니라 **소비처**예요.

## 찌타임 미니게임

1. `/낚시` -> 내구도 1 소모 + "찌를 던졌어요" + **🎣 챔질 버튼**
2. 2~8초 뒤 메시지가 "🐟 입질이 왔어요!"로 바뀌어요
3. 그때부터 **2.5초 안에** 버튼을 눌러야 잡혀요
4. 결과 화면에 **🎣 다시 던지기** 버튼이 붙어요 (내구도가 남아 있으면)

⭐ **한 번 던지기는 `run_cast()` 하나예요.** `/낚시`는 `edit=False`로, 다시던지기 버튼은
`edit=True`로 불러요. 로직을 복붙하지 말고 꼭 이 함수를 쓰세요 - 선차감·환불·타이밍
규칙이 전부 여기 들어있어서, 복사본은 반드시 한쪽만 고쳐지고 어긋나요.

- 입질 전에 누르면 **성급** (놓침 → 횟수 돌려줌)
- 늦게 누르면 **놓침** (횟수 돌려줌)
- 제때 누르면 **반드시** 물고기가 나와요 (꽝 없음)

🚨 **제한시간 시계는 메시지를 보낸 뒤에 시작해요.** 전엔 보내기 전에 찍어서, 유저가
"입질!"을 보기도 전에 2.5초가 흐르기 시작했어요(왕복 지연 100~300ms를 통째로 손해).

⭐ **놓치면 횟수를 돌려줘요**(2026-10-17). 처음엔 소모시켰는데, 디스코드 왕복 지연 탓에
실력과 무관하게 놓치는 경우가 있어서 그 몫까지 물릴 수는 없어요. 덕분에 낚시대 1개가
**항상 10마리**를 줘서 순이익이 실력과 무관하게 고정돼요(5차 기준 +4.13).
🚨 **내구도는 던지기 전에 깎아요.** 끝나고 깎으면 미니게임 도중에 `/낚시`를 여러 번 쳐서
내구도 1개로 여러 판을 돌릴 수 있어요.

⚠️ 버튼은 처음부터 **눌리는 상태**로 둬요. 비활성으로 두면 디스코드가 클릭 자체를
막아서 "성급하게 눌렀다"를 잡아낼 수가 없어요 - 미니게임의 절반이 사라져요.

⚠️ 기다리는 동안 `asyncio.sleep`을 쓰는데, 그건 이벤트 루프를 막지 않아요(동기 `time.sleep`
이었다면 봇 전체가 멈춰요 - 이 봇은 그 사고 전력이 있어요).

## 왜 어항인가

낚을 때마다 코인을 주지 않고 **팔 때 한 번만** 발행해요. `coin_log`에 `낚시판매`가
한 줄씩 깔끔하게 남아서 낚시가 얼마나 찍어냈는지 정확히 떼어볼 수 있어요.

## 🚨 가시성 - 낚시는 전부 **본인에게만** 보여요

| 명령어 | 보이는 범위 |
|---|---|
| `/낚시` `/어항` `/물고기판매` | **본인에게만** (ephemeral) |
| `/낚시왕` | 공개 (순위표라 같이 보는 게 맞아요) |

왜 비공개인가: 한 채널에서 여러 명이 동시에 던지면 **찌가 뒤섞여요.** 어느 게 내 건지
모르고, 남의 "입질이 왔어요!"를 보고 눌러버리기도 해요. 🎴 뽑기는 자랑하는 재미 때문에
뽑기방에서 공개인데, 낚시는 **몇 초짜리 실시간 조작**이라 성격이 정반대예요.

⚠️ `/물고기판매`는 **`defer`부터 ephemeral이어야** 해요. 공개로 defer하면 "생각 중..."
자리가 채널에 남아서, 결과만 비공개로 보내봐야 흔적이 섞여요.
⚠️ `strike` 버튼의 `defer()`는 컴포넌트 상호작용이라 **메시지를 만들지 않아요**
(deferred_message_update). 거기엔 ephemeral이 필요 없어요.
"""
import asyncio
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import coin_wallet, fish_data, fishing_store
from utils.channel_check import restrict_to_channel
from utils.fish_data import (
    BY_KEY, COIN_PIECES, FISH, GRADE_ORDER, GRADES, ROD_DURABILITY,
    ROD_PRICE, pieces_of, roll_size,
)

log = logging.getLogger(__name__)

CHANNEL_GROUP = "fishing"
CHANNEL_ENV = "FISHING_CHANNEL_ID"
COIN_LOG_NOTE = "낚시판매"
# 🚨 소각(낚시대)과 발행(판매)을 **다른 note로** 갈라요. 같으면 리포트에서
#    순발행을 계산할 수 없어요. 둘 다 "낚시"로 시작하지만 kind가 달라요.
ROD_NOTE = "낚시대"

BITE_MIN, BITE_MAX = 2.0, 8.0      # 입질까지 기다리는 시간
BITE_WINDOW = 2.5                  # 입질 후 챔질 제한시간

# ------------------------------------------------------------------
# 🎣 한 사람당 **동시에 한 판만** (2026-10-18 사용자 결정)
#
# ## 왜 막는가
#
# `/낚시`를 연달아 쳐서 찌를 여러 개 띄워두고 기다리는 방법이 있었어요. 코인이
# 복제되는 건 아니에요 - 내구도는 던질 때마다 정직하게 깎이니까요(`use_rod`는
# 조건부 원자 차감이에요). 문제는 **속도**예요.
#
# 입질 대기(2~8초)가 낚시의 유일한 속도 제한인데, 병렬로 던지면 그게 사라져요.
# 10-18 실측: 한 사람이 낚시대를 **중앙 2초 간격**으로 147개 사며 1,390캐스트를
# 돌렸어요(서버 전체 캐스트의 47%). 같은 시기 정상 플레이어는 **129초 간격**이었고요.
# 즉 방법을 아는 소수만 수십 배 빨리 벌고 있었어요. 낚시는 전체 발행의 70%고요.
#
# ## 어떻게 막는가
#
# 유저별로 "지금 한 판 돌고 있음"을 들고, 끝나면 `finally`로 지워요.
#
# ⚠️ **메모리 dict면 충분해요.** 봇이 단일 프로세스고, 재시작되면 진행 중이던 판은
#    어차피 사라지니 플래그도 같이 사라지는 게 맞아요(`FishingView`와 같은 성격).
# 🚨 **TTL이 안전장치예요.** `finally`가 어떤 이유로든 안 돌면 그 사람은 영영 낚시를
#    못 하게 돼요. 뷰 타임아웃보다 넉넉한 시간이 지나면 저절로 풀리게 해뒀어요.
# ⚠️ 기존 `CastAgainView._started`는 **같은 버튼의 연타**만 막아요(뷰 인스턴스 소유).
#    서로 다른 `/낚시` 호출은 각자 새 뷰라 그걸로는 못 막아서 이 가드가 따로 필요해요.
_casting: dict[int, float] = {}
CAST_GUARD_TTL = BITE_MAX + BITE_WINDOW + 15.0
WAIT_COLOR, BITE_COLOR = 0x2B6CB0, 0x38A169
MISS_COLOR = 0x6B7280

_GRADE_KEYS = {g: [f["key"] for f in rows] for g, rows in FISH.items()}


def roll_catch(rng: random.Random | None = None) -> str:
    """한 번 챔질에 **성공했을 때** 뭐가 잡히나.

    ⚠️ **꽝이 없어요**(2026-10-17 2차 설계). 타이밍만 맞히면 반드시 물고기가 나와요.
    1차엔 꽝 60%로 발행을 조절했는데, 꽝 확률은 1회당 수익만 낮출 뿐 **총 발행량을
    못 막아요**. 발행 조절은 `fish_data.ROD_PRICE`가 해요.

    🚨 **상한은 이제 없어요.** 4차에 낚시대 하루 1개 제한이 풀리고 5차에 물고기 값을
    올렸으니, 낚시대를 몇 개든 사는 만큼 발행이 늘어나요(실측 개당 순 +3.5코인).
    "낚시대가 상한을 건다"고 적혀 있었는데 그건 3차까지의 이야기예요 — 지금 코드를
    읽고 상한이 있다고 착각하면 발행량 추정이 통째로 틀려요.

    못 잡는 경우는 이제 **타이밍 실패뿐**이고, 그건 내 실수지 운이 아니에요."""
    rng = rng or random
    grades = list(GRADES)
    weights = [GRADES[g]["weight"] for g in grades]
    grade = rng.choices(grades, weights=weights, k=1)[0]
    return rng.choice(_GRADE_KEYS[grade])


async def purchase_rod(user_id) -> tuple[bool, str]:
    """낚시대 한 개를 사요. (성공, 안내문). `/악귀상점`과 🎣 버튼이 **같이** 써요.

    🚨 **지급을 먼저, 차감을 나중에** 해요. 반대로 하면 차감 뒤 지급이 실패했을 때
    코인만 사라져요. 차감이 실패하면 `refund_rod`로 되돌려서 공짜 낚시대를 막아요.
    (🎲 도박 한도 연장권과 같은 순서예요.)"""
    # ⚠️ 하루 제한이 없어서(2026-10-17 4차) 지급은 항상 성공해요. 그래도 순서는
    #    그대로 지급 -> 차감 -> 실패 시 환불이에요.
    await fishing_store.buy_rod(user_id, ROD_DURABILITY)

    if not await coin_wallet.spend(user_id, ROD_PRICE, reason=ROD_NOTE):
        await fishing_store.refund_rod(user_id, ROD_DURABILITY)
        balance = await coin_wallet.get_balance(user_id)
        return False, (
            f"악귀코인이 부족해요. 낚시대는 **{ROD_PRICE}코인**인데 "
            f"지금 **{balance}개** 있어요.\n"
            "-# `/출석` · `/미션` · `/업적`으로 모을 수 있어요."
        )

    balance = await coin_wallet.get_balance(user_id)
    log.info("🎣 낚시대 구매: %s %d코인", user_id, ROD_PRICE)
    return True, (
        f"🎣 낚시대를 샀어요! **{ROD_DURABILITY}번** 던질 수 있어요.\n"
        f"남은 악귀코인 **{balance}개** · `/낚시` 로 시작해보세요"
    )


class BuyRodView(discord.ui.View):
    """🎣 낚시대 구매 버튼.

    🚨 `/악귀상점`에만 두면 안 팔려요 - 리롤권·보호권·테마가 **12일째 0건**이에요
    (구매력이 아니라 발견이 문제였어요). 그래서 **낚시대가 없어서 막힌 바로 그 자리**에
    버튼을 띄워요. 🔓 도박 한도 연장권이 같은 이유로 그렇게 해서 잘 팔려요."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="낚시대 사기", emoji="🎣", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        button.disabled = True
        ok, msg = await purchase_rod(interaction.user.id)
        try:
            await interaction.edit_original_response(content=msg, view=None)
        except discord.HTTPException:
            await interaction.followup.send(msg, ephemeral=True)


async def finish_cast(interaction: discord.Interaction, view: "FishingView") -> None:
    """낚시 한 판의 결과를 보여줘요. `run_cast`가 불러요.

    ⚠️ `FishingView`가 **아래에** 정의돼 있어서 타입 힌트를 따옴표로 감쌌어요.
    그냥 쓰면 모듈을 불러올 때 `NameError`로 cog 전체가 죽어요."""
    key = view.caught if view.result == "ok" else None
    size = view.size if key else None

    # 🚨 **놓치면 내구도를 돌려줘요** (2026-10-17 사용자 결정).
    #
    # 전엔 놓쳐도 1 소모였어요("미니게임이 장식이 되지 않게"). 그런데 디스코드
    # 왕복 지연 때문에 **실력과 무관하게 놓치는 경우**가 있어서, 그 몫까지
    # 유저가 물게 되는 건 맞지 않아요.
    #
    # ⭐ 경제적으로도 이쪽이 더 깔끔해요. 낚시대 1개가 **항상 10마리**를 주니
    #    순이익이 실력과 무관하게 고정돼요(5차 기준 +4.13). 전엔 못 하는 사람만 손해를
    #    봤는데, 무제한 구매 구조에서 그건 "못하면 벌칙"이 돼요.
    #
    # ⚠️ 그래도 **던지기 전 선차감**은 그대로예요. 돌려주는 건 결과가 난 뒤라,
    #    미니게임 도중에 `/낚시`를 여러 번 쳐서 한 개로 여러 판을 돌리는 건 여전히
    #    막혀요(동시에 여러 판을 열면 그만큼 선차감되니까요).
    if key is None:
        await fishing_store.give_back_rod(interaction.user.id)
        view.rod_left += 1

    await fishing_store.record_cast(interaction.user.id, key, size)
    state = await fishing_store.get(interaction.user.id)
    total = sum(len(v) for v in state["tank"].values())

    if key:
        grade, name = BY_KEY[key]
        g = GRADES[grade]
        pieces = pieces_of(key, size)
        lo, hi = fish_data.SIZE_BY_KEY[key]
        # 📏 같은 어종 안에서 몇 %짜리인지 - "대물급 피라미"의 재미가 여기서 나와요.
        pct = int((size - lo) / max(1, hi - lo) * 100)
        tag = " 🏆 **최대급!**" if pct >= 90 else (" ✨ 큼직해요" if pct >= 70 else "")
        embed = discord.Embed(
            title=f"{g['emoji']} {grade} · {name} {size}cm{tag}",
            description=f"판매가 **{pieces / COIN_PIECES:.1f}코인**",
            color=g["color"],
        )
    else:
        # ⚠️ 이제 **못 잡는 경우는 타이밍 실패뿐**이에요(꽝 제거, 2026-10-17 2차).
        #    운이 아니라 내 실수라서, 사유를 분명히 알려줘요.
        reason = {
            "early": "너무 일찍 챘어요. 미끼만 날아갔네요.",
            "late": "늦었어요. 물고기가 도망갔어요.",
        }.get(view.result, "놓쳤어요.")
        embed = discord.Embed(
            title="💨 놓쳤어요",
            description=reason + "\n-# 🎣 **횟수는 돌려드렸어요.** 다시 던져보세요!",
            color=MISS_COLOR)

    embed.add_field(name="어항", value=f"**{total}마리**", inline=True)
    embed.add_field(name="🎣 낚시대",
                    value=(f"**{view.rod_left}번** 남음" if view.rod_left
                           else "**부서졌어요**"), inline=True)
    embed.set_footer(
        text=("/어항 으로 확인하고 /물고기판매 로 한 번에 팔아요" if view.rod_left
              else f"{ROD_PRICE}코인으로 새 낚시대를 사면 이어서 던질 수 있어요"))

    # 🎣 횟수가 남았으면 **바로 다시 던질 수 있게**, 없으면 **살 수 있게**.
    #    매번 `/낚시`를 치게 하면 10회짜리 낚시대가 고역이에요.
    next_view = (CastAgainView(interaction.user.id, view.rod_left) if view.rod_left
                 else BuyRodView(interaction.user.id))
    try:
        await interaction.edit_original_response(embed=embed, view=next_view)
    except discord.HTTPException:
        await interaction.followup.send(embed=embed, view=next_view, ephemeral=True)


class CastAgainView(discord.ui.View):
    """🎣 다시 던지기 - 결과 화면에 붙어요.

    낚시대가 10회라 `/낚시`를 열 번 치게 하는 건 번거로워요. 🎴 뽑기의 "한 번 더"와
    같은 패턴이에요.

    🚨 **연타 방어가 필수예요.** 내구도는 던지기 전에 깎이니까, 두 번 눌리면
    **1판만 돌면서 2회가 사라져요.** `_started`로 한 번만 통과시켜요(봇이 단일
    프로세스라 인스턴스 상태로 충분해요).

    ⚠️ 같은 ephemeral 메시지를 **재사용**해요(`edit=True`). 새 메시지를 띄우면
    던질 때마다 쌓여서 어느 게 지금 찌인지 알 수 없어져요."""

    def __init__(self, user_id: int, rod_left: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self._started = False
        self.again.label = f"다시 던지기 ({rod_left}번 남음)"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="다시 던지기", emoji="🎣",
                       style=discord.ButtonStyle.primary)
    async def again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._started:
            await interaction.response.defer()
            return
        self._started = True

        # ⚠️ 던지기가 **시작조차 못 하면** 가드를 되돌려요. 이 뷰는 화면에 그대로
        #    남아 있는데 `_started`를 세워둔 채 두면 버튼이 **영구히 죽어서**, 유저는
        #    낚시대가 남았는데도 `/낚시`를 다시 쳐야 해요.
        #
        # 🚨 되돌리는 건 "한 판도 안 돌았을 때"뿐이에요. 판이 돈 뒤에 화면만
        #    실패한 경우까지 되돌리면 내구도가 두 번 깎여요(`run_cast`의 반환값 참고).
        try:
            started = await run_cast(interaction, edit=True)
        except Exception:
            self._started = False
            raise
        if not started:
            self._started = False


async def run_cast(interaction: discord.Interaction, *, edit: bool) -> bool:
    """한 판 돌리기. **동시에 한 판만** 허용하는 가드를 씌운 얇은 껍데기예요.

    실제 진행은 `_run_cast`가 해요. 가드를 여기서 따로 떼어둔 이유는, 안쪽에서
    무슨 일이 나든(예외·조기 return) `finally`가 **반드시** 플래그를 지우게 하려고요.
    플래그가 남으면 그 사람은 낚시를 영영 못 해요.

    이미 한 판이 돌고 있으면 거절하고 `False`를 줘요. `CastAgainView`는 `False`를
    받으면 자기 연타 가드를 되돌리는데, 그게 맞아요 — 앞 판이 끝난 뒤에는 그 버튼이
    다시 눌려야 하니까요(그때는 이 가드도 이미 풀려 있어요)."""
    uid = interaction.user.id
    now = time.monotonic()

    started_at = _casting.get(uid)
    if started_at is not None and now - started_at < CAST_GUARD_TTL:
        try:
            await interaction.response.send_message(
                "🎣 이미 찌를 던져뒀어요. **그 판을 먼저 끝내주세요.**\n"
                "-# 한 번에 한 판만 할 수 있어요. 결과 화면의 **다시 던지기**를 쓰면 편해요.",
                ephemeral=True,
            )
        except discord.HTTPException:
            # 이미 응답됐거나 토큰이 죽었어도 **던지지 않은 것**이 중요해요.
            log.info("🎣 동시 낚시 거절 안내 실패 (user=%s)", uid)
        return False

    _casting[uid] = now
    try:
        return await _run_cast(interaction, edit=edit)
    finally:
        _casting.pop(uid, None)


async def _run_cast(interaction: discord.Interaction, *, edit: bool) -> bool:
    """한 번 던지기. `/낚시`와 🎣 다시 던지기 버튼이 **같이** 써요.

    `edit=False`면 새 메시지를 띄우고(슬래시 명령), `edit=True`면 **지금 메시지를
    고쳐서** 찌를 다시 띄워요(버튼). 던질 때마다 새 메시지를 만들면 쌓여서
    어느 게 지금 찌인지 알 수 없어져요.

    상호작용을 받아냈으면 `True`, 토큰이 이미 죽어 아무것도 못 했으면 `False`를
    줘요(호출한 쪽이 연타 가드를 되돌릴 수 있게).

    ⚠️ 두 경로 모두 이후에는 `interaction.edit_original_response`로 같은 메시지를
    고쳐요. 컴포넌트 상호작용에서도 그 메서드는 **버튼이 달려 있던 메시지**를 가리켜요."""
    uid = interaction.user.id

    # 🚨 **DB보다 응답이 먼저예요.** 상호작용 토큰은 **3초**면 만료돼요.
    #
    # 전에는 `use_rod()`로 Atlas를 다녀온 **뒤에** 첫 화면을 띄웠어요. 메모리가
    # 빠듯해 왕복이 밀리면 그 3초를 넘겨서 `404 Unknown interaction (10062)`으로
    # 터졌고, 하필 그 순서에선 **내구도는 이미 깎인 뒤**라 유저는 아무 화면도 못 본 채
    # 1회를 잃었어요 (2026-10-17 12:47 실제 발생).
    #
    # ⭐ 먼저 `defer()`로 받아두면 그 뒤로는 **15분**짜리 웹훅 토큰을 쓰게 돼서, DB가
    #    얼마나 느리든 안전해요. 컴포넌트의 인자 없는 `defer()`는 화면을 건드리지
    #    않아서(`deferred_message_update`) 찌가 깜빡이지도 않아요. 슬래시 쪽은
    #    그 타입을 쓸 수 없어서 `ephemeral=True`로 "생각 중"을 잠깐 띄웠다가
    #    아래 `show()`가 바로 덮어써요.
    try:
        if edit:
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True)
    except discord.HTTPException:
        # ⚠️ 여기서 실패하면 **내구도를 건드리기 전에** 빠져나와요. 화면을 띄울 수
        #    없는 상황에서 낚시대만 깎는 게 제일 나쁜 결과예요.
        log.warning("🎣 상호작용을 받지 못했어요 (user=%s edit=%s)", uid, edit)
        return False

    async def show(**kw):
        """첫 화면을 띄워요. `defer()`로 받아둔 응답을 고쳐 쓰니 경로가 하나예요."""
        await interaction.edit_original_response(**kw)

    # 🚨 **내구도를 먼저 깎고** 시작해요. 던지고 나서 깎으면, 미니게임 도중에
    #    여러 번 `/낚시`를 쳐서 내구도 1개로 여러 판을 돌릴 수 있어요.
    left = await fishing_store.use_rod(uid)
    if left is None:
        await show(
            content=(f"🎣 낚시대가 없어요. **{ROD_PRICE}코인**으로 하나 사면 "
                     f"**{ROD_DURABILITY}번** 던질 수 있어요.\n"
                     # ⚠️ 전엔 "평균적으로는 본전"이라고 적어뒀는데 5차(값 인상)로
                     #    **거짓이 됐어요.** 이제 1개당 평균 +4코인쯤 남아요.
                     "-# 몇 개든 살 수 있어요. 10번 던지면 평균 **14코인**쯤 벌려요."),
            # ⚠️ 메시지를 재사용하니 이전 임베드를 **명시적으로 지워야** 해요.
            embed=None,
            view=BuyRodView(uid),
        )
        return True

    view = FishingView(uid)
    view.rod_left = left
    embed = discord.Embed(
        title="🎣 찌를 던졌어요",
        description="찌를 지켜보세요... **입질이 오면 바로 챔질!**",
        color=WAIT_COLOR,
    )
    embed.set_footer(text="너무 일찍 누르면 미끼만 날려요")
    # 🚨 **본인에게만** 보여요. 한 채널에서 여러 명이 동시에 던지면 찌가 뒤섞여서
    #    어느 게 내 건지 알 수 없고, 남의 '입질!'을 보고 눌러버리기도 해요.
    await show(content=None, embed=embed, view=view)

    # 입질까지 기다려요. 그 사이에 유저가 누르면 done이 먼저 떨어져요(= 성급).
    try:
        await asyncio.wait_for(view.done.wait(),
                               timeout=random.uniform(BITE_MIN, BITE_MAX))
    except asyncio.TimeoutError:
        pass

    if not view.done.is_set():
        bite = discord.Embed(
            title="🐟 입질이 왔어요!",
            description="**지금 챔질하세요!**",
            color=BITE_COLOR,
        )
        try:
            await interaction.edit_original_response(embed=bite, view=view)
        except discord.HTTPException:
            log.info("입질 표시 실패 (메시지가 사라졌을 수 있어요)")

        # 🚨 제한시간 시계는 **메시지를 보낸 뒤에** 시작해요.
        #
        # 전에는 `edit_original_response` **앞**에서 찍었는데, 그 호출이 디스코드까지
        # 다녀오는 데 100~300ms가 걸려요. 즉 유저가 "입질!"을 보기도 전에 제한시간이
        # 흐르기 시작해서, 체감 2.5초가 실제로는 2초 남짓이었어요. 못 잡는 게
        # 실력이 아니라 **지연 때문**이었던 거예요(2026-10-17 사용자 신고).
        #
        # ⚠️ 돌아오는 길(클릭 -> 봇)은 여전히 포함돼요. 그건 클라이언트 시각을
        #    받을 수 없어서 어쩔 수 없고, 대신 창을 넉넉히 잡아 상쇄해요.
        view.bite_at = time.monotonic()
        try:
            await asyncio.wait_for(view.done.wait(), timeout=BITE_WINDOW + 1.0)
        except asyncio.TimeoutError:
            view.result = "late"
            view.done.set()

    view.stop()
    # 🚨 여기서 터지면 유저는 **아무 반응도 못 봐요**(찌만 띄워놓고 끝).
    #    2026-10-17에 "눌렀는데 봇이 반응이 없다"는 신고가 있었는데 로그가 없어서
    #    원인 찾기가 어려웠어요. 결과 표시 실패는 반드시 흔적을 남겨요.
    try:
        await finish_cast(interaction, view)
    except Exception:
        log.exception("🎣 낚시 결과 표시 실패 (user=%s result=%s)", uid, view.result)
        try:
            await interaction.followup.send(
                "결과를 보여주는 데 실패했어요. `/어항` 으로 확인해주세요.",
                ephemeral=True)
        except discord.HTTPException:
            pass

    # 던지기는 끝났어요. 결과 화면을 못 띄웠더라도 **판은 돌았고 기록도 남았으니**
    # True예요(연타 가드를 되돌리면 안 돼요 - 한 판이 두 번 돌아요).
    return True


class FishingView(discord.ui.View):
    """찌 하나짜리 화면. 한 사람의 한 번의 낚시에만 쓰여요.

    ⚠️ 영속(DynamicItem)이 아니에요. 낚시는 **몇 초 안에 끝나는 일회성**이라 봇이
    재시작되면 그 판은 그냥 없던 일이 되는 게 맞아요(뽑기 버튼과는 성격이 달라요)."""

    def __init__(self, user_id: int):
        super().__init__(timeout=BITE_MAX + BITE_WINDOW + 10)
        self.user_id = user_id
        self.bite_at: float | None = None     # 입질이 온 시각 (None = 아직)
        self.done = asyncio.Event()
        self.result: str | None = None        # "early" | "late" | "ok"
        self.caught: str | None = None
        self.size: int | None = None          # 📏 잡힌 물고기의 치수(cm)
        self.rod_left = 0                     # 이번 캐스트 뒤 남은 내구도

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "남의 찌예요. `/낚시`로 직접 던져주세요.", ephemeral=True)
        return False

    @discord.ui.button(label="챔질!", emoji="🎣", style=discord.ButtonStyle.primary)
    async def strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        """🚨 **판정만 하고 화면은 안 건드려요.**

        전에는 여기서 `interaction.response.edit_message(view=self)`로 버튼을 끄고
        있었어요. 그런데 `done.set()` 하는 순간 `fish()`가 깨어나 **같은 메시지를
        동시에 편집**해서, 둘이 엇갈리면 결과 화면이 덮여 "눌렀는데 아무 반응이 없는"
        것처럼 보였어요(2026-10-17 유저 신고 - 예외가 안 나서 로그에도 안 남아요).

        이제 화면은 `_finish` 혼자 책임져요. 여기선 `defer()`만 해서 상호작용을
        받아줬다는 표시만 남겨요(컴포넌트 defer는 메시지를 안 만들어요)."""
        # ⚠️ 판정을 **먼저**, 응답을 나중에. 응답을 기다리는 사이에 `fish()`가
        #    "늦음"으로 처리해버리면 제때 누른 게 놓친 걸로 바뀌어요.
        if not self.done.is_set():
            if self.bite_at is None:
                # 🚨 입질 전에 누른 경우. 버튼을 처음부터 눌리게 둔 이유가 이걸 잡기 위해서예요.
                self.result = "early"
            elif time.monotonic() - self.bite_at > BITE_WINDOW:
                self.result = "late"
            else:
                self.result = "ok"
                self.caught = roll_catch()
                # 📏 치수는 잡힌 **그 순간** 정해져요. 나중에 굴리면 같은 물고기가
                #    볼 때마다 크기가 달라져요.
                self.size = roll_size(self.caught)
            self.done.set()

        try:
            await interaction.response.defer()
        except discord.HTTPException:
            # 이미 응답했거나 만료됐어도 판정은 끝났어요. 결과는 _finish가 보여줘요.
            log.info("🎣 챔질 defer 실패 (판정은 완료, user=%s)", interaction.user.id)

    async def on_timeout(self):
        if not self.done.is_set():
            self.result = "late"
            self.done.set()


class Fishing(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="낚시", description="찌를 던져 물고기를 낚아요. (낚시대가 필요해요)")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def fish(self, interaction: discord.Interaction):
        await run_cast(interaction, edit=False)

    @app_commands.command(name="어항", description="낚아둔 물고기를 봐요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def tank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = await fishing_store.get(interaction.user.id)
        tank = data["tank"]

        embed = discord.Embed(title="🪣 내 어항", color=0x3B82F6)
        if not tank:
            embed.description = "어항이 비었어요. `/낚시` 로 한 마리 낚아보세요!"
        else:
            lines = []
            for grade in GRADE_ORDER:
                rows = [(k, s) for k, sizes in tank.items()
                        if BY_KEY.get(k, ("", ""))[0] == grade for s in sizes]
                if not rows:
                    continue
                g = GRADES[grade]
                lo_p, hi_p = g["pieces"]
                # 📏 **큰 놈부터** 보여줘요. 어항을 열었을 때 제일 궁금한 게 최대어예요.
                rows.sort(key=lambda r: -(r[1] or 0))
                part = " · ".join(
                    f"{BY_KEY[k][1]}" + (f" {s}cm" if s is not None else "")
                    for k, s in rows[:8])
                if len(rows) > 8:
                    part += f" 외 {len(rows) - 8}마리"
                lines.append(
                    f"{g['emoji']} **{grade}** "
                    f"({lo_p / COIN_PIECES:.1f}~{hi_p / COIN_PIECES:.1f}코인) — {part}")
            embed.description = "\n".join(lines)

            total_n = sum(len(v) for v in tank.values())
            pieces = data["pieces"] + data["dust"]
            embed.add_field(name="마리 수", value=f"**{total_n}마리**", inline=True)
            # ⚠️ 실제 지급은 **내림**이에요(나머지는 다음 판매로 넘어가요). 기대를
            #    부풀리지 않게 정확한 값과 받을 코인을 같이 보여줘요.
            embed.add_field(
                name="팔면",
                value=(f"**{pieces // COIN_PIECES}코인**"
                       + (f"\n-# (정확히 {pieces / COIN_PIECES:.1f} · "
                          f"남는 {pieces % COIN_PIECES / COIN_PIECES:.1f}은 다음에)"
                          if pieces % COIN_PIECES else "")),
                inline=True)

        # 🎣 낚시대 상태를 제일 먼저 보여줘요 - "몇 번 더 던질 수 있나"가
        #    낚시에서 제일 궁금한 정보예요.
        #
        # ⚠️ 전엔 "부서졌어요 (내일 다시)"를 띄웠는데, 하루 제한을 푼 뒤로는
        #    **거짓 안내**예요. 지금은 바로 또 살 수 있어요.
        left, _bought_today = await fishing_store.rod_state(interaction.user.id)
        rod = (f"**{left}/{ROD_DURABILITY}번** 남음" if left
               else f"없어요 (`/악귀상점` {ROD_PRICE}코인)")
        embed.add_field(name="🎣 낚시대", value=rod, inline=True)

        hit = f"{data['caught']}/{data['casts']}" if data["casts"] else "0/0"
        embed.add_field(name="챔질 성공률", value=f"{hit}", inline=True)
        if data.get("best"):
            bg, bn = BY_KEY.get(data["best"]["key"], ("?", "?"))
            embed.add_field(name="최고 기록",
                            value=f"{GRADES.get(bg, {}).get('emoji', '')} {bn}", inline=True)
        if data["sold"]:
            embed.add_field(name="누적 판매", value=f"**{data['sold']}코인**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="물고기판매", description="어항에 든 물고기를 전부 팔아요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def sell(self, interaction: discord.Interaction):
        # ⚠️ defer부터 ephemeral이어야 해요. 공개로 defer하면 "생각 중..." 자리가
        #    채널에 남아서, 결과만 비공개로 보내봐야 흔적이 섞여요.
        await interaction.response.defer(ephemeral=True)

        # 🚨 **비우면서 내용을 받아와요**(원자적). 읽고 나서 비우면 그 사이에 낚은
        #    물고기가 증발해요.
        # ⚠️ **3개를 받아야 해요** (tank, coins, dust). 치수 시스템에서 `sell_all`이
        #    잔돈까지 돌려주게 바뀌었는데 여기를 2개로 두는 바람에
        #    `ValueError: too many values to unpack`으로 **판매가 통째로 죽었어요**
        #    (2026-10-17 유저 신고). 테스트가 store만 직접 불러서 못 잡았어요.
        tank, coins, dust = await fishing_store.sell_all(interaction.user.id)
        if not tank:
            await interaction.followup.send(
                "어항이 비었어요. `/낚시` 로 한 마리 낚아보세요!", ephemeral=True)
            return

        try:
            balance = await coin_wallet.add(interaction.user.id, coins, reason=COIN_LOG_NOTE)
        except Exception:
            # 🚨 코인이 안 들어갔으면 물고기를 반드시 되돌려요. 잔돈까지 같이요.
            await fishing_store.restore(interaction.user.id, tank, dust)
            log.exception("물고기 판매 실패 - 어항을 되돌렸어요 (user=%s)", interaction.user.id)
            await interaction.followup.send(
                "판매 중 문제가 생겼어요. **물고기는 어항에 그대로 있어요.**", ephemeral=True)
            return

        await fishing_store.add_sold(interaction.user.id, coins)

        lines = []
        for grade in GRADE_ORDER:
            rows = [(k, sz) for k, sizes in tank.items()
                    if BY_KEY.get(k, ("", ""))[0] == grade for sz in sizes]
            if rows:
                g = GRADES[grade]
                sub = sum(pieces_of(k, sz) for k, sz in rows)
                big = max((sz for _, sz in rows if sz is not None), default=None)
                lines.append(
                    f"{g['emoji']} **{grade}** {len(rows)}마리 — "
                    f"{sub / COIN_PIECES:.1f}코인"
                    + (f" (최대 {big}cm)" if big else ""))

        embed = discord.Embed(
            title="🪙 물고기를 팔았어요!",
            description="\n".join(lines),
            color=0xFFC850,
        )
        embed.add_field(name="받은 코인", value=f"**+{coins}개**", inline=True)
        embed.add_field(name="보유 악귀코인", value=f"**{balance}개**", inline=True)
        # 🚨 남은 조각을 **반드시 알려줘요.** 안 그러면 "3.7코인어치인데 3개만 받았다"가
        #    떼먹힌 걸로 보여요. 다음 판매에 더해진다는 걸 명시해요.
        if dust:
            embed.add_field(name="다음에 더해져요",
                            value=f"**{dust / COIN_PIECES:.1f}코인**", inline=True)
        embed.set_footer(text="어항이 비었어요 · /낚시 로 다시 채워보세요")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="낚시왕", description="누가 제일 많이 벌었는지 봐요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await fishing_store.leaderboard(10)
        if not rows:
            await interaction.followup.send("아직 아무도 물고기를 팔지 않았어요.")
            return
        medals = ["🥇", "🥈", "🥉"]
        body = "\n".join(
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — **{coins}코인**"
            for i, (uid, coins) in enumerate(rows)
        )
        embed = discord.Embed(title="🎣 낚시왕", description=body, color=0xFFC850)
        await interaction.followup.send(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="낚시확률",
                          description="등급별 확률과 물고기 값을 공개해요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def rates(self, interaction: discord.Interaction):
        """🎣 확률·값 공개. `/카드확률`과 같은 성격이에요.

        🚨 **숫자를 손으로 적지 말 것.** 전부 `fish_data`에서 계산해요. 값을 올리거나
        확률을 바꿀 때 안내문만 옛값으로 남는 사고가 이 저장소에서 반복됐어요
        (`/악귀상점`의 "하루 1개"가 4차 이후로 거짓이었던 게 그 예예요).

        ⚠️ 평균 벌이는 `expected_*` 헬퍼를 써요. 등급 값 범위의 **중앙값으로 계산하면
        과대 안내**예요 - 치수가 작은 쪽으로 치우쳐 있어서(`SIZE_SKEW`) 14.8이 아니라
        14.1이 맞아요.
        """
        total_w = sum(g["weight"] for g in GRADES.values())
        lines = []
        for grade in GRADE_ORDER:
            g = GRADES[grade]
            lo_p, hi_p = g["pieces"]
            lines.append(
                f"{g['emoji']} **{grade}** — {g['weight'] / total_w * 100:.1f}% · "
                f"{lo_p / COIN_PIECES:.1f}~{hi_p / COIN_PIECES:.1f}코인 · "
                f"{len(FISH[grade])}종")

        embed = discord.Embed(
            title="🎣 낚시 확률과 값",
            description="\n".join(lines),
            color=0x3B82F6,
        )
        embed.add_field(
            name="🎣 낚시대",
            value=(f"`/악귀상점`에서 **{ROD_PRICE}코인** · 한 개로 **{ROD_DURABILITY}번**\n"
                   "　└ **몇 개든** 살 수 있어요 (하루 제한 없어요)"),
            inline=False,
        )
        per_cast = fish_data.expected_coin_per_cast()
        per_rod = fish_data.expected_coin_per_day()
        net = fish_data.net_issue_per_rod()
        embed.add_field(
            name="⭐ 평균 얼마 벌리나",
            value=(f"한 번 던지면 평균 **{per_cast:.1f}코인** → 낚시대 하나로 "
                   f"약 **{per_rod:.0f}코인**\n"
                   f"　└ 낚시대값 {ROD_PRICE}코인을 빼면 **{net:+.0f}코인**쯤 남아요\n"
                   "　└ ⚠️ 판매는 **내림**이에요(1코인 = 10조각) — 남는 조각은 "
                   "다음 판매로 넘어가요"),
            inline=False,
        )
        embed.add_field(
            name="📏 같은 어종도 치수가 값을 갈라요",
            value=("위 등급 값 범위의 **아래쪽~위쪽**을 치수가 정해요.\n"
                   "　└ 치수는 **작은 쪽으로 치우쳐** 있어서 최대어는 드물어요 "
                   "(그래서 기록에 의미가 있어요)"),
            inline=False,
        )
        embed.add_field(
            name="🐟 어떤 물고기가 있나",
            value="\n".join(
                f"{GRADES[grade]['emoji']} " + " · ".join(
                    f"{f['name']} {f['size'][0]}~{f['size'][1]}cm"
                    for f in FISH[grade])
                for grade in GRADE_ORDER),
            inline=False,
        )
        embed.add_field(
            name="꽝은 없어요",
            value=("타이밍만 맞히면 **반드시 뭔가 나와요.**\n"
                   "　└ 챔질을 놓쳐도 **횟수를 돌려드려요** — 운이 아니라 실수니까요"),
            inline=False,
        )
        embed.set_footer(text="/어항 에서 지금 가치를 확인해보세요")
        # DB를 안 건드려서 defer 없이 바로 답해도 3초를 안 넘겨요.
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fishing(bot))
