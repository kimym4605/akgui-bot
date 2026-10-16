"""🎣 낚시 어종표 - 등급·확률·판매가를 한 군데 모아뒀어요.

## 🚨 이건 코인을 **만들어내는** 기능이에요 (faucet)

뽑기·상점이 코인을 태우는 쪽이라면 낚시는 찍어내는 쪽이에요. 그래서 숫자 하나가
서버 경제를 통째로 흔들 수 있어요. 2026-10-17 실측 기준:

- 서버 전체 **일일 발행 27~52코인**, 지갑 58개 총 923코인(중앙값 5)
- 🎴 뽑기는 천장을 240장으로 올리면서 에픽 완주 3,322 / 레전드 완주 6,165코인이 됐어요
  -> **소비처 용량이 수입을 압도**하는 상태라 버는 수단을 늘리는 건 맞는 방향이에요

## 🚨 하루 상한이 없어요 (사용자 결정)

대신 **꽝 확률을 높여서** 1회 기댓값을 낮췄어요. 하지만 분명히 해둘 게 있어요 -
**꽝 확률은 1회당 수익만 낮출 뿐 총 발행량을 막지 못해요.** 작정하고 돌리면 수입이
무제한이에요. 지금 이걸 버티는 건 찌타임 미니게임이 1회에 10초 이상을 쓰게 만들기
때문이지, 구조적인 상한이 있어서가 아니에요.

→ 과열되면 **가장 먼저 건드릴 손잡이는 `MISS_RATE`**예요. 그 다음이 판매가고,
그래도 안 되면 하루 상한을 넣어야 해요. `scripts/report_economy.py`가 낚시 발행을
따로 찍어주니 며칠 뒤 꼭 재볼 것.

## 기댓값 계산 (바꿀 때마다 `scripts/test_fishing.py`가 다시 재요)

꽝 60% · 일반 25% x1 · 희귀 10% x2 · 대물 4% x6 · 전설 1% x25
= **1회 평균 약 0.94코인**. 느긋하게 20번 던지면 하루 ~19코인이에요.
"""

# 등급 -> (이모지, 색, 판매가, 뽑힐 가중치)
GRADES: dict[str, dict] = {
    "일반": {"emoji": "🐟", "color": 0x9BA3AF, "price": 1, "weight": 25.0},
    "희귀": {"emoji": "🐠", "color": 0x3B82F6, "price": 2, "weight": 10.0},
    "대물": {"emoji": "🐡", "color": 0xA855F7, "price": 6, "weight": 4.0},
    "전설": {"emoji": "🐋", "color": 0xFFD700, "price": 25, "weight": 1.0},
}

# 🚨 꽝이 전체의 몇 %인지. 여기만 올리면 발행이 바로 줄어요(제일 먼저 만질 손잡이).
MISS_RATE = 60.0

GRADE_ORDER = ["전설", "대물", "희귀", "일반"]      # 보여줄 때 높은 등급부터

# 어종. key는 저장용(ASCII 아니어도 되지만 짧게), name은 보여줄 이름이에요.
FISH: dict[str, list[dict]] = {
    "일반": [
        {"key": "f01", "name": "피라미"},
        {"key": "f02", "name": "붕어"},
        {"key": "f03", "name": "미꾸라지"},
        {"key": "f04", "name": "송사리"},
        {"key": "f05", "name": "버들치"},
    ],
    "희귀": [
        {"key": "f11", "name": "무지개송어"},
        {"key": "f12", "name": "쏘가리"},
        {"key": "f13", "name": "은어"},
        {"key": "f14", "name": "가물치"},
    ],
    "대물": [
        {"key": "f21", "name": "대왕붕어"},
        {"key": "f22", "name": "철갑상어"},
        {"key": "f23", "name": "황금잉어"},
    ],
    "전설": [
        {"key": "f31", "name": "악귀어"},
        {"key": "f32", "name": "달빛가물치"},
    ],
}

# 꽝일 때 건져 올리는 것들. 코인은 0이에요(재미용).
JUNK = [
    "낡은 장화", "빈 캔", "물풀 뭉치", "부러진 낚싯바늘", "젖은 양말",
    "돌멩이", "수초에 걸린 비닐", "이끼 낀 나뭇가지",
]

BY_KEY: dict[str, tuple[str, str]] = {
    f["key"]: (grade, f["name"]) for grade, rows in FISH.items() for f in rows
}
TOTAL_SPECIES = len(BY_KEY)


def price_of(key: str) -> int:
    grade = BY_KEY.get(key, (None, None))[0]
    return GRADES[grade]["price"] if grade else 0


def expected_coin_per_cast() -> float:
    """1회 던질 때 평균 몇 코인이 생기나. 숫자를 바꿀 때 이 값을 꼭 확인하세요."""
    hit = 100.0 - MISS_RATE
    total_w = sum(g["weight"] for g in GRADES.values())
    return sum(
        hit * (g["weight"] / total_w) / 100.0 * g["price"] for g in GRADES.values()
    )
