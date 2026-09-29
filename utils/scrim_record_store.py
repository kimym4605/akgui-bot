"""내전 전적 - 누가 몇 승 몇 패인지, 지금 몇 연승인지를 쌓아두는 곳이에요.

## 왜 새로 만들었나

지금까지 봇 어디에도 **개인 단위 승패가 남지 않았어요.** `bets` 컬렉션에 승리 팀은
기록되지만 거기 들어있는 사람은 팀장 2명과 코인을 건 사람뿐이라, 실제로 경기를 뛴
10명이 누군지 알 수가 없었어요. 그래서 "31승 24패", "최고 연승 7" 같은 걸 보여줄 방법이
없었고, 업적·주간 랭킹처럼 그 위에 얹는 기능도 전부 막혀 있었어요.

## 기록이 들어오는 경로

**`/팀짜기` 결과 메시지의 승리 보고 버튼 하나뿐이에요.** 음성채널 인원으로 팀을 짠
직후라 출전 명단이 그대로 손에 있어서, 버튼 한 번이면 양 팀 전원의 전적이 한꺼번에
들어가요.

⚠️ `/베팅결과`에도 물려볼까 했는데 **일부러 안 했어요.** `bets` 문서에는 팀장 2명과
코인을 건 사람만 있고 실제로 뛴 10명이 없어서, 거기서 기록하면 *팀장만 판수가 쌓여요*.
"내전 200판"이 사실은 "팀장 200번"이 되는 식으로 전적이 통째로 왜곡돼요. 기록이 적은
것보다 틀린 게 나쁘다고 봤어요.

## 문서 구조

한 사람이 **통산 문서 하나 + 시즌 문서 하나**를 가져요.

    {"_id": "all:123", "userId": "123", "scope": "all",
     "wins": 31, "losses": 24, "streak": 3, "bestStreak": 7, "worstStreak": -4, ...}
    {"_id": "S1:123",  "userId": "123", "scope": "S1",  ...}

시즌을 문서 안의 중첩 dict로 넣지 않고 `_id`를 나눈 이유는 **랭킹 때문**이에요.
중첩이면 `seasons.S1.wins`로 정렬해야 해서 시즌이 늘 때마다 인덱스가 따라 늘어나는데,
문서를 나누면 `{"scope": "S1"}` 하나로 걸러서 정렬하면 끝이에요.

## 동시성

10명이 한 경기로 동시에 갱신되고, 같은 사람이 연달아 두 경기를 보고할 수도 있어요.
그래서 읽고-계산해서-쓰지 않고 **update 파이프라인**으로 DB 안에서 계산해요
(MongoDB 4.2+). 연승은 "이기면 (직전이 양수면 +1, 아니면 1)"이라 조건식이 필요한데,
이걸 파이썬에서 하면 동시에 들어온 두 경기 중 하나가 통째로 사라져요.
"""
import asyncio
import logging
from datetime import datetime, timezone

from utils.pokemon_store import _db
from utils.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

_records = _db["scrim_records"]
# 경기 단위 원본이에요. 집계가 틀어졌을 때 되짚어보려고 남겨둬요("나 그날 이겼는데요").
_matches = _db["scrim_matches"]

SCOPE_ALL = "all"
SEASON_SETTING_KEY = "scrimSeason"
DEFAULT_SEASON = "S1"

# 한 경기로 인정할 최소 인원이에요. 2명(1대1)부터 쳐요.
MIN_PLAYERS = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_season() -> str:
    """지금 시즌 이름. `/내전시즌` 으로 서버 소유자가 바꿔요."""
    return get_setting(SEASON_SETTING_KEY) or DEFAULT_SEASON


def set_season(name: str):
    set_setting(SEASON_SETTING_KEY, name)


def _update_pipeline(won: bool, scope: str, user_id: str) -> list[dict]:
    """이겼는지에 따라 승/패·연승을 DB 안에서 계산하는 파이프라인이에요.

    연승(streak)은 이기면 양수, 지면 음수로 이어져요. 3연승이면 3, 2연패면 -2예요.
    한 필드로 둘 다 표현하면 "연승이 끊겼다"를 부호가 바뀌는 것만으로 알 수 있어요."""
    prev = {"$ifNull": ["$streak", 0]}
    if won:
        # 이겼을 때: 직전이 양수(연승 중)면 이어서 +1, 아니면 1부터 다시 시작해요.
        next_streak = {"$cond": [{"$gt": [prev, 0]}, {"$add": [prev, 1]}, 1]}
    else:
        # 졌을 때: 직전이 음수(연패 중)면 이어서 -1, 아니면 -1부터 다시 시작해요.
        next_streak = {"$cond": [{"$lt": [prev, 0]}, {"$add": [prev, -1]}, -1]}

    return [
        {
            "$set": {
                "userId": user_id,
                "scope": scope,
                "wins": {"$add": [{"$ifNull": ["$wins", 0]}, 1 if won else 0]},
                "losses": {"$add": [{"$ifNull": ["$losses", 0]}, 0 if won else 1]},
                "streak": next_streak,
                "lastAt": _now_iso(),
            }
        },
        {
            # 위에서 streak를 확정한 뒤라야 최고/최저 기록을 비교할 수 있어서 단계를 나눠요.
            "$set": {
                "bestStreak": {"$max": [{"$ifNull": ["$bestStreak", 0]}, "$streak"]},
                "worstStreak": {"$min": [{"$ifNull": ["$worstStreak", 0]}, "$streak"]},
            }
        },
    ]


