"""📅 예약된 일정과 참가자를 저장해요. 메시지 id가 곧 일정 id예요.

## 왜 메시지 id를 키로 쓰나

참가 버튼은 **영속 뷰**예요(며칠 뒤 일정이라 봇이 그 사이 몇 번이나 재시작돼요).
영속 뷰는 봇 전체에 객체가 **하나뿐**이라 버튼 안에 상태를 담으면 모든 일정이 같은
상태를 공유해요. `cogs/team.py`가 이걸 어겨서 "9/22 배포 이후 내전 경기가 한 건도
기록되지 못한" 사고가 났어요. 그래서 상태는 전부 여기 두고 메시지 id로 읽고 써요.

## 🚨 시간은 UTC로 저장하고 KST로 보여줘요

한국 시간을 그대로 저장하면 비교할 때마다 헷갈려요(이 저장소가 `coin_log`에서 겪은
문제예요). **저장은 timezone-aware UTC, 표시는 KST**로 통일해요.

## 🚨 리마인더는 "보냈는지"를 기록해야 해요

루프가 1분마다 도는데 플래그가 없으면 같은 일정을 수십 번 알려요.
`remindedAt`이 있으면 보낸 거예요.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_events = _db["events"]
# 평문 줍기 전용. `_id`가 **원본(사람이 쓴) 모집글 id**예요.
# 🚨 일정 문서의 `_id`는 봇이 새로 올릴 메시지 id라서 "이미 등록됐나"를 그걸로는
#    막을 수 없어요 — 두 사람이 동시에 📅 를 누르면 같은 모집이 두 번 올라가요.
#    `utils/suggestion_store.py`가 같은 이유로 같은 구조예요.
_claims = _db["event_claims"]

KST = timezone(timedelta(hours=9))

# 시작 몇 분 전에 알릴지.
REMIND_BEFORE_MINUTES = 30

# 지난 일정을 목록에서 언제까지 보여줄지.
KEEP_AFTER_HOURS = 6


def _mid(message_id) -> str:
    return str(message_id)


def _claim_source_sync(source_id) -> bool:
    """이 모집글을 내가 찜했으면 True. 누가 이미 찜했으면 False예요."""
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


def _create_sync(message_id, guild_id, channel_id, host_id, title: str,
                 start_at: datetime, capacity: int | None) -> None:
    _events.insert_one({
        "_id": _mid(message_id),
        "guildId": str(guild_id),
        "channelId": str(channel_id),
        "hostId": str(host_id),
        "title": title,
        # 🚨 UTC로 저장해요. KST로 저장하면 비교할 때마다 헷갈려요.
        "startAt": start_at.astimezone(timezone.utc),
        "capacity": capacity,
        "going": [str(host_id)],     # 만든 사람은 자동 참가
        "declined": [],
        "remindedAt": None,
        "canceledAt": None,
        "createdAt": datetime.now(timezone.utc),
    })


def _get_sync(message_id) -> dict | None:
    return _events.find_one({"_id": _mid(message_id)})


def _rsvp_sync(message_id, user_id, going: bool) -> dict | None:
    """참가/불참을 바꿔요. 같은 걸 또 누르면 취소돼요. 정원이 찼으면 None 대신 그대로 둬요.

    🚨 참가·불참을 **한 번의 update로** 처리해요. 두 번에 나누면 중간에 끊겼을 때
    같은 사람이 양쪽에 들어가요."""
    from pymongo import ReturnDocument

    uid = str(user_id)
    doc = _events.find_one({"_id": _mid(message_id)})
    if doc is None or doc.get("canceledAt"):
        return None

    in_going = uid in (doc.get("going") or [])
    in_declined = uid in (doc.get("declined") or [])

    if going:
        if in_going:
            update = {"$pull": {"going": uid}}            # 참가 취소
        else:
            cap = doc.get("capacity")
            if cap and len(doc.get("going") or []) >= cap:
                return doc  # 정원이 찼어요 (바뀐 것 없이 그대로)
            update = {"$addToSet": {"going": uid}, "$pull": {"declined": uid}}
    else:
        if in_declined:
            update = {"$pull": {"declined": uid}}
        else:
            update = {"$addToSet": {"declined": uid}, "$pull": {"going": uid}}

    return _events.find_one_and_update(
        {"_id": _mid(message_id)}, update, return_document=ReturnDocument.AFTER
    )


def _cancel_sync(message_id, user_id) -> dict | None:
    """주최자만 취소할 수 있어요. 권한이 없으면 None."""
    from pymongo import ReturnDocument

    doc = _events.find_one({"_id": _mid(message_id)})
    if doc is None or str(doc.get("hostId")) != str(user_id):
        return None
    return _events.find_one_and_update(
        {"_id": _mid(message_id)},
        {"$set": {"canceledAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def _due_sync() -> list[dict]:
    """지금 알려야 할 일정들. **아직 안 알린 것만.**"""
    now = datetime.now(timezone.utc)
    return list(_events.find({
        "canceledAt": None,
        "remindedAt": None,
        "startAt": {
            "$lte": now + timedelta(minutes=REMIND_BEFORE_MINUTES),
            "$gte": now - timedelta(minutes=10),   # 너무 지난 건 조용히 넘겨요
        },
    }))


def _mark_reminded_sync(message_id) -> None:
    _events.update_one(
        {"_id": _mid(message_id)},
        {"$set": {"remindedAt": datetime.now(timezone.utc)}},
    )


def _upcoming_sync(guild_id, limit: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    return list(
        _events.find({
            "guildId": str(guild_id),
            "canceledAt": None,
            "startAt": {"$gte": now - timedelta(hours=KEEP_AFTER_HOURS)},
        }).sort("startAt", 1).limit(limit)
    )


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요)
# ------------------------------------------------------------------
async def create(message_id, guild_id, channel_id, host_id, title, start_at, capacity):
    await asyncio.to_thread(
        _create_sync, message_id, guild_id, channel_id, host_id, title, start_at, capacity
    )


async def claim_source(source_id) -> bool:
    """평문 줍기 전에 모집글을 찜해요. False면 이미 일정이 된 글이에요.

    🚨 **조회로 막으려 하지 마세요** — 확인과 insert 사이가 비어서, 동시에 📅 를
    누르면 같은 모집이 두 번 올라가요."""
    try:
        return await asyncio.to_thread(_claim_source_sync, source_id)
    except Exception:  # noqa: BLE001
        log.warning("일정 원본 찜 실패 (source=%s)", source_id, exc_info=True)
        return False  # DB가 흔들릴 때는 **중복을 만드는 쪽보다 안 올리는 쪽**이 나아요


async def release_source(source_id) -> None:
    """메시지를 못 올렸을 때 찜을 풀어요(안 풀면 그 모집은 영영 못 올려요)."""
    try:
        await asyncio.to_thread(_release_source_sync, source_id)
    except Exception:  # noqa: BLE001
        log.warning("일정 원본 찜 해제 실패 (source=%s)", source_id, exc_info=True)


async def get(message_id) -> dict | None:
    try:
        return await asyncio.to_thread(_get_sync, message_id)
    except Exception:  # noqa: BLE001
        log.warning("일정 조회 실패 (message=%s)", message_id, exc_info=True)
        return None


async def rsvp(message_id, user_id, going: bool) -> dict | None:
    return await asyncio.to_thread(_rsvp_sync, message_id, user_id, going)


async def cancel(message_id, user_id) -> dict | None:
    return await asyncio.to_thread(_cancel_sync, message_id, user_id)


async def due() -> list[dict]:
    try:
        return await asyncio.to_thread(_due_sync)
    except Exception:  # noqa: BLE001
        log.warning("일정 리마인더 조회 실패", exc_info=True)
        return []


async def mark_reminded(message_id) -> None:
    await asyncio.to_thread(_mark_reminded_sync, message_id)


async def upcoming(guild_id, limit: int = 10) -> list[dict]:
    try:
        return await asyncio.to_thread(_upcoming_sync, guild_id, limit)
    except Exception:  # noqa: BLE001
        return []
