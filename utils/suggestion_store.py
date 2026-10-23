"""💡 건의와 투표를 저장해요. 메시지 id가 곧 건의 id예요.

## 왜 메시지 id를 키로 쓰나

투표 버튼은 **영속 뷰**라 봇이 재시작돼도 살아 있어야 해요. 그런데 영속 뷰는 봇 전체에
객체가 **하나뿐**이라, 버튼 안에 상태를 담으면 모든 건의가 같은 상태를 공유해요
(`cogs/team.py`가 같은 이유로 메시지 id를 키로 써요). 그래서 "누른 메시지의 id로
여기서 읽고 쓴다"가 유일하게 안전한 방식이에요.

## 🚨 찬반은 서로 배타적이에요

👍를 눌렀던 사람이 👎를 누르면 **찬성에서 빼고 반대에 넣어야** 해요. 한 번의 update로
둘 다 처리하지 않으면, 중간에 끊겼을 때 같은 사람이 양쪽에 들어가요.

## 🚨 평문 줍기는 **먼저 찜한다** (2026-10-23)

평문에 달린 💡를 눌러 건의를 만들 때, 건의 문서의 `_id`는 **봇이 새로 올릴 메시지의
id**예요. 그 메시지는 아직 없으니까 "이미 등록됐나"를 건의 문서로는 막을 수 없어요.
그 사이에 두 사람이 💡를 누르면 **같은 글이 두 번 올라가요.**

그래서 원본 메시지 id를 `suggestion_claims`에 **먼저 insert**해요. 중복 키가 터지면
누군가 이미 찜한 거예요(`insert_one`은 원자적이라 경합에서 한쪽만 이겨요).
메시지를 못 올렸으면 `release_source`로 찜을 풀어서 다시 누를 수 있게 해요.
"""
import asyncio
import logging
from datetime import datetime, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_sug = _db["suggestions"]
# 평문 줍기 전용. `_id`가 **원본(사람이 쓴) 메시지 id**예요 — 위 "먼저 찜한다" 참고.
_claims = _db["suggestion_claims"]

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


def _create_sync(message_id, user_id, text: str, source_id=None) -> None:
    _sug.insert_one({
        "_id": _mid(message_id),
        "userId": str(user_id),
        "text": text,
        "up": [],
        "down": [],
        "status": OPEN,
        "note": None,
        # 평문에서 주워 온 건의면 원본 메시지 id예요. `/건의`로 쓴 건 None이에요.
        # 이게 들어있는 건수를 세면 "평문 줍기가 실제로 쓰이는지"를 바로 알 수 있어요.
        "sourceId": _mid(source_id) if source_id else None,
        "at": datetime.now(timezone.utc),
    })


def _claim_source_sync(source_id) -> bool:
    """이 원본 메시지를 내가 찜했으면 True. 누가 이미 찜했으면 False예요."""
    from pymongo.errors import DuplicateKeyError
    try:
        _claims.insert_one({
            "_id": _mid(source_id),
            "at": datetime.now(timezone.utc),
        })
        return True
    except DuplicateKeyError:
        return False


def _release_source_sync(source_id) -> None:
    _claims.delete_one({"_id": _mid(source_id)})


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
async def create(message_id, user_id, text: str, source_id=None) -> None:
    await asyncio.to_thread(_create_sync, message_id, user_id, text, source_id)


async def claim_source(source_id) -> bool:
    """평문 줍기 전에 원본을 찜해요. False면 이미 등록된 글이에요.

    🚨 **이걸 건너뛰면 두 사람이 동시에 💡를 눌러 같은 글이 두 번 올라가요.**
    조회로 막으려 하지 마세요(확인과 insert 사이가 비어요)."""
    try:
        return await asyncio.to_thread(_claim_source_sync, source_id)
    except Exception:  # noqa: BLE001
        log.warning("건의 원본 찜 실패 (source=%s)", source_id, exc_info=True)
        return False  # DB가 흔들릴 때는 **중복을 만드는 쪽보다 안 올리는 쪽**이 나아요


async def release_source(source_id) -> None:
    """메시지를 못 올렸을 때 찜을 풀어요(안 풀면 그 글은 영영 못 올려요)."""
    try:
        await asyncio.to_thread(_release_source_sync, source_id)
    except Exception:  # noqa: BLE001
        log.warning("건의 원본 찜 해제 실패 (source=%s)", source_id, exc_info=True)


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
