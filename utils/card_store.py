"""🎴 악귀카드 수집 - 뽑기 확률·천장·도감 보유를 전부 여기서 다뤄요.

## 이건 수급처가 아니라 **소비처**예요

코인을 내고 뽑는 구조라 코인이 사라져요. 2026-10-15 실측에서 `/악귀상점` 3종(리롤권·보호권·
테마)이 **열흘째 0건**이었는데, 구매력은 충분했어요(12코인 이상 21명). 돈이 없어서가 아니라
**상점에 진열만 해뒀기 때문**이에요. 반대로 🎰 도박은 224판이 돌았고, 차이는 "막히는 그 자리에서
파는가"였어요 -> [[project_akgui_shop_coin_sinks]]

그래서 이 기능은 처음부터 **`/출석` 응답에 🎴 버튼을 달아요**(코인이 손에 들어오는 그 순간이
쓸 자리예요). 상점 진열에 의존하지 않는 게 설계의 전제예요.

## 중복 규칙이 등급마다 다른 이유 (사용자 지정)

- **일반·레어**: 중복으로 나와요. 장수를 세요(`counts`). 같은 카드가 여러 장 쌓여요.
- **에픽·레전드**: **이미 가진 카드를 풀에서 제외**해요. 모을수록 남은 종류가 줄어서
  "다 모으는" 체감이 분명해져요.

## 그 등급을 다 모았는데 또 그 등급이 나오면? -> 다시 뽑아요

사용자 결정(2026-10-17): "똑같은거 나오면 다시 뽑기 할 수 있게 해주자".
에픽·레전드는 가진 걸 제외하니, 그 등급을 **전부** 모은 사람에게는 뽑을 카드가 없어요.
그때는 그 등급을 가중치에서 빼고 **다시 굴려요**(`_roll_grade`).

⚠️ 재굴림이 무한루프가 안 되는 건 **일반·레어가 중복을 허용**하기 때문이에요. 최악의 경우
(에픽·레전드 전부 보유) 가중치에 일반·레어만 남고, 그 둘은 언제나 뽑힐 수 있어요.
그래서 종료가 보장돼요 - 그래도 혹시 모를 상황에 `_MAX_REROLL` 상한을 둬요.

## 천장(240장 = 80뽑기)

레전드는 0.5%예요. 천장이 없으면 **평균 200장**을 뽑아야 하나 나오는데, 운이 나쁘면
끝없이 안 나올 수 있어요. 그래서 `since_legend`로 레전드 없이 지나간 장수를 세고,
**240장**이 되면 그 장은 레전드를 확정으로 줘요.

### 천장 값이 레전드 체감을 거의 혼자 정해요 (2026-10-17 실측)

| 천장 | 레전드 1장당 | 코인 | 천장에서 나온 비율 |
|---|---|---|---|
| 30장 | 27.9장 | 93 | **86%** |
| 90장 | 72.3장 | 241 | 64% |
| **240장 (지금)** | **138.9장** | **463** | **31%** |

🚨 천장이 낮을수록 **자연확률을 깎아도 체감이 안 변해요.** 천장 30장 시절엔 레전드의
86%가 천장에서 나와서, 확률을 1.5% -> 0.5%로 내려도 81 -> 93코인밖에 안 움직였어요.
**레전드를 귀하게 만들려면 확률이 아니라 여기를 올려야 해요.**

지금은 천장 의존도가 31%까지 내려가서 **운이 주도**하고 천장은 보험 역할만 해요.

🚨 **"N연속이면 레전드 확정" 같은 문구를 쓰면 안 돼요.** 한 번에 지를 수 있는 최대가
10연(30장)인데 천장은 240장이라 **한 번의 연속뽑기로는 절대 천장에 못 닿아요.**

⚠️ 세는 단위가 "뽑기 횟수"가 아니라 **카드 장수**예요. 1뽑기에 3장이 나오니 30장 = 10뽑기 =
100코인이에요. 사용자가 천장을 고를 때 본 기준이 "90코인쯤에 레전드"였어서(그때는 1장 3코인
안이었어요), 가격이 10코인/3장으로 바뀐 뒤에도 **그 감각을 유지**하려고 장수로 세요.

⚠️ 레전드를 **13종 전부 모은 사람**에게는 천장이 발동하지 않아요(줄 카드가 없어요).
그 경우 카운터만 계속 쌓이는데, 어차피 쓸 일이 없으니 그대로 둬요.

## 동시성

버튼을 빠르게 두 번 누르면 뽑기가 겹쳐요. 그러면 "읽은 보유 목록"이 낡아서 같은 에픽이
두 번 나올 수 있어요. 그래서 **읽은 `draws` 값을 필터에 걸어** 한 번의 update로 쓰고,
어긋나면 다시 읽어서 재시도해요(`mission_store._reroll_sync`가 `picks`로 하는 것과 같아요).

⚠️ `draws` 카운터는 **필드가 없을 수 있어요**. `{"draws": 0}`으로 필터하면 필드가 없는
새 문서를 못 잡아요 - `$exists: False`를 같이 허용해요(inventory_store가 같은 함정을 겪었어요).
"""
import asyncio
import logging
import random

