"""악귀코인 지갑 - 포켓몬을 아직 시작하지 않은 사람도 코인을 모을 수 있게 해주는 계층이에요.

## 왜 필요한가

코인은 원래 `trainers` 문서 안의 `coin` 필드에만 있었어요. 그런데 그러면 **포켓몬 웹을
시작한 사람만** 코인을 가질 수 있어요. 서버 미션으로 코인을 벌게 하려는데, 정작 포켓몬을
안 하는 사람들은 코인을 담을 곳이 없는 셈이죠.

## 어디에 담는가

- **트레이너면** `trainers.coin` (지금까지와 완전히 동일 - 웹 상점이 그대로 읽어요)
- **아니면** `coin_reset_backup` 컬렉션

두 번째가 핵심이에요. `coin_reset_backup`은 웹이 **이미 쓰고 있는** 컬렉션이에요.
정식 오픈 때 계정을 전부 초기화하면서 코인만 살려두려고 만든 건데, 하는 일이 정확히
"포켓몬 없이 코인만 보관해뒀다가, 나중에 그 사람이 스타팅을 고르면 자동으로 얹어주기"예요
(웹 `pokemon_store._claim_backed_up_coin`). 우리가 필요한 게 딱 이거라서 그대로 재사용해요.

덕분에 **웹 코드를 한 줄도 고치지 않고** 포켓몬 미시작자도 코인을 모을 수 있고, 나중에 웹에서
스타팅을 고르면 모아둔 코인이 그대로 따라가요.

⚠️ 이름이 `coin_reset_backup`이라 "초기화 백업"처럼 보이지만 지금은 **지갑 겸용**이에요.
웹에서 `reset_all_trainers()`를 다시 돌릴 일이 있으면, 그 함수가 `$set`으로 덮어쓰기 때문에
지갑 잔액과 충돌할 수 있어요(단, trainers에 없는 사람은 루프에 안 걸려서 실제로는 안전해요).

## 동시성

잔액 변경은 전부 `$inc`(더하기)와 **조건부 update**로 해요. 읽어서 계산한 뒤 덮어쓰면
같은 순간 두 번 들어왔을 때 하나가 사라져요(미션 완료 + 송금이 겹치는 식으로).

⚠️ "트레이너인지 확인 → 해당 컬렉션에 반영" 사이에 그 사람이 웹에서 스타팅을 고르면 아주
드물게 코인이 지갑 쪽에 남을 수 있어요. 그래도 잃지는 않아요 - 다음에 웹이
`_claim_backed_up_coin()`으로 회수해가요.
"""
import asyncio
import logging

from pymongo import ReturnDocument

# pokemon_store가 이미 타임아웃까지 맞춰둔 클라이언트를 갖고 있어서 그대로 빌려 써요.
# (연결을 따로 만들면 커넥션 풀이 두 배가 되는데, 256MB 머신에선 그만한 이유가 없어요.)
from utils.pokemon_store import _db, _trainers

log = logging.getLogger(__name__)

# 웹의 pokemon_store._coin_backup과 같은 컬렉션이에요. 이름을 바꾸면 웹과 어긋나니 그대로 둬요.
_wallet = _db["coin_reset_backup"]

# 코인이 오간 기록. 분쟁("안 받았는데요") 대비용이라 실패해도 본 거래는 막지 않아요.
_coin_log = _db["coin_log"]


def _uid(user_id) -> str:
    return str(user_id)


def _is_trainer_sync(user_id) -> bool:
    return _trainers.find_one({"_id": _uid(user_id)}, {"_id": 1}) is not None


def _get_balance_sync(user_id) -> int:
    doc = _trainers.find_one({"_id": _uid(user_id)}, {"coin": 1})
    if doc is None:
        doc = _wallet.find_one({"_id": _uid(user_id)}, {"coin": 1})
    return int((doc or {}).get("coin", 0) or 0)


def _add_sync(user_id, amount: int) -> int:
    """코인을 넣고 바뀐 잔액을 돌려줘요. 트레이너 문서가 있으면 거기에, 없으면 지갑에 넣어요."""
    uid = _uid(user_id)
    doc = _trainers.find_one_and_update(
        {"_id": uid},
        {"$inc": {"coin": amount}},
        projection={"coin": 1},
        return_document=ReturnDocument.AFTER,
    )
    if doc is not None:
        return int(doc.get("coin", 0) or 0)

    # 트레이너가 아니면 지갑에. upsert라 처음 받는 사람도 알아서 지갑이 생겨요.
    doc = _wallet.find_one_and_update(
        {"_id": uid},
        {"$inc": {"coin": amount}},
        projection={"coin": 1},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc.get("coin", 0) or 0)


