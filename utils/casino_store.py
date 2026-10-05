"""도박 베팅 한도 기록 - 하루에 얼마나 걸었는지만 담아요.

## 왜 한도가 필요한가 (2026-10-05 실측)

지갑 **중앙값이 3코인**인 서버예요. 한도가 없으면 한 번에 전재산을 날리는 사람이 나오고,
그 사람은 그날로 모든 기능에서 떨어져 나가요(칭호도 리롤권도 못 사요). 하루 한도를
출석·미션으로 하루면 회복되는 수준(20코인)으로 눌러서, **잃어도 내일이면 돌아오게** 해요.

소각량의 진짜 조절판도 배당표가 아니라 이 한도예요. 블랙잭은 잘 치는 사람일수록 환수율이
올라가서 배당표만으로는 소각량을 못 묶거든요.

날짜가 바뀌면 그냥 새 문서로 덮어써요(기록을 쌓을 이유가 없어요 - 통계는 `coin_log`에 남아요).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_casino = _db["casino_daily"]

KST = timezone(timedelta(hours=9))

MIN_BET = 1
MAX_BET = 5          # 1회 최대
DAILY_LIMIT = 20     # 하루 총 베팅액


def today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _uid(user_id) -> str:
    return str(user_id)


def _wagered_sync(user_id) -> int:
    doc = _casino.find_one({"_id": _uid(user_id)}, {"date": 1, "wagered": 1})
    if not doc or doc.get("date") != today_iso():
        return 0
    return int(doc.get("wagered") or 0)


def _try_wager_sync(user_id, amount: int) -> tuple[bool, int]:
    """한도 안이면 기록하고 (True, 누적액). 넘으면 (False, 누적액)이고 아무것도 안 바꿔요.

    ⚠️ 읽고 나서 더하면 동시에 두 번 들어왔을 때 한도를 넘어요. 그래서 **조건을 붙인 한 번의
    update**로 처리해요. 날짜가 바뀐 경우를 같은 쿼리에서 다루려고 두 번 시도해요."""
    uid, today = _uid(user_id), today_iso()
    limit_left = DAILY_LIMIT - amount

    # ① 오늘 문서가 이미 있고 한도가 남은 경우
    res = _casino.update_one(
        {"_id": uid, "date": today, "wagered": {"$lte": limit_left}},
        {"$inc": {"wagered": amount}},
    )
    if res.modified_count == 1:
        return True, _wagered_sync(user_id)

    # ② 오늘 문서가 없거나 날짜가 지난 경우 → 새로 시작
    res = _casino.update_one(
        {"_id": uid, "date": {"$ne": today}},
        {"$set": {"date": today, "wagered": amount}},
    )
    if res.modified_count == 1:
        return True, amount

    # ③ 문서 자체가 없으면 만들어요(처음 하는 사람).
    if _casino.find_one({"_id": uid}, {"_id": 1}) is None:
        try:
            _casino.insert_one({"_id": uid, "date": today, "wagered": amount})
            return True, amount
        except Exception:  # noqa: BLE001  (그 찰나에 누가 먼저 만들었어요)
            pass

    # 여기까지 왔으면 한도를 넘은 거예요.
    return False, _wagered_sync(user_id)


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요 - 2026-09-04 먹통 사고)
# ------------------------------------------------------------------
async def wagered_today(user_id) -> int:
    try:
        return await asyncio.to_thread(_wagered_sync, user_id)
    except Exception:  # noqa: BLE001
        # 조회 실패 시 **한도를 다 쓴 것처럼** 봐요. 열어주는 쪽으로 틀리면 한도가 무의미해져요.
        log.warning("도박 한도 조회 실패 - 한도 소진으로 처리해요 (user=%s)", user_id, exc_info=True)
        return DAILY_LIMIT


async def try_wager(user_id, amount: int) -> tuple[bool, int]:
    return await asyncio.to_thread(_try_wager_sync, user_id, amount)


async def refund_wager(user_id, amount: int) -> None:
    """베팅을 기록했는데 게임이 진행되지 못했을 때 한도를 되돌려줘요."""
    await asyncio.to_thread(
        lambda: _casino.update_one({"_id": _uid(user_id), "date": today_iso()},
                                   {"$inc": {"wagered": -amount}})
    )
