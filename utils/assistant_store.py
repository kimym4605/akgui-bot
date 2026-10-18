"""❓ 봇 매니저가 Claude를 부른 횟수를 날짜별로 세요. **돈이 나가는 쪽이라 한도가 필요해요.**

## 왜 세는가

규칙으로 못 잡은 질문만 Claude(Haiku)로 넘기는데, 그건 질문 하나에 몇 원씩 나가요.
한 사람이 장난으로 수백 번 묻거나, 누가 봇을 긁으면 그대로 청구서가 돼요. 그래서
**사람별·서버별 하루 한도**를 두고, 한도를 넘으면 규칙 답변으로만 돌려요(기능이 죽지는 않아요).

## 🚨 세는 것과 쓰는 것의 순서

`take()`는 **부르기 전에** 호출해서 자리를 먼저 잡아요(`$inc` 한 번으로). 부른 뒤에 세면
동시에 여러 개가 들어왔을 때 한도를 넘겨요 — 코인 지갑과 같은 이유예요.
Claude 호출이 실패하면 `refund()`로 돌려줘요(돈이 안 나갔으니 한도도 안 깎아야 해요).

## 왜 날짜를 문서 _id로 쓰나

하루가 지나면 그 문서는 다시 볼 일이 없어요. 날짜를 키로 두면 리셋 작업이 필요 없고,
지난 기록이 그대로 남아서 "매니저를 얼마나 쓰는지"를 나중에 실측할 수 있어요
(기능을 만들었으면 DB 건수로 실사용을 확인한다 — 이 저장소의 규칙이에요).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_usage = _db["assistant_usage"]

KST = timezone(timedelta(hours=9))

# 하루 한도. Haiku 기준 질문 하나가 몇 원이라, 아래 숫자가 곧 하루 최대 지출이에요.
PER_USER_DAILY = 10
GUILD_DAILY = 60


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _take_sync(user_id: str) -> tuple[bool, str]:
    """자리를 잡고 (성공?, 막힌 이유)를 돌려줘요.

    ⚠️ 서버 한도와 개인 한도를 **따로** 확인해요. 조건부 `$inc` 하나로는 둘을 같이
    못 봐서, 서버 자리를 먼저 잡고 개인 한도에서 걸리면 서버 쪽을 되돌려요."""
    day = _today()
    field = f"users.{user_id}"

    # ⒜ 서버 자리 먼저 (`$lt`에 안 걸리는 '없는 필드'까지 허용해야 첫 질문이 통과해요)
    res = _usage.update_one(
        {
            "_id": day,
            "$or": [{"total": {"$lt": GUILD_DAILY}}, {"total": {"$exists": False}}],
        },
        {"$inc": {"total": 1}},
        upsert=True,
    )
    if res.modified_count == 0 and res.upserted_id is None:
        return False, "guild"

    # ⒝ 개인 한도
    res = _usage.update_one(
        {
            "_id": day,
            "$or": [{field: {"$lt": PER_USER_DAILY}}, {field: {"$exists": False}}],
        },
        {"$inc": {field: 1}},
    )
    if res.modified_count == 0:
        _usage.update_one({"_id": day}, {"$inc": {"total": -1}})  # ⒜ 되돌려요
        return False, "user"

    return True, ""


def _refund_sync(user_id: str) -> None:
    day = _today()
    _usage.update_one(
        {"_id": day},
        {"$inc": {"total": -1, f"users.{user_id}": -1}},
    )


def _today_count_sync() -> tuple[int, int]:
    doc = _usage.find_one({"_id": _today()}, {"total": 1, "users": 1}) or {}
    return int(doc.get("total", 0) or 0), len(doc.get("users") or {})


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요)
# ------------------------------------------------------------------
async def take(user_id) -> tuple[bool, str]:
    """Claude를 부를 자리를 잡아요. (성공?, "user" | "guild" | "")

    조회·기록이 실패하면 **통과시켜요.** DB가 삐끗했다고 안내 기능까지 멈추는 건 과해요
    (한도는 비용 안전장치일 뿐이고, 상한은 Claude 쪽 호출 실패로도 자연히 걸려요)."""
    try:
        return await asyncio.to_thread(_take_sync, str(user_id))
    except Exception:  # noqa: BLE001
        log.warning("매니저 사용량 기록 실패 - 통과시켜요 (user=%s)", user_id, exc_info=True)
        return True, ""


async def refund(user_id) -> None:
    try:
        await asyncio.to_thread(_refund_sync, str(user_id))
    except Exception:  # noqa: BLE001
        log.warning("매니저 사용량 환불 실패 (user=%s)", user_id, exc_info=True)


async def today_count() -> tuple[int, int]:
    """오늘 (호출 수, 쓴 사람 수). 실사용 확인용이에요."""
    try:
        return await asyncio.to_thread(_today_count_sync)
    except Exception:  # noqa: BLE001
        return 0, 0