from pymongo.errors import DuplicateKeyError

from utils.card_data import BY_KEY, CARDS, TOTAL
from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_cards = _db["cards"]

# ------------------------------------------------------------------
# 설계 수치 (2026-10-17 사용자 확정)
# ------------------------------------------------------------------
PULL_PRICE = 10        # 1뽑기 가격 (악귀코인)
CARDS_PER_PULL = 3     # 1뽑기에 나오는 장수
# 이 장수만큼 레전드가 없으면 그 장은 레전드 확정.
#
# ⚠️ 단위가 **카드 장수**예요(뽑기 횟수가 아니라). 1뽑기 = 3장이라 240장 = **80뽑기**예요.
#    사용자가 "천장 80회"라고 한 게 뽑기 80번이라 240으로 적어요.
#
# 2026-10-17: 30 -> 240 (사용자 지시). 레전드를 귀하게 만들려면 확률이 아니라 여기를
# 올려야 해요 - 자연확률 0.5%에선 천장이 레전드 공급을 지배하거든요. 실측:
#
#   천장  30장 → 레전드 1장당 평균  27.9장( 93코인) · 86%가 천장에서 나옴
#   천장  90장 → 평균  72.3장(241코인) · 64%가 천장
#   천장 240장 → 평균 138.9장(463코인) · 31%가 천장   ← 지금
#
# 천장 의존도가 31%로 내려가서 이제는 **운이 주도**해요(천장은 보험 역할).
PITY_DRAWS = 240

# 연속뽑기 상한 (2026-10-17). 한 번에 최대 10뽑기 = 30장 = 100코인.
#
# 🚨 **"10연 = 레전드 확정"은 더 이상 사실이 아니에요.** 천장이 30장이던 시절엔
#    10연(30장)이 정확히 천장이라 그 약속이 성립했는데, 2026-10-17에 천장을 240장
#    (80뽑기)으로 올리면서 깨졌어요. 안내문·`/카드확률`에서 그 문구를 전부 지웠어요 -
#    **지키지 못할 약속을 띄우면 안 돼요.** 상한 10은 그냥 '한 번에 지를 수 있는 최대'예요.
# ⚠️ 할인은 없어요(사용자 결정). 뽑기는 지금 유일하게 잘 도는 소비처라 소각을 깎을 이유가
# 없어요 - 2026-10-17 실측으로 서버 총 코인이 870 -> 678로 줄었고 그 대부분이 뽑기예요.
# ⚠️ 2026-10-17 기준 **100코인을 가진 사람은 0명**이에요(최대 96, 중앙값 4). 10연은 당분간
# 아무도 못 써요 - 그래도 상한은 열어둬요(못 사면 잔액 부족으로 거절될 뿐이에요).
MAX_PULLS = 10

