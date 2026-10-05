"""도박 게임 3종의 **순수 로직**이에요. 디스코드도 DB도 모르고, 숫자만 다뤄요.

## 왜 코인 소비처로 도박인가 (2026-10-05)

공정한 도박은 소비처가 **아니에요**. 사람끼리 걸면(`/내전베팅`) 진 사람 코인이 이긴 사람에게
갈 뿐 총량은 그대로예요. 코인이 사라지려면 **하우스 몫(엣지)** 이 있어야 해요.

엣지가 있는 게임은 그동안 없던 성질을 가져요 — **무한 반복되고, 소각량이 활동량에 비례해서
자동으로 조절돼요.** 테마(6종 90코인이면 소진) 같은 유한한 소비처로는 못 하던 일이에요.

## 환수율(RTP)을 상수로 못 박지 않고 '계산'하는 이유

배당표를 손으로 고치다 보면 환수율이 슬그머니 100%를 넘어요(= 코인을 찍어내는 기계가 돼요).
그래서 슬롯·하이로우는 **배당표에서 환수율을 정확히 계산하는 함수**를 같이 두고,
`scripts/test_casino.py`가 0.85~0.95 밖으로 나가면 실패하게 해뒀어요.

⚠️ 코인은 정수예요. 배당은 전부 **베팅액의 정수 배수**로만 둬요(0.5배 같은 걸 쓰면
1코인 베팅에서 반올림 때문에 환수율이 틀어져요).
"""
import random
from itertools import product

# ── 🎰 슬롯 ───────────────────────────────────────────────────────────────
# 릴 3개, 심볼 4종(균등). 심볼이 적을수록 '세 개 일치'가 자주 나와서 배당을 낮게 둘 수 있어요.
# 심볼 6종으로 하면 세 개 일치가 1/36이라 배당이 17배까지 올라가고, 지갑 중앙값이 3코인인
# 서버에서 한 번에 90코인이 튀어나와요. 4종이면 1/16이라 4~7배로 끝나요(= 변동성이 낮아요).
SLOT_SYMBOLS: tuple[tuple[str, int], ...] = (
    ("💣", 4),   # (심볼, 세 개 일치 배당)
    ("🔫", 5),
    ("🛡️", 6),
    ("💎", 7),
)
SLOT_PAIR_PAYOUT = 1   # 두 개 일치 = 본전 (베팅액 그대로 돌려줘요)


def slot_rtp() -> float:
    """배당표에서 환수율을 **정확히** 계산해요(몬테카를로가 아니라 전수 계산)."""
    total = 0.0
    combos = list(product(range(len(SLOT_SYMBOLS)), repeat=3))
    for combo in combos:
        total += _slot_payout_multiplier(combo)
    return total / len(combos)


def _slot_payout_multiplier(combo: tuple[int, int, int]) -> int:
    a, b, c = combo
    if a == b == c:
        return SLOT_SYMBOLS[a][1]
    if a == b or b == c or a == c:
        return SLOT_PAIR_PAYOUT
    return 0


def spin_slot(rng: random.Random | None = None) -> tuple[list[str], int, str]:
    """(릴 3개 심볼, 배당 배수, 결과 설명)."""
    rng = rng or random
    combo = tuple(rng.randrange(len(SLOT_SYMBOLS)) for _ in range(3))
    multiplier = _slot_payout_multiplier(combo)
    symbols = [SLOT_SYMBOLS[i][0] for i in combo]
    if multiplier == 0:
        note = "꽝"
    elif multiplier == SLOT_PAIR_PAYOUT:
        note = "두 개 일치 — 본전이에요"
    else:
        note = f"**세 개 일치!** {SLOT_SYMBOLS[combo[0]][0]} {multiplier}배"
    return symbols, multiplier, note


# ── 🎲 하이로우 ────────────────────────────────────────────────────────────
# 1~100 중 하나를 굴려요. 높다(56~100) / 낮다(1~45) 각각 45칸이고,
# **46~55 열 칸이 하우스 몫**이에요. 그래서 맞출 확률이 45%, 배당 2배 → 환수율 정확히 90%.
# 엣지를 숨기지 않고 '하우스 구간'으로 눈에 보이게 둔 거예요.
HIGHLOW_MAX = 100
HIGHLOW_LOW_MAX = 45        # 1~45 = 낮다 승
HIGHLOW_HIGH_MIN = 56       # 56~100 = 높다 승
HIGHLOW_PAYOUT = 2          # 맞히면 베팅액의 2배