def _apply_sync(user_id, won: bool, season: str):
    uid = str(user_id)
    for scope in (SCOPE_ALL, season):
        _records.update_one(
            {"_id": f"{scope}:{uid}"},
            _update_pipeline(won, scope, uid),
            upsert=True,
        )


def _record_match_sync(guild_id, winners: list, losers: list, reported_by, note: str) -> str:
    season = current_season()

    for user_id in winners:
        _apply_sync(user_id, True, season)
    for user_id in losers:
        _apply_sync(user_id, False, season)

    result = _matches.insert_one({
        "guildId": str(guild_id) if guild_id else None,
        "season": season,
        "winners": [str(u) for u in winners],
        "losers": [str(u) for u in losers],
        "reportedBy": str(reported_by) if reported_by else None,
        "note": note,
        "at": _now_iso(),
    })
    return str(result.inserted_id)


def _blank(user_id, scope: str) -> dict:
    return {
        "_id": f"{scope}:{user_id}", "userId": str(user_id), "scope": scope,
        "wins": 0, "losses": 0, "streak": 0, "bestStreak": 0, "worstStreak": 0,
    }


def _get_sync(user_id, scope: str) -> dict:
    uid = str(user_id)
    return _records.find_one({"_id": f"{scope}:{uid}"}) or _blank(uid, scope)


def _top_sync(scope: str, limit: int, min_matches: int) -> list[dict]:
    """승수 내림차순 랭킹이에요. 승수가 같으면 패가 적은 쪽이 위로 가요."""
    docs = list(
        _records.find({"scope": scope})
        .sort([("wins", -1), ("losses", 1)])
        .limit(max(limit * 3, 30))  # 최소 경기 수로 걸러낼 걸 감안해 넉넉히 읽어요
    )
    filtered = [d for d in docs if (d.get("wins", 0) + d.get("losses", 0)) >= min_matches]
    return filtered[:limit]


def _recent_matches_sync(user_id, limit: int) -> list[dict]:
    uid = str(user_id)
    return list(
        _matches.find({"$or": [{"winners": uid}, {"losers": uid}]})
        .sort([("at", -1)])
        .limit(limit)
    )


def win_rate(doc: dict) -> float | None:
    """승률(0~100). 한 판도 안 했으면 None."""
    total = doc.get("wins", 0) + doc.get("losses", 0)
    if total == 0:
        return None
    return doc["wins"] / total * 100


def streak_text(doc: dict) -> str:
    """지금 연승/연패를 사람이 읽는 말로. 기록이 없으면 '-'."""
    streak = doc.get("streak", 0)
    if streak > 0:
        return f"{streak}연승 중"
    if streak < 0:
        return f"{-streak}연패 중"
    return "-"


# ------------------------------------------------------------------
# 바깥에서 쓰는 async 함수들
#
# pymongo는 동기라서 그대로 부르면 이벤트 루프가 멈춰요(2026-09-04 먹통 사고의 원인).
# coin_wallet과 똑같이 asyncio.to_thread로 넘겨요.
# ------------------------------------------------------------------
async def record_match(guild_id, winners: list, losers: list, *, reported_by=None, note: str = "") -> str | None:
    """한 경기 결과를 양 팀 전원에게 반영해요. 인원이 너무 적으면 아무것도 안 하고 None."""
    if len(winners) + len(losers) < MIN_PLAYERS or not winners or not losers:
        return None
    match_id = await asyncio.to_thread(
        _record_match_sync, guild_id, winners, losers, reported_by, note
    )
    log.info("🏅 내전 결과 기록: 승 %s명 / 패 %s명 (%s)", len(winners), len(losers), note or "-")
    return match_id


async def get_record(user_id, scope: str = SCOPE_ALL) -> dict:
    """그 사람의 전적 문서. 기록이 없으면 전부 0인 문서를 돌려줘요(None 아니에요)."""
    return await asyncio.to_thread(_get_sync, user_id, scope)


async def get_season_record(user_id) -> dict:
    return await asyncio.to_thread(_get_sync, user_id, current_season())


async def top(scope: str = SCOPE_ALL, limit: int = 10, min_matches: int = 1) -> list[dict]:
    return await asyncio.to_thread(_top_sync, scope, limit, min_matches)


async def recent_matches(user_id, limit: int = 5) -> list[dict]:
    return await asyncio.to_thread(_recent_matches_sync, user_id, limit)
