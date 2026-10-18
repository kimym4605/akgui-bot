"""💡 건의와 투표를 저장해요. 메시지 id가 곧 건의 id예요.

## 왜 메시지 id를 키로 쓰나

투표 버튼은 **영속 뷰**라 봇이 재시작돼도 살아 있어야 해요. 그런데 영속 뷰는 봇 전체에
객체가 **하나뿐**이라, 버튼 안에 상태를 담으면 모든 건의가 같은 상태를 공유해요
(`cogs/team.py`가 같은 이유로 메시지 id를 키로 써요). 그래서 "누른 메시지의 id로
여기서 읽고 쓴다"가 유일하게 안전한 방식이에요.

## 🚨 찬반은 서로 배타적이에요

👍를 눌렀던 사람이 👎를 누르면 **찬성에서 빼고 반대에 넣어야** 해요. 한 번의 update로
둘 다 처리하지 않으면, 중간에 끊겼을 때 같은 사람이 양쪽에 들어가요.
"""
import asyncio
import logging
from datetime import datetime, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_sug = _db["suggestions"]

# 상태값. 운영자가 바꿔요.
OPEN, ACCEPTED, DONE, DECLINED = "open", "accepted", "done", "declined"

STATUS_LABEL = {
    OPEN: ("💭", "검토 중"),
    ACCEPTED: ("✅", "채택"),
    DONE: ("🎉", "반영 완료"),
    DECLINED: ("🙏", "이번엔 보류"),
}
STATUS_COLOR = {
    OPEN: 0x6B7280,
    ACCEPTED: 0x3B82F6,
    DONE: 0x22C55E,
    DECLINED: 0x9BA3AF,
}


def _mid(message_id) -> str:
    return str(message_id)


def _create_sync(message_id, user_id, text: str) -> None:
    _sug.insert_one({
        "_id": _mid(message_id),
        "userId": str(user_id),
        "text": text,
        "up": [],
        "down": [],
        "status": OPEN,
        "note": None,
        "at": datetime.now(timezone.utc),
    })


def _get_sync(message_id) -> dict | None:
    return _sug.find_one({"_id": _mid(message_id)})


def _vote_sync(message_id, user_id, up: bool) -> dict | None:
    """투표하고 바뀐 문서를 돌려줘요. 같은 걸 또 누르면 **취소**돼요.

    🚨 찬성·반대를 **한 번의 update로** 처리해요. 두 번에 나누면 중간에 끊겼을 때
    같은 사람이 양쪽에 들어가요."""
    uid = str(user_id)
    doc = _sug.find_one({"_id": _mid(message_id)}, {"up": 1, "down": 1})
    if doc is None:
        return None

    already = uid in (doc.get("up") or []) if up else uid in (doc.get("down") or [])
    target, other = ("up", "down") if up else ("down", "up")

    if already:
        update = {"$pull": {target: uid}}            # 같은 걸 또 누르면 취소
    else:
        update = {"$addToSet": {target: uid}, "$pull": {other: uid}}

    from pymongo import ReturnDocument
    return _sug.find_one_and_update(
        {"_id": _mid(message_id)}, update, return_document=ReturnDocument.AFTER
    )


def _set_status_sync(message_id, status: str, note: str | None) -> dict | None:
    from pymongo import ReturnDocument
    return _sug.find_one_and_update(
        {"_id": _mid(message_id)},
        {"$set": {"status": status, "note": note}},
        return_document=ReturnDocument.AFTER,
    )


def _recent_sync(limit: int, status: str | None) -> list[dict]:
    query = {"status": status} if status else {}
    return list(_sug.find(query).sort("_id", -1).limit(limit))


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요)
# ------------------------------------------------------------------
async def create(message_id, user_id, text: str) -> None:
    await asyncio.to_thread(_create_sync, message_id, user_id, text)


async def get(message_id) -> dict | None:
    try:
        return await asyncio.to_thread(_get_sync, message_id)
    except Exception:  # noqa: BLE001
        log.warning("건의 조회 실패 (message=%s)", message_id, exc_info=True)
        return None


async def vote(message_id, user_id, up: bool) -> dict | None:
    return await asyncio.to_thread(_vote_sync, message_id, user_id, up)


async def set_status(message_id, status: str, note: str | None = None) -> dict | None:
    return await asyncio.to_thread(_set_status_sync, message_id, status, note)


async def recent(limit: int = 10, status: str | None = None) -> list[dict]:
    try:
        return await asyncio.to_thread(_recent_sync, limit, status)
    except Exception:  # noqa: BLE001
        return []
