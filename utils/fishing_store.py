"""🎣 어항 - 낚은 물고기를 담아뒀다가 한 번에 팔아요.

`fish` 컬렉션에 사람당 문서 하나예요.

    {_id: uid, tank: {어종key: 마리수}, casts: 총 던진 횟수, caught: 잡은 수, sold: 판 코인}

## 왜 바로 코인을 안 주고 어항에 담나

사용자 결정("어항에 모았다가 판매"). 쌓이는 걸 보는 재미도 있지만, 운영상 이점이 더 커요 -
**판매 시점에 코인이 한 번만 발행**되니 `coin_log`에 `낚시판매`가 깔끔하게 한 줄씩 남고,
`scripts/report_economy.py`에서 낚시 발행량을 정확히 떼어볼 수 있어요. 낚을 때마다
코인을 주면 기록이 잘게 쪼개져서 추적이 번거로워요.

## 동시성

- 담기: `$inc`라 겹쳐도 안전해요.
- 팔기: **읽고 나서 비우면** 그 사이에 들어온 물고기까지 날아가요. 그래서
  `find_one_and_update`로 **어항을 비우면서 그 직전 내용을 받아와요**(원자적 교환).
  받아온 내용으로 코인을 계산하니 잃어버리는 물고기가 없어요.

🚨 코인 지급이 실패하면 어항을 **되돌려줘야** 해요(`restore`). 안 그러면 물고기만
사라지고 코인은 없는 최악이 돼요.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from utils.fish_data import BY_KEY, price_of
from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_fish = _db["fish"]


def _uid(user_id) -> str:
    return str(user_id)


# ------------------------------------------------------------------
# 🎣 낚시대 (2026-10-17 2차 설계)
#
# 문서에 `rod`(남은 내구도)와 `rod_date`(마지막으로 산 날짜)를 둬요.
# 하루 1개 제한은 `rod_date`로, 10회 제한은 `rod`로 걸려요.
#
# 🚨 **둘 다 조건부 update 한 번으로** 처리해요. "읽고 → 확인하고 → 쓰기"로 하면 빠르게
#    두 번 누를 때 하루에 두 개를 사거나 내구도가 음수가 돼요.
# ------------------------------------------------------------------
KST = timezone(timedelta(hours=9))


def today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _rod_sync(user_id) -> tuple[int, bool]:
    """(남은 내구도, 오늘 이미 샀는지)."""
    doc = _fish.find_one({"_id": _uid(user_id)}, {"rod": 1, "rod_date": 1}) or {}
    return int(doc.get("rod", 0) or 0), doc.get("rod_date") == today_iso()


def _buy_rod_sync(user_id, durability: int) -> bool:
    """낚시대를 지급해요. 오늘 이미 샀으면 False(아무것도 안 바꿔요).

    🚨 **코인 차감은 호출자가** 해요. 여기서 False가 나오면 차감하면 안 되고, 차감이
    실패하면 `_refund_rod_sync`로 되돌려야 해요.
    ⚠️ 날짜 조건을 필터에 넣어 **한 번의 update로** 확인과 지급을 함께 해요.
    ⚠️ 남은 내구도는 **덮어써요**(`$set`). 쌓이게 하면 며칠 모아서 하루에 몰아 쓰는
       길이 열려서 '하루 10번' 제한이 무의미해져요."""
    uid, today = _uid(user_id), today_iso()
    res = _fish.update_one(
        {"_id": uid, "rod_date": {"$ne": today}},
        {"$set": {"rod": durability, "rod_date": today}},
        upsert=True,
    )
    return res.modified_count == 1 or res.upserted_id is not None


def _refund_rod_sync(user_id) -> None:
    """지급을 되돌려요(코인 차감 실패 시). 오늘 산 기록도 같이 지워 다시 살 수 있게 해요."""
    _fish.update_one({"_id": _uid(user_id)},
                     {"$set": {"rod": 0}, "$unset": {"rod_date": ""}})


def _use_rod_sync(user_id) -> int | None:
    """내구도를 1 깎고 **남은 수**를 돌려줘요. 낚시대가 없으면 None.

    ⚠️ 조건부 차감(`$gte: 1`)이라 동시에 여러 번 눌러도 음수가 안 돼요."""
    doc = _fish.find_one_and_update(
        {"_id": _uid(user_id), "rod": {"$gte": 1}},
        {"$inc": {"rod": -1}},
        return_document=ReturnDocument.AFTER,
    )
    return None if doc is None else int(doc.get("rod", 0) or 0)


def _get_sync(user_id) -> dict:
    doc = _fish.find_one({"_id": _uid(user_id)}) or {}
    return {
        "tank": {k: int(v) for k, v in (doc.get("tank") or {}).items() if v},
        "casts": int(doc.get("casts", 0) or 0),
        "caught": int(doc.get("caught", 0) or 0),
        "sold": int(doc.get("sold", 0) or 0),
        "best": doc.get("best"),
    }


def _record_cast_sync(user_id, key: str | None) -> None:
    """던진 횟수를 세고, 잡았으면 어항에 담아요. key가 None이면 꽝이에요."""
    inc = {"casts": 1}
    if key:
        inc[f"tank.{key}"] = 1
        inc["caught"] = 1
    update: dict = {"$inc": inc}
    if key:
        # 최고 등급 기록 - 희귀도가 더 높은 걸 잡았을 때만 갱신해요.
        grade = BY_KEY[key][0]
        from utils.fish_data import GRADE_ORDER
        rank = len(GRADE_ORDER) - GRADE_ORDER.index(grade)
        doc = _fish.find_one({"_id": _uid(user_id)}, {"best": 1}) or {}
        prev = doc.get("best") or {}
        if int(prev.get("rank", 0)) < rank:
            update["$set"] = {"best": {"key": key, "rank": rank}}
    _fish.update_one({"_id": _uid(user_id)}, update, upsert=True)


def _sell_all_sync(user_id) -> tuple[dict[str, int], int]:
    """어항을 비우면서 **비우기 직전 내용**을 받아와요. (담겨있던 것, 코인)

    🚨 읽고 -> 계산하고 -> 비우면 그 사이에 낚은 물고기가 증발해요.
    `find_one_and_update`로 한 번에 바꾸고 BEFORE 문서를 받아서 그걸로 계산해요."""
    doc = _fish.find_one_and_update(
        {"_id": _uid(user_id)},
        {"$set": {"tank": {}}},
        return_document=ReturnDocument.BEFORE,
    )
    tank = {k: int(v) for k, v in ((doc or {}).get("tank") or {}).items() if v}
    coins = sum(price_of(k) * n for k, n in tank.items())
    return tank, coins


def _restore_sync(user_id, tank: dict[str, int]) -> None:
    """판매가 실패했을 때 어항을 되돌려요. 그 사이 새로 낚은 것과 **합쳐져요**."""
    if not tank:
        return
    _fish.update_one(
        {"_id": _uid(user_id)},
        {"$inc": {f"tank.{k}": n for k, n in tank.items()}},
        upsert=True,
    )


def _add_sold_sync(user_id, coins: int) -> None:
    _fish.update_one({"_id": _uid(user_id)}, {"$inc": {"sold": coins}}, upsert=True)


def _leaderboard_sync(limit: int) -> list[tuple[str, int]]:
    rows = _fish.find({"sold": {"$gt": 0}}, {"sold": 1}).sort("sold", -1).limit(limit)
    return [(str(r["_id"]), int(r.get("sold", 0) or 0)) for r in rows]


# ------------------------------------------------------------------
# 공개 API (async) - 동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요
# ------------------------------------------------------------------
async def rod_state(user_id) -> tuple[int, bool]:
    """(남은 내구도, 오늘 이미 샀는지)."""
    return await asyncio.to_thread(_rod_sync, user_id)


async def buy_rod(user_id, durability: int) -> bool:
    """낚시대 지급. 오늘 이미 샀으면 False. **코인 차감 전에** 부르세요."""
    return await asyncio.to_thread(_buy_rod_sync, user_id, durability)


async def refund_rod(user_id) -> None:
    """지급을 되돌려요(차감 실패 시 반드시)."""
    await asyncio.to_thread(_refund_rod_sync, user_id)


async def use_rod(user_id) -> int | None:
    """내구도 1 소모. 남은 수를 돌려주고, 낚시대가 없으면 None."""
    return await asyncio.to_thread(_use_rod_sync, user_id)


async def get(user_id) -> dict:
    return await asyncio.to_thread(_get_sync, user_id)


async def record_cast(user_id, key: str | None) -> None:
    await asyncio.to_thread(_record_cast_sync, user_id, key)


async def sell_all(user_id) -> tuple[dict[str, int], int]:
    return await asyncio.to_thread(_sell_all_sync, user_id)


async def restore(user_id, tank: dict[str, int]) -> None:
    await asyncio.to_thread(_restore_sync, user_id, tank)


async def add_sold(user_id, coins: int) -> None:
    await asyncio.to_thread(_add_sold_sync, user_id, coins)


async def leaderboard(limit: int = 10) -> list[tuple[str, int]]:
    return await asyncio.to_thread(_leaderboard_sync, limit)
