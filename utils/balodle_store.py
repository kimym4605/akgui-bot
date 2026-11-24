"""🧩 발로들 DB — 오늘 문제·풀이·사람별 기록. 전부 async(`asyncio.to_thread`)예요.

세 컬렉션을 써요(설계서 "데이터" 절).

    balodle_days   {_id: "2026-11-24", no, agent, ability, map, map_focus,
                    solved: {agent,ability,map}, finished: {…}, created_at}
    balodle_plays  {_id: "2026-11-24:<uid>", date, uid,
                    agent: {opened_at, status, guesses, reward, rank, done_at}, ability, map,
                    share_msg}
    balodle_users  {_id: "<uid>", streak, best_streak, last_solved_day, titles, notify,
                    agent: {played, solved, dist: {"1"…"6","x"}}, ability, map}

🚨 `_id`가 유저 ID(문자열)예요 — `userId` 필드는 없어요.

## 동시성 — **읽고 나서 쓰지 않아요**

- 오늘 문제: `$setOnInsert` + upsert라 두 사람이 동시에 열어도 먼저 들어간 하나만 남아요.
- 답 넣기: **넣기 전 개수까지 조건에 걸어요**(`guesses: {$size: n}`). 입력창을 두 번 빨리 보내도
  한 번만 들어가요. 끝나는 순간의 `status`·`reward`도 같은 업데이트에서 정해요 — 그 업데이트가
  성공한 요청만 카운터를 올리고 코인을 주니까 두 번 지급되지 않아요.
- "오늘 N번째": 맞힌 순간 `$inc`한 뒤의 값을 받아와요(전체를 세지 않아요).
- 연속: `last_solved_day` 조건으로 하루에 한 번만 올라가요.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils import balodle_logic
from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_days = _db["balodle_days"]
_plays = _db["balodle_plays"]
_users = _db["balodle_users"]

KINDS = balodle_logic.KINDS


def _uid(user_id) -> str:
    return str(user_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _play_id(day_iso: str, user_id) -> str:
    return f"{day_iso}:{_uid(user_id)}"


# ------------------------------------------------------------------
# 오늘 문제 (balodle_days)
# ------------------------------------------------------------------
def _get_day_sync(day_iso: str) -> dict | None:
    return _days.find_one({"_id": day_iso})


def _get_or_create_day_sync(day_iso: str, doc: dict) -> dict:
    """그날 문서가 없을 때만 `doc`으로 만들어요. 이미 있으면 **있던 것**을 돌려줘요."""
    fresh = {k: v for k, v in doc.items() if k != "_id"}
    fresh.setdefault("solved", {k: 0 for k in KINDS})
    fresh.setdefault("finished", {k: 0 for k in KINDS})
    fresh.setdefault("created_at", _now())
    try:
        return _days.find_one_and_update(
            {"_id": day_iso}, {"$setOnInsert": fresh},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # 같은 순간에 두 요청이 upsert하면 한쪽이 여기로 와요. 먼저 들어간 문서를 읽어요.
        return _days.find_one({"_id": day_iso})


def _recent_answers_sync(day_iso: str, days_by_kind: dict) -> dict:
    """최근에 나온 답 — `{kind: {답…}}`. 종류마다 며칠 치를 볼지가 달라요."""
    longest = max([int(v) for v in days_by_kind.values()] or [0])
    if longest <= 0:
        return {k: set() for k in KINDS}
    today = date.fromisoformat(day_iso)
    since = (today - timedelta(days=longest)).isoformat()
    recent = {k: set() for k in KINDS}
    for doc in _days.find({"_id": {"$gte": since, "$lt": day_iso}},
                          {"agent": 1, "ability": 1, "map": 1}):
        age = (today - date.fromisoformat(doc["_id"])).days
        for kind in KINDS:
            if age <= int(days_by_kind.get(kind, 0)) and doc.get(kind):
                recent[kind].add(doc[kind])
    return recent


def _finish_counters_sync(day_iso: str, kind: str, solved: bool) -> dict:
    """끝낸 사람 수(맞히면 맞힌 사람 수도)를 올리고 **올린 뒤** 문서를 받아요.
    맞혔다면 `solved[kind]`가 곧 "오늘 N번째"예요."""
    inc = {f"finished.{kind}": 1}
    if solved:
        inc[f"solved.{kind}"] = 1
    return _days.find_one_and_update(
        {"_id": day_iso}, {"$inc": inc}, return_document=ReturnDocument.AFTER,
    ) or {}


# ------------------------------------------------------------------
# 한 사람의 하루 풀이 (balodle_plays)
# ------------------------------------------------------------------
def _get_play_sync(day_iso: str, user_id) -> dict | None:
    return _plays.find_one({"_id": _play_id(day_iso, user_id)})


def _open_play_sync(day_iso: str, user_id, kind: str) -> dict:
    """문제 버튼을 눌렀을 때. 그 종류를 **처음 열 때만** `opened_at`을 적어요(참여자 수 지표).

    ⚠️ "조건부 필터 + upsert" 한 방으로 쓰지 않아요 — 이미 연 문제는 필터에 안 걸리는데 upsert가
    같은 `_id`로 새 문서를 만들려다 DuplicateKeyError가 나요(`achievement_store`와 같은 이유).
    그래서 '문서 보장'과 '처음 연 표시'를 나눠요."""
    pid = _play_id(day_iso, user_id)
    try:
        _plays.update_one(
            {"_id": pid}, {"$setOnInsert": {"date": day_iso, "uid": _uid(user_id)}}, upsert=True)
    except DuplicateKeyError:
        pass
    _plays.update_one(
        {"_id": pid, f"{kind}.opened_at": {"$exists": False}},
        {"$set": {kind: {"opened_at": _now(), "status": "playing", "guesses": []}}},
    )
    return _plays.find_one({"_id": pid}) or {}


def _submit_guess_sync(day_iso: str, user_id, kind: str, guess: str, count_before: int,
                       finish: str | None, reward: int) -> dict | None:
    """답 하나를 넣어요. 넣었으면 **넣은 뒤** 문서, 못 넣었으면 `None`.

    `count_before`는 호출한 쪽이 본 "지금까지 넣은 답 수"예요. 그사이 다른 요청이 먼저 넣었으면
    개수가 달라져 조건에 안 걸리고 `None`이 돼요(= 이 요청은 아무것도 하지 않아요).
    `finish`가 `"solved"`/`"failed"`면 같은 업데이트에서 끝내요."""
    update = {"$push": {f"{kind}.guesses": guess}}
    if finish:
        update["$set"] = {f"{kind}.status": finish, f"{kind}.reward": int(reward),
                          f"{kind}.done_at": _now()}
    return _plays.find_one_and_update(
        {"_id": _play_id(day_iso, user_id), f"{kind}.status": "playing",
         f"{kind}.guesses": {"$size": int(count_before)}},
        update, return_document=ReturnDocument.AFTER,
    )


def _set_play_fields_sync(day_iso: str, user_id, fields: dict) -> None:
    _plays.update_one({"_id": _play_id(day_iso, user_id)}, {"$set": fields})


# ------------------------------------------------------------------
# 🎯 사람별 정답 (2026-11-24) — `balodle_plays.answers`
#
# 원래는 그날 문제(`balodle_days`)를 서버 전원이 같이 풀었어요. 그러니 먼저 푼 사람이 정답을
# 말해 버리고, 결과 칸도 다 비슷했어요. 이제 **그날 처음 문제를 열 때** 그 사람 몫의 정답을
# 뽑아 풀이 문서에 적어요. `balodle_days`는 번호·카운터(푼 사람 수)만 맡아요.
#
#     answers: {agent, ability, map, map_variant, map_focus}
#
# 동시성: '문서 보장' 뒤 `answers`가 **없을 때만** 써요 → 두 요청이 동시에 와도 먼저 쓴 게 남고,
# 둘 다 남은 것을 다시 읽어요(`_open_play_sync`와 같은 이유로 upsert 한 방으로 쓰지 않아요).
# ------------------------------------------------------------------
def _set_answers_sync(day_iso: str, user_id, answers: dict) -> dict:
    pid = _play_id(day_iso, user_id)
    try:
        _plays.update_one(
            {"_id": pid}, {"$setOnInsert": {"date": day_iso, "uid": _uid(user_id)}}, upsert=True)
    except DuplicateKeyError:
        pass
    _plays.update_one({"_id": pid, "answers": {"$exists": False}}, {"$set": {"answers": answers}})
    return _plays.find_one({"_id": pid}) or {}


def _recent_user_answers_sync(user_id, day_iso: str, days_by_kind: dict) -> dict:
    """그 사람이 최근에 받은 정답 — `{kind: {답…}}`. 반복 금지를 **사람별로** 걸어요.

    `answers`가 없는 옛 풀이(11/24 공통 문제 시절)는 그날 문서의 정답을 그 사람 것으로 봐요."""
    longest = max([int(v) for v in days_by_kind.values()] or [0])
    recent = {k: set() for k in KINDS}
    if longest <= 0:
        return recent
    today = date.fromisoformat(day_iso)
    since = (today - timedelta(days=longest)).isoformat()
    plays = list(_plays.find({"uid": _uid(user_id), "date": {"$gte": since, "$lt": day_iso}},
                             {"date": 1, "answers": 1}))
    legacy = [p["date"] for p in plays if not p.get("answers")]
    shared = {d["_id"]: d for d in _days.find({"_id": {"$in": legacy}})} if legacy else {}
    for play in plays:
        answers = play.get("answers") or shared.get(play["date"]) or {}
        age = (today - date.fromisoformat(play["date"])).days
        for kind in KINDS:
            if age <= int(days_by_kind.get(kind, 0)) and answers.get(kind):
                recent[kind].add(answers[kind])
    return recent


# ------------------------------------------------------------------
# 사람별 누적 (balodle_users)
# ------------------------------------------------------------------
def _get_user_sync(user_id) -> dict:
    return _users.find_one({"_id": _uid(user_id)}) or {}


def _record_result_sync(user_id, kind: str, solved: bool, attempts: int) -> None:
    """종류별 푼 횟수·맞힌 횟수·시도 분포. 실패는 분포의 `x`에 쌓여요."""
    inc = {f"{kind}.played": 1, f"{kind}.dist.{attempts if solved else 'x'}": 1}
    if solved:
        inc[f"{kind}.solved"] = 1
    _users.update_one({"_id": _uid(user_id)}, {"$inc": inc}, upsert=True)


def _bump_streak_sync(user_id, day_iso: str, titles: dict) -> dict:
    """그날 첫 정답 때 연속을 올려요. `{streak, best, bumped, new_titles}`.

    - 어제(`day_iso` 하루 전)까지 이어져 있으면 +1
    - 그보다 오래됐거나 처음이면 1부터
    - 오늘 이미 올렸으면(또는 더 뒤 날짜가 적혀 있으면) 그대로 — 0시 직전에 연 문제를 0시가
      지나 맞혀도, 이미 오늘 문제를 맞혔다면 기록이 뒤로 가지 않아요."""
    uid = _uid(user_id)
    yesterday = balodle_logic.day_before(day_iso)
    try:
        _users.update_one({"_id": uid}, {"$setOnInsert": {"streak": 0, "best_streak": 0}},
                          upsert=True)
    except DuplicateKeyError:
        pass

    before = _users.find_one_and_update(
        {"_id": uid, "last_solved_day": yesterday},
        {"$inc": {"streak": 1}, "$set": {"last_solved_day": day_iso}},
        return_document=ReturnDocument.BEFORE,
    )
    if before is None:
        before = _users.find_one_and_update(
            {"_id": uid, "$or": [{"last_solved_day": {"$exists": False}},
                                 {"last_solved_day": None},
                                 {"last_solved_day": {"$lt": yesterday}}]},
            {"$set": {"streak": 1, "last_solved_day": day_iso}},
            return_document=ReturnDocument.BEFORE,
        )
    if before is None:                      # 오늘 이미 올렸어요
        doc = _users.find_one({"_id": uid}) or {}
        return {"streak": int(doc.get("streak", 0) or 0),
                "best": int(doc.get("best_streak", 0) or 0), "bumped": False, "new_titles": []}

    streak, _ = balodle_logic.next_streak(
        before.get("last_solved_day"), day_iso, int(before.get("streak", 0) or 0))
    best_before = int(before.get("best_streak", 0) or 0)
    best = max(best_before, streak)
    gained = [t for t in balodle_logic.new_titles(best_before, best, titles)
              if t not in (before.get("titles") or [])]
    update = {"$max": {"best_streak": best}}
    if gained:
        update["$addToSet"] = {"titles": {"$each": gained}}
    _users.update_one({"_id": uid}, update)
    return {"streak": streak, "best": best, "bumped": True, "new_titles": gained}


def _set_notify_sync(user_id, on: bool) -> None:
    _users.update_one({"_id": _uid(user_id)}, {"$set": {"notify": bool(on)}}, upsert=True)


def _ensure_indexes_sync() -> None:
    _plays.create_index("date")
    _plays.create_index("uid")
    _plays.create_index([("uid", 1), ("date", 1)])     # 사람별 최근 정답 (2026-11-24)


# ------------------------------------------------------------------
# 공개 API (전부 async)
# ------------------------------------------------------------------
async def get_day(day_iso: str) -> dict | None:
    return await asyncio.to_thread(_get_day_sync, day_iso)


async def get_or_create_day(day_iso: str, doc: dict) -> dict:
    return await asyncio.to_thread(_get_or_create_day_sync, day_iso, doc)


async def recent_answers(day_iso: str, days_by_kind: dict) -> dict:
    return await asyncio.to_thread(_recent_answers_sync, day_iso, days_by_kind)


async def finish_counters(day_iso: str, kind: str, solved: bool) -> dict:
    return await asyncio.to_thread(_finish_counters_sync, day_iso, kind, solved)


async def count_today(day_iso: str) -> dict:
    """오늘 종류별로 끝낸 사람 수 `{agent, ability, map}` (패널에 보여줘요)."""
    day = await get_day(day_iso) or {}
    return {k: int(((day.get("finished") or {}).get(k)) or 0) for k in KINDS}


async def get_play(day_iso: str, user_id) -> dict | None:
    return await asyncio.to_thread(_get_play_sync, day_iso, user_id)


async def open_play(day_iso: str, user_id, kind: str) -> dict:
    return await asyncio.to_thread(_open_play_sync, day_iso, user_id, kind)


async def submit_guess(day_iso: str, user_id, kind: str, guess: str, count_before: int, *,
                       finish: str | None = None, reward: int = 0) -> dict | None:
    return await asyncio.to_thread(
        _submit_guess_sync, day_iso, user_id, kind, guess, count_before, finish, reward)


async def set_answers(day_iso: str, user_id, answers: dict) -> dict:
    """그 사람의 그날 정답을 적어요(이미 있으면 그대로). 적은 뒤의 풀이 문서를 돌려줘요."""
    return await asyncio.to_thread(_set_answers_sync, day_iso, user_id, answers)


async def recent_user_answers(user_id, day_iso: str, days_by_kind: dict) -> dict:
    return await asyncio.to_thread(_recent_user_answers_sync, user_id, day_iso, days_by_kind)


async def set_rank(day_iso: str, user_id, kind: str, rank: int) -> None:
    await asyncio.to_thread(_set_play_fields_sync, day_iso, user_id, {f"{kind}.rank": int(rank)})


async def mark_reward_failed(day_iso: str, user_id, kind: str) -> None:
    """코인 지급이 실패했다는 표시. 풀이 상태는 되돌리지 않아요(나중에 스크립트로 지급)."""
    await asyncio.to_thread(
        _set_play_fields_sync, day_iso, user_id, {f"{kind}.reward_failed": True})


async def set_share_msg(day_iso: str, user_id, message_id: int) -> None:
    await asyncio.to_thread(_set_play_fields_sync, day_iso, user_id, {"share_msg": int(message_id)})


async def get_user(user_id) -> dict:
    return await asyncio.to_thread(_get_user_sync, user_id)


async def record_result(user_id, kind: str, solved: bool, attempts: int) -> None:
    await asyncio.to_thread(_record_result_sync, user_id, kind, solved, attempts)


async def bump_streak(user_id, day_iso: str, titles: dict) -> dict:
    return await asyncio.to_thread(_bump_streak_sync, user_id, day_iso, titles)


async def set_notify(user_id, on: bool) -> None:
    await asyncio.to_thread(_set_notify_sync, user_id, on)


async def ensure_indexes() -> None:
    await asyncio.to_thread(_ensure_indexes_sync)