# 등급 가중치.
#
# ⚠️ `random.choices`가 알아서 정규화하니 **합이 100이 아니어도 돌아가요.** 그래서 더 위험해요
#    - 에픽만 8.5 -> 5로 고치고 나머지를 안 건드리면 합이 96.5가 되고, 에픽의 실제 확률은
#    5%가 아니라 5.18%가 돼요(`/카드확률`이 보여주는 값과도 어긋나요).
#    **한 등급을 고치면 반드시 나머지를 조정해 합을 100으로 맞출 것.** 아래 테스트가 잡아줘요.
#
# 2026-10-17 조정 이력 (전부 사용자 지시):
#   1차 → 2차: 에픽 8.5 -> 5, 레전드 1.5 -> 0.5, 뺀 만큼 일반으로(60 -> 64.5)
#   2차 → 3차: 레어 30 -> 20, 에픽 5 -> 3. 뺀 12%p를 전부 일반으로(64.5 -> 76.5)
#              이 조정과 함께 **그때까지의 카드·코인을 전부 되돌렸어요**(테스트 기간으로 정리)
#              → scripts/reset_cards_refund.py
GRADE_WEIGHTS: dict[str, float] = {
    "일반": 76.5,
    "레어": 20.0,
    "에픽": 3.0,
    "레전드": 0.5,
}
assert abs(sum(GRADE_WEIGHTS.values()) - 100) < 1e-9, (
    f"가중치 합이 100이 아니에요: {sum(GRADE_WEIGHTS.values())} "
    "- 한 등급만 고치고 나머지를 안 맞춘 것 같아요"
)

# 중복이 나와도 되는 등급 = 장수로 세는 등급. 나머지는 가진 걸 풀에서 제외해요.
DUPE_OK = frozenset({"일반", "레어"})

GRADE_ORDER = ["레전드", "에픽", "레어", "일반"]   # 보여줄 때 높은 등급부터

GRADE_EMOJI = {"일반": "⚪", "레어": "🔵", "에픽": "🟣", "레전드": "🟡"}

# 등급 색 (2026-10-17 사용자 지정): 일반 하양 · 레어 파랑 · 에픽 보라 · 레전드 황금.
#
# 뽑기 결과 이미지의 **테두리와 이름**, 그리고 디스코드 임베드 색에 같이 쓰여요
# (`utils/card_render.py`, `cogs/card_gacha.py`). 한 군데서만 바꾸면 임베드와 그림의
# 색이 어긋나니 **반드시 여기만 고칠 것.**
#
# ⚠️ 어두운 배경(BG_TOP/BG_BOTTOM) 위에 올라가는 색이라 전부 밝은 쪽이어야 해요.
#    어두운 색을 넣으면 테두리도 이름도 안 보여요(테마에서 이미 한 번 겪었어요).
GRADE_COLOR = {
    "일반":   0xFFFFFF,   # 하양
    "레어":   0x3B82F6,   # 파랑
    "에픽":   0xA855F7,   # 보라
    "레전드": 0xFFD700,   # 황금 (전에는 0xFBBF24 호박색이었어요)
}

# 재굴림 상한. 일반·레어가 중복을 허용하므로 이론상 1~2회로 끝나지만, 가중치를
# 잘못 고쳐서(예: 일반·레어를 0으로) 무한루프가 되는 사고를 막는 안전장치예요.
_MAX_REROLL = 20

# 낙관적 동시성 재시도 횟수.
_MAX_RETRY = 5

_ALL_KEYS_BY_GRADE = {grade: [c["key"] for c in cards] for grade, cards in CARDS.items()}


def _uid(user_id) -> str:
    return str(user_id)


# ------------------------------------------------------------------
# 뽑기 알고리즘 (순수 함수 - DB를 안 건드려서 테스트가 쉬워요)
# ------------------------------------------------------------------
def _exhausted(grade: str, counts: dict[str, int]) -> bool:
    """이 등급을 더 뽑을 게 없는지. 중복 허용 등급은 영원히 고갈되지 않아요."""
    if grade in DUPE_OK:
        return False
    return all(counts.get(k) for k in _ALL_KEYS_BY_GRADE.get(grade, []))