def highlow_rtp() -> float:
    wins = HIGHLOW_LOW_MAX
    return wins / HIGHLOW_MAX * HIGHLOW_PAYOUT


def roll_highlow(choice: str, rng: random.Random | None = None) -> tuple[int, int, str]:
    """(굴린 수, 배당 배수, 결과 설명). choice는 "high" 또는 "low"."""
    rng = rng or random
    number = rng.randint(1, HIGHLOW_MAX)

    if number <= HIGHLOW_LOW_MAX:
        winner = "low"
    elif number >= HIGHLOW_HIGH_MIN:
        winner = "high"
    else:
        winner = "house"

    if winner == "house":
        return number, 0, f"**{number}** — 하우스 구간({HIGHLOW_LOW_MAX + 1}~{HIGHLOW_HIGH_MIN - 1})이에요 😈"
    if winner == choice:
        return number, HIGHLOW_PAYOUT, f"**{number}** — 맞혔어요!"
    return number, 0, f"**{number}** — 빗나갔어요"


# ── 🃏 블랙잭 ──────────────────────────────────────────────────────────────
# 딜러는 17 이상이 될 때까지 뽑아요. **무승부는 베팅액을 돌려줘요.**
# ⚠️ 무승부를 하우스가 먹게 하면 환수율이 83%까지 떨어져요(2026-10-05 30만판 시뮬레이션).
#    너무 가혹해서, 대신 **블랙잭 배당을 2.5배가 아닌 2배**로 줄여 엣지를 만들었어요 → 약 92%.
# ⚠️ 이 92%는 "17 될 때까지 뽑는" 평범한 플레이 기준이에요. 더 잘 치는 사람은 환수율이
#    올라가요. 그래서 소각량의 실제 안전장치는 배당표가 아니라 **하루 베팅 한도**예요.
BJ_WIN_PAYOUT = 2
BJ_PUSH_PAYOUT = 1       # 무승부 = 베팅액 반환
BJ_BLACKJACK_PAYOUT = 2  # 2장 21 (보통 카지노는 2.5배지만 여기선 엣지를 위해 2배)
BJ_DEALER_STANDS_AT = 17

CARD_NAMES = {1: "A", 11: "J", 12: "Q", 13: "K"}
SUITS = ("♠", "♥", "♦", "♣")


def new_deck(rng: random.Random | None = None) -> list[int]:
    rng = rng or random
    deck = [rank for rank in range(1, 14) for _ in SUITS]
    rng.shuffle(deck)
    return deck


def hand_value(cards: list[int]) -> int:
    """A는 21을 넘지 않는 선에서 11로 쳐요."""
    total = sum(min(card, 10) for card in cards)
    aces = cards.count(1)
    while aces and total + 10 <= 21:
        total += 10
        aces -= 1
    return total


def card_label(card: int) -> str:
    return CARD_NAMES.get(card, str(card))


def hand_label(cards: list[int]) -> str:
    return " ".join(f"`{card_label(c)}`" for c in cards)


def is_blackjack(cards: list[int]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def dealer_play(dealer: list[int], deck: list[int]) -> list[int]:
    while hand_value(dealer) < BJ_DEALER_STANDS_AT:
        dealer.append(deck.pop())
    return dealer


def settle_blackjack(player: list[int], dealer: list[int]) -> tuple[int, str]:
    """(배당 배수, 결과 설명). 배수는 **돌려받는 총액**이에요(0이면 전액 손실)."""
    pv, dv = hand_value(player), hand_value(dealer)
    if pv > 21:
        return 0, f"버스트! ({pv})"
    if is_blackjack(player) and not is_blackjack(dealer):
        return BJ_BLACKJACK_PAYOUT, "**블랙잭!** 🃏"
    if dv > 21:
        return BJ_WIN_PAYOUT, f"딜러 버스트! ({dv}) 승리 🎉"
    if pv > dv:
        return BJ_WIN_PAYOUT, f"승리! {pv} vs {dv} 🎉"
    if pv < dv:
        return 0, f"패배… {pv} vs {dv}"
    return BJ_PUSH_PAYOUT, f"무승부 ({pv}) — 베팅액은 돌려드려요"
