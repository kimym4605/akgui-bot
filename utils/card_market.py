"""🤝 악귀카드 거래 - **상대를 지정해** 카드를 팔아요.

## 2026-10-18: 공개 장터 → 지목 거래로 바뀌었어요 (사용자 결정)

전에는 아무나 먼저 누르면 사는 **공개 매물**이었어요. 12일간 0건이다가 첫 거래가
나자마자 "판매자가 상대를 고를 수 없다"는 문제가 드러나서 **지목 거래**로 바꿨어요.

- 파는 사람이 **상대와 가격을 정해** 제안해요 (`offer`)
- 지목된 사람만 수락할 수 있어요 — `claim()` 필터에 `buyer`가 들어가요
- 코인을 받아낸 뒤에 카드를 넘겨요 (순서는 아래 "원자성" 참고)

🚨 **`buyer` 필드의 의미가 달라졌어요.** 전에는 "산 사람"(결과)이었는데 이제는
**"지목된 상대"**(처음부터 정해짐)예요. 옛 문서(`status: sold`)에도 `buyer`가 있어서
구분이 안 되니, 과거 데이터를 읽을 땐 `status`를 같이 볼 것.

## 🚨 거래는 소비처가 **아니에요** (재분배예요)

코인이 산 사람 -> 판 사람으로 옮겨갈 뿐 **사라지지 않아요.** `/악귀상점`이나 🎴 뽑기처럼
소각되는 게 아니에요. 전에 🎲 내전 베팅(파리뮤추얼)을 "소비처"로 잘못 세던 것과 같은
함정이라([[project_akgui_shop_coin_sinks]]), `scripts/report_economy.py`에서 **발행·소각
양쪽에서 빼요.**

소각을 원하면 수수료(판매가의 N%)를 태우면 되는데, 지금은 **수수료 없음**이에요(사용자 결정).

## 에스크로 - 제안하면 내 도감에서 바로 빠져요

제안 시점에 **카드를 회수**하고, 취소·거절되면 돌려줘요. 수락될 때만 빼면
같은 카드를 여러 사람에게 제안해두고 전부 수락돼서 **없는 카드를 넘겨야 하는**
상태가 돼요. 에스크로면 그런 상태가 아예 생기지 않아요(사용자 결정).

덕분에 제안 중인 카드는 `/도감`에서 안 가진 걸로 보여요 - "내놨으니 지금은 없다"가
맞는 표현이라 그대로 뒀어요.

⚠️ 에픽·레전드를 내놓으면 그 등급 풀에서 다시 뽑힐 수 있게 돼요(가진 게 없어졌으니까요).
의도한 동작이에요 - 내놓은 건 내 것이 아니니까요.

## 🚨 원자성 - 수락과 취소가 겹칠 때

지목 거래라 "둘이 동시에 산다"는 없어졌지만, **수락과 (판매자의) 취소가 동시에** 올 수
있어요. 그러면 카드를 판매자에게 돌려주고 구매자에게도 주는 **복제**가 생겨요.

그래서 상태를 바꾸는 쪽이 전부 **한 번의 `find_one_and_update`**로 승자를 정해요 —
`claim`(open→sold) · `decline`(open→declined) · `cancel`(open→cancelled).
조회해서 "열려있네" 확인하고 처리하면 그 사이에 뒤집힐 수 있어요.

결제가 실패하면(잔액 부족) **status를 open으로 되돌려요**(`release`). 되돌리는 건
이긴 사람뿐이라 안전해요.
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
MAX_OFFERS = 10         # 한 사람이 동시에 보낼 수 있는 제안 수

STATUS_OPEN = "open"
STATUS_SOLD = "sold"
STATUS_CANCELLED = "cancelled"
STATUS_DECLINED = "declined"    # 지목된 상대가 거절했어요 (카드는 판매자에게)


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


def _offer_sync(seller_id, buyer_id, key: str, price: int) -> str:
    """거래를 제안해요. **카드 회수는 호출자가 먼저** 하고 들어와요.

    돌려주는 건 제안 id예요. `buyer`는 **지목된 상대**고, 이 사람만 수락할 수 있어요."""
    doc = {
        "seller": _uid(seller_id),
        "buyer": _uid(buyer_id),
        "key": key,
        "price": int(price),
        "status": STATUS_OPEN,
    }
    return str(_market.insert_one(doc).inserted_id)


def _incoming_sync(buyer_id) -> list[dict]:
    """나에게 온 제안. 오래된 것부터요."""
    cur = _market.find({"buyer": _uid(buyer_id), "status": STATUS_OPEN}).sort("_id", 1)
    return [{**d, "_id": str(d["_id"])} for d in cur]


def _outgoing_sync(seller_id) -> list[dict]:
    """내가 보낸 제안."""
    cur = _market.find({"seller": _uid(seller_id), "status": STATUS_OPEN}).sort("_id", 1)
    return [{**d, "_id": str(d["_id"])} for d in cur]


def _get_sync(listing_id) -> dict | None:
    oid = _oid(listing_id)
    if oid is None:
        return None
    doc = _market.find_one({"_id": oid})
    return {**doc, "_id": str(doc["_id"])} if doc else None


def _claim_sync(listing_id, buyer_id) -> dict | None:
    """제안을 **원자적으로** 선점해요. 내 제안이 아니거나 이미 끝났으면 None.

    🚨 필터에 **`buyer`가 들어가는 게 핵심**이에요. 이게 "지목된 사람만 수락"을
    보장하는 **유일한** 지점이에요 — 조회해서 "내 거네" 확인하고 결제하면 그 사이에
    판매자가 취소할 수 있어요. 권한 검사와 선점을 **한 번의 update로** 합쳐요.

    ⚠️ 전(공개 장터)에는 여기서 `buyer`를 **써넣었어요**. 이제는 **읽어서 맞추는**
    조건이에요. 이 필터를 빼면 남의 제안을 가로채 살 수 있어요."""
    oid = _oid(listing_id)
    if oid is None:
        return None
    doc = _market.find_one_and_update(
        {"_id": oid, "status": STATUS_OPEN, "buyer": _uid(buyer_id)},
        {"$set": {"status": STATUS_SOLD}},
        return_document=ReturnDocument.AFTER,
    )
    return {**doc, "_id": str(doc["_id"])} if doc else None


def _decline_sync(listing_id, buyer_id) -> dict | None:
    """지목된 상대가 거절해요. **카드 반환은 호출자가** 해요.

    🚨 `cancel`과 같은 이유로 한 번의 update예요. 조회 후 변경이면 이미 수락된 제안을
    거절하고 카드까지 돌려주는 **복제 사고**가 나요."""
    oid = _oid(listing_id)
    if oid is None:
        return None
    doc = _market.find_one_and_update(
        {"_id": oid, "status": STATUS_OPEN, "buyer": _uid(buyer_id)},
        {"$set": {"status": STATUS_DECLINED}},
        return_document=ReturnDocument.AFTER,
    )
    return {**doc, "_id": str(doc["_id"])} if doc else None


def _release_sync(listing_id) -> None:
    """선점을 되돌려요(결제 실패 시). 이긴 사람만 부르니까 안전해요.

    🚨 `buyer`를 **지우지 않아요.** 공개 장터 땐 buyer가 "산 사람"이라 지우는 게 맞았는데,
    이제는 **지목된 상대**라 지우면 제안의 주인이 사라져서 아무도 수락할 수 없게 돼요
    (카드는 에스크로에 잠긴 채)."""
    oid = _oid(listing_id)
    if oid is not None:
        _market.update_one(
            {"_id": oid, "status": STATUS_SOLD},
            {"$set": {"status": STATUS_OPEN}},
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


async def offer(seller_id, buyer_id, key: str, price: int) -> str:
    """거래를 제안해요. 카드 회수(`card_store.take_card`)는 **호출자가 먼저**."""
    return await asyncio.to_thread(_offer_sync, seller_id, buyer_id, key, price)


async def incoming(buyer_id) -> list[dict]:
    """나에게 온 제안."""
    return await asyncio.to_thread(_incoming_sync, buyer_id)


async def outgoing(seller_id) -> list[dict]:
    """내가 보낸 제안."""
    return await asyncio.to_thread(_outgoing_sync, seller_id)


async def get(listing_id) -> dict | None:
    return await asyncio.to_thread(_get_sync, listing_id)


async def claim(listing_id, buyer_id) -> dict | None:
    """수락 선점. None이면 **내게 온 제안이 아니거나** 이미 끝났어요."""
    return await asyncio.to_thread(_claim_sync, listing_id, buyer_id)


async def decline(listing_id, buyer_id) -> dict | None:
    """거절. **카드 반환(`give_card`)은 호출자가** 해요. None이면 이미 끝났어요."""
    return await asyncio.to_thread(_decline_sync, listing_id, buyer_id)


async def release(listing_id) -> None:
    """선점 취소 (결제 실패 시 반드시 불러주세요)."""
    await asyncio.to_thread(_release_sync, listing_id)


async def cancel(listing_id, user_id) -> dict | None:
    return await asyncio.to_thread(_cancel_sync, listing_id, user_id)


async def stats() -> dict:
    return await asyncio.to_thread(_stats_sync)