def _roll_grade(counts: dict[str, int], rng: random.Random) -> str | None:
    """등급을 하나 굴려요. 고갈된 등급이 나오면 그 등급을 빼고 다시 굴려요.

    돌려줄 등급이 하나도 없으면 None(= 도감을 전부 모았고 중복 허용 등급도 없는 상태인데,
    일반·레어가 중복을 허용하는 한 실제로는 일어나지 않아요)."""
    weights = dict(GRADE_WEIGHTS)
    for _ in range(_MAX_REROLL):
        pool = {g: w for g, w in weights.items() if w > 0}
        if not pool:
            return None
        grade = rng.choices(list(pool), weights=list(pool.values()), k=1)[0]
        if not _exhausted(grade, counts):
            return grade
        # 고갈된 등급 -> 가중치에서 제거하고 다시 굴려요 ("똑같은거 나오면 다시 뽑기")
        weights[grade] = 0.0
    log.warning("등급 재굴림 상한 도달 - 가중치 설정을 확인해주세요")
    return None


def _pick_card(grade: str, counts: dict[str, int], rng: random.Random) -> str:
    """등급 안에서 카드 하나를 골라요. 중복 제외 등급은 **안 가진 것만**에서 골라요."""
    keys = _ALL_KEYS_BY_GRADE[grade]
    if grade not in DUPE_OK:
        unowned = [k for k in keys if not counts.get(k)]
        if unowned:
            keys = unowned
    return rng.choice(keys)


def draw_cards(
    counts: dict[str, int],
    since_legend: int,
    n: int = CARDS_PER_PULL,
    rng: random.Random | None = None,
) -> tuple[list[dict], int]:
    """카드 n장을 뽑아요. (뽑힌 목록, 바뀐 since_legend)

    ⚠️ 한 장 뽑을 때마다 `counts`를 갱신해요. 안 그러면 **같은 뽑기 안에서 같은 에픽이
    두 번** 나와요(중복 제외가 무의미해져요).

    `counts`는 복사해서 쓰니 호출자의 dict는 안 바뀌어요.
    돌려주는 각 항목: {key, grade, name, is_new, pity}
    """
    rng = rng or random
    counts = dict(counts)
    results: list[dict] = []

    for _ in range(n):
        pity = False

        # 천장: 이 장이 레전드 없이 뽑는 PITY_DRAWS번째 장이면 레전드 확정.
        # 단 13종을 다 모았으면 줄 카드가 없어서 평소대로 굴려요.
        #
        # ⚠️ `>= PITY_DRAWS`가 아니라 **`>= PITY_DRAWS - 1`**이에요. since_legend는 "지금까지
        #    레전드 없이 뽑은 장수"라, 30번째 장을 뽑기 직전의 값은 29예요. `>= 30`으로 쓰면
        #    확정이 31번째 장으로 밀려서 최악이 11뽑기(110코인)가 돼요 - 사용자가 천장을
        #    고를 때 본 기준이 "90~100코인"이었으니 30장 = 정확히 10뽑기 = 100코인에 맞춰요.
        if since_legend >= PITY_DRAWS - 1 and not _exhausted("레전드", counts):
            grade = "레전드"
            pity = True
        else:
            grade = _roll_grade(counts, rng)

        if grade is None:
            # 도감 완성 + 중복 허용 등급도 없음 = 줄 게 없어요. 남은 장수는 건너뛰어요.
            break

        key = _pick_card(grade, counts, rng)
        is_new = not counts.get(key)
        counts[key] = counts.get(key, 0) + 1

        if grade == "레전드":
            since_legend = 0
        else:
            since_legend += 1

        results.append({
            "key": key,
            "grade": grade,
            "name": BY_KEY[key][1],
            "is_new": is_new,
            "pity": pity,
        })

    return results, since_legend


# ------------------------------------------------------------------
# DB (동기) - 공개 API는 전부 async예요
# ------------------------------------------------------------------
def _get_sync(user_id) -> dict:
    doc = _cards.find_one({"_id": _uid(user_id)}) or {}
    return {
        "counts": dict(doc.get("counts") or {}),
        "draws": int(doc.get("draws", 0) or 0),
        "since_legend": int(doc.get("since_legend", 0) or 0),
    }


