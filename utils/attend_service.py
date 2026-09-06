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

from utils import coin_wallet
from utils.pokemon_store import COIN_PER_ATTENDANCE, _db, _trainers

log = logging.getLogger(__name__)

_guest = _db["attendance_guest"]

KST = timezone(timedelta(hours=9))


def _today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _yesterday_iso() -> str:
    return (datetime.now(KST).date() - timedelta(days=1)).isoformat()


def _next_streak(last_date: str | None, current: int) -> int:
    """어제 출석했으면 이어붙이고, 하루라도 빠졌으면(또는 첫 출석이면) 1부터 다시 세요."""
    return current + 1 if last_date == _yesterday_iso() else 1


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


def _attend_trainer_sync(user_id) -> tuple[bool, dict]:
    """트레이너용. (성공여부, 정보) - 코인 지급은 호출한 쪽에서 지갑으로 해요."""
    uid = str(user_id)
    doc = _trainers.find_one({"_id": uid}) or {}
    today = _today_iso()

    if doc.get("lastAttendanceDate") == today:
        return False, {
            "streak": doc.get("attendanceStreak", 0),
            "attendance": doc.get("attendance", 0),
        }

    streak = _next_streak(doc.get("lastAttendanceDate"), doc.get("attendanceStreak", 0))
    # ⚠️ 조건에 lastAttendanceDate를 넣어서, 같은 순간 두 번 눌러도 하루 두 번 처리되지 않게 해요.
    result = _trainers.update_one(
        {"_id": uid, "lastAttendanceDate": doc.get("lastAttendanceDate")},
        {"$set": {"lastAttendanceDate": today, "attendanceStreak": streak}, "$inc": {"attendance": 1}},
    )
    if result.modified_count != 1:
        return False, {"streak": doc.get("attendanceStreak", 0), "attendance": doc.get("attendance", 0)}

    return True, {"streak": streak, "attendance": doc.get("attendance", 0) + 1}


def _attend_guest_sync(user_id) -> tuple[bool, dict]:
    """포켓몬 미시작자용. 출석 기록만 따로 남겨요."""
    uid = str(user_id)
    doc = _guest.find_one({"_id": uid}) or {}
    today = _today_iso()

    if doc.get("lastAttendanceDate") == today:
        return False, {
            "streak": doc.get("attendanceStreak", 0),
            "attendance": doc.get("attendance", 0),
        }

    streak = _next_streak(doc.get("lastAttendanceDate"), doc.get("attendanceStreak", 0))
    result = _guest.update_one(
        {"_id": uid, "lastAttendanceDate": doc.get("lastAttendanceDate")},
        {"$set": {"lastAttendanceDate": today, "attendanceStreak": streak}, "$inc": {"attendance": 1}},
        upsert=not doc,   # 처음이면 문서를 만들어요
    )
    if result.modified_count != 1 and result.upserted_id is None:
        return False, {"streak": doc.get("attendanceStreak", 0), "attendance": doc.get("attendance", 0)}

    return True, {"streak": streak, "attendance": doc.get("attendance", 0) + 1}


async def attend(user_id) -> tuple[bool, dict]:
    """출석 처리. (오늘 처음인가, 정보)

    정보에는 streak / attendance / coin(현재 잔액) / isTrainer 가 들어있어요."""
    is_trainer = await coin_wallet.is_trainer(user_id)

    if is_trainer:
        # 게스트로 쌓아둔 기록이 있으면 먼저 이어붙여요.
        await asyncio.to_thread(_migrate_sync, user_id)
        success, info = await asyncio.to_thread(_attend_trainer_sync, user_id)
    else:
        success, info = await asyncio.to_thread(_attend_guest_sync, user_id)

    if success:
        info["coin"] = await coin_wallet.add(user_id, COIN_PER_ATTENDANCE, reason="출석")
        info["coinGain"] = COIN_PER_ATTENDANCE
    else:
        info["coin"] = await coin_wallet.get_balance(user_id)

    info["isTrainer"] = is_trainer
    return success, info
