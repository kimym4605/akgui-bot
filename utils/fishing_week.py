"""🎣 주간 낚시 기록 — 이주의 최대어와 최다 수익을 따로 센다.

## 왜 별도 컬렉션인가

`fish` 문서에는 **누적만** 있어요(`casts`·`caught`·`sold`·`best`). 주간 기록을 거기에
끼워 넣으려면 핵심 기능의 저장 구조를 건드려야 하는데, 낚시는 코인 발행의 70%를
차지하는 기능이라 **건드릴수록 위험**해요. 그래서 주간 집계만 별도 컬렉션에 쌓고,
기존 코드에는 호출 한 줄씩만 더해요.

## 왜 주간 대회인가 (2026-10-18 실측)

낚시가 발행의 70%인데 **참여자는 10명뿐**이에요. 그중 한 사람이 1,612캐스트로 전체의
절반을 넘겨요. 캐스트 수를 겨루면 그 사람이 영원히 1등이라 아무도 도전하지 않아요.
그래서 종목을 **둘**로 나눠요.

- 🏆 **최대어** — 운이 섞여서 누구나 하루아침에 1등이 될 수 있어요.
- 💰 **최다 수익** — 꾸준함을 보상해요.

🚨 **코인은 상으로 주지 않아요.** 낚시는 이미 최대 발행원이라 여기에 코인을 더 얹으면
경제가 기울어요. 상은 역할(명예)이에요.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_week = _db["fishing_week"]

KST = timezone(timedelta(hours=9))


def week_key(when: datetime | None = None) -> str:
    now = when or datetime.now(KST)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def previous_week_key() -> str:
    return week_key(datetime.now(KST) - timedelta(days=7))


def _doc_id(wk: str, user_id) -> str:
    return f"{wk}:{user_id}"


def _record_catch_sync(user_id, key: str, size: int | None, rank: int) -> None:
    """한 마리 잡았을 때. 주간 최대어는 **등급(rank) 먼저, 같으면 치수**로 비교해요."""
    wk = week_key()
    did = _doc_id(wk, user_id)

    _week.update_one(
        {"_id": did},
        {
            "$inc": {"caught": 1},
            "$setOnInsert": {"week": wk, "userId": str(user_id), "sold": 0},
        },
        upsert=True,
    )

    if key is None:
        return

    doc = _week.find_one({"_id": did}, {"bestRank": 1, "bestSize": 1}) or {}
    prev_rank = int(doc.get("bestRank") or 0)
    prev_size = int(doc.get("bestSize") or 0)
    better = (rank > prev_rank) or (rank == prev_rank and (size or 0) > prev_size)
    if better:
        _week.update_one(
            {"_id": did},
            {"$set": {"bestKey": key, "bestSize": size or 0, "bestRank": rank}},
        )


def _add_sold_sync(user_id, coins: int) -> None:
    wk = week_key()
    _week.update_one(
        {"_id": _doc_id(wk, user_id)},
        {
            "$inc": {"sold": int(coins)},
            "$setOnInsert": {"week": wk, "userId": str(user_id), "caught": 0},
        },
        upsert=True,
    )


def _top_sync(wk: str, by: str, limit: int) -> list[dict]:
    if by == "size":
        # 🚨 등급이 높은 쪽이 먼저예요. 치수는 같은 등급 안에서만 의미가 있어요
        #    (전설 30cm가 일반 40cm보다 대단해요).
        sort = [("bestRank", -1), ("bestSize", -1)]
        query = {"week": wk, "bestKey": {"$exists": True}}
    else:
        sort = [("sold", -1)]
        query = {"week": wk, "sold": {"$gt": 0}}
    return list(_week.find(query).sort(sort).limit(limit))


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요)
# ------------------------------------------------------------------
def _record_catches_sync(user_id, caught: int, key: str | None,
                         size: int | None, rank: int) -> None:
    """🎣 몰아 던지기 — N마리를 **한 번의 왕복으로** 적립해요. (8차)

    `key`/`size`/`rank`는 그 묶음에서 **제일 좋은 한 마리**예요
    (`fishing_store._record_casts_sync`가 골라서 넘겨줘요).

    🚨 `record_catch`를 N번 부르면 Atlas 왕복이 N×2회예요 — 30번 몰아 던지면 60회라
       결과 화면이 그만큼 늦어요.
    🚨 주간 최대어는 **등급(rank) 먼저, 같으면 치수**로 비교해요(`/낚시대회`가 그 규칙)."""
    wk = week_key()
    did = _doc_id(wk, user_id)

    _week.update_one(
        {"_id": did},
        {
            "$inc": {"caught": max(0, caught)},
            "$setOnInsert": {"week": wk, "userId": str(user_id), "sold": 0},
        },
        upsert=True,
    )
    if key is None:
        return

    doc = _week.find_one({"_id": did}, {"bestRank": 1, "bestSize": 1}) or {}
    prev_rank = int(doc.get("bestRank") or 0)
    prev_size = int(doc.get("bestSize") or 0)
    better = (rank > prev_rank) or (rank == prev_rank and (size or 0) > prev_size)
    if better:
        _week.update_one(
            {"_id": did},
            {"$set": {"bestKey": key, "bestSize": size or 0, "bestRank": rank}},
        )


async def record_catch(user_id, key: str | None, size: int | None, rank: int) -> None:
    """🚨 실패해도 **예외를 올리지 않아요.** 낚시 본 흐름을 막으면 안 돼요."""
    try:
        await asyncio.to_thread(_record_catch_sync, user_id, key, size, rank)
    except Exception:  # noqa: BLE001
        log.warning("🎣 주간 기록 적립 실패 (user=%s)", user_id, exc_info=True)


async def record_catches(user_id, caught: int, key: str | None,
                         size: int | None, rank: int) -> None:
    """🎣 몰아 던지기 묶음 적립. 🚨 실패해도 **예외를 올리지 않아요.**"""
    try:
        await asyncio.to_thread(_record_catches_sync, user_id, caught, key, size, rank)
    except Exception:  # noqa: BLE001
        log.warning("🎣 주간 묶음 적립 실패 (user=%s)", user_id, exc_info=True)


async def add_sold(user_id, coins: int) -> None:
    if coins <= 0:
        return
    try:
        await asyncio.to_thread(_add_sold_sync, user_id, coins)
    except Exception:  # noqa: BLE001
        log.warning("🎣 주간 수익 적립 실패 (user=%s)", user_id, exc_info=True)


async def top(wk: str | None = None, by: str = "size", limit: int = 5) -> list[dict]:
    try:
        return await asyncio.to_thread(_top_sync, wk or week_key(), by, limit)
    except Exception:  # noqa: BLE001
        return []
