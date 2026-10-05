"""소모성 아이템 보유량 - 지금은 🧊 출석 보호권만 담아요. (`/악귀상점`에서 사요)

## 왜 따로 두는가

`cosmetic_store`는 **영구 보유**(테마)라 목록이면 충분한데, 보호권은 **쓰면 사라지는 개수**라
성격이 달라요. 개수는 `$inc`와 조건부 차감으로 다뤄야 동시에 두 번 들어와도 음수가 안 돼요
(코인 지갑과 같은 이유 → `utils/coin_wallet.py` 주석).

## 보호권이 하는 일

하루 빠져도 연속 출석이 안 끊겨요. 2026-10-05 실측에서 **누적 41회인데 연속 3일**인 사람이
여럿 있었어요. 거의 매일 오는데 한 번 놓쳐서 0으로 돌아간 거예요. 그러면 "어차피 끊겼으니"가
되어버려서, 열심히 온 사람일수록 보상이 없어지는 구조였어요.

⚠️ **하루치만** 살려요. 이틀 이상 빠진 건 못 살려요(그걸 허용하면 연속이라는 말이 무의미해져요).
⚠️ 보유 상한(`PROTECT_MAX`)을 두는 것도 같은 이유예요. 쌓아두면 사실상 영구 면제가 돼요.
"""
import asyncio
import logging

from pymongo import ReturnDocument

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_inventory = _db["inventory"]

PROTECT_KEY = "streak_protect"
PROTECT_PRICE = 5    # 악귀코인
PROTECT_MAX = 2      # 한 사람이 들고 있을 수 있는 최대 장수


def _uid(user_id) -> str:
    return str(user_id)


def _count_sync(user_id, key: str) -> int:
    doc = _inventory.find_one({"_id": _uid(user_id)}, {key: 1})
    return int((doc or {}).get(key, 0) or 0)


def _grant_sync(user_id, key: str, limit: int) -> bool:
    """상한을 넘지 않을 때만 1장 늘리고 True. 꽉 찼으면 아무것도 안 하고 False.

    ⚠️ 필터에 `$lt: limit`을 넣어 **한 번의 update로** 끝내요. 읽고 나서 더하면 동시에
    두 번 들어왔을 때 상한을 넘어요.
    ⚠️ 문서가 없는 사람도 `$lt`에 안 걸려요(없는 필드는 비교가 안 돼요). 그래서 `$exists:false`를
    같이 허용하는 `$or`로 묶어요."""
    res = _inventory.update_one(
        {
            "_id": _uid(user_id),
            "$or": [{key: {"$lt": limit}}, {key: {"$exists": False}}],
        },
        {"$inc": {key: 1}},
        upsert=True,
    )
    return res.modified_count == 1 or res.upserted_id is not None


def _consume_sync(user_id, key: str) -> bool:
    """1장 쓰고 True. 없으면 아무것도 안 하고 False (조건부 차감이라 음수가 안 돼요)."""
    doc = _inventory.find_one_and_update(
        {"_id": _uid(user_id), key: {"$gte": 1}},
        {"$inc": {key: -1}},
        return_document=ReturnDocument.AFTER,
    )
    return doc is not None


def _refund_sync(user_id, key: str) -> None:
    """차감했는데 그 뒤 처리가 실패했을 때 되돌려요. 상한은 안 봐요(원래 갖고 있던 거니까요)."""
    _inventory.update_one({"_id": _uid(user_id)}, {"$inc": {key: 1}}, upsert=True)


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요 - 2026-09-04 먹통 사고)
# ------------------------------------------------------------------
async def protect_count(user_id) -> int:
    try:
        return await asyncio.to_thread(_count_sync, user_id, PROTECT_KEY)
    except Exception:  # noqa: BLE001
        # 조회 실패 시 **0으로** 봐요. 없는 보호권을 쓴 셈 치면 연속일이 거짓으로 늘어나요.
        log.warning("보호권 조회 실패 - 0으로 처리해요 (user=%s)", user_id, exc_info=True)
        return 0


async def grant_protect(user_id) -> bool:
    return await asyncio.to_thread(_grant_sync, user_id, PROTECT_KEY, PROTECT_MAX)


async def consume_protect(user_id) -> bool:
    return await asyncio.to_thread(_consume_sync, user_id, PROTECT_KEY)


async def refund_protect(user_id) -> None:
    await asyncio.to_thread(_refund_sync, user_id, PROTECT_KEY)
