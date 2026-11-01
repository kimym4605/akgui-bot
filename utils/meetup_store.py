"""🎿 정모 참가 신청을 저장해요. **한 사람의 선택은 한 줄**이에요.

## 왜 있나 (2026-11-01)

겨울 정모(2027-01-08~10) 1차 공지를 올렸는데 **참여 인원을 셀 수단이 하나도 없었어요.**
`#📢｜공지사항`은 @everyone에게 글쓰기·스레드가 막혀 있어서, 방장이 결국
`@everyone 정모 참여 할 인원은 ... 저에게 DM 남겨주세용`(11-01 05:12)으로 받기
시작했어요. DM은 봇이 집계할 수 없어서 **손으로 세야** 해요.

⭐ **버튼은 글쓰기 권한이 필요 없어요.** 잠긴 채널에 올라간 봇 메시지의 버튼도 누를 수
있어요. 그래서 "투표가 유일한 응답 경로"라던 판단이 뒤집혔어요.
(투표는 **최대 32일**이라 1월까지 못 끌고 가고, 성인·미성년 구분 집계도 안 돼요)

## 🚨 선택지 5개를 줄이지 마세요

날짜를 확정하고 날짜 투표를 뺐으니, 그냥 두면 **"안 간다"가 두 뜻으로 섞여요** —
관심 없는 사람과 *가고 싶지만 그날만 안 되는* 사람이 똑같이 ❌를 눌러서 구분이 안 돼요.
`other_date`가 **유일한 되돌림 장치**예요(✅보다 많으면 날짜를 다시 볼 신호).
`resort`(안 타지만 놀러는)도 빼면 안 돼요 — 그 칸이 없으면 그 사람들이 ❌를 눌러서
**정모가 실제보다 작아 보여요.**

## 🚨 한 사람당 한 문서예요 (배열이 아니에요)

`_id`가 `"<정모>:<유저>"`라서 **한 선택만 남는 게 구조로 보장돼요.** 선택지가 5개인데
배열 5개로 두면 "다른 배열에서 빼기"를 매번 맞춰야 하고, 중간에 끊기면 한 사람이 두
칸에 들어가요(`event_store`가 배열 2개로 그 위험을 안고 있어요).

## 🚨 집계를 공지 메시지에 그려 넣지 마세요

버튼을 누를 때마다 공지를 수정하면 **429 `30046`(1시간 넘은 메시지 편집 한도)** 에
걸려요. 집계는 **누른 사람에게 비공개 응답**으로, 전체 현황은 `/정모현황`으로 보여줘요.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_rsvp = _db["meetup_rsvp"]
# 어느 메시지가 어느 정모의 패널인지. 🚨 영속 뷰는 봇에 **객체가 하나뿐**이라
# 버튼에 정모 이름을 담을 수 없어요 — 담으면 다음 정모가 같은 집계를 공유해요
# (`event_store` 머리말의 사고가 이것이에요). 그래서 메시지 id로 찾아요.
_panels = _db["meetup_panels"]

KST = timezone(timedelta(hours=9))

# 지금 받고 있는 정모. 패널이 등록되지 않은 메시지에서 눌렸을 때 쓰는 기본값이에요.
DEFAULT_MEETUP = "ski2027"

# 🚨 순서가 화면 버튼 순서예요. 키는 DB에 들어가니 **바꾸면 옛 응답이 사라져요.**
CHOICES: dict[str, dict] = {
    "going":      {"emoji": "✅", "label": "갈래요",            "counts": True},
    "maybe":      {"emoji": "🤔", "label": "일정 보고",          "counts": True},
    "resort":     {"emoji": "🎿", "label": "안 타지만 놀러는",     "counts": True},
    "other_date": {"emoji": "📅", "label": "그날은 안 돼요",       "counts": False},
    "no":         {"emoji": "❌", "label": "못 가요",            "counts": False},
}
# `counts=True`는 **인원에 넣는 칸**이에요(견적 인원). `resort`도 오는 사람이라 넣어요.

CHOICE_HELP = {
    "going": "스키 타고 숙박까지 갈래요",
    "maybe": "가고 싶은데 일정을 더 봐야 해요",
    "resort": "스키·보드는 안 타고 리조트에서만 놀래요 (환영이에요)",
    "other_date": "가고 싶은데 **1월 8~10일이 안 돼요** (다른 날이면 갈래요)",
    "no": "이번엔 못 가요",
}


def _key(meetup: str, user_id) -> str:
    return f"{meetup}:{user_id}"


# ------------------------------------------------------------------ 패널 등록
def _register_sync(message_id, meetup: str, guild_id=None, channel_id=None) -> None:
    _panels.update_one(
        {"_id": str(message_id)},
        {"$set": {
            "meetup": meetup,
            "guildId": str(guild_id) if guild_id is not None else None,
            "channelId": str(channel_id) if channel_id is not None else None,
            "at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


def _meetup_of_sync(message_id) -> str:
    doc = _panels.find_one({"_id": str(message_id)})
    return (doc or {}).get("meetup") or DEFAULT_MEETUP


# ------------------------------------------------------------------ 응답 쓰기/읽기
def _set_choice_sync(meetup: str, user_id, choice: str) -> tuple[str | None, str | None]:
    """`(이전 선택, 지금 선택)`을 돌려줘요. 같은 걸 또 누르면 **취소**(지금 선택=None)예요.

    🚨 취소를 넣는 이유: 잘못 눌렀을 때 되돌릴 길이 없으면 사람들이 아예 안 눌러요.
    `event_store`의 참가 버튼도 같은 규칙이에요(같은 걸 또 누르면 취소)."""
    if choice not in CHOICES:
        raise ValueError(f"모르는 선택지: {choice}")
    uid = str(user_id)
    doc = _rsvp.find_one({"_id": _key(meetup, uid)})
    before = (doc or {}).get("choice")
    if before == choice:
        _rsvp.delete_one({"_id": _key(meetup, uid)})
        return before, None
    _rsvp.update_one(
        {"_id": _key(meetup, uid)},
        {"$set": {"meetup": meetup, "userId": uid, "choice": choice,
                  "at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return before, choice


def _counts_sync(meetup: str) -> dict[str, int]:
    """선택지별 인원. **고르지 않은 칸도 0으로 채워서** 돌려줘요
    (화면에서 `.get`을 빼먹어도 KeyError가 안 나게요)."""
    out = {key: 0 for key in CHOICES}
    for row in _rsvp.aggregate([
        {"$match": {"meetup": meetup}},
        {"$group": {"_id": "$choice", "n": {"$sum": 1}}},
    ]):
        if row["_id"] in out:
            out[row["_id"]] = int(row["n"])
    return out


def _members_sync(meetup: str) -> dict[str, list[str]]:
    """선택지별 유저 id 목록. 오래 누른 사람부터예요(먼저 신청한 순서)."""
    out: dict[str, list[str]] = {key: [] for key in CHOICES}
    for doc in _rsvp.find({"meetup": meetup}).sort("at", 1):
        if doc.get("choice") in out:
            out[doc["choice"]].append(str(doc.get("userId")))
    return out


def _choice_of_sync(meetup: str, user_id) -> str | None:
    doc = _rsvp.find_one({"_id": _key(meetup, user_id)})
    return (doc or {}).get("choice")


# ------------------------------------------------------------------ async 껍데기
async def register_panel(message_id, meetup: str, guild_id=None, channel_id=None) -> None:
    await asyncio.to_thread(_register_sync, message_id, meetup, guild_id, channel_id)


async def meetup_of(message_id) -> str:
    try:
        return await asyncio.to_thread(_meetup_of_sync, message_id)
    except Exception:  # noqa: BLE001
        # 🚨 조회가 실패해도 버튼은 먹어야 해요 — 기본 정모로 받아둬요.
        log.warning("정모 패널 조회 실패 (message=%s)", message_id, exc_info=True)
        return DEFAULT_MEETUP


async def set_choice(meetup: str, user_id, choice: str) -> tuple[str | None, str | None]:
    return await asyncio.to_thread(_set_choice_sync, meetup, user_id, choice)


async def counts(meetup: str) -> dict[str, int]:
    try:
        return await asyncio.to_thread(_counts_sync, meetup)
    except Exception:  # noqa: BLE001
        log.warning("정모 집계 실패 (%s)", meetup, exc_info=True)
        return {key: 0 for key in CHOICES}


async def members(meetup: str) -> dict[str, list[str]]:
    return await asyncio.to_thread(_members_sync, meetup)


async def choice_of(meetup: str, user_id) -> str | None:
    return await asyncio.to_thread(_choice_of_sync, meetup, user_id)


# ------------------------------------------------------------------ 보여주기
def headcount(counts_map: dict[str, int]) -> int:
    """견적에 쓸 인원 = `counts=True`인 칸의 합(`갈래요` + `일정 보고` + `안 타지만 놀러는`).

    🚨 `일정 보고`를 빼지 마세요 — 숙박 견적은 **올 수 있는 최대**로 받아야 해요.
    단 입금 마감 때는 `갈래요`만 세야 해요(그건 부르는 쪽에서 가려요)."""
    return sum(n for key, n in counts_map.items() if CHOICES[key]["counts"])


def confirmed(counts_map: dict[str, int]) -> int:
    """확실히 온다고 한 사람(`갈래요` + `안 타지만 놀러는`). 입금·방 배정 기준이에요."""
    return counts_map.get("going", 0) + counts_map.get("resort", 0)


def date_warning(counts_map: dict[str, int]) -> str | None:
    """`📅 그날은 안 돼요`가 `✅ 갈래요`보다 많으면 **날짜를 다시 볼 신호**예요."""
    blocked, going = counts_map.get("other_date", 0), counts_map.get("going", 0)
    if blocked and blocked > going:
        return (f"🔴 **날짜를 다시 볼 신호** — `📅 그날은 안 돼요` {blocked}명이 "
                f"`✅ 갈래요` {going}명보다 많아요.")
    return None
