"""도박 베팅 한도 기록 - 하루에 얼마나 걸었는지만 담아요.

## 왜 한도가 필요한가 (2026-10-05 실측)

지갑 **중앙값이 3코인**인 서버예요. 한도가 없으면 한 번에 전재산을 날리는 사람이 나오고,
그 사람은 그날로 모든 기능에서 떨어져 나가요(칭호도 리롤권도 못 사요). 하루 한도를
출석·미션으로 하루면 회복되는 수준(20코인)으로 눌러서, **잃어도 내일이면 돌아오게** 해요.

소각량의 진짜 조절판도 배당표가 아니라 이 한도예요. 블랙잭은 잘 치는 사람일수록 환수율이
올라가서 배당표만으로는 소각량을 못 묶거든요.

날짜가 바뀌면 그냥 새 문서로 덮어써요(기록을 쌓을 이유가 없어요 - 통계는 `coin_log`에 남아요).

## 🔓 한도 연장권 (2026-10-06)

한도는 **실제로 병목이다.** 그날 도박한 9명 중 **5명이 20코인을 전부 소진**했고, 한도 근처
(15~19코인)에서 멈춘 사람은 **0명**이었어요 - 닿으면 끝까지 써요. 그래서 "더 걸고 싶으면
코인을 내라"는 소비처를 붙였어요. 코인이 **확실히 사라지는** 소각이라, 엣지로 조금씩 태우는
도박 본체보다 소각 효율이 좋아요(5코인당 즉시 5 + 늘어난 10코인에서 엣지 ~1).

**낼 때마다 +10코인씩, 횟수 제한 없이** 늘어나요. 다만 **살수록 값이 올라가요**
(5 → 10 → 15 → 20 …, `extend_price`). 2026-10-06에 셋 다 사용자 결정으로 정했어요:
하루 1회 → 고정가 반복 → **가격 점증 반복** 순으로 바뀌었어요.

🚨 **값이 올라가는 게 제동이에요.** 고정가로 두면 지갑이 두꺼운 사람이 한도를 사실상 무한히
늘릴 수 있는데, 5씩 비싸지면 **연장비가 베팅할 돈을 먼저 잡아먹어요**(98코인 → 5번 연장에
75코인, 남는 건 23코인). 그래도 상한이 코드에 박혀 있진 않으니, 자각할 수 있게 **몇 번째
연장인지·이번 값·누적 지출**을 매번 보여줘요. **이 안내를 빼면 안 돼요.**

⚠️ 한도 도달자의 지갑은 대개 비어 있어요(실측: 5명 중 3명이 잔액 0~1코인). 한도까지 걸었다는
건 보통 코인을 다 태웠다는 뜻이라, **연장권의 실수요자는 "한도는 찼지만 지갑이 두꺼운 사람"**
이에요. 그래서 가격을 5코인으로 잡았어요 - 지갑 중앙값 3코인 기준으로 아무나 못 사는 값이에요.
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
DAILY_LIMIT = 20     # 하루 총 베팅액 (연장권을 사면 늘어나요)

EXTEND_BASE_PRICE = 5    # 🔓 첫 연장 값. 살수록 이만큼씩 비싸져요 (5 → 10 → 15 …)
EXTEND_BONUS = 10        # 한 번 살 때마다 늘어나는 한도 (이쪽은 고정이에요)


def today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _uid(user_id) -> str:
    return str(user_id)


def limit_of(extended: int) -> int:
    """연장 횟수에 맞는 그 사람의 오늘 한도."""
    return DAILY_LIMIT + EXTEND_BONUS * max(0, int(extended or 0))


def extend_price(already: int) -> int:
    """**다음** 연장 값. 이미 `already`번 샀으면 그 다음은 얼마인지.

    5 → 10 → 15 → 20 … 으로 **살수록 비싸져요**(2026-10-06 사용자 결정). 고정가로 두면
    지갑이 두꺼운 사람이 한도를 사실상 무한히 늘릴 수 있는데, 값이 올라가면 그 자체가
    제동이 돼요. 98코인을 가진 사람도 5+10+15+20+25=75코인을 쓰면 **걸 돈이 23코인**밖에
    안 남아요."""
    return EXTEND_BASE_PRICE * (max(0, int(already or 0)) + 1)


def extend_spent(times: int) -> int:
    """오늘 연장에만 쓴 코인 합계 (5+10+15+… = 5·n(n+1)/2)."""
    n = max(0, int(times or 0))
    return EXTEND_BASE_PRICE * n * (n + 1) // 2


def _state_sync(user_id) -> tuple[int, int]:
    """(오늘 누적 베팅액, 오늘 연장 횟수). 날짜가 지난 문서는 0으로 봐요."""
    doc = _casino.find_one({"_id": _uid(user_id)}, {"date": 1, "wagered": 1, "extended": 1})
    if not doc or doc.get("date") != today_iso():
        return 0, 0
    return int(doc.get("wagered") or 0), int(doc.get("extended") or 0)


def _wagered_sync(user_id) -> int:
    return _state_sync(user_id)[0]


def _try_wager_sync(user_id, amount: int) -> tuple[bool, int]:
    """한도 안이면 기록하고 (True, 누적액). 넘으면 (False, 누적액)이고 아무것도 안 바꿔요.

    ⚠️ 읽고 나서 더하면 동시에 두 번 들어왔을 때 한도를 넘어요. 그래서 **조건을 붙인 한 번의
    update**로 처리해요. 날짜가 바뀐 경우를 같은 쿼리에서 다루려고 두 번 시도해요."""
    uid, today = _uid(user_id), today_iso()
    # ⚠️ 한도가 사람마다 달라졌으니(연장권) 먼저 읽어야 해요. 읽은 뒤에 연장권이 팔려도
    #    **한도를 작게 보는 쪽**으로만 틀려서 안전해요(`extended`는 늘기만 해요). 열어주는
    #    쪽으로 틀리면 한도가 무의미해지니까, 거절 쪽으로 기우는 게 맞아요.
    limit_left = limit_of(_state_sync(user_id)[1]) - amount

    # ① 오늘 문서가 이미 있고 한도가 남은 경우
    res = _casino.update_one(
        {"_id": uid, "date": today, "wagered": {"$lte": limit_left}},
        {"$inc": {"wagered": amount}},
    )
    if res.modified_count == 1:
        return True, _wagered_sync(user_id)

    # ② 오늘 문서가 없거나 날짜가 지난 경우 → 새로 시작
    # 🚨 `extended`를 0으로 **반드시 같이** 되돌려요. 안 그러면 어제 산 연장권이 오늘도 살아서
    #    한도가 영구히 30코인이 돼요.
    res = _casino.update_one(
        {"_id": uid, "date": {"$ne": today}},
        {"$set": {"date": today, "wagered": amount, "extended": 0}},
    )
    if res.modified_count == 1:
        return True, amount

    # ③ 문서 자체가 없으면 만들어요(처음 하는 사람).
    if _casino.find_one({"_id": uid}, {"_id": 1}) is None:
        try:
            _casino.insert_one({"_id": uid, "date": today, "wagered": amount, "extended": 0})
            return True, amount
        except Exception:  # noqa: BLE001  (그 찰나에 누가 먼저 만들었어요)
            pass

    # 여기까지 왔으면 한도를 넘은 거예요.
    return False, _wagered_sync(user_id)


def _extend_sync(user_id) -> tuple[bool, int, int]:
    """한도를 늘려 **자리를 먼저 잡아요**. (성공, 늘어난 뒤의 한도, 오늘 몇 번째인지).

    🚨 코인을 빼기 **전에** 이걸 불러요. 코인 차감이 실패하면 `_undo_extend_sync`로 되돌려서
    공짜 연장이 안 남게 해요.
    횟수 제한은 없어요(5코인 낼 때마다 +10). 그래서 **몇 번째인지를 돌려줘요** - 호출부가
    그 숫자와 누적 지출을 보여줘야 사는 사람이 자기가 얼마를 쓰고 있는지 알 수 있어요.
    오늘 문서가 없으면(= 오늘 아직 한 판도 안 걸었으면) 실패해요. 연장권은 한도에 막힌
    자리에서만 파니까 그 상황은 안 생겨요."""
    uid, today = _uid(user_id), today_iso()
    res = _casino.update_one({"_id": uid, "date": today}, {"$inc": {"extended": 1}})
    _, extended = _state_sync(user_id)
    if res.modified_count != 1:
        return False, limit_of(extended), extended
    return True, limit_of(extended), extended


def _undo_extend_sync(user_id) -> None:
    _casino.update_one({"_id": _uid(user_id), "date": today_iso()},
                       {"$inc": {"extended": -1}})


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


async def state_today(user_id) -> tuple[int, int]:
    """(오늘 누적 베팅액, 오늘 한도). 조회가 실패하면 **한도를 다 쓴 것처럼** 봐요."""
    try:
        wagered, extended = await asyncio.to_thread(_state_sync, user_id)
        return wagered, limit_of(extended)
    except Exception:  # noqa: BLE001
        log.warning("도박 한도 조회 실패 - 한도 소진으로 처리해요 (user=%s)", user_id, exc_info=True)
        return DAILY_LIMIT, DAILY_LIMIT


async def extend_limit(user_id) -> tuple[bool, int, int]:
    """한도 연장 자리를 선점해요. (성공, 늘어난 뒤의 한도, 오늘 몇 번째). 차감 **전에** 부르세요."""
    return await asyncio.to_thread(_extend_sync, user_id)


async def extend_count(user_id) -> int:
    """오늘 몇 번 늘렸는지. 조회가 실패하면 0으로 봐요(안내용 숫자라 막을 이유가 없어요)."""
    try:
        return (await asyncio.to_thread(_state_sync, user_id))[1]
    except Exception:  # noqa: BLE001
        return 0


async def undo_extend(user_id) -> None:
    """연장을 선점했는데 코인을 못 뺐을 때 되돌려요."""
    await asyncio.to_thread(_undo_extend_sync, user_id)


async def try_wager(user_id, amount: int) -> tuple[bool, int]:
    return await asyncio.to_thread(_try_wager_sync, user_id, amount)


async def refund_wager(user_id, amount: int) -> None:
    """베팅을 기록했는데 게임이 진행되지 못했을 때 한도를 되돌려줘요."""
    await asyncio.to_thread(
        lambda: _casino.update_one({"_id": _uid(user_id), "date": today_iso()},
                                   {"$inc": {"wagered": -amount}})
    )
