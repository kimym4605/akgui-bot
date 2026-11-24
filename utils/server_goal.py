"""🤝 서버 공동 목표 — 이번 주에 "몇 명이 했나"를 세고, 다 같이 채우면 참여한 사람에게 코인 (2026-11-25).

## 왜 합계가 아니라 인원이냐

"물고기 500마리"처럼 합계로 세면 많이 하는 몇 명이 혼자 채워요. 그러면 나머지는 할 일이 없어요.
인원으로 세면 한 번만 해도 한 칸을 채우니까 **조금 하는 사람도 기여**해요(사용자 결정).

## 목표 숫자 (2026-11-25 실측: W44~W47)

| 칸 | 지금 | 목표 |
|---|---|---|
| 🎯 미션 완주한 사람 | 9명(W47) | 12 |
| 🧩 발로들 하나라도 끝낸 사람 | 이틀에 11명(W48) | 15 |
| 🎣 낚시 1마리라도 잡은 사람 | 11~12명 | 15 |

지금보다 2~3명 더 하면 닿게 잡았어요. 너무 쉬우면 의미가 없고, 너무 어려우면 아무도 안 봐요.
바꿀 땐 `GOALS`만 고치면 돼요.

## 보상 — 작게

칸 하나 달성 → 그 칸에 참여한 사람마다 2코인. 세 칸 다 → 하나라도 참여한 사람마다 3코인 더.
한 사람 최대 9코인/주. 지갑 중앙값 36·소각률 85%(11/22)라 크게 주면 경제가 기울어요.
**달성한 뒤에 참여해도 받아요**(늦게 온 사람도 손해 없게).

## 새로 세지 않아요 — 이미 쌓이는 기록만 읽어요

- 🎯 `coin_log`의 `note: "미션완주"` (`cogs/mission.py`의 `FULL_CLEAR_REASON`). 시각은 `_id`에서.
- 🧩 `balodle_plays`에서 그 주 날짜에 `status`가 solved/failed인 칸이 있는 사람.
  (🔁 연습 문제는 DB에 안 남아서 안 세요 — 의도대로예요.)
- 🎣 `fishing_week`의 그 주 문서에서 `caught >= 1`.

기존 기능 코드는 한 줄도 안 건드려요.

## 🚨 두 번 지급하지 않기

`server_goals` 문서의 `paid.<칸>` 배열에 **먼저 넣는 데 성공한 경우만** 코인을 줘요
(`{paid.x: {$ne: uid}}` 조건 + `$addToSet`). 넣고 나서 코인 지급이 실패하면 그 사람은 못 받아요
(2코인이라 두 번 주는 쪽보다 낫다고 봤어요) — 로그에 남겨요.

    server_goals  {_id: "2026-W48", reached: {mission: iso, …}, all_reached: iso,
                   paid: {mission: [uid], balodle: [...], fishing: [...], all: [...]},
                   closed: bool, summary_msg: id}
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

_goals = _db["server_goals"]
_coin_log = _db["coin_log"]
_plays = _db["balodle_plays"]
_fish_week = _db["fishing_week"]

MISSION_CLEAR_NOTE = "미션완주"      # cogs/mission.py FULL_CLEAR_REASON 과 같아야 해요
REASON_PREFIX = "공동목표"           # coin_log note: 공동목표:2026-W48:mission


@dataclass(frozen=True)
class Goal:
    key: str
    emoji: str
    name: str       # 패널 제목줄
    how: str        # 어떻게 참여하나
    target: int
    reward: int


GOALS: list[Goal] = [
    Goal("mission", "🎯", "미션 완주한 사람", "`/미션` 그날 미션을 전부 깨기", 12, 2),
    Goal("balodle", "🧩", "발로들 푼 사람", "발로들 채널에서 문제 하나 끝내기", 15, 2),
    Goal("fishing", "🎣", "낚시한 사람", "`/낚시`로 한 마리 잡기", 15, 2),
]
BY_KEY = {g.key: g for g in GOALS}
ALL_KEY = "all"
ALL_BONUS = 3
# 이 주부터 세요. 기능이 없던 주를 소급 정산·발표하지 않게(배포 첫날 지난주 결과 글이 뜨면 이상해요).
FIRST_WEEK = "2026-W48"


# ------------------------------------------------------------------
# 주(週) — ISO 주, 한국 시간 월요일 0시 ~ 다음 월요일 0시
# ------------------------------------------------------------------
def week_key(when: datetime | None = None) -> str:
    """`fishing_week.week_key`와 같은 모양이어야 해요(그 컬렉션을 이 키로 찾아요)."""
    now = when or datetime.now(KST)
    year, week, _ = now.astimezone(KST).isocalendar()
    return f"{year}-W{week:02d}"


def week_start(week: str) -> datetime:
    """"2026-W48" → 그 주 월요일 0시(KST)."""
    year, w = week.split("-W")
    monday = date.fromisocalendar(int(year), int(w), 1)
    return datetime(monday.year, monday.month, monday.day, tzinfo=KST)


def previous_week_key(when: datetime | None = None) -> str:
    return week_key((when or datetime.now(KST)) - timedelta(days=7))


def week_label(week: str) -> str:
    """"11/23(월) ~ 11/29(일)"."""
    start = week_start(week)
    end = start + timedelta(days=6)
    return f"{start.month}/{start.day}(월) ~ {end.month}/{end.day}(일)"


# ------------------------------------------------------------------
# 순수 계산 (DB를 몰라요 — 테스트하기 쉽게)
# ------------------------------------------------------------------
def progress_bar(count: int, target: int, width: int = 12) -> str:
    filled = width if target <= 0 else min(width, round(width * count / target))
    return "█" * filled + "░" * (width - filled)


def reached_keys(counts: dict[str, int]) -> list[str]:
    return [g.key for g in GOALS if counts.get(g.key, 0) >= g.target]


def contributors_all(people: dict[str, set]) -> set:
    """세 칸 중 하나라도 참여한 사람."""
    out: set = set()
    for g in GOALS:
        out |= people.get(g.key, set())
    return out


# ------------------------------------------------------------------
# 세기 (읽기만)
# ------------------------------------------------------------------
def _oid_range(week: str) -> dict:
    start = week_start(week)
    end = start + timedelta(days=7)
    return {"$gte": ObjectId.from_datetime(start.astimezone(timezone.utc)),
            "$lt": ObjectId.from_datetime(end.astimezone(timezone.utc))}


def _people_sync(week: str) -> dict[str, set]:
    people: dict[str, set] = {}

    people["mission"] = {
        str(d["to"]) for d in _coin_log.find(
            {"_id": _oid_range(week), "note": MISSION_CLEAR_NOTE, "kind": "add"}, {"to": 1})
        if d.get("to")
    }

    start = week_start(week)
    first = start.date().isoformat()
    last = (start + timedelta(days=6)).date().isoformat()
    done = set()
    for d in _plays.find({"date": {"$gte": first, "$lte": last}},
                         {"uid": 1, "agent.status": 1, "ability.status": 1, "map.status": 1}):
        if any((d.get(k) or {}).get("status") in ("solved", "failed")
               for k in ("agent", "ability", "map")) and d.get("uid"):
            done.add(str(d["uid"]))
    people["balodle"] = done

    people["fishing"] = {
        str(d["userId"]) for d in _fish_week.find(
            {"week": week, "caught": {"$gte": 1}}, {"userId": 1})
        if d.get("userId")
    }
    return people


async def people(week: str) -> dict[str, set]:
    """칸마다 참여한 사람(유저 ID 문자열) 집합."""
    return await asyncio.to_thread(_people_sync, week)


# ------------------------------------------------------------------
# 상태 (server_goals)
# ------------------------------------------------------------------
def _ensure_sync(week: str) -> dict:
    try:
        _goals.update_one({"_id": week}, {"$setOnInsert": {"paid": {}, "reached": {}}}, upsert=True)
    except DuplicateKeyError:
        pass
    return _goals.find_one({"_id": week}) or {}


async def get_state(week: str) -> dict:
    return await asyncio.to_thread(_ensure_sync, week)


def _claim_sync(week: str, key: str, uid: str) -> bool:
    res = _goals.update_one(
        {"_id": week, f"paid.{key}": {"$ne": uid}}, {"$addToSet": {f"paid.{key}": uid}})
    return res.modified_count == 1


async def claim(week: str, key: str, uid: str) -> bool:
    """이 사람에게 이 칸 보상을 **처음** 주는 거면 True (그때만 코인을 줘요)."""
    return await asyncio.to_thread(_claim_sync, week, key, uid)


def _mark_once_sync(week: str, field: str) -> bool:
    res = _goals.update_one({"_id": week, field: {"$exists": False}},
                            {"$set": {field: datetime.now(timezone.utc).isoformat()}})
    return res.modified_count == 1


async def mark_reached(week: str, key: str) -> bool:
    """처음 달성한 순간이면 True (달성 글을 한 번만 올리려고)."""
    field = "all_reached" if key == ALL_KEY else f"reached.{key}"
    return await asyncio.to_thread(_mark_once_sync, week, field)


async def close_week(week: str) -> bool:
    """지난주 마감 표시. 처음 마감하는 거면 True (결과 글을 한 번만)."""
    return await asyncio.to_thread(_mark_once_sync, week, "closed")


def _save_summary_sync(week: str, counts: dict, contributors: int) -> None:
    _goals.update_one({"_id": week}, {"$set": {"summary": {
        "counts": counts, "contributors": contributors,
        "reached": reached_keys(counts)}}})


async def save_summary(week: str, counts: dict, contributors: int) -> None:
    """마감한 주의 결과. 패널의 '지난주' 줄과 월요일 배너가 이걸 읽어요."""
    await asyncio.to_thread(_save_summary_sync, week, counts, contributors)


def _summary_sync(week: str) -> dict | None:
    doc = _goals.find_one({"_id": week}, {"summary": 1})
    return (doc or {}).get("summary")


async def summary(week: str) -> dict | None:
    if week < FIRST_WEEK:
        return None
    return await asyncio.to_thread(_summary_sync, week)


def banner_line(s: dict | None) -> str | None:
    """배너 맨 아래 한 줄. 🚨 배너 글꼴은 이모지를 못 그려요 — 글자만."""
    if not s:
        return None
    n = len(s.get("reached") or [])
    if n == len(GOALS):
        return f"다 같이 공동 목표 {n}/{len(GOALS)} 달성!  참여 {s.get('contributors', 0)}명"
    return f"공동 목표 {n}/{len(GOALS)} 달성  참여 {s.get('contributors', 0)}명"

