"""출석 처리 - 포켓몬을 시작하지 않은 사람도 출석할 수 있게 해주는 계층이에요.

## 왜 필요한가

`/출석`은 원래 트레이너 문서에 직접 기록해서, 포켓몬을 시작한 사람만 쓸 수 있었어요.
그런데 `/미션`은 누구나 깰 수 있으니 "미션은 되는데 출석은 안 되는" 이상한 상태가 됐어요.

## 어디에 기록하나

- **트레이너면** 지금까지처럼 `trainers` 문서에 (웹이 그대로 읽어요)
- **아니면** `attendance_guest` 컬렉션에 출석 기록만 따로

코인은 어느 쪽이든 `coin_wallet`이 알아서 맞는 곳에 넣어줘요.

## 나중에 포켓몬을 시작하면

연속 출석이 끊기면 억울하니까, 트레이너가 된 뒤 처음 출석할 때 **게스트 기록을 트레이너
문서로 옮겨줘요**(`_migrate_sync`). 코인 쪽은 웹의 `_claim_backed_up_coin`이 이미 같은 일을
해주고 있어서, 이걸로 출석까지 완전히 이어져요.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils import coin_wallet, inventory_store
from utils.pokemon_store import COIN_PER_ATTENDANCE, _db, _trainers

log = logging.getLogger(__name__)

_guest = _db["attendance_guest"]

KST = timezone(timedelta(hours=9))


def _today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _yesterday_iso() -> str:
    return (datetime.now(KST).date() - timedelta(days=1)).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(KST).date() - timedelta(days=days)).isoformat()


# ── 연속 출석 보상 ────────────────────────────────────────────────────────
# 2026-10-05 실측: 연속일 중앙값이 **1일**이고 7일 이상이 4명뿐이었어요. 원인은 셋이었어요.
#   ⒜ 일일 보상이 1코인 고정이라 42일 연속인 사람과 오늘 처음 온 사람이 같았고
#   ⒝ 업적 마일스톤이 7일 다음 30일이라 그 사이 23일이 텅 비어 있었고
#   ⒞ 한 번 놓치면 0으로 리셋인데 되살릴 방법이 없었어요(누적 41회인데 연속 3일인 사람들).
# ⒜는 아래 구간 보너스, ⒝는 주간 보너스(반복), ⒞는 🧊 보호권으로 각각 메워요.
#
# ⚠️ 발행량이 늘어나는 변경이에요. 활성자 14명이 전원 매일 출석하면 하루 14 → 25코인으로
#    늘어요(월 420 → 750, 당시 유통량 869). 소비처가 따라오지 못하면 여기 숫자를 먼저 낮추세요.
STREAK_BONUS_TIERS = ((30, 2), (7, 1))   # (연속일 이상, 추가 코인) - 위에서부터 먼저 맞는 것 하나만
WEEKLY_BONUS_EVERY = 7                   # 연속일이 이 배수가 되는 날
WEEKLY_BONUS_COIN = 3


def streak_bonus(streak: int) -> int:
    """연속일에 따라 일일 출석에 얹어주는 추가 코인. (7일↑ +1, 30일↑ +2)"""
    for threshold, bonus in STREAK_BONUS_TIERS:
        if streak >= threshold:
            return bonus
    return 0


def weekly_bonus(streak: int) -> int:
    """7일마다 돌아오는 보너스. **업적과 달리 반복돼요** - 30일이 지나도 계속 의미가 있게."""
    if streak > 0 and streak % WEEKLY_BONUS_EVERY == 0:
        return WEEKLY_BONUS_COIN
    return 0


def _next_streak(last_date: str | None, current: int, protected: bool = False) -> int:
    """어제 출석했으면 이어붙이고, 하루라도 빠졌으면(또는 첫 출석이면) 1부터 다시 세요.

    `protected=True`면 **이틀 전까지만** 되살려요(=하루만 빠진 경우). 이틀 이상 빠진 걸
    살려주면 '연속'이라는 말이 무의미해져요."""
    if last_date == _yesterday_iso():
        return current + 1
    if protected and current > 0 and last_date == _days_ago_iso(2):
        return current + 1
    return 1


def can_protect(last_date: str | None, current: int) -> bool:
    """보호권을 써서 살릴 수 있는 상태인지. (딱 하루만 빠졌고 이어갈 연속이 있을 때)"""
    return bool(current > 0 and last_date == _days_ago_iso(2))


def _migrate_sync(user_id) -> None:
    """게스트로 쌓아둔 출석 기록을 트레이너 문서로 옮겨요. (트레이너가 된 직후 한 번)

    트레이너로서 이미 출석한 적이 있으면(=lastAttendanceDate가 있으면) 그쪽이 최신이니
    게스트 기록은 그냥 버려요."""
    uid = str(user_id)
    legacy = _guest.find_one_and_delete({"_id": uid})
    if legacy is None:
        return

    trainer = _trainers.find_one({"_id": uid}, {"lastAttendanceDate": 1})
    if trainer is None or trainer.get("lastAttendanceDate"):
        return

    _trainers.update_one({"_id": uid}, {"$set": {
        "lastAttendanceDate": legacy.get("lastAttendanceDate"),
        "attendanceStreak": legacy.get("attendanceStreak", 0),
    }, "$inc": {"attendance": legacy.get("attendance", 0)}})
    log.info("📆 게스트 출석 기록을 트레이너로 이관: %s (연속 %s일)", uid, legacy.get("attendanceStreak"))


def _attend_trainer_sync(user_id, protected: bool = False) -> tuple[bool, dict]:
    """트레이너용. (성공여부, 정보) - 코인 지급은 호출한 쪽에서 지갑으로 해요."""
    uid = str(user_id)
    doc = _trainers.find_one({"_id": uid}) or {}
    today = _today_iso()

    if doc.get("lastAttendanceDate") == today:
        return False, {
            "streak": doc.get("attendanceStreak", 0),
            "attendance": doc.get("attendance", 0),
        }

    used_protect = protected and can_protect(
        doc.get("lastAttendanceDate"), doc.get("attendanceStreak", 0)
    )
    streak = _next_streak(doc.get("lastAttendanceDate"), doc.get("attendanceStreak", 0),
                          protected=used_protect)
    # ⚠️ 조건에 lastAttendanceDate를 넣어서, 같은 순간 두 번 눌러도 하루 두 번 처리되지 않게 해요.
    result = _trainers.update_one(
        {"_id": uid, "lastAttendanceDate": doc.get("lastAttendanceDate")},
        {"$set": {"lastAttendanceDate": today, "attendanceStreak": streak}, "$inc": {"attendance": 1}},
    )
    if result.modified_count != 1:
        return False, {"streak": doc.get("attendanceStreak", 0), "attendance": doc.get("attendance", 0)}

    return True, {"streak": streak, "attendance": doc.get("attendance", 0) + 1,
                  "usedProtect": used_protect}


def _attend_guest_sync(user_id, protected: bool = False) -> tuple[bool, dict]:
    """포켓몬 미시작자용. 출석 기록만 따로 남겨요."""
    uid = str(user_id)
    doc = _guest.find_one({"_id": uid}) or {}
    today = _today_iso()

    if doc.get("lastAttendanceDate") == today:
        return False, {
            "streak": doc.get("attendanceStreak", 0),
            "attendance": doc.get("attendance", 0),
        }

    used_protect = protected and can_protect(
        doc.get("lastAttendanceDate"), doc.get("attendanceStreak", 0)
    )
    streak = _next_streak(doc.get("lastAttendanceDate"), doc.get("attendanceStreak", 0),
                          protected=used_protect)
    result = _guest.update_one(
        {"_id": uid, "lastAttendanceDate": doc.get("lastAttendanceDate")},
        {"$set": {"lastAttendanceDate": today, "attendanceStreak": streak}, "$inc": {"attendance": 1}},
        upsert=not doc,   # 처음이면 문서를 만들어요
    )
    if result.modified_count != 1 and result.upserted_id is None:
        return False, {"streak": doc.get("attendanceStreak", 0), "attendance": doc.get("attendance", 0)}

    return True, {"streak": streak, "attendance": doc.get("attendance", 0) + 1,
                  "usedProtect": used_protect}


def _peek_sync(user_id, is_trainer: bool) -> tuple[str | None, int]:
    """(마지막 출석일, 연속일). 보호권을 **차감하기 전에** 쓸 상황인지 보려고 먼저 읽어요."""
    col = _trainers if is_trainer else _guest
    doc = col.find_one({"_id": str(user_id)}, {"lastAttendanceDate": 1, "attendanceStreak": 1}) or {}
    return doc.get("lastAttendanceDate"), int(doc.get("attendanceStreak") or 0)


async def attend(user_id) -> tuple[bool, dict]:
    """출석 처리. (오늘 처음인가, 정보)

    정보에는 streak / attendance / coin(현재 잔액) / isTrainer 가 들어있어요."""
    is_trainer = await coin_wallet.is_trainer(user_id)

    if is_trainer:
        # 게스트로 쌓아둔 기록이 있으면 먼저 이어붙여요.
        await asyncio.to_thread(_migrate_sync, user_id)

    # 🧊 보호권: 딱 하루 빠진 상태면 **차감부터** 하고 출석을 처리해요.
    # 반대 순서(출석 먼저)면 차감이 실패했을 때 공짜로 연속이 이어져요.
    last_date, current_streak = await asyncio.to_thread(_peek_sync, user_id, is_trainer)
    protected = False
    if can_protect(last_date, current_streak):
        protected = await inventory_store.consume_protect(user_id)

    attend_sync = _attend_trainer_sync if is_trainer else _attend_guest_sync
    success, info = await asyncio.to_thread(attend_sync, user_id, protected)

    # 차감했는데 안 쓰였으면(이미 출석했거나 그 사이 상태가 바뀌었으면) 돌려줘요.
    if protected and not info.get("usedProtect"):
        await inventory_store.refund_protect(user_id)
        info["usedProtect"] = False

    if success:
        streak = info["streak"]
        bonus = streak_bonus(streak)
        weekly = weekly_bonus(streak)
        gain = COIN_PER_ATTENDANCE + bonus + weekly
        info["coin"] = await coin_wallet.add(user_id, gain, reason="출석")
        info["coinGain"] = gain
        info["streakBonus"] = bonus
        info["weeklyBonus"] = weekly
    else:
        info["coin"] = await coin_wallet.get_balance(user_id)

    info["isTrainer"] = is_trainer
    return success, info


# ------------------------------------------------------------------
# 🏆 출석 순위
# ------------------------------------------------------------------
def _rankings_sync(limit: int = 10) -> dict:
    """연속 출석 / 누적 출석 순위를 각각 돌려줘요.

    ⚠️ 저장된 `attendanceStreak`은 **다음 출석 때까지 줄어들지 않아요**. 그래서 한 달 전에
    42일을 찍고 안 오는 사람이 1등으로 남아요. 연속 순위는 **아직 살아있는 기록만**
    (오늘이나 어제 출석) 올려요. 보호권으로 살릴 수 있는 이틀 전까지는 '위험'으로 같이 보여줘요."""
    today, yesterday, two = _today_iso(), _yesterday_iso(), _days_ago_iso(2)
    alive, risky, totals = [], [], []

    for col in (_trainers, _guest):
        for doc in col.find(
            {"lastAttendanceDate": {"$exists": True}},
            {"attendanceStreak": 1, "attendance": 1, "lastAttendanceDate": 1},
        ):
            uid = str(doc["_id"])
            streak = int(doc.get("attendanceStreak") or 0)
            total = int(doc.get("attendance") or 0)
            last = doc.get("lastAttendanceDate")
            totals.append((uid, total))
            if last in (today, yesterday):
                alive.append((uid, streak, last == today))
            elif last == two and streak > 0:
                risky.append((uid, streak))

    alive.sort(key=lambda r: -r[1])
    risky.sort(key=lambda r: -r[1])
    totals.sort(key=lambda r: -r[1])
    return {
        "streak": alive[:limit],
        "risky": risky[:3],
        "total": totals[:limit],
    }


async def rankings(limit: int = 10) -> dict:
    return await asyncio.to_thread(_rankings_sync, limit)
