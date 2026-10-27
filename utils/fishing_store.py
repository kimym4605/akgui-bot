"""🎣 어항 - 낚은 물고기를 담아뒀다가 한 번에 팔아요.

`fish` 컬렉션에 사람당 문서 하나예요.

    {_id: uid, tank: {어종key: [치수...]}, casts: 총 던진 횟수, caught: 잡은 수,
     sold: 판 코인, dust: 남은 조각, rod: 남은 내구도,
     cast_date: "YYYY-MM-DD", casts_today: 그날 던진 횟수}

🚨 **`_id`가 유저 ID예요** — `userId` 필드는 없어요. 조회 스크립트를 짤 때
`{"userId": ...}`로 찾으면 조용히 0건이 나와요.

## 왜 바로 코인을 안 주고 어항에 담나

사용자 결정("어항에 모았다가 판매"). 쌓이는 걸 보는 재미도 있지만, 운영상 이점이 더 커요 -
**판매 시점에 코인이 한 번만 발행**되니 `coin_log`에 `낚시판매`가 깔끔하게 한 줄씩 남고,
`scripts/report_economy.py`에서 낚시 발행량을 정확히 떼어볼 수 있어요. 낚을 때마다
코인을 주면 기록이 잘게 쪼개져서 추적이 번거로워요.

## 동시성

- 담기: `$inc`라 겹쳐도 안전해요.
- 팔기: **읽고 나서 비우면** 그 사이에 들어온 물고기까지 날아가요. 그래서
  `find_one_and_update`로 **어항을 비우면서 그 직전 내용을 받아와요**(원자적 교환).
  받아온 내용으로 코인을 계산하니 잃어버리는 물고기가 없어요.

🚨 코인 지급이 실패하면 어항을 **되돌려줘야** 해요(`restore`). 안 그러면 물고기만
사라지고 코인은 없는 최악이 돼요.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from utils import fishing_week
from utils.fish_data import (
    BY_KEY, COIN_PIECES, DAILY_CAST_CAP, GRADE_ORDER, daily_cap_for, pieces_of,
)
from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_fish = _db["fish"]
# 🚨 연속 출석(7차 캐스트 보너스)을 읽으려고 둬요. 출석은 **두 컬렉션**에 나뉘어요 —
#    포켓몬을 시작한 사람은 `trainers`, 안 한 사람은 `attendance_guest`예요
#    (`utils/attend_service.py` 맨 위 설명). 한쪽만 보면 **게스트는 보너스를 못 받아요.**
#    ⚠️ `attend_service`를 import하지 않고 컬렉션을 직접 봐요 — 그쪽은 `coin_wallet`·
#       `inventory_store`를 끌어와서 순환 참조가 생길 수 있어요.
_trainers = _db["trainers"]
_attend_guest = _db["attendance_guest"]


def _uid(user_id) -> str:
    return str(user_id)


# ------------------------------------------------------------------
# 🎣 낚시대 (2026-10-17 2차 설계 · 2026-10-20 6차에 하루 상한 추가)
#
# 문서에 네 개를 둬요:
#   `rod`         남은 내구도 (낚시대 1개 = 10, 소형 = 3)
#   `rod_date`    마지막으로 산 날짜 (제한에 안 쓰고 이상 패턴 볼 때만)
#   `cast_date`   하루 상한을 세는 기준 날짜 (KST)
#   `casts_today` 그날 던진 횟수
#
# 🚨 **전부 조건부 update 한 번으로** 처리해요. "읽고 → 확인하고 → 쓰기"로 하면 빠르게
#    두 번 누를 때 상한을 넘겨 던지거나 내구도가 음수가 돼요.
#
# ⚠️ `casts`(누적)와 `casts_today`(그날)는 **다른 값이에요.** 누적은 `record_cast`가
#    결과가 난 뒤에 세고, 그날 횟수는 `use_rod`가 던지기 **전에** 세요. 놓치면
#    그날 횟수만 되돌아가니(`give_back_rod`) 둘이 안 맞는 게 정상이에요.
# ------------------------------------------------------------------
KST = timezone(timedelta(hours=9))


def today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _yesterday_iso() -> str:
    """어제(KST). 7차 캐스트 보너스가 "연속이 살아있나"를 볼 때만 써요."""
    return (datetime.now(KST).date() - timedelta(days=1)).isoformat()


def _rod_sync(user_id) -> tuple[int, bool]:
    """(남은 내구도, 오늘 이미 샀는지)."""
    doc = _fish.find_one({"_id": _uid(user_id)}, {"rod": 1, "rod_date": 1}) or {}
    return int(doc.get("rod", 0) or 0), doc.get("rod_date") == today_iso()


def _buy_rod_sync(user_id, durability: int) -> bool:
    """낚시대를 지급해요. 언제나 성공해요(2026-10-17 4차부터 **하루 제한 없음**).

    🚨 **코인 차감은 호출자가** 해요. 차감이 실패하면 `_refund_rod_sync`로 되돌려야 해요.

    ⚠️ 내구도는 **더해요**(`$inc`). 예전엔 `$set`으로 덮어썼는데, 그건 "하루 1개"라
       덮어쓸 일이 없어서였어요. 제한을 푼 지금 덮어쓰면 **남은 횟수가 날아가요**
       (5번 남은 상태에서 사면 15가 아니라 10이 돼요).
    ⚠️ `rod_date`는 더 이상 제한에 안 쓰지만, 마지막으로 산 날을 남겨두면 나중에
       제한을 되살릴 때나 이상 패턴을 볼 때 쓸모가 있어서 계속 기록해요."""
    _fish.update_one(
        {"_id": _uid(user_id)},
        {"$inc": {"rod": durability}, "$set": {"rod_date": today_iso()}},
        upsert=True,
    )
    return True


def _refund_rod_sync(user_id, durability: int) -> None:
    """지급을 되돌려요(코인 차감 실패 시).

    ⚠️ **방금 준 만큼만** 빼요. 0으로 밀어버리면 원래 들고 있던 내구도까지 날아가요."""
    _fish.update_one({"_id": _uid(user_id)}, {"$inc": {"rod": -durability}})


def _streak_sync(user_id) -> int:
    """**살아있는** 연속 출석 일수. 끊긴 기록은 0으로 봐요. (7차 캐스트 보너스용)

    🚨 `attendanceStreak`은 **다음 출석 때까지 줄어들지 않아요.** 그래서 한 달 전에
    55일을 찍고 안 오는 사람도 DB엔 55로 남아 있어요
    (`attend_service._rankings_sync`가 같은 함정을 설명해요). 그 값을 그대로 상한에
    쓰면 **안 오는 사람이 보너스를 영구히 받아요.**
    → `/출석순위`와 **같은 규칙**을 써요: `lastAttendanceDate`가 **오늘이나 어제**여야
      살아있는 것으로 봐요.

    ⭐ "어제"까지 인정하는 게 중요해요. 오늘 출석하기 **전에** 낚시부터 하는 사람이
       흔한데, 오늘만 인정하면 그 사람은 보너스를 못 받아요.
    ⚠️ 이틀 이상 빠지면 0이에요. 🧊 보호권이 있어도 그건 **다음 출석 때** 적용되니,
       출석을 하는 순간 `lastAttendanceDate`가 오늘이 돼서 보너스가 돌아와요."""
    uid = _uid(user_id)
    today, yesterday = today_iso(), _yesterday_iso()
    for col in (_trainers, _attend_guest):
        doc = col.find_one(
            {"_id": uid}, {"attendanceStreak": 1, "lastAttendanceDate": 1})
        if not doc:
            continue
        if doc.get("lastAttendanceDate") in (today, yesterday):
            return int(doc.get("attendanceStreak") or 0)
    return 0


def _cap_sync(user_id) -> int:
    """그 사람의 하루 캐스트 상한(= 기본 + 연속 출석 보너스). 0이면 무제한.

    🚨 **상한을 쓰는 곳은 전부 이걸 거쳐야 해요.** `DAILY_CAST_CAP`을 직접 비교하면
    7차 보너스를 무시하고 20에서 막혀요 — 아래 조건부 update가 특히 그래요
    (거기서 틀리면 "보너스를 받았는데 던질 수 없다"가 돼요)."""
    if not DAILY_CAST_CAP:
        return 0
    return daily_cap_for(_streak_sync(user_id))


def _quota_sync(user_id) -> tuple[int, int]:
    """(오늘 던진 횟수, 하루 상한). 상한이 0이면 무제한이에요.

    🚨 `cast_date`가 오늘이 아니면 **0으로 봐요.** 어제 숫자를 그대로 읽으면
    자정이 지나도 "상한 다 썼어요"가 떠요(리셋은 실제 차감 때 일어나요).
    ⚠️ 상한은 사람마다 달라요(7차) — `DAILY_CAST_CAP`을 그대로 돌려주면 안 돼요."""
    doc = _fish.find_one(
        {"_id": _uid(user_id)}, {"cast_date": 1, "casts_today": 1}) or {}
    used = int(doc.get("casts_today", 0) or 0) if doc.get("cast_date") == today_iso() else 0
    return used, _cap_sync(user_id)


def _use_rod_sync(user_id) -> tuple[int | None, str | None]:
    """내구도를 1 깎고 하루 횟수를 1 세요. **(남은 내구도, 막힌 이유)**를 줘요.

    이유는 성공이면 `None`, 낚시대가 없으면 `"no_rod"`, 하루 상한에 걸리면 `"cap"`
    이에요. 상한에 걸렸을 땐 내구도를 **안 깎아요**(낚시대가 그대로 남아요).

    🚨 **내구도와 하루 횟수를 한 번의 update로 같이** 움직여요. "읽고 → 확인하고 →
    쓰기"로 하면 빠르게 두 번 누를 때 상한을 넘겨 던지거나 내구도가 음수가 돼요.
    (같은 이유로 `_buy_rod_sync`도 조건부 update 하나로 돼 있어요.)

    ⚠️ 쿼리가 **두 개**인 건 날짜 리셋 때문이에요. 하나로 합칠 방법이 없어요 —
    "오늘자 카운터를 늘린다"와 "날짜가 바뀌었으니 1로 리셋한다"는 서로 다른 조건과
    서로 다른 연산(`$inc` vs `$set`)이라서요. 순서는 **반드시 오늘자 먼저**예요.
    반대로 두면 날짜가 바뀐 첫 캐스트가 아니라 **매번** 리셋 쪽에 걸려요.

    🚨 `{"cast_date": {"$ne": today}}`는 **필드가 없는 문서에도 걸려요**(MongoDB의
    `$ne`는 missing을 포함해요). 그래서 낚시를 처음 하는 사람도 2번 쿼리가 받아줘요."""
    today = today_iso()
    uid = _uid(user_id)
    # 🚨 **상한을 먼저 구해요**(7차). 사람마다 다르니 `DAILY_CAST_CAP`을 조건에 그대로
    #    넣으면 보너스를 받은 사람이 20에서 막혀요.
    # ⚠️ 읽기 1~2번이 늘지만 이 함수는 이미 스레드에서 돌고, 호출부가 `defer`를
    #    **먼저** 해둬요(`cogs/fishing.py`의 3초 토큰 주석). 그래서 안전해요.
    cap = _cap_sync(user_id)

    # 1) 오늘 이미 던진 적이 있고 상한에 안 걸렸으면 → 둘 다 원자적으로
    cond: dict = {"_id": uid, "rod": {"$gte": 1}, "cast_date": today}
    if cap:
        cond["casts_today"] = {"$lt": cap}
    doc = _fish.find_one_and_update(
        cond,
        {"$inc": {"rod": -1, "casts_today": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is not None:
        return int(doc.get("rod", 0) or 0), None

    # 2) 날짜가 바뀌었거나 오늘이 첫 캐스트면 → 카운터를 1로 리셋하면서 차감
    doc = _fish.find_one_and_update(
        {"_id": uid, "rod": {"$gte": 1}, "cast_date": {"$ne": today}},
        {"$inc": {"rod": -1}, "$set": {"cast_date": today, "casts_today": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is not None:
        return int(doc.get("rod", 0) or 0), None

    # 3) 둘 다 안 걸렸으면 **왜** 막혔는지 알려줘요.
    #
    # ⚠️ 여기는 읽기만 해요. 위 두 쿼리가 이미 "안 던졌다"를 확정했으니, 이 읽기가
    #    경쟁 상태에 져도 **안내문이 조금 틀릴 뿐** 횟수나 코인은 안 틀려요.
    # ⭐ 낚시대가 없으면서 상한도 찼으면 **상한을 먼저** 알려줘요 — 그 사람에게
    #    "낚시대를 사라"고 하면 오늘은 못 쓰는 걸 사게 돼요.
    doc = _fish.find_one({"_id": uid}, {"rod": 1, "cast_date": 1, "casts_today": 1}) or {}
    rod = int(doc.get("rod", 0) or 0)
    used = int(doc.get("casts_today", 0) or 0) if doc.get("cast_date") == today else 0
    # ⚠️ 위 조건부 update와 **같은 `cap`**을 써요. 여기서 `DAILY_CAST_CAP`을 보면
    #    보너스를 받은 사람이 21번째 캐스트에서 "상한이에요"를 보는데 실제로는
    #    던질 수 있는 모순이 생겨요(안내문만 틀리는 게 아니라 못 던지게 돼요).
    if cap and used >= cap:
        return rod, "cap"
    return None, "no_rod"


def _give_back_rod_sync(user_id) -> None:
    """내구도 1과 **하루 횟수 1**을 돌려줘요 (챔질을 놓쳤을 때).

    ⚠️ `_refund_rod_sync`와 다른 함수예요. 이쪽은 **1회분**만 돌려주고, 저쪽은
    구매가 실패했을 때 **방금 준 한 세트**를 통째로 뺄 때 써요. 헷갈려서 섞어 쓰면
    내구도가 10씩 왔다 갔다 해요.

    🚨 **하루 횟수도 같이 돌려줘야** 해요. 놓친 판은 안 던진 것으로 치니까요
    (내구도만 돌려주면 "놓치면 상한만 깎인다"가 돼서 오히려 벌칙이 돼요).

    🚨 단 **오늘자 카운터일 때만** 깎아요. 자정을 넘겨 돌려주는 경우에 조건 없이
    `$inc: -1`을 하면 어제 놓친 몫으로 **오늘 한 번을 공짜로** 더 던지게 돼요.
    그래서 `cast_date`와 `casts_today >= 1`을 둘 다 확인해요."""
    uid = _uid(user_id)
    _fish.update_one({"_id": uid}, {"$inc": {"rod": 1}}, upsert=True)
    _fish.update_one(
        {"_id": uid, "cast_date": today_iso(), "casts_today": {"$gte": 1}},
        {"$inc": {"casts_today": -1}},
    )


def _normalize_tank(raw: dict) -> dict[str, list[int]]:
    """어항을 **{어종: [치수, ...]}** 로 통일해요.

    🚨 치수 시스템(2026-10-17 3차) 전에 잡은 물고기는 `{어종: 마리수}`(정수)로만
    남아 있어요. 마이그레이션 스크립트 대신 **읽을 때 변환**해요 - 그래야 변환이
    실패해도 데이터가 안 날아가요. 옛 물고기는 치수를 모르니 `None`으로 두고,
    값을 매길 때 그 어종의 중앙 크기로 쳐요(`fish_data.pieces_of`)."""
    out: dict[str, list[int]] = {}
    for key, val in (raw or {}).items():
        if isinstance(val, list):
            sizes = [int(s) if s is not None else None for s in val]
        else:
            sizes = [None] * int(val or 0)        # 옛 형식: 마리수만
        if sizes:
            out[key] = sizes
    return out


def tank_pieces(tank: dict[str, list[int]]) -> int:
    """어항 전체의 값(조각)."""
    return sum(pieces_of(k, s) for k, sizes in tank.items() for s in sizes)


def _get_sync(user_id) -> dict:
    doc = _fish.find_one({"_id": _uid(user_id)}) or {}
    tank = _normalize_tank(doc.get("tank") or {})
    return {
        "tank": tank,
        "pieces": tank_pieces(tank),
        "dust": int(doc.get("dust", 0) or 0),     # 지난 판매에서 남은 조각
        "casts": int(doc.get("casts", 0) or 0),
        "caught": int(doc.get("caught", 0) or 0),
        "sold": int(doc.get("sold", 0) or 0),
        "best": doc.get("best"),
    }


def _record_cast_sync(user_id, key: str | None, size: int | None = None) -> None:
    """던진 횟수를 세고, 잡았으면 어항에 담아요. key가 None이면 놓친 거예요."""
    update: dict = {"$inc": {"casts": 1}}
    if key:
        update["$inc"]["caught"] = 1
        # ⚠️ `$push`라 같은 어종을 여러 마리 담아도 각자의 치수가 남아요.
        update["$push"] = {f"tank.{key}": size}

        # 최고 기록 - 등급이 더 높거나, 같은 등급이면 **더 큰 놈**일 때 갱신해요.
        grade = BY_KEY[key][0]
        from utils.fish_data import GRADE_ORDER
        rank = len(GRADE_ORDER) - GRADE_ORDER.index(grade)
        doc = _fish.find_one({"_id": _uid(user_id)}, {"best": 1}) or {}
        prev = doc.get("best") or {}
        prev_rank, prev_size = int(prev.get("rank", 0)), prev.get("size") or 0
        better = rank > prev_rank or (
            rank == prev_rank and (size or 0) > prev_size)
        if better:
            update["$set"] = {"best": {"key": key, "rank": rank, "size": size}}
    _fish.update_one({"_id": _uid(user_id)}, update, upsert=True)


def _sell_all_sync(user_id) -> tuple[dict[str, list[int]], int, int]:
    """어항을 비우면서 **비우기 직전 내용**을 받아와요.

    돌려주는 건 (담겨있던 것, 지급 코인, 남은 조각)이에요.

    🚨 읽고 -> 계산하고 -> 비우면 그 사이에 낚은 물고기가 증발해요.
    `find_one_and_update`로 한 번에 바꾸고 BEFORE 문서를 받아서 그걸로 계산해요.

    🚨 **나머지 조각은 버리지 않고 `dust`에 남겨요.** 그냥 버리면 손해고, 매번
    반올림하면 0.5짜리를 한 마리씩 팔아 1코인씩 받는 구멍이 생겨요."""
    doc = _fish.find_one_and_update(
        {"_id": _uid(user_id)},
        {"$set": {"tank": {}, "dust": 0}},
        return_document=ReturnDocument.BEFORE,
    )
    tank = _normalize_tank((doc or {}).get("tank") or {})
    total = tank_pieces(tank) + int((doc or {}).get("dust", 0) or 0)
    coins, dust = divmod(total, COIN_PIECES)

    if dust and (tank or total):
        # 남은 조각을 되돌려 놔요(위에서 0으로 비웠으니 다시 심어요).
        _fish.update_one({"_id": _uid(user_id)}, {"$set": {"dust": dust}})
    return tank, coins, dust


def _restore_sync(user_id, tank: dict[str, list[int]], dust: int = 0) -> None:
    """판매가 실패했을 때 어항을 되돌려요. 그 사이 새로 낚은 것과 **합쳐져요**.

    ⚠️ `$push`에 `$each`를 써요. 리스트를 통째로 `$set`하면 그 사이에 낚은 물고기를
    덮어써서 날려버려요."""
    update: dict = {}
    if tank:
        update["$push"] = {f"tank.{k}": {"$each": sizes} for k, sizes in tank.items()}
    if dust:
        update["$inc"] = {"dust": dust}
    if update:
        _fish.update_one({"_id": _uid(user_id)}, update, upsert=True)


def _add_sold_sync(user_id, coins: int) -> None:
    _fish.update_one({"_id": _uid(user_id)}, {"$inc": {"sold": coins}}, upsert=True)


def _leaderboard_sync(limit: int) -> list[tuple[str, int]]:
    rows = _fish.find({"sold": {"$gt": 0}}, {"sold": 1}).sort("sold", -1).limit(limit)
    return [(str(r["_id"]), int(r.get("sold", 0) or 0)) for r in rows]


# ------------------------------------------------------------------
# 공개 API (async) - 동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요
# ------------------------------------------------------------------
async def rod_state(user_id) -> tuple[int, bool]:
    """(남은 내구도, 오늘 이미 샀는지)."""
    return await asyncio.to_thread(_rod_sync, user_id)


async def buy_rod(user_id, durability: int) -> bool:
    """낚시대 지급. 오늘 이미 샀으면 False. **코인 차감 전에** 부르세요."""
    return await asyncio.to_thread(_buy_rod_sync, user_id, durability)


async def refund_rod(user_id, durability: int) -> None:
    """지급을 되돌려요(차감 실패 시 반드시). **방금 준 만큼만** 빼요."""
    await asyncio.to_thread(_refund_rod_sync, user_id, durability)


async def give_back_rod(user_id) -> None:
    """놓쳤을 때 내구도 1을 돌려줘요."""
    await asyncio.to_thread(_give_back_rod_sync, user_id)


async def use_rod(user_id) -> tuple[int | None, str | None]:
    """내구도 1 + 하루 횟수 1 소모. **(남은 내구도, 막힌 이유)**를 줘요.

    이유는 성공 `None` · 낚시대 없음 `"no_rod"` · 하루 상한 `"cap"`이에요.

    🚨 **반환값이 2026-10-20에 단일값에서 튜플로 바뀌었어요.** 예전처럼
    `if left is None:`으로 받으면 튜플은 항상 참이라 **상한도 품절도 안 걸리고
    그냥 던져져요.** 호출부를 고칠 때 이 주석을 지우지 마세요."""
    return await asyncio.to_thread(_use_rod_sync, user_id)


async def cast_quota(user_id) -> tuple[int, int]:
    """(오늘 던진 횟수, 하루 상한). 안내문에 쓰라고 따로 뺀 읽기예요."""
    return await asyncio.to_thread(_quota_sync, user_id)


async def get(user_id) -> dict:
    return await asyncio.to_thread(_get_sync, user_id)


async def record_cast(user_id, key: str | None, size: int | None = None) -> None:
    await asyncio.to_thread(_record_cast_sync, user_id, key, size)

    # 🎣 주간 대회 집계 (2026-10-18). 기존 문서 구조는 그대로 두고 별도 컬렉션에만 쌓아요.
    # 🚨 여기서 실패해도 낚시 본 흐름은 계속돼야 해요(fishing_week가 예외를 삼켜요).
    if key is not None:
        grade = BY_KEY.get(key, (None, None))[0]
        rank = (len(GRADE_ORDER) - GRADE_ORDER.index(grade)) if grade in GRADE_ORDER else 0
        await fishing_week.record_catch(user_id, key, size, rank)


async def sell_all(user_id) -> tuple[dict[str, list[int]], int, int]:
    """(담겨있던 것, 지급 코인, 남은 조각)."""
    return await asyncio.to_thread(_sell_all_sync, user_id)


async def restore(user_id, tank: dict[str, list[int]], dust: int = 0) -> None:
    await asyncio.to_thread(_restore_sync, user_id, tank, dust)


async def add_sold(user_id, coins: int) -> None:
    await asyncio.to_thread(_add_sold_sync, user_id, coins)
    await fishing_week.add_sold(user_id, coins)   # 🎣 주간 대회 집계


async def leaderboard(limit: int = 10) -> list[tuple[str, int]]:
    return await asyncio.to_thread(_leaderboard_sync, limit)
