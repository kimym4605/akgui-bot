"""🎪 악귀카드 장터 - 카드를 코인 가격에 내놓고 사고팔아요.

## 🚨 장터는 소비처가 **아니에요** (재분배예요)

코인이 산 사람 -> 판 사람으로 옮겨갈 뿐 **사라지지 않아요.** `/악귀상점`이나 🎴 뽑기처럼
소각되는 게 아니에요. 전에 🎲 내전 베팅(파리뮤추얼)을 "소비처"로 잘못 세던 것과 같은
함정이라([[project_akgui_shop_coin_sinks]]), `scripts/report_economy.py`에서 **발행·소각
양쪽에서 빼요.**

소각을 원하면 수수료(판매가의 N%)를 태우면 되는데, 지금은 **수수료 없음**이에요(사용자 결정).

## 에스크로 - 등록하면 내 도감에서 바로 빠져요

등록(`list_card`) 시점에 **카드를 회수**하고, 취소하면 돌려줘요. 팔릴 때만 빼면
같은 카드를 여러 번 등록해두고 전부 팔려서 **없는 카드를 넘겨야 하는** 상태가 돼요.
에스크로면 그런 상태가 아예 생기지 않아요.

덕분에 등록 중인 카드는 `/도감`에서 안 가진 걸로 보여요 - "내놨으니 지금은 없다"가
맞는 표현이라 그대로 뒀어요.

⚠️ 에픽·레전드를 내놓으면 그 등급 풀에서 다시 뽑힐 수 있게 돼요(가진 게 없어졌으니까요).
의도한 동작이에요 - 내놓은 건 내 것이 아니니까요.

## 🚨 동시 구매

두 사람이 같은 매물을 동시에 사면 **둘 다 코인을 내고 카드는 하나**가 돼요.
그래서 **먼저 `status`를 open -> sold 로 원자적으로 뒤집어** 한 명만 통과시켜요
(`find_one_and_update`). 이긴 사람만 결제로 넘어가요.

결제가 실패하면(잔액 부족) **status를 open으로 되돌려요.** 되돌리는 건 이긴 사람뿐이라
안전해요.
"""
import asyncio
import logging

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_market = _db["card_market"]

MIN_PRICE = 1
MAX_PRICE = 1000        # 지갑 최대가 147코인이라 넉넉한 상한이에요
MAX_LISTINGS = 10       # 한 사람이 동시에 올릴 수 있는 매물 수

STATUS_OPEN = "open"
STATUS_SOLD = "sold"
STATUS_CANCELLED = "cancelled"


def _uid(user_id) -> str:
    return str(user_id)


def _oid(listing_id):
    """문자열 id를 ObjectId로. 이상한 값이면 None (사용자 입력이 들어올 수 있어요)."""
    if isinstance(listing_id, ObjectId):
        return listing_id
    try:
        return ObjectId(str(listing_id))
    except (InvalidId, TypeError):
        return None


# ------------------------------------------------------------------
# 동기 구현
# ------------------------------------------------------------------
def _open_count_sync(user_id) -> int:
    return _market.count_documents({"seller": _uid(user_id), "status": STATUS_OPEN})


def _list_sync(user_id, key: str, price: int) -> str:
    """매물을 올려요. **카드 회수는 호출자가 먼저** 하고 들어와요.

    돌려주는 건 매물 id예요."""
    doc = {
        "seller": _uid(user_id),
        "key": key,
        "price": int(price),
        "status": STATUS_OPEN,
    }
    return str(_market.insert_one(doc).inserted_id)


def _browse_sync(grade_keys: list[str] | None, limit: int, skip: int) -> list[dict]:
    flt: dict = {"status": STATUS_OPEN}
    if grade_keys is not None:
        flt["key"] = {"$in": grade_keys}
    # 싼 것부터 보여줘요 - 살 수 있는 게 먼저 보이는 게 장터답죠.
    cur = _market.find(flt).sort([("price", 1), ("_id", 1)]).skip(skip).limit(limit)
    return [{**d, "_id": str(d["_id"])} for d in cur]


def _count_open_sync(grade_keys: list[str] | None) -> int:
    flt: dict = {"status": STATUS_OPEN}
    if grade_keys is not None:
        flt["key"] = {"$in": grade_keys}
    return _market.count_documents(flt)


