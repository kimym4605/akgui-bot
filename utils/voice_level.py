"""🎙️ 통화방에 머문 시간을 누적해 레벨로 바꿔요. **코인과는 별개의 명예 지표예요.**

## 왜 (2026-10-18)

통화방이 이 서버에서 **참여가 가장 넓은 활동**이에요. 실측으로 `voice_together` 미션을
깬 사람이 **36명**(지갑 58개 중 62%), 누적 230회, 최다 23일이에요. 그런데 보상은
하루 1코인이 전부라, 두 시간을 있든 삼십 분을 있든 똑같았어요.

## 🚨 코인을 주지 않아요

코인은 이미 낚시가 발행의 70%를 차지하는 상태라, 통화에까지 코인을 얹으면 경제가
또 기울어요. 레벨은 **역할과 숫자만** 줘요. 경제(코인)와 명예(레벨)를 분리하면
둘 다 각자 의미를 지켜요.

## 🚨 시간 측정은 이미 돌고 있어요

`cogs/mission.py`가 입·퇴장을 감지하고 5분마다 중간 정산해요. **혼자 접속해두는
어뷰징도 거기서 이미 막아요**(봇 뺀 2명 이상인 채널만 인정). 여기서는 그 결과를
받아 누적만 해요 — 추적을 새로 만들면 두 벌이 되어 어긋나요.

## 레벨 곡선

레벨 N을 올리는 데 필요한 시간 = `BASE + STEP × (N-1)` 분.
처음엔 금방 오르고 갈수록 느려져요(선형이면 금세 지루해지고, 지수면 금방 막혀요).

    Lv1   30분      Lv10  약 16시간
    Lv5   약 5시간   Lv20  약 57시간

실측에서 가장 열심인 사람이 23일 참여였는데, 하루 한 시간이면 Lv12쯤이에요.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_voice = _db["voice_level"]

KST = timezone(timedelta(hours=9))

# 레벨 곡선. 🚨 바꾸면 **모두의 레벨이 한꺼번에 움직여요**(누적 분으로 매번 계산해요).
BASE_MINUTES = 30
STEP_MINUTES = 15

# 이 레벨을 넘으면 역할을 줘요. 🚨 역할을 너무 잘게 쪼개면 역할 목록이 지저분해져요.
ROLE_TIERS: tuple[tuple[int, str], ...] = (
    (30, "🎙️ 통화방 터줏대감"),
    (20, "🎙️ 통화방 단골"),
    (10, "🎙️ 수다쟁이"),
    (5, "🎙️ 말동무"),
)
ROLE_NAMES = {name for _, name in ROLE_TIERS}


def minutes_for_level(level: int) -> int:
    """그 레벨에 **도달하는 데** 필요한 누적 분."""
    if level <= 0:
        return 0
    # BASE*n + STEP*(0+1+...+(n-1))
    return BASE_MINUTES * level + STEP_MINUTES * (level - 1) * level // 2


def level_of(minutes: int) -> int:
    """누적 분 → 레벨. 역산이 귀찮아서 올려가며 세요(레벨이 수백이 될 일은 없어요)."""
    level = 0
    while minutes >= minutes_for_level(level + 1):
        level += 1
        if level > 999:  # 혹시 모를 무한루프 방지
            break
    return level


def progress(minutes: int) -> tuple[int, int, int]:
    """(지금 레벨, 이번 레벨에서 쌓은 분, 다음 레벨까지 필요한 분)."""
    level = level_of(minutes)
    done = minutes - minutes_for_level(level)
    need = minutes_for_level(level + 1) - minutes_for_level(level)
    return level, done, need


def role_for(level: int) -> str | None:
    """이 레벨에서 달아야 할 역할 이름. 없으면 None."""
    for need, name in ROLE_TIERS:
        if level >= need:
            return name
    return None


def format_minutes(minutes: int) -> str:
    hours, mins = divmod(max(0, minutes), 60)
    if hours and mins:
        return f"{hours}시간 {mins}분"
    if hours:
        return f"{hours}시간"
    return f"{mins}분"


def week_key(when: datetime | None = None) -> str:
    now = when or datetime.now(KST)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


# ------------------------------------------------------------------
def _add_sync(user_id, minutes: int) -> tuple[int, int]:
    """누적하고 (누적 분, 이번 주 분)을 돌려줘요.

    ⚠️ 주차가 바뀌면 주간 누적을 0부터 다시 세요. 읽고-비교하고-쓰면 경합에서 틀리니까
    **주차가 같을 때만 $inc** 하고, 아니면 통째로 교체해요(두 번의 update지만 각각
    조건부라 안전해요)."""
    uid = str(user_id)
    wk = week_key()

    res = _voice.update_one(
        {"_id": uid, "weekKey": wk},
        {"$inc": {"minutes": minutes, "weekMinutes": minutes}},
    )
    if res.matched_count == 0:
        # 이 사람의 첫 기록이거나 주차가 넘어갔어요.
        _voice.update_one(
            {"_id": uid},
            {
                "$inc": {"minutes": minutes},
                "$set": {"weekKey": wk, "weekMinutes": minutes},
            },
            upsert=True,
        )

    doc = _voice.find_one({"_id": uid}, {"minutes": 1, "weekMinutes": 1}) or {}
    return int(doc.get("minutes") or 0), int(doc.get("weekMinutes") or 0)


def _get_sync(user_id) -> dict:
    doc = _voice.find_one({"_id": str(user_id)}) or {}
    total = int(doc.get("minutes") or 0)
    week = int(doc.get("weekMinutes") or 0) if doc.get("weekKey") == week_key() else 0
    return {"minutes": total, "weekMinutes": week, "level": level_of(total)}


def _top_sync(limit: int, weekly: bool) -> list[dict]:
    field = "weekMinutes" if weekly else "minutes"
    query = {"weekKey": week_key()} if weekly else {}
    rows = list(_voice.find(query).sort(field, -1).limit(limit))
    return [
        {
            "userId": r["_id"],
            "minutes": int(r.get(field) or 0),
            "level": level_of(int(r.get("minutes") or 0)),
        }
        for r in rows
        if int(r.get(field) or 0) > 0
    ]


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요)
# ------------------------------------------------------------------
async def add_minutes(user_id, minutes: int) -> tuple[int, int, int, int]:
    """시간을 더하고 (이전 레벨, 새 레벨, 누적 분, 이번 주 분)을 돌려줘요.

    🚨 실패해도 **예외를 올리지 않아요.** 이건 미션 정산 흐름 안에서 불리는데,
    레벨 때문에 코인 지급이 막히면 안 돼요."""
    if minutes <= 0:
        return 0, 0, 0, 0
    try:
        before = await asyncio.to_thread(_get_sync, user_id)
        total, week = await asyncio.to_thread(_add_sync, user_id, minutes)
        return before["level"], level_of(total), total, week
    except Exception:  # noqa: BLE001
        log.warning("🎙️ 음성 시간 적립 실패 (user=%s)", user_id, exc_info=True)
        return 0, 0, 0, 0


async def get(user_id) -> dict:
    try:
        return await asyncio.to_thread(_get_sync, user_id)
    except Exception:  # noqa: BLE001
        return {"minutes": 0, "weekMinutes": 0, "level": 0}


async def top(limit: int = 10, weekly: bool = False) -> list[dict]:
    try:
        return await asyncio.to_thread(_top_sync, limit, weekly)
    except Exception:  # noqa: BLE001
        return []
