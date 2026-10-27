"""🎣 낚시 - 찌를 던져 물고기를 낚고, 어항에 모았다가 팔아 코인을 벌어요.

## ⭐ 하루 상한 + 값 x1.5 (2026-10-20 6차 · 사용자 결정)

낚시하려면 `/악귀상점`에서 **낚시대**를 사야 해요(`ROD_PRICE`코인 · 내구도 10회).
개수는 **몇 개든** 살 수 있지만, 던지는 건 **하루 `DAILY_CAST_CAP`번까지**예요.

    1캐스트: 기댓값 2.1코인 − 낚시대값 1코인 = 순이익 **+1.1코인**
    하루 20번을 다 쓰면: 수입 42코인 − 낚시대값 20코인 = **+22코인**

### 왜 상한이 생겼나 (사용자가 짚은 문제)

5차까지는 **캐스트 수 = 수입**이라 시간을 쓸 수 있는 사람만 벌었어요. 사용자가
"시간이 없는 사람들은 코인을 벌기 어렵다"고 짚었고, 실측이 그걸 확인했어요:

    하루 최다 캐스트 1,360회 → 그날 수입 1,403코인 (같은 날 꼴찌는 13코인)
    전체 캐스트 중 상위 1명 몫 50% · 하루 20캐스트로 끊으면 총량이 13%로 줄어듦

그래서 **상한을 걸고 그 안에서 버는 양을 늘렸어요**(둘은 꼭 같이 가야 해요 —
상한만 걸면 보상이 짜지고, 값만 올리면 격차가 더 벌어져요).

🚨 **라이트 유저는 안 깎여요.** 하루 10~20캐스트가 평범한 범위라 20이 그 바로
위예요. 깎인 건 9명 중 상위 몇 명뿐이에요.

### 설계가 여섯 번 바뀐 이유 (같은 실수를 반복하지 않게)

1. **상한 없음 + 꽝 60%** → 꽝 확률은 1회당 수익만 낮출 뿐 **총 발행량을 못 막아요**
   (작정하면 하루 189코인). 출석 3~5코인이 무의미해졌어요.
2. **낚시대 하루 1개(+8.8/일)** → 상한은 잡혔지만 "더 하고 싶다"는 요구가 남았어요.
3. **치수 시스템** → 고정가를 범위로. 같은 어종도 큰 놈이 비싸요.
4. **제한 해제 + 순이익 ≈ 0** → 무제한이어도 안전했지만, 평균이 본전이라 **"벌이가
   안 된다"**는 체감이 남았어요. 그게 5차를 부른 이유예요.
5. **값 인상(+4.13/개)** → 보상 체감을 택하고 발행 증가를 받아들였어요. 그런데
   상한이 없으니 **시간 부자에게만** 닿았어요 — 그게 6차를 부른 이유예요.
6. **하루 캐스트 상한 + 값 x1.5** ← 지금. 상한이 **횟수**에 걸려요.

🚨 **상한은 낚시대 개수가 아니라 던진 횟수에 걸어요.** 개수로 걸면 🪝소형(3회)을
쓰는 하위권이 하루 3캐스트에 막혀요 — 진입을 넓히려 만든 상품이 불리해져요.
→ 자세한 이유는 `utils/fish_data.py`의 `DAILY_CAST_CAP` 주석.

🚨 **「낚시 한도 연장권」은 만들지 마세요.** 🎲 도박 연장권이 소각의 9할인 건 도박이
**발행원이 아니기** 때문이에요. 낚시는 발행원이라, 연장권이 추가 캐스트의 기대
순이익(+1.1코인)보다 싸면 **코인 복사기**가 되고 비싸면 死상품이에요.

📉 ⚠️ **소각은 상한과 **같이** 줄어요.** 낚시대값이 유일한 소각이라, 캐스트가 줄면
소각도 비례해서 줄어요(소각률 지표가 떨어져 보이는 건 정상이에요 — 순발행은 줄어요).

## 찌타임 미니게임

1. `/낚시` -> 내구도 1 소모 + "찌를 던졌어요" + **🎣 챔질 버튼**
2. 2~8초 뒤 메시지가 "🐟 입질이 왔어요!"로 바뀌어요
3. 그 뒤에 버튼을 누르면 **언제 눌렀든 잡혀요** (아래 '늦었다는 없어요')
4. 결과 화면에 **🎣 다시 던지기** 버튼이 붙어요 (내구도가 남아 있으면)

⭐ **한 번 던지기는 `run_cast()` 하나예요.** `/낚시`는 `edit=False`로, 다시던지기 버튼은
`edit=True`로 불러요. 로직을 복붙하지 말고 꼭 이 함수를 쓰세요 - 선차감·환불·타이밍
규칙이 전부 여기 들어있어서, 복사본은 반드시 한쪽만 고쳐지고 어긋나요.

- 입질 전에 누르면 **성급** (놓침 → 횟수 돌려줌)
- 입질 뒤에 누르면 **반드시** 물고기가 나와요 (꽝도 없고 '늦었다'도 없어요)
- 아무것도 안 누르면 **방치** (놓침 → 횟수 돌려줌)

🚨 **'늦었다' 판정은 없어요**(2026-10-19 사용자 결정). 전엔 입질 후 2.5초를 넘기면
놓침이었는데, 그 측정에는 **클릭이 봇까지 오는 시간**이 섞여 있어요. 모바일에서 제때
눌러도 늦게 도착해 놓치는 일이 생겨서 아예 없앴어요. 클라이언트가 **언제 눌렀는지**는
디스코드가 알려주지 않으니, 받은 시각으로 재는 건 결국 회선 속도를 재는 거예요.
→ `FishingView.strike`의 주석에 자세히 적어뒀어요. 되돌리지 말 것.

🚨 **그래도 시계는 메시지를 보낸 뒤에 찍어요.** 되돌리면 입질 메시지가 뜨기 전에
`bite_at` 깃발이 서서, 아직 아무것도 못 본 사람의 클릭이 '성급'을 면해버려요.

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

from cogs import mission
from utils import coin_wallet, fish_data, fishing_store
from utils.channel_check import restrict_to_channel
from utils.fish_data import (
    BY_KEY, COIN_PIECES, DAILY_CAST_CAP, FISH, GRADE_ORDER, GRADES,
    ROD_DURABILITY, ROD_PRICE, SMALL_ROD_DURABILITY, SMALL_ROD_PRICE,
    pieces_of, roll_size,
)

log = logging.getLogger(__name__)

CHANNEL_GROUP = "fishing"
CHANNEL_ENV = "FISHING_CHANNEL_ID"
COIN_LOG_NOTE = "낚시판매"
# 🚨 소각(낚시대)과 발행(판매)을 **다른 note로** 갈라요. 같으면 리포트에서
#    순발행을 계산할 수 없어요. 둘 다 "낚시"로 시작하지만 kind가 달라요.
ROD_NOTE = "낚시대"

BITE_MIN, BITE_MAX = 2.0, 8.0      # 입질까지 기다리는 시간
# 🚨 **입질 후에는 "늦었다"가 없어요**(2026-10-19 사용자 결정).
#    이건 "제한시간"이 아니라 **챔질을 기다려주는 시간**이에요. 이 안에 클릭이
#    도착하면 **언제 도착했든 성공**이고, 아무것도 안 오면 방치로 끝내요.
#    왜 바꿨는지는 `STRIKE_WAIT`를 쓰는 자리의 주석에 적어뒀어요.
STRIKE_WAIT = 6.0                  # 입질 후 챔질을 기다려주는 시간


def _streak_cast_hint(my_cap: int) -> str:
    """🔥 연속 출석으로 캐스트를 **늘리는 방법**을 알려주는 한 줄 (7차).

    🚨 **"막히는 그 자리"에 띄워요.** 만들어두고 안 쓰이는 걸 세 번 반복한 서버라
       (💡건의·📅일정·❓매니저, 리롤권·보호권·테마) 보너스를 상점이나 도움말에만
       적어두면 아무도 모른 채 20번에서 막혀요.
    ⚠️ 끝에 개행을 붙여서 돌려줘요(호출부가 문장을 이어 붙여요). 보너스가 꺼져
       있으면 **빈 문자열**이라 안내문이 저절로 사라져요.
    """
    if not DAILY_CAST_CAP or not fish_data.STREAK_CAST_MAX:
        return ""
    every, per = fish_data.STREAK_CAST_EVERY, fish_data.STREAK_CAST_BONUS
    bonus = my_cap - DAILY_CAST_CAP
    if bonus >= fish_data.STREAK_CAST_MAX:
        return f"-# 🔥 연속 출석 보너스 **+{bonus}번**을 받고 있어요 (최대치예요)\n"
    if bonus > 0:
        return (f"-# 🔥 연속 출석으로 **+{bonus}번** 받고 있어요 · "
                f"{every}일마다 **+{per}번** (최대 +{fish_data.STREAK_CAST_MAX}번)\n")
    return (f"-# 🔥 `/출석`을 **{every}일 연속**하면 던지는 횟수가 **+{per}번** 늘어요 "
            f"({every}일마다 · 최대 +{fish_data.STREAK_CAST_MAX}번)\n")

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
CAST_GUARD_TTL = BITE_MAX + STRIKE_WAIT + 15.0
WAIT_COLOR, BITE_COLOR = 0x2B6CB0, 0x38A169
MISS_COLOR = 0x6B7280

_GRADE_KEYS = {g: [f["key"] for f in rows] for g, rows in FISH.items()}


def roll_catch(rng: random.Random | None = None) -> str:
    """한 번 챔질에 **성공했을 때** 뭐가 잡히나.

    ⚠️ **꽝이 없어요**(2026-10-17 2차 설계). 타이밍만 맞히면 반드시 물고기가 나와요.
    1차엔 꽝 60%로 발행을 조절했는데, 꽝 확률은 1회당 수익만 낮출 뿐 **총 발행량을
    못 막아요**. 발행 조절은 `fish_data.ROD_PRICE`가 해요.

    🚨 **발행 상한은 `fish_data.DAILY_CAST_CAP`(하루 던진 횟수)에 있어요**(6차).
    낚시대 **개수**는 무제한이라, 개수로 발행량을 추정하면 통째로 틀려요. 1인 하루
    상한은 `fish_data.max_daily_net_issue()`가 알려줘요.

    못 잡는 경우는 이제 **타이밍 실패뿐**이고, 그건 내 실수지 운이 아니에요.

    🛑 **묶음 크기로 희귀를 깎는 인자를 다시 넣지 마세요.** 8차에 넣었다가 같은 날
    사용자가 "불합리하다"로 되돌렸어요 — 벌칙은 **바빠서 몰아 던지는 사람에게만**
    물려서, 몰아 던지기를 만든 이유("자리잡고 못 하는 사람을 돕자")와 어긋나요.
    몰아 던지기와 한 판은 **기대값이 같아야** 해요.
    → `utils/fish_data.BATCH_SIZES` 위 주석 · `test_fishing.py` [19]가 검사해요."""
    rng = rng or random
    grades = list(GRADES)
    weights = [GRADES[g]["weight"] for g in grades]
    grade = rng.choices(grades, weights=weights, k=1)[0]
    return rng.choice(_GRADE_KEYS[grade])


async def purchase_rod(user_id, small: bool = False) -> tuple[bool, str]:
    """낚시대 한 개를 사요. (성공, 안내문). `/악귀상점`과 🎣 버튼이 **같이** 써요.

    🚨 **지급을 먼저, 차감을 나중에** 해요. 반대로 하면 차감 뒤 지급이 실패했을 때
    코인만 사라져요. 차감이 실패하면 `refund_rod`로 되돌려서 공짜 낚시대를 막아요.
    (🎲 도박 한도 연장권과 같은 순서예요.)

    `small=True`면 ⭐ **입문용 소형 낚시대**(3코인/3번)예요. 횟수당 값이 큰 것과
    **똑같아서** 발행 구조는 안 바뀌고 진입 문턱만 낮아져요 — 자세한 이유는
    `utils/fish_data.py`의 `SMALL_ROD_PRICE` 주석에 있어요.
    ⚠️ **분기는 값 두 개뿐이에요.** 로직을 복사해서 두 함수로 만들면 지급→차감→환불
    순서를 한쪽만 고치는 사고가 나요(이 저장소에서 반복된 사고예요)."""
    price = SMALL_ROD_PRICE if small else ROD_PRICE
    durability = SMALL_ROD_DURABILITY if small else ROD_DURABILITY
    # 🚨 note를 갈라야 리포트에서 어느 쪽이 팔리는지 보여요. `낚시대`로 시작하니
    #    `report_economy.py`의 🎣 낚시대 집계에는 **둘 다** 그대로 들어가요.
    note = f"{ROD_NOTE}:소형" if small else ROD_NOTE
    label = "🎣 소형 낚시대" if small else "🎣 낚시대"

    # ⚠️ 하루 제한이 없어서(2026-10-17 4차) 지급은 항상 성공해요. 그래도 순서는
    #    그대로 지급 -> 차감 -> 실패 시 환불이에요.
    await fishing_store.buy_rod(user_id, durability)

    if not await coin_wallet.spend(user_id, price, reason=note):
        await fishing_store.refund_rod(user_id, durability)
        balance = await coin_wallet.get_balance(user_id)
        # ⭐ 큰 걸 못 사는 사람에게 **소형이 있다는 걸 알려줘요.** 이 안내가 없으면
        #    문턱을 낮춰도 그런 상품이 있는 줄 모르고 끝나요(상점 3종이 그래서 0건이었어요).
        hint = (f"\n-# 🎣 **소형 낚시대**는 **{SMALL_ROD_PRICE}코인**에 "
                f"**{SMALL_ROD_DURABILITY}번**이에요. 그쪽은 지금 살 수 있어요."
                if not small and balance >= SMALL_ROD_PRICE else
                "\n-# `/출석` · `/미션` · `/업적`으로 모을 수 있어요.")
        return False, (
            f"악귀코인이 부족해요. {label}는 **{price}코인**인데 "
            f"지금 **{balance}개** 있어요.{hint}"
        )

    balance = await coin_wallet.get_balance(user_id)
    log.info("🎣 낚시대 구매(%s): %s %d코인", "소형" if small else "일반", user_id, price)

    # ⭐ 하루 상한(2026-10-20 6차)을 **산 직후에 알려줘요.** 오늘 횟수가 다 찼거나
    #    내구도보다 적게 남았으면 "내일 이어서 쓴다"를 분명히 해야 해요 — 모르고
    #    사면 "코인만 날렸다"로 읽혀요(코인이 사라지는 건 아니지만 체감이 그래요).
    used, cap = await fishing_store.cast_quota(user_id)
    tail = "`/낚시` 로 시작해보세요"
    if cap:
        today_left = max(0, cap - used)
        if today_left == 0:
            tail = (f"⏳ **오늘 {cap}번을 이미 다 썼어요** — 이 낚시대는 "
                    "내일 자정부터 쓸 수 있어요")
        elif today_left < durability:
            tail = (f"⏳ 오늘은 **{today_left}번**만 더 던질 수 있어요 "
                    f"(나머지 {durability - today_left}번은 내일 이어서)")
    # ⭐ 7차: 상한 때문에 다 못 쓰게 됐을 때만 **늘리는 법**을 붙여요. 넉넉한 사람에게
    #    띄우면 잔소리예요(메시지가 길어지면 아무도 안 읽어요).
    hint = ""
    if cap and max(0, cap - used) < durability:
        hint = "\n" + _streak_cast_hint(cap).rstrip("\n")
    return True, (
        f"{label}를 샀어요! **{durability}번** 던질 수 있어요.\n"
        f"남은 악귀코인 **{balance}개** · {tail}" + hint
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
        await self._buy(interaction, small=False)

    # ⭐ **코인이 모자란 사람이 막히는 바로 그 자리**에 소형을 같이 띄워요. 상점 진열만
    #    해두면 발견이 안 돼요(리롤권·보호권·테마가 그래서 0건이에요).
    @discord.ui.button(label="소형 낚시대", emoji="🪝", style=discord.ButtonStyle.secondary)
    async def buy_small(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._buy(interaction, small=True)

    async def _buy(self, interaction: discord.Interaction, *, small: bool) -> None:
        await interaction.response.defer(ephemeral=True)
        ok, msg = await purchase_rod(interaction.user.id, small=small)
        try:
            # ⚠️ 실패했으면 뷰를 남겨둬요 — 큰 걸 못 사서 소형을 누를 수 있어야 해요.
            await interaction.edit_original_response(
                content=msg, view=None if ok else self)
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
    #    순이익이 실력과 무관하게 고정돼요. 전엔 못 하는 사람만 손해를 봤는데,
    #    그건 "못하면 벌칙"이 돼요.
    #
    # 🚨 **하루 횟수도 같이 돌려줘요**(`give_back_rod` 안에서). 안 그러면 놓친 판이
    #    하루 상한만 깎아먹어서, 상한이 생긴 6차에서는 벌칙이 두 배가 돼요.
    #
    # ⚠️ 그래도 **던지기 전 선차감**은 그대로예요. 돌려주는 건 결과가 난 뒤라,
    #    미니게임 도중에 `/낚시`를 여러 번 쳐서 한 개로 여러 판을 돌리는 건 여전히
    #    막혀요(동시에 여러 판을 열면 그만큼 선차감되니까요).
    if key is None:
        await fishing_store.give_back_rod(interaction.user.id)
        view.rod_left += 1

    # 🎣 주간 대회 적립은 `fishing_store.record_cast` **안에서** 일어나요.
    #    🚨 여기서 또 부르면 `caught`가 2배로 세어져요(2026-10-18에 실제로 그랬어요).
    await fishing_store.record_cast(interaction.user.id, key, size)

    # 🎯 🎣 "세 마리 낚기" 미션 (2026-10-23). **잡았을 때만** 1마리씩 올려요.
    #
    # 🚨 `COMMAND_MISSIONS`에 "낚시"를 넣으면 안 돼요 - 낚시대가 없어도 `/낚시` 명령어는
    #    정상 종료되니 세 번 쳐서 공짜로 깨요. 놓친 판(`key is None`)도 안 세는 게 맞아요:
    #    위에서 `give_back_rod`로 **하루 횟수를 돌려주니** 안 던진 것으로 치거든요.
    # ⚠️ 적립은 `record_cast` 뒤에 둬요. 미션 알림이 먼저 가면 "완료"가 떴는데 어항엔
    #    아직 없는 순간이 생겨요.
    if key:
        await mission.on_action(
            interaction.user.id, "catch_fish", interaction.channel, interaction.user
        )

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
        # 🚨 "늦었어요"는 없어요(2026-10-19). 남은 건 **입질 전에 누른 것**과
        #    **아예 안 누른 것** 둘뿐이에요. → `FishingView.strike`의 주석
        reason = {
            "early": "너무 일찍 챘어요. 미끼만 날아갔네요.",
            "afk": "챔질을 하지 않아서 물고기가 그냥 갔어요.",
        }.get(view.result, "놓쳤어요.")
        embed = discord.Embed(
            title="💨 놓쳤어요",
            description=reason + "\n-# 🎣 **횟수는 돌려드렸어요.** 다시 던져보세요!",
            color=MISS_COLOR)

    embed.add_field(name="어항", value=f"**{total}마리**", inline=True)
    embed.add_field(name="🎣 낚시대",
                    value=(f"**{view.rod_left}번** 남음" if view.rod_left
                           else "**부서졌어요**"), inline=True)

    # ⭐ 하루 상한을 **매 판 보여줘요**(2026-10-20 6차). 안 보여주면 20번째에서
    #    갑자기 막혀서 "버그 아니냐"가 돼요. 🎲 도박 한도도 같은 이유로 매번 띄워요.
    used, cap = await fishing_store.cast_quota(interaction.user.id)
    today_left = max(0, cap - used) if cap else None
    if cap:
        # ⭐ 7차: 보너스를 받고 있으면 **분모에 그게 보여요**(25/30 같은 식).
        #    "왜 내 상한이 남과 다르지?"를 그 자리에서 설명해주려고 +N을 적어요.
        bonus = cap - DAILY_CAST_CAP
        embed.add_field(name="오늘 남은 횟수",
                        value=((f"**{today_left}/{cap}번**" if today_left
                                else "**다 썼어요** (내일 자정에 채워져요)")
                               + (f"\n-# 🔥 연속 출석 +{bonus}" if bonus > 0 else "")),
                        inline=True)

    embed.set_footer(
        text=("/어항 으로 확인하고 /물고기판매 로 한 번에 팔아요"
              if view.rod_left and today_left != 0
              else (f"오늘은 {cap}번을 다 썼어요 · /물고기판매 로 팔아두세요"
                    if today_left == 0
                    else f"{ROD_PRICE}코인으로 새 낚시대를 사면 이어서 던질 수 있어요")))

    # 🎣 횟수가 남았으면 **바로 다시 던질 수 있게**, 없으면 **살 수 있게**.
    #    매번 `/낚시`를 치게 하면 10회짜리 낚시대가 고역이에요.
    #
    # 🚨 **하루 상한을 다 썼으면 둘 다 안 띄워요.** 다시던지기는 눌러도 거절되고,
    #    낚시대 구매는 오늘 못 쓰는 걸 사게 돼요(상한에 걸린 사람에게 파는 건
    #    🎲 "하루 한도를 넘는 1회 연장"과 같은 死상품이에요).
    if today_left == 0:
        next_view = None
    elif view.rod_left:
        next_view = CastAgainView(interaction.user.id, view.rod_left, today_left)
    else:
        next_view = BuyRodView(interaction.user.id)
    try:
        await interaction.edit_original_response(embed=embed, view=next_view)
    except discord.HTTPException:
        await interaction.followup.send(embed=embed, view=next_view, ephemeral=True)


async def finish_batch(interaction: discord.Interaction, view: "FishingView") -> None:
    """🎣 **몰아 던지기** 결과를 보여줘요 (8차). `_run_cast`가 `batch > 1`일 때 불러요.

    ## 규칙 (한 판 낚시와 일부러 다르게 둔 것만)

    - 챔질 **1회**가 묶음 전체를 판정해요. 성공하면 `batch`판이 전부 잡혀요.
    - 🚨 **놓치면 묶음 전체를 환불**해요(손해 0). 한 판 낚시의 `give_back_rod`와
      같은 원칙이고, 묶음은 `give_back_rods`로 한 번에 돌려줘요.
    - 🚨 **미스를 흉내내지 않아요.** 놓친 판은 하루 횟수까지 돌려주니(`finish_cast`
      주석) 미스는 **소비한 캐스트당 수익에 영향이 없어요** — 흉내내면 "자동인데
      왜 놓쳐?"라는 혼란만 남아요.
    - 🛑 **확률 벌칙이 없어요.** 8차에 묶음 크기에 따라 희귀를 깎는 규칙을 넣었다가
      같은 날 사용자가 되돌렸어요("불합리하다"). 바빠서 몰아 던지는 사람에게만
      물리는 벌칙이라 기능의 취지와 어긋나요. **다시 넣지 마세요.**

    ⚠️ 기록은 `record_casts` **한 번**으로 끝내요. `record_cast`를 N번 부르면
       Atlas 왕복이 N×2회라 30판이면 결과 화면이 몇 초씩 늦어요."""
    uid = interaction.user.id
    n = view.batch

    if view.result != "ok":
        # 🚨 묶음을 통째로 돌려줘요. 안 돌려주면 한 번 놓치고 하루치를 날려요.
        await fishing_store.give_back_rods(uid, n)
        view.rod_left += n
        reason = {
            "early": "너무 일찍 챘어요. 미끼만 날아갔네요.",
            "afk": "챔질을 하지 않아서 물고기가 그냥 갔어요.",
        }.get(view.result, "놓쳤어요.")
        used, cap = await fishing_store.cast_quota(uid)
        embed = discord.Embed(
            title="💨 전부 놓쳤어요",
            description=(f"{reason}\n"
                         f"**{n}번**을 묶어 던졌는데 한 번에 다 놓쳤어요 — "
                         f"**횟수는 전부 돌려드렸어요.**"),
            color=MISS_COLOR,
        )
        embed.set_footer(text="손해는 없어요 · 다시 던져보세요")
        today_left = max(0, cap - used) if cap else None
        next_view = (CastAgainView(uid, view.rod_left, today_left)
                     if view.rod_left else BuyRodView(uid))
        try:
            await interaction.edit_original_response(embed=embed, view=next_view)
        except discord.HTTPException:
            await interaction.followup.send(embed=embed, view=next_view, ephemeral=True)
        return

    # ── 성공: n판을 굴려요 ────────────────────────────────────────────
    # 🚨 `n`은 **받은 수**(`view.batch` = `granted`)예요. 요청한 수로 굴리면
    #    받지도 않은 캐스트로 물고기를 만들어서 **없는 코인을 발행**해요.
    catches: list[tuple[str, int]] = []
    for _ in range(n):
        key = roll_catch()
        catches.append((key, roll_size(key)))

    await fishing_store.record_casts(uid, n, catches)

    # 🎯 🎣 "세 마리 낚기" — 묶음은 **목표치만큼만** 불러요.
    #    `progress`는 1씩 올리니 N번 불러야 N마리가 세어지는데, 목표를 넘겨 부르면
    #    아무 일도 안 일어나요(이미 깬 미션). 30판이면 왕복이 60회라 그만큼 늦어요.
    # 🚨 목표치를 손으로 적지 마세요 — `MISSIONS`에서 읽어요.
    target = int((mission.MISSIONS.get("catch_fish") or {}).get("target") or 1)
    for _ in range(min(len(catches), target)):
        await mission.on_action(uid, "catch_fish", interaction.channel, interaction.user)

    # ── 결과 표 ──────────────────────────────────────────────────────
    total_pieces = sum(pieces_of(k, s) for k, s in catches)
    by_grade: dict[str, int] = {}
    for key, _size in catches:
        by_grade[BY_KEY[key][0]] = by_grade.get(BY_KEY[key][0], 0) + 1

    # 📏 묶음 안의 최고 한 마리 — 등급이 먼저, 같으면 치수
    def _rank(key: str) -> int:
        return len(GRADE_ORDER) - GRADE_ORDER.index(BY_KEY[key][0])

    bkey, bsize = max(catches, key=lambda kv: (_rank(kv[0]), kv[1]))
    bgrade, bname = BY_KEY[bkey]
    blo, bhi = fish_data.SIZE_BY_KEY[bkey]
    bpct = int((bsize - blo) / max(1, bhi - blo) * 100)
    btag = " 🏆 **최대급!**" if bpct >= 90 else (" ✨ 큼직해요" if bpct >= 70 else "")

    embed = discord.Embed(
        title=f"🎣 {n}번 던져서 {len(catches)}마리!",
        description=f"판매가 합계 **{total_pieces / COIN_PIECES:.1f}코인**",
        color=GRADES[bgrade]["color"],
    )
    embed.add_field(
        name="등급별",
        value=" · ".join(f"{GRADES[g]['emoji']} **{g}** {by_grade[g]}마리"
                         for g in GRADE_ORDER if g in by_grade),
        inline=False,
    )
    embed.add_field(
        name="가장 좋은 놈",
        value=f"{GRADES[bgrade]['emoji']} **{bgrade} · {bname} {bsize}cm**{btag}",
        inline=False,
    )
    # ⚠️ 전부 나열하면 30마리에서 임베드가 터져요(필드 1024자). 희귀 이상만 적어요 —
    #    일반은 등급별 수만 보여줘도 충분하고, 사람들이 궁금한 건 희귀 쪽이에요.
    rare = [(k, s) for k, s in catches if BY_KEY[k][0] != fish_data.COMMON_GRADE]
    if rare:
        lines = [f"{GRADES[BY_KEY[k][0]]['emoji']} {BY_KEY[k][1]} {s}cm "
                 f"({pieces_of(k, s) / COIN_PIECES:.1f}코인)"
                 for k, s in sorted(rare, key=lambda kv: -_rank(kv[0]))[:12]]
        more = len(rare) - len(lines)
        embed.add_field(
            name=f"🐠 희귀 이상 {len(rare)}마리",
            value="\n".join(lines) + (f"\n-# 외 {more}마리" if more > 0 else ""),
            inline=False,
        )

    state = await fishing_store.get(uid)
    total = sum(len(v) for v in state["tank"].values())
    used, cap = await fishing_store.cast_quota(uid)
    today_left = max(0, cap - used) if cap else None
    embed.add_field(name="어항", value=f"**{total}마리** 모여 있어요", inline=True)
    if cap:
        bonus = cap - DAILY_CAST_CAP
        embed.add_field(
            name="오늘 남은 횟수",
            value=((f"**{today_left}/{cap}번**" if today_left
                    else "**다 썼어요** (내일 자정에 채워져요)")
                   + (f"\n-# 🔥 연속 출석 +{bonus}" if bonus > 0 else "")),
            inline=True,
        )
    embed.set_footer(text="확률은 한 판씩 던질 때와 똑같아요 "
                          "· /물고기판매 로 한 번에 팔아요")

    next_view = (CastAgainView(uid, view.rod_left, today_left)
                 if view.rod_left else BuyRodView(uid))
    try:
        await interaction.edit_original_response(embed=embed, view=next_view)
    except discord.HTTPException:
        await interaction.followup.send(embed=embed, view=next_view, ephemeral=True)

    log.info("🎣 몰아 던지기: %s / %d판 %d마리 %.1f코인",
             uid, n, len(catches), total_pieces / COIN_PIECES)


class CastAgainView(discord.ui.View):
    """🎣 다시 던지기 - 결과 화면에 붙어요.

    낚시대가 10회라 `/낚시`를 열 번 치게 하는 건 번거로워요. 🎴 뽑기의 "한 번 더"와
    같은 패턴이에요.

    🚨 **연타 방어가 필수예요.** 내구도는 던지기 전에 깎이니까, 두 번 눌리면
    **1판만 돌면서 2회가 사라져요.** `_started`로 한 번만 통과시켜요(봇이 단일
    프로세스라 인스턴스 상태로 충분해요).

    ⚠️ 같은 ephemeral 메시지를 **재사용**해요(`edit=True`). 새 메시지를 띄우면
    던질 때마다 쌓여서 어느 게 지금 찌인지 알 수 없어져요."""

    def __init__(self, user_id: int, rod_left: int, today_left: int | None = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self._started = False
        # ⭐ 둘 중 **먼저 바닥나는 쪽**을 라벨에 적어요. 낚시대가 8번 남았는데 오늘
        #    2번만 남았으면 "8번 남음"은 거짓이에요(눌러보고 나서 막히면 혼란스러워요).
        left = rod_left if today_left is None else min(rod_left, today_left)
        self.again.label = f"다시 던지기 ({left}번 남음)"

        # ⭐ 🎣 **몰아 던지기 버튼**(8차). 사용자가 "결과 화면 버튼 + `/낚시` 옵션
        #    둘 다"로 정했어요. → `utils/fish_data.BATCH_SIZES`
        #
        # 🚨 **던질 수 있는 수보다 큰 묶음은 아예 안 보여줘요.** 보여주고 나서
        #    "5번 남았는데 10번 버튼"을 누르면 5판만 돌아가는데, 그건 유저가
        #    **벌칙은 10판 기준으로 받는다고 오해**할 자리예요(실제로는 받은 수
        #    기준으로 계산해요 — `_run_cast`의 `granted` 주석).
        # ⚠️ 라벨에 숫자를 손으로 적지 않아요. 묶음 크기를 바꾸면 버튼이 따라와요.
        for size in fish_data.BATCH_SIZES:
            if left > size:
                btn = discord.ui.Button(
                    label=f"{size}번 몰아 던지기", emoji="🎣",
                    style=discord.ButtonStyle.secondary, row=1)
                btn.callback = self._make_batch(size)
                self.add_item(btn)
        # 「남은 전부」는 **2판 이상 남았을 때만** — 1판이면 '다시 던지기'와 같아요.
        if left > 1:
            all_btn = discord.ui.Button(
                label=f"남은 {left}번 전부", emoji="🎣",
                style=discord.ButtonStyle.success, row=1)
            all_btn.callback = self._make_batch(0)
            self.add_item(all_btn)

    def _make_batch(self, size: int):
        """묶음 버튼의 콜백을 만들어요. `size=0`이면 **남은 전부**예요.

        🚨 `again`과 **같은 연타 가드**(`self._started`)를 써요. 따로 두면
        '다시 던지기'와 '10번 몰아'를 동시에 눌러 두 판이 겹쳐요."""
        async def _cb(interaction: discord.Interaction):
            if self._started:
                await interaction.response.defer()
                return
            self._started = True
            try:
                started = await run_cast(interaction, edit=True, batch=size)
            except Exception:
                self._started = False
                raise
            if not started:
                self._started = False
        return _cb

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


async def run_cast(interaction: discord.Interaction, *, edit: bool,
                   batch: int = 1) -> bool:
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
        return await _run_cast(interaction, edit=edit, batch=batch)
    finally:
        _casting.pop(uid, None)


async def _run_cast(interaction: discord.Interaction, *, edit: bool,
                    batch: int = 1) -> bool:
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
    #
    # ⭐ 🎣 **몰아 던지기**(8차). `batch`가 몇 판을 묶을지예요 — `0`이면 **남은 전부**.
    #
    # 🚨 요청한 만큼 **못 받을 수 있어요**(상한·내구도가 모자랄 때). 아래부터는
    #    `want`가 아니라 **`granted`**를 써야 해요. `want`로 굴리면 받지도 않은
    #    캐스트로 물고기를 만들어서 **없는 코인을 발행**해요.
    # 🚨 `use_rods`는 **3-튜플**이에요(`use_rod`는 2-튜플). 섞어 받으면 `blocked`
    #    자리에 숫자가 들어가서 상한도 품절도 안 걸리고 그냥 던져져요.
    want = batch if batch > 0 else 0
    if want == 0:
        # "남은 전부" — 상한과 내구도 중 **먼저 바닥나는 쪽**까지예요.
        # ⚠️ `use_rods`가 어차피 둘 다 보고 깎지만, `want=0`을 넘기면 0개를 받아요.
        #    그래서 여기서 한 번 읽어 상한을 알아내요(무제한이면 내구도까지).
        used_q, cap_q = await fishing_store.cast_quota(uid)
        rod_q, _ = await fishing_store.rod_state(uid)
        want = max(1, min(rod_q, cap_q - used_q) if cap_q else max(1, rod_q))
    granted, left, blocked = await fishing_store.use_rods(uid, want)

    if blocked == "cap":
        # ⭐ 하루 상한. **낚시대는 안 깎였어요** — 남은 횟수를 같이 알려줘서
        #    "낚시대가 사라진 게 아니다"를 분명히 해요.
        # 🚨 여기서 낚시대 구매 버튼을 띄우면 **오늘 못 쓰는 걸 사게 돼요.**
        #
        # 🚨 **`DAILY_CAST_CAP`을 적지 마세요**(7차). 상한이 사람마다 달라졌어요.
        #    보너스를 받은 사람에게 "20번을 다 던졌어요"라고 하면 거짓이에요.
        _, my_cap = await fishing_store.cast_quota(uid)
        await show(
            content=(f"🎣 오늘은 **{my_cap}번**을 다 던졌어요. "
                     f"내일 자정(한국 시간)에 다시 채워져요.\n"
                     f"-# 🎣 낚시대는 그대로 있어요"
                     + (f" (**{left}번** 남음)" if left else "")
                     + f" · 하루 {my_cap}번이면 평균 "
                     f"**{fish_data.income_for_cap(my_cap):.0f}코인**쯤 벌려요\n"
                     + _streak_cast_hint(my_cap)
                     + "-# `/어항` 으로 확인하고 `/물고기판매` 로 팔아두세요"),
            embed=None,
            view=None,
        )
        return True

    if blocked == "no_rod":
        quota_hint = ""
        used, cap = await fishing_store.cast_quota(uid)
        if cap:
            # ⚠️ 낚시대를 사라고 하기 **전에** 오늘 몇 번 남았는지 알려줘요. 상한이
            #    1~2번만 남았는데 10회짜리를 사면 나머지는 내일로 넘어가거든요.
            quota_hint = f"\n-# 오늘 남은 횟수는 **{max(0, cap - used)}번**이에요"
        await show(
            content=(f"🎣 낚시대가 없어요. **{ROD_PRICE}코인**으로 하나 사면 "
                     f"**{ROD_DURABILITY}번** 던질 수 있어요.\n"
                     # 🚨 숫자를 손으로 적지 마세요. 6차에서 값이 x1.5가 됐는데
                     #    여기 "평균 14코인"이 박혀 있었어요(5차 값).
                     f"-# 10번 던지면 평균 "
                     f"**{fish_data.expected_coin_per_day():.0f}코인**쯤 벌려요"
                     + quota_hint),
            # ⚠️ 메시지를 재사용하니 이전 임베드를 **명시적으로 지워야** 해요.
            embed=None,
            view=BuyRodView(uid),
        )
        return True

    if blocked or granted <= 0:
        # ⭐ `"race"` — 조건부 update가 동시 요청에 계속 졌어요(8차에 생긴 사유).
        #    아무것도 안 깎였으니 그냥 다시 누르면 돼요.
        # 🚨 `granted <= 0`을 **같이** 보는 게 중요해요. 새 사유가 생겼을 때
        #    분기를 빠뜨리면 0판으로 미니게임이 돌아가서 "잡았는데 어항이 안 늘어요"가 돼요.
        await show(
            content=("🎣 방금 다른 처리가 먼저 들어갔어요. **다시 눌러주세요.**\n"
                     "-# 낚시대도 횟수도 **그대로**예요."),
            embed=None, view=None,
        )
        log.info("🎣 캐스트 차감 실패 (user=%s want=%s reason=%s)", uid, want, blocked)
        return True

    view = FishingView(uid)
    view.rod_left = left
    view.batch = granted
    if granted > 1:
        # ⭐ 묶음이면 **몇 판인지를 먼저** 보여줘요. 요청보다 적게 받았을 수 있어서
        #    (상한·내구도가 모자랄 때) "내가 누른 수"가 아니라 **받은 수**를 적어요.
        embed = discord.Embed(
            title=f"🎣 {granted}번 몰아 던졌어요",
            description=("찌를 지켜보세요... **입질이 오면 한 번만 챔질!**\n"
                         f"그 한 번으로 **{granted}판**이 전부 판정돼요."),
            color=WAIT_COLOR,
        )
        # 🛑 "희귀 확률이 N% 낮아져요"가 있던 자리예요. 8차에 벌칙을 넣었다가
        #    사용자가 되돌렸어요 — **확률이 같다는 걸 명시**해요(안 적으면
        #    "몰아 던지면 손해 아닌가?"를 각자 추측해요).
        embed.set_footer(
            text="확률은 한 판씩 던질 때와 똑같아요 · 놓치면 횟수를 전부 돌려받아요")
    else:
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

        # 🚨 시계는 **메시지를 보낸 뒤에** 시작해요.
        #
        # 전에는 `edit_original_response` **앞**에서 찍었는데, 그 호출이 디스코드까지
        # 다녀오는 데 100~300ms가 걸려요. 즉 유저가 "입질!"을 보기도 전에 시간이
        # 흐르기 시작했어요(2026-10-17 사용자 신고).
        #
        # ⚠️ `bite_at`은 이제 **판정에 안 쓰여요**(늦었다를 없앴으니까요). '입질이
        #    왔다'를 표시하는 깃발일 뿐이라, 입질 전에 누른 걸 가려내는 데만 써요.
        #    그래도 순서는 그대로 지켜요 — 되돌리면 입질 메시지가 뜨기 **전에**
        #    깃발이 서서, 아직 아무것도 못 본 사람의 클릭이 '성급'을 면해버려요.
        view.bite_at = time.monotonic()
        try:
            await asyncio.wait_for(view.done.wait(), timeout=STRIKE_WAIT)
        except asyncio.TimeoutError:
            # ⭐ 여기까지 왔으면 클릭이 **아예 안 온** 거예요(= 방치). 늦게 눌러서가
            #    아니에요 — 늦은 클릭은 위 `wait_for`가 받아서 성공으로 처리해요.
            view.result = "afk"
            view.done.set()

    view.stop()
    # 🚨 여기서 터지면 유저는 **아무 반응도 못 봐요**(찌만 띄워놓고 끝).
    #    2026-10-17에 "눌렀는데 봇이 반응이 없다"는 신고가 있었는데 로그가 없어서
    #    원인 찾기가 어려웠어요. 결과 표시 실패는 반드시 흔적을 남겨요.
    try:
        if view.batch > 1:
            await finish_batch(interaction, view)
        else:
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
        super().__init__(timeout=BITE_MAX + STRIKE_WAIT + 10)
        self.user_id = user_id
        self.bite_at: float | None = None     # 입질이 왔다는 깃발 (None = 아직)
        self.done = asyncio.Event()
        self.result: str | None = None        # "early" | "afk" | "ok"
        self.caught: str | None = None
        self.size: int | None = None          # 📏 잡힌 물고기의 치수(cm)
        self.rod_left = 0                     # 이번 캐스트 뒤 남은 내구도
        # ⭐ 🎣 몰아 던지기(8차). 이 찌가 **몇 판을 묶고 있나**예요. 1이면 한 판.
        # ⚠️ 이 뷰는 **한 사람의 한 번**에만 쓰이는 일회성이라 상태를 담아도 돼요
        #    (영속 뷰라면 금지예요 — `cogs/suggestion.py` 주석 참고).
        self.batch = 1

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
                #
                # ⭐ 지연은 이쪽을 **느슨하게** 만들어요(클릭이 늦게 도착하면 입질 뒤가
                #    되니까요). 그래서 '성급'은 지연과 무관하게 진짜 실수뿐이에요.
                self.result = "early"
            else:
                # 🚨 **입질 뒤에 눌렀으면 언제 눌렀든 성공이에요**(2026-10-19 사용자 결정).
                #
                # 전엔 `monotonic() - bite_at > BITE_WINDOW`면 "늦었어요"로 돌렸어요.
                # 그런데 그 뺄셈에는 **클릭이 봇까지 오는 시간이 섞여 있어요.** 모바일은
                # 앱이 백그라운드였거나 망이 느리면 그게 초 단위로 벌어져요. 즉 유저가
                # 제때 눌러도 **봇에게는 늦게 도착**해서, 실력이 아니라 기기·회선 탓으로
                # 놓치는 판이 생겼어요(사용자가 모바일에서 직접 확인했어요).
                #
                # 클라이언트가 **언제 눌렀는지**는 알 방법이 없어요(디스코드가 클릭 시각을
                # 안 줘요). 받은 시각으로 재는 건 결국 지연을 재는 거예요. 그래서 판정을
                # 없앴어요 — 챔질이 **도착하기만 하면** 잡혀요.
                #
                # ⚠️ 그래도 미니게임은 남아요: 입질 전에 누르면 여전히 '성급'이고,
                #    아무것도 안 누르면 방치로 끝나요(`STRIKE_WAIT` 참고).
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
        # ⚠️ 여기까지 오면 `run_cast`의 `STRIKE_WAIT`가 이미 지난 거예요(뷰 타임아웃이
        #    10초 더 길어요). 그래서 사실상 안 불리지만, 불리더라도 **방치**예요.
        if not self.done.is_set():
            self.result = "afk"
            self.done.set()


class Fishing(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="낚시", description="찌를 던져 물고기를 낚아요. (낚시대가 필요해요)")
    @app_commands.describe(
        횟수="한 번에 몰아서 던질 횟수 (안 적으면 1판 · 확률은 한 판씩과 똑같아요)")
    @app_commands.choices(횟수=[
        app_commands.Choice(name="1번 (한 판씩)", value=1),
        # ⚠️ 선택지 이름에 **숫자나 확률을 손으로 적지 않아요.** 8차에 "희귀 확률
        #    그대로"라고 적어뒀는데, 벌칙을 되돌리면서 그 말이 **벌칙이 있다는 뜻으로
        #    읽히는** 자리가 됐어요. 수치 안내는 `/낚시확률`이 계산해서 해요.
        app_commands.Choice(name="5번 몰아 던지기", value=5),
        app_commands.Choice(name="10번 몰아 던지기", value=10),
        app_commands.Choice(name="남은 횟수 전부 몰아 던지기", value=0),
    ])
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def fish(self, interaction: discord.Interaction,
                   횟수: app_commands.Choice[int] | None = None):
        """🎣 한 판 또는 **몰아 던지기**(8차).

        ⚠️ 선택지는 `BATCH_SIZES`와 맞춰 두세요. 데코레이터엔 f-string을 못 써서
           손으로 적을 수밖에 없는 자리인데, `test_fishing.py`가 둘이 어긋나면 잡아요."""
        await run_cast(interaction, edit=False,
                       batch=(횟수.value if 횟수 else 1))

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

        # ⭐ 하루 상한(2026-10-20 6차). 낚시대 남은 횟수와 **별개**라 따로 보여줘요 —
        #    "낚시대는 8번 남았는데 왜 못 던지냐"를 막는 자리예요.
        used, cap = await fishing_store.cast_quota(interaction.user.id)
        if cap:
            # ⭐ 7차: 연속 출석 보너스를 받고 있으면 그 몫을 따로 적어요.
            _b = cap - DAILY_CAST_CAP
            embed.add_field(
                name="오늘 남은 횟수",
                value=((f"**{max(0, cap - used)}/{cap}번**" if used < cap
                        else "**다 썼어요**\n-# 내일 자정(한국 시간)에 채워져요")
                       + (f"\n-# 🔥 연속 출석 +{_b}" if _b > 0 else "")),
                inline=True)

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

        # 🎣 주간 대회의 💰 최다 수익도 `fishing_store.add_sold` 안에서 같이 쌓여요.
        #    🚨 여기서 또 부르면 `sold`가 2배가 돼요(수익 순위가 통째로 틀려져요).
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
        🚨 **7차부터 DB를 한 번 다녀와요**(내 상한을 알려주려고 `cast_quota`를 봐요).
        그래서 **먼저 받아둬야** 해요 — 안 그러면 Atlas가 느린 날 3초를 넘겨서
        `10062`로 죽어요. `scripts/scan_interaction_latency.py`가 실제로 이걸 잡았고
        (`test_cog_load`가 그 스캐너를 불러서 **배포를 막아요**), 전엔 "DB를 안
        건드려서 defer 없이 바로 답해도 된다"는 주석이 붙어 있었어요.
        """
        await interaction.response.defer()
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
                   f"　└ 🪝 **소형**은 {SMALL_ROD_PRICE}코인에 "
                   f"**{SMALL_ROD_DURABILITY}번** — 횟수당 값이 **똑같아요**\n"
                   "　└ **몇 개든** 살 수 있어요 (개수 제한은 없어요)"),
            inline=False,
        )
        per_cast = fish_data.expected_coin_per_cast()
        per_rod = fish_data.expected_coin_per_day()
        net = fish_data.net_issue_per_rod()
        # ⭐ 하루 상한을 **"평균 얼마 벌리나"보다 먼저** 보여줘요. 벌이만 보고 기대를
        #    키웠다가 상한을 뒤늦게 발견하면 속은 기분이 들어요.
        if DAILY_CAST_CAP:
            # ⭐ 7차: **내 상한**을 보여줘요(사람마다 달라졌어요). `/낚시확률`은
            #    본인이 치는 명령이라 여기선 본인 값을 적는 게 맞아요.
            _, my_cap = await fishing_store.cast_quota(interaction.user.id)
            _bonus = my_cap - DAILY_CAST_CAP
            embed.add_field(
                name="⏳ 하루 던질 수 있는 횟수",
                value=(f"기본 **{DAILY_CAST_CAP}번** · **내 상한은 {my_cap}번**이에요 "
                       "(한국 시간 자정에 채워져요)\n"
                       + (f"　└ 🔥 연속 출석 보너스 **+{_bonus}번**을 받고 있어요"
                          + ("  (최대치예요)\n" if _bonus >= fish_data.STREAK_CAST_MAX
                             else "\n")
                          if _bonus > 0 else
                          f"　└ 🔥 `/출석`을 **{fish_data.STREAK_CAST_EVERY}일 연속**하면 "
                          f"**+{fish_data.STREAK_CAST_BONUS}번** 늘어나요 "
                          f"(최대 +{fish_data.STREAK_CAST_MAX}번)\n")
                       + "　└ ⭐ 상한에 걸려도 **낚시대는 안 없어져요** — 남은 횟수는 "
                       "다음 날 이어서 써요\n"
                       f"　└ 어떤 낚시대를 쓰든 상한은 같아요 "
                       f"(🪝 소형도 하루 {my_cap}번 중 한 번이에요)"),
                inline=False,
            )
        embed.add_field(
            name="⭐ 평균 얼마 벌리나",
            value=(f"한 번 던지면 평균 **{per_cast:.1f}코인** → 낚시대 하나로 "
                   f"약 **{per_rod:.0f}코인**\n"
                   f"　└ 낚시대값 {ROD_PRICE}코인을 빼면 **{net:+.0f}코인**쯤 남아요\n"
                   # 🚨 **내 상한 기준**으로 적어요(7차). `DAILY_CAST_CAP`으로 적으면
                   #    보너스를 받는 사람에게 실제보다 적게 말해요.
                   + (f"　└ 🏁 내 상한 {my_cap}번을 다 쓰면 "
                      f"**{fish_data.income_for_cap(my_cap):.0f}코인**쯤 벌리고, "
                      f"낚시대값을 빼면 "
                      f"**{my_cap * fish_data.net_issue_per_cast():+.0f}코인**"
                      "이 남아요\n" if DAILY_CAST_CAP else "")
                   + "　└ ⚠️ 판매는 **내림**이에요(1코인 = 10조각) — 남는 조각은 "
                   "다음 판매로 넘어가요"),
            inline=False,
        )
        # ⭐ 🎣 몰아 던지기 안내(8차). 🛑 여기 "희귀 확률이 낮아져요" 표가 있었는데
        #    벌칙을 되돌리면서 **같이 지웠어요.** 안내문만 남으면 거짓이 돼요.
        #    🚨 "확률이 똑같다"를 **명시**해야 해요 — 안 적으면 "몰아 던지면
        #       손해 아닌가?"를 각자 추측해요(그게 기능을 안 쓰게 만들어요).
        if fish_data.BATCH_SIZES:
            picks = " · ".join(f"`{n}번`" for n in fish_data.BATCH_SIZES)
            embed.add_field(
                name="🎣 몰아 던지기 — 한 번 눌러 여러 판",
                value=(f"`/낚시 횟수:` 에서 {picks} · `남은 전부`를 고르거나, "
                       "결과 화면의 **몰아 던지기** 버튼을 눌러요.\n"
                       "　└ 입질을 기다려 **한 번만 챔질**하면 묶음 전체가 판정돼요\n"
                       "　└ ⭐ **확률·값은 한 판씩 던질 때와 똑같아요** "
                       "(몰아 던져서 손해 보는 건 없어요)\n"
                       f"　└ 하루 상한({my_cap}번)은 **똑같이** 써요 — 더 벌리는 게 "
                       "아니라 **빨리 쓰는** 거예요\n"
                       "　└ 챔질을 놓치면 **묶음 전체를 돌려받아요**"),
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
            value=("**입질이 온 뒤에 누르면 반드시 뭔가 나와요.**\n"
                   "　└ 늦게 눌러도 괜찮아요 — **'늦었다'는 판정이 없어요**\n"
                   "　└ 입질 전에 누르거나 아예 안 누르면 놓치지만, "
                   "그때도 **횟수를 돌려드려요**"),
            inline=False,
        )
        embed.set_footer(text="/어항 에서 지금 가치를 확인해보세요")
        # 🚨 위에서 `defer()`를 했으니 **followup**이에요. `response.send_message`를
        #    그대로 두면 `InteractionResponded`로 터져요(7차에 defer를 넣으면서 같이
        #    고쳤어요 — AST 검사로는 안 잡히는 종류라 테스트가 실제로 돌려봐요).
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fishing(bot))