def _mine_sync(user_id) -> list[dict]:
    cur = _market.find({"seller": _uid(user_id), "status": STATUS_OPEN}).sort("_id", 1)
    return [{**d, "_id": str(d["_id"])} for d in cur]


def _get_sync(listing_id) -> dict | None:
    oid = _oid(listing_id)
    if oid is None:
        return None
    doc = _market.find_one({"_id": oid})
    return {**doc, "_id": str(doc["_id"])} if doc else None


def _claim_sync(listing_id, buyer_id) -> dict | None:
    """매물을 **원자적으로** 선점해요. 이미 팔렸거나 취소됐으면 None.

    🚨 이게 동시 구매를 막는 유일한 지점이에요. 조회해서 "열려있네" 확인하고 결제하면
    그 사이에 남이 사버릴 수 있어요. 상태를 바꾸는 **한 번의 update로** 승자를 정해요."""
    oid = _oid(listing_id)
    if oid is None:
        return None
    doc = _market.find_one_and_update(
        {"_id": oid, "status": STATUS_OPEN},
        {"$set": {"status": STATUS_SOLD, "buyer": _uid(buyer_id)}},
        return_document=ReturnDocument.AFTER,
    )
    return {**doc, "_id": str(doc["_id"])} if doc else None


def _release_sync(listing_id) -> None:
    """선점을 되돌려요(결제 실패 시). 이긴 사람만 부르니까 안전해요."""
    oid = _oid(listing_id)
    if oid is not None:
        _market.update_one(
            {"_id": oid, "status": STATUS_SOLD},
            {"$set": {"status": STATUS_OPEN}, "$unset": {"buyer": ""}},
        )


def _cancel_sync(listing_id, user_id) -> dict | None:
    """내 매물을 거둬들여요. **카드 반환은 호출자가** 해요.

    남의 매물이거나 이미 팔렸으면 None - 필터에 seller와 status를 같이 걸어서
    한 번의 update로 확인과 변경을 함께 해요(확인 후 변경은 경합에 뚫려요)."""
    oid = _oid(listing_id)
    if oid is None:
        return None
    doc = _market.find_one_and_update(
        {"_id": oid, "seller": _uid(user_id), "status": STATUS_OPEN},
        {"$set": {"status": STATUS_CANCELLED}},
        return_document=ReturnDocument.AFTER,
    )
    return {**doc, "_id": str(doc["_id"])} if doc else None


def _stats_sync() -> dict:
    sold = list(_market.find({"status": STATUS_SOLD}, {"price": 1, "seller": 1, "buyer": 1}))
    return {
        "open": _market.count_documents({"status": STATUS_OPEN}),
        "sold": len(sold),
        "volume": sum(int(d.get("price", 0) or 0) for d in sold),
        "traders": len({d.get("seller") for d in sold} | {d.get("buyer") for d in sold}),
    }


# ------------------------------------------------------------------
# 공개 API (async) - 동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요
# ------------------------------------------------------------------
async def open_count(user_id) -> int:
    return await asyncio.to_thread(_open_count_sync, user_id)


async def create(user_id, key: str, price: int) -> str:
    return await asyncio.to_thread(_list_sync, user_id, key, price)


async def browse(grade_keys: list[str] | None = None, limit: int = 10, skip: int = 0):
    return await asyncio.to_thread(_browse_sync, grade_keys, limit, skip)


async def count_open(grade_keys: list[str] | None = None) -> int:
    return await asyncio.to_thread(_count_open_sync, grade_keys)


async def mine(user_id) -> list[dict]:
    return await asyncio.to_thread(_mine_sync, user_id)


async def get(listing_id) -> dict | None:
    return await asyncio.to_thread(_get_sync, listing_id)


async def claim(listing_id, buyer_id) -> dict | None:
    """구매 선점. None이면 이미 팔렸거나 취소된 매물이에요."""
    return await asyncio.to_thread(_claim_sync, listing_id, buyer_id)


async def release(listing_id) -> None:
    """선점 취소 (결제 실패 시 반드시 불러주세요)."""
    await asyncio.to_thread(_release_sync, listing_id)


async def cancel(listing_id, user_id) -> dict | None:
    return await asyncio.to_thread(_cancel_sync, listing_id, user_id)


async def stats() -> dict:
    return await asyncio.to_thread(_stats_sync)