def _spend_sync(user_id, amount: int) -> bool:
    """잔액이 충분할 때만 차감하고 True. 부족하면 아무것도 안 하고 False.

    ⚠️ 조회 후 차감이 아니라 **조건을 붙인 한 번의 update**로 해요. 안 그러면 잔액을 읽은
    직후 다른 명령이 먼저 써버렸을 때 마이너스가 될 수 있어요."""
    uid = _uid(user_id)
    col = _trainers if _is_trainer_sync(user_id) else _wallet
    res = col.update_one({"_id": uid, "coin": {"$gte": amount}}, {"$inc": {"coin": -amount}})
    return res.modified_count == 1


def _log_sync(kind: str, from_id, to_id, amount: int, note: str = ""):
    try:
        _coin_log.insert_one({
            "kind": kind,
            "from": _uid(from_id) if from_id is not None else None,
            "to": _uid(to_id) if to_id is not None else None,
            "amount": amount,
            "note": note,
        })
    except Exception:
        # 기록 실패로 거래 자체를 되돌리진 않아요. 기록은 어디까지나 사후 확인용이에요.
        log.warning("코인 기록 저장 실패 (%s %s→%s %d)", kind, from_id, to_id, amount, exc_info=True)


def _transfer_sync(from_id, to_id, amount: int) -> tuple[bool, str]:
    """돌려주는 두 번째 값은 실패 사유예요: self(자기 자신) / amount(0 이하) / balance(잔액 부족)."""
    if amount <= 0:
        return False, "amount"
    if _uid(from_id) == _uid(to_id):
        return False, "self"

    if not _spend_sync(from_id, amount):
        return False, "balance"

    try:
        _add_sync(to_id, amount)
    except Exception:
        # 받는 쪽에서 터지면 보낸 사람 코인이 증발해버려요. 반드시 되돌려놔요.
        _add_sync(from_id, amount)
        log.error("송금 실패로 되돌림 (%s→%s %d개)", from_id, to_id, amount, exc_info=True)
        raise

    _log_sync("transfer", from_id, to_id, amount)
    return True, "ok"


# ------------------------------------------------------------------
# 공개 API - 전부 async예요. 반드시 await 하세요.
#
# DB 작업은 동기 pymongo라, 그대로 부르면 이벤트 루프가 멈춰요(2026-09-04 먹통 사고의
# 원인). pokemon_store와 똑같이 asyncio.to_thread로 넘겨서 루프는 계속 돌게 해요.
# ------------------------------------------------------------------
async def is_trainer(user_id) -> bool:
    """포켓몬을 시작한 사람인지(= 코인이 트레이너 문서에 들어있는지)."""
    return await asyncio.to_thread(_is_trainer_sync, user_id)


async def get_balance(user_id) -> int:
    """지금 가진 악귀코인 개수. 트레이너든 아니든 알아서 맞는 곳에서 읽어요."""
    return await asyncio.to_thread(_get_balance_sync, user_id)


async def add(user_id, amount: int, *, reason: str = "") -> int:
    """코인을 지급하고 바뀐 잔액을 돌려줘요. (출석/미션 보상 등)"""
    balance = await asyncio.to_thread(_add_sync, user_id, amount)
    await asyncio.to_thread(_log_sync, "add", None, user_id, amount, reason)
    return balance


async def spend(user_id, amount: int, *, reason: str = "") -> bool:
    """잔액이 충분하면 차감하고 True, 부족하면 아무것도 안 하고 False. (상점 구매 등)"""
    ok = await asyncio.to_thread(_spend_sync, user_id, amount)
    if ok:
        await asyncio.to_thread(_log_sync, "spend", user_id, None, amount, reason)
    return ok


async def transfer(from_id, to_id, amount: int) -> tuple[bool, str]:
    """유저 간 송금. (성공여부, 실패사유) - 사유는 self/amount/balance 중 하나예요."""
    return await asyncio.to_thread(_transfer_sync, from_id, to_id, amount)
