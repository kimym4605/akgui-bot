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

from utils.fish_data import BY_KEY, COIN_PIECES, pieces_of
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


def _normalize_tank(raw: dict) -> dict[str, list[int]]:
    """어항을 **{어종: [치수, ...]}** 로 통일해요.

    🚨 치수 시스템(2026-10-17 3차) 전에 잡은 물고기는 `{어종: 마리수}`(정수)로만
    남아 있어요. 마이그레이션 스크립트 대신 **읽을 때 변환**해요 - 그래야 변환이
    실패해도 데이터가 안 날아가요. 옛 물고기는 치수를 모르니 `None`으로 두고,
    값을 매길 때 그 어종의 중앙 크기로 쳐요(`fish_data.pieces_of`)."""
    out: dict[str, list[int]] = {}
    for key, val in (raw or {}).items():
        if isinstance(val, list):
            sizes = [int(s) if s is not None else None for s in val]
        else:
            sizes = [None] * int(val or 0)        # 옛 형식: 마리수만
        if sizes:
            out[key] = sizes
    return out


def tank_pieces(tank: dict[str, list[int]]) -> int:
    """어항 전체의 값(조각)."""
    return sum(pieces_of(k, s) for k, sizes in tank.items() for s in sizes)


def _get_sync(user_id) -> dict:
    doc = _fish.find_one({"_id": _uid(user_id)}) or {}
    tank = _normalize_tank(doc.get("tank") or {})
    return {
        "tank": tank,
        "pieces": tank_pieces(tank),
        "dust": int(doc.get("dust", 0) or 0),     # 지난 판매에서 남은 조각
        "casts": int(doc.get("casts", 0) or 0),
        "caught": int(doc.get("caught", 0) or 0),
        "sold": int(doc.get("sold", 0) or 0),
        "best": doc.get("best"),
    }


def _record_cast_sync(user_id, key: str | None, size: int | None = None) -> None:
    """던진 횟수를 세고, 잡았으면 어항에 담아요. key가 None이면 놓친 거예요."""
    update: dict = {"$inc": {"casts": 1}}
    if key:
        update["$inc"]["caught"] = 1
        # ⚠️ `$push`라 같은 어종을 여러 마리 담아도 각자의 치수가 남아요.
        update["$push"] = {f"tank.{key}": size}

        # 최고 기록 - 등급이 더 높거나, 같은 등급이면 **더 큰 놈**일 때 갱신해요.
        grade = BY_KEY[key][0]
        from utils.fish_data import GRADE_ORDER
        rank = len(GRADE_ORDER) - GRADE_ORDER.index(grade)
        doc = _fish.find_one({"_id": _uid(user_id)}, {"best": 1}) or {}
        prev = doc.get("best") or {}
        prev_rank, prev_size = int(prev.get("rank", 0)), prev.get("size") or 0
        better = rank > prev_rank or (
            rank == prev_rank and (size or 0) > prev_size)
        if better:
            update["$set"] = {"best": {"key": key, "rank": rank, "size": size}}
    _fish.update_one({"_id": _uid(user_id)}, update, upsert=True)


def _sell_all_sync(user_id) -> tuple[dict[str, list[int]], int, int]:
    """어항을 비우면서 **비우기 직전 내용**을 받아와요.

    돌려주는 건 (담겨있던 것, 지급 코인, 남은 조각)이에요.

    🚨 읽고 -> 계산하고 -> 비우면 그 사이에 낚은 물고기가 증발해요.
    `find_one_and_update`로 한 번에 바꾸고 BEFORE 문서를 받아서 그걸로 계산해요.

    🚨 **나머지 조각은 버리지 않고 `dust`에 남겨요.** 그냥 버리면 손해고, 매번
    반올림하면 0.5짜리를 한 마리씩 팔아 1코인씩 받는 구멍이 생겨요."""
    doc = _fish.find_one_and_update(
        {"_id": _uid(user_id)},
        {"$set": {"tank": {}, "dust": 0}},
        return_document=ReturnDocument.BEFORE,
    )
    tank = _normalize_tank((doc or {}).get("tank") or {})
    total = tank_pieces(tank) + int((doc or {}).get("dust", 0) or 0)
    coins, dust = divmod(total, COIN_PIECES)

    if dust and (tank or total):
        # 남은 조각을 되돌려 놔요(위에서 0으로 비웠으니 다시 심어요).
        _fish.update_one({"_id": _uid(user_id)}, {"$set": {"dust": dust}})
    return tank, coins, dust


def _restore_sync(user_id, tank: dict[str, list[int]], dust: int = 0) -> None:
    """판매가 실패했을 때 어항을 되돌려요. 그 사이 새로 낚은 것과 **합쳐져요**.

    ⚠️ `$push`에 `$each`를 써요. 리스트를 통째로 `$set`하면 그 사이에 낚은 물고기를
    덮어써서 날려버려요."""
    update: dict = {}
    if tank:
        update["$push"] = {f"tank.{k}": {"$each": sizes} for k, sizes in tank.items()}
    if dust:
        update["$inc"] = {"dust": dust}
    if update:
        _fish.update_one({"_id": _uid(user_id)}, update, upsert=True)


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


async def record_cast(user_id, key: str | None, size: int | None = None) -> None:
    await asyncio.to_thread(_record_cast_sync, user_id, key, size)


async def sell_all(user_id) -> tuple[dict[str, list[int]], int, int]:
    """(담겨있던 것, 지급 코인, 남은 조각)."""
    return await asyncio.to_thread(_sell_all_sync, user_id)


async def restore(user_id, tank: dict[str, list[int]], dust: int = 0) -> None:
    await asyncio.to_thread(_restore_sync, user_id, tank, dust)


async def add_sold(user_id, coins: int) -> None:
    await asyncio.to_thread(_add_sold_sync, user_id, coins)


async def leaderboard(limit: int = 10) -> list[tuple[str, int]]:
    return await asyncio.to_thread(_leaderboard_sync, limit)
