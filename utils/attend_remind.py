"""⏰ 연속 출석이 **끊기기 전에** 알려줘요.

## 왜 (2026-10-18 실측)

출석 상위권은 55일·46일·26일로 꾸준한데, **누적 5회 이상인데 연속이 끊긴 사람이 6명**이에요.
그중엔 **누적 41회인데 연속 3일**인 사람도 있어요(10/04 이후로 안 왔어요).

🚨 그리고 이게 **🧊 출석 보호권이 열흘 넘게 0건인 진짜 이유**로 보여요. 보호권은
"끊기기 전에 미리 사둬야" 쓸모 있는데, 사람들은 **끊긴 뒤에야** 아쉬워해요.
끊긴다는 걸 알려주는 사람이 아무도 없었던 거예요.

## 🚨 스팸이 되지 않게

알림은 금방 미움받아요. 그래서 좁게 보내요.

- **잃을 게 있는 사람만** — 연속 `MIN_STREAK`일 이상.
- **아직 떠나지 않은 사람만** — 최근 `ACTIVE_WITHIN_DAYS`일 안에 출석한 적이 있어야 해요.
  한 달째 안 오는 사람에게 보내는 건 그냥 스팸이에요.
- **하루 한 번**, 밤에만.
- `/알림설정`에서 끌 수 있어요.
- 🧊 보호권이 있으면 "하루는 괜찮아요"라고 알려줘요(사둔 보람이 있어야죠).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_trainers = _db["trainers"]

KST = timezone(timedelta(hours=9))

# 이만큼 쌓인 사람에게만 보내요. 1일짜리는 "끊긴다"고 할 게 없어요.
MIN_STREAK = 3
# 최근 이 기간 안에 출석한 적이 있어야 해요. 떠난 사람을 쫓아다니지 않으려고요.
ACTIVE_WITHIN_DAYS = 3


def _today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _candidates_sync() -> list[dict]:
    """오늘 아직 출석 안 한, 연속이 걸린 사람들."""
    today = _today_iso()
    cutoff = (datetime.now(KST).date() - timedelta(days=ACTIVE_WITHIN_DAYS)).isoformat()

    rows = _trainers.find(
        {
            "attendanceStreak": {"$gte": MIN_STREAK},
            # 🚨 문자열 날짜 비교예요. ISO(YYYY-MM-DD)라 사전순 == 시간순이에요.
            "lastAttendanceDate": {"$lt": today, "$gte": cutoff},
        },
        {"attendanceStreak": 1, "lastAttendanceDate": 1},
    )
    return [
        {
            "userId": r["_id"],
            "streak": int(r.get("attendanceStreak") or 0),
            "lastDate": r.get("lastAttendanceDate"),
        }
        for r in rows
    ]


async def candidates() -> list[dict]:
    try:
        return await asyncio.to_thread(_candidates_sync)
    except Exception:  # noqa: BLE001
        log.warning("⏰ 출석 리마인더 대상 조회 실패", exc_info=True)
        return []


def message_for(streak: int, protects: int) -> str:
    """보낼 문구. 보호권이 있으면 다르게 말해요."""
    head = f"⏰ 아직 오늘 `/출석`을 안 하셨어요. **연속 {streak}일**이 걸려 있어요!"
    if protects > 0:
        return (f"{head}\n"
                f"　└ 🧊 출석 보호권이 **{protects}장** 있어서 오늘 놓쳐도 하루는 살려드려요. "
                f"그래도 하는 게 이득이에요!")
    return (f"{head}\n"
            f"　└ 지금 하면 연속이 이어져요. "
            f"자주 놓치신다면 `/악귀상점`의 🧊 **출석 보호권**을 미리 사두면 하루는 살려줘요.\n"
            f"-# 이 알림이 번거로우면 `/알림설정`에서 꺼주세요.")