def _pull_sync(user_id, n: int = CARDS_PER_PULL) -> list[dict] | None:
    """뽑고 저장해요. 동시 실행에 밀리면 None(호출자가 코인을 되돌려야 해요).

    ⚠️ **코인 차감은 이 함수가 하지 않아요.** 호출자가 먼저 차감하고, 여기서 None이
    돌아오면 환불해요. 차감과 저장을 한 트랜잭션으로 묶을 수 없어서(단일 노드 Mongo에
    트랜잭션을 걸지 않았어요) 역할을 명확히 갈라둬요 -> [[project_akgui_casino]]에서
    "게임이 시작 못 하면 코인+한도 둘 다 환불"을 놓쳐 사고가 났어요."""
    uid = _uid(user_id)

    for _ in range(_MAX_RETRY):
        state = _get_sync(uid)
        drawn, new_since = draw_cards(state["counts"], state["since_legend"], n)
        if not drawn:
            return []   # 도감 완성 - 호출자가 환불 + 안내

        # 바뀐 카드만 $inc 해요. counts 전체를 $set으로 덮으면 동시에 들어온 다른
        # 뽑기의 결과를 지워요. 한 뽑기에서 같은 일반/레어가 두 번 나올 수 있으니
        # 키별로 더해서 세요.
        inc: dict[str, int] = {}
        for d in drawn:
            field = f"counts.{d['key']}"
            inc[field] = inc.get(field, 0) + 1
        inc["draws"] = len(drawn)

        # 읽은 시점의 draws와 같을 때만 써요(낙관적 동시성).
        # 처음 뽑는 사람은 draws 필드가 아예 없어서 $exists도 같이 허용해요.
        flt: dict = {"_id": uid}
        if state["draws"] == 0:
            flt["$or"] = [{"draws": 0}, {"draws": {"$exists": False}}]
        else:
            flt["draws"] = state["draws"]

        try:
            res = _cards.update_one(
                flt, {"$inc": inc, "$set": {"since_legend": new_since}}, upsert=True
            )
        except DuplicateKeyError:
            # 같은 순간 둘 다 "문서 없음"으로 보고 upsert를 시도하면 한쪽이 여기로 와요.
            # 이제 문서가 있으니 다시 읽어서 재시도하면 돼요.
            log.info("카드 문서 동시 생성 - 재시도 (user=%s)", uid)
            continue

        if res.modified_count or res.upserted_id is not None:
            return drawn
        # 밀렸으면 최신 상태로 다시 계산해요.
        log.info("카드 뽑기 동시 실행 감지 - 재시도 (user=%s)", uid)

    log.warning("카드 뽑기 저장이 %d회 모두 밀렸어요 (user=%s)", _MAX_RETRY, uid)
    return None


# ------------------------------------------------------------------
# 공개 API (async) - 동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요
#                    (2026-09-04 먹통 사고 -> utils/coin_wallet.py 주석)
# ------------------------------------------------------------------
async def get_collection(user_id) -> dict:
    return await asyncio.to_thread(_get_sync, user_id)


async def pull(user_id, n: int = CARDS_PER_PULL) -> list[dict] | None:
    """카드를 뽑아 저장해요.

    - 성공: 뽑힌 카드 목록
    - `[]`: 도감을 전부 모아서 줄 카드가 없음 -> 환불하고 안내해주세요
    - `None`: 동시 실행에 밀려 저장 실패 -> **환불해주세요**
    """
    return await asyncio.to_thread(_pull_sync, user_id, n)


def summarize(counts: dict[str, int]) -> dict:
    """도감 진행도. `/도감`이 써요."""
    per_grade = {}
    for grade in GRADE_ORDER:
        keys = _ALL_KEYS_BY_GRADE.get(grade, [])
        owned = [k for k in keys if counts.get(k)]
        per_grade[grade] = {"owned": len(owned), "total": len(keys)}
    return {
        "per_grade": per_grade,
        "owned": sum(1 for k in BY_KEY if counts.get(k)),
        "total": TOTAL,
        "cards": sum(counts.values()),   # 중복 포함 총 장수
    }
