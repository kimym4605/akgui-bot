"""주간 악귀력 - `/전적`을 돌릴 때마다 그 주의 악귀 스코어를 한 칸에 적어두는 곳이에요.

## 왜 저장해두나

악귀 스코어는 이미 `cogs/rank.py`가 계산해요(최근 경기들을 HenrikDev에서 받아서 2000점
만점으로 환산). 문제는 **그 값을 보관하지 않는다**는 거예요. 프로필 카드나 주간 랭킹을
띄울 때마다 다시 계산하려면 사람 수만큼 HenrikDev를 불러야 하는데, 그 API는 키 하나로
분당 30회를 나눠 쓰고 있어서(utils/henrik_api.py) 랭킹 한 번에 한도가 녹아요.

그래서 **이미 `/전적`을 돌릴 때 손에 들어온 값을 그 주 칸에 적어두고**, 카드와 랭킹은
저장된 값만 읽어요. API 호출이 0회예요.

## 주 경계

월요일 시작(ISO 주차)이고 한국 시간 기준이에요. `2026-W39` 같은 문자열을 키로 써요.
같은 주에 `/전적`을 여러 번 돌리면 **가장 높은 점수가 남아요** — 그 주의 최고 기록이
그 사람의 그 주 성적이라고 보는 게 자연스럽고, 한 판 망했다고 주간 순위가 내려가면
오히려 `/전적`을 안 돌리게 되거든요.

## 문서 구조

    {"_id": "2026-W39:123", "userId": "123", "week": "2026-W39",
     "score": 892, "grade": "악귀", "riotId": "먹9름#KR1", "at": "..."}
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_weekly = _db["agwi_weekly"]

KST = timezone(timedelta(hours=9))


def week_key(when: datetime | None = None) -> str:
    """'2026-W39'. 한국 시간 기준 ISO 주차(월요일 시작)예요."""
    moment = (when or datetime.now(KST)).astimezone(KST)
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def previous_week_key() -> str:
    return week_key(datetime.now(KST) - timedelta(days=7))


def _record_sync(user_id, score: float, grade: str, riot_id: str, week: str,
                 stats: dict | None = None) -> bool:
    """그 주 최고 점수만 남겨요. 갱신됐으면 True.

    ⚠️ "조건부 update + upsert=True"로 쓰면 안 돼요. 기존 점수가 더 높으면 필터에 안 걸리는데,
    그때 upsert가 같은 _id로 새 문서를 만들려다 **매번 DuplicateKeyError**를 던져요
    (점수가 안 오른 흔한 경우마다 예외가 나요). mission_store._claim_one_time_sync에
    적어둔 것과 똑같은 함정이에요. 그래서 갱신과 최초 생성을 나눠서 해요."""
    uid = str(user_id)
    doc_id = f"{week}:{uid}"
    payload = {
        "userId": uid, "week": week,
        "score": round(float(score), 1), "grade": grade, "riotId": riot_id,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    # 프로필 카드에 띄울 간략 전적(K/D·승률·HS%·경기수)이에요. 점수와 같은 조회에서 나온
    # 값이라 같이 적어둬요 — 카드가 HenrikDev를 다시 부르지 않게 하려는 거예요.
    #
    # ⚠️ **점수와 수명이 달라요.** 점수는 "그 주 최고"만 남기지만 전적은 **마지막 조회**를
    # 보여주는 게 맞아요. 그래서 stats를 payload에만 얹으면, 그 주 최고점이 이미 있는 흔한
    # 경우에 update가 통째로 안 걸려서 전적이 영영 안 써져요(실제로 이 순서 때문에 배포
    # 직후 카드에 줄이 안 떴어요). 아래에서 점수와 별개로 한 번 더 적어요.
    if stats:
        payload["stats"] = stats
        payload["statsAt"] = payload["at"]

    updated = False

    # 1) 이미 있고 이번 점수가 더 높을 때만 갱신해요.
    result = _weekly.update_one({"_id": doc_id, "score": {"$lt": score}}, {"$set": payload})
    if result.matched_count:
        updated = True
    else:
        # 2) 문서가 아직 없으면 새로 만들어요. 이 사이에 다른 호출이 먼저 만들었으면
        #    중복 키 에러가 나는데, 그건 "이미 더 높은 점수가 있다"는 뜻이라 그냥 False면 돼요.
        try:
            _weekly.insert_one({"_id": doc_id, **payload})
            updated = True
        except DuplicateKeyError:
            pass

    # 3) 점수가 안 올랐어도 전적·라이엇ID는 최신으로 덮어써요. (위 설명 참고)
    if stats and not updated:
        _weekly.update_one(
            {"_id": doc_id},
            {"$set": {"stats": stats, "statsAt": payload["at"], "riotId": riot_id}},
        )

    return updated


def _get_sync(user_id, week: str) -> dict | None:
    return _weekly.find_one({"_id": f"{week}:{str(user_id)}"})


def _top_sync(week: str, limit: int) -> list[dict]:
    return list(_weekly.find({"week": week}).sort([("score", -1)]).limit(limit))


def _latest_sync(user_id) -> dict | None:
    """가장 최근에 남긴 주간 스냅샷이에요(주차 무관).

    프로필 카드의 **간략 전적**은 "이번 주"가 아니라 "마지막으로 조회한 전적"을 보여주는 게
    자연스러워요. 이번 주에 `/전적`을 아직 안 돌렸다고 카드에서 전적이 통째로 사라지면
    빈칸만 남거든요. 악귀력 칸은 그대로 이번 주 것만 써요(그건 주간 경쟁 지표라서)."""
    # `at`이 아니라 `statsAt`으로 정렬해요. 점수가 안 올라도 전적만 갱신되는 경우가 있어서
    # (위 _record_sync 3번) `at`은 그때 안 움직이거든요.
    docs = list(
        _weekly.find({"userId": str(user_id), "stats": {"$exists": True}})
        .sort([("statsAt", -1)])
        .limit(1)
    )
    return docs[0] if docs else None


def _best_ever_sync(user_id) -> dict | None:
    """그 사람이 지금까지 찍은 역대 최고 주간 점수예요. 업적 판정에 써요."""
    docs = list(
        _weekly.find({"userId": str(user_id)}).sort([("score", -1)]).limit(1)
    )
    return docs[0] if docs else None


# ------------------------------------------------------------------
# async 래퍼 (동기 pymongo가 이벤트 루프를 멈추지 않게)
# ------------------------------------------------------------------
async def record(user_id, score: float, grade: str, riot_id: str,
                 stats: dict | None = None) -> bool:
    """`/전적`이 계산한 악귀 스코어를 이번 주 칸에 적어둬요."""
    week = week_key()
    try:
        updated = await asyncio.to_thread(
            _record_sync, user_id, score, grade, riot_id, week, stats
        )
    except Exception:
        # 주간 기록은 부가 기능이에요. 여기서 터져도 /전적 자체는 정상으로 끝나야 해요.
        log.exception("주간 악귀력 저장 실패 (user=%s)", user_id)
        return False
    if updated:
        log.info("📈 주간 악귀력 갱신: %s = %.0f점 (%s)", riot_id, score, week)
    return updated


async def get(user_id, week: str | None = None) -> dict | None:
    return await asyncio.to_thread(_get_sync, user_id, week or week_key())


async def top(week: str | None = None, limit: int = 10) -> list[dict]:
    return await asyncio.to_thread(_top_sync, week or week_key(), limit)


async def latest(user_id) -> dict | None:
    """주차와 무관하게 마지막으로 남은 전적 스냅샷이에요(프로필 카드의 간략 전적용)."""
    return await asyncio.to_thread(_latest_sync, user_id)


async def best_ever(user_id) -> dict | None:
    return await asyncio.to_thread(_best_ever_sync, user_id)
