"""일일 미션 - 매일 3개씩 배정되고, 하나 깰 때마다 악귀코인 1개를 줘요.

## 왜 시간이 아니라 미션인가

원래는 "통화방에 오래 있으면 코인"을 생각했는데, 그러면 숙면방에 접속만 걸어두고 자도
코인이 쌓여요. 미션은 실제로 뭔가를 해야 깨지니까 서버가 실제로 활발해져요.

## 배정 방식

- **라이엇 계정을 연동한 사람**: 발로란트 미션 2개 + 서버 미션 1개
- **연동 안 한 사람**: 서버 미션 3개 (발로란트 미션은 판정할 방법이 없어요)

같은 사람의 같은 날 미션은 **항상 같아요**. `(유저ID, 날짜)`를 시드로 쓰는 결정적 랜덤이라,
문서를 다시 만들어도 미션이 바뀌지 않아요. (미션이 마음에 안 들 때 문서를 지웠다 다시 받는
식의 리롤을 막아요.)

## 판정 방식이 두 가지예요

- **서버 미션**은 이벤트가 올 때 그때그때 진행도를 올려요(명령어 사용, 통화방 체류).
- **발로란트 미션**은 `/미션`을 칠 때 전적을 조회해서 판정해요. 매번 API를 두드리면
  호출량이 감당이 안 되고, 어차피 본인이 확인할 때만 알면 되니까요.
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_missions = _db["missions"]

KST = timezone(timedelta(hours=9))

REWARD_PER_MISSION = 1   # 미션 하나당 악귀코인
DAILY_MISSION_COUNT = 3  # 하루에 배정되는 미션 수 (= 하루 최대 3코인)

# 🎲 미션 리롤권 (`/악귀상점`). 하루 1회만 — 안 그러면 쉬운 미션이 나올 때까지 돌릴 수 있어요.
# 가격은 보상(1코인)보다 비싸게 둬요. 그래야 "코인을 벌려고 리롤"이 성립하지 않아요.
REROLL_PRICE = 2
REROLL_LIMIT_PER_DAY = 1

# 통화방 미션에서 "함께 있었다"로 인정할 최소 인원(본인 포함). 혼자 접속해두는 걸 막아요.
VOICE_MIN_MEMBERS = 2

# ------------------------------------------------------------------
# 미션 정의
#
# kind="server"   : 봇이 이벤트로 바로 감지해요 (명령어 사용, 통화방 체류)
# kind="valorant" : /미션 칠 때 전적을 조회해서 판정해요 (라이엇 연동 필요)
# target          : 이 수치에 도달하면 완료
# ------------------------------------------------------------------
MISSIONS: dict[str, dict] = {
    # --- 서버 활동 (전원 가능) ---
    "voice_together": {
        "kind": "server", "target": 30,
        "title": "같이 통화하기",
        "desc": f"다른 사람과 함께 통화방에 30분 있기 (혼자 있으면 인정 안 돼요)",
        "unit": "분",
    },
    "create_room": {
        "kind": "server", "target": 1,
        "title": "방 만들기",
        "desc": "`/방만들기`로 통화방 만들기",
        "unit": "회",
    },
    "use_myshop": {
        "kind": "server", "target": 1,
        "title": "오늘의 상점 확인",
        "desc": "`/오상`으로 내 상점 확인하기",
        "unit": "회",
    },
    "use_rank": {
        "kind": "server", "target": 1,
        "title": "전적 확인",
        "desc": "`/전적`으로 전적 조회하기",
        "unit": "회",
    },
    "use_map": {
        "kind": "server", "target": 1,
        "title": "맵 추천 받기",
        "desc": "`/맵추천` 써보기",
        "unit": "회",
    },
    # --- 이미 하는 활동에 얹는 쪽 (2026-10-23) ---
    #
    # ⭐ **왜 이 셋인가**: 서버 미션 5종이 균등 배정인데 누적 완료가 통화 251건 vs
    #    맵추천 **2건**으로 125배 갈렸어요(2026-10-23 실측). 갈라지는 기준은 난이도가
    #    아니라 **"미션을 몰라도 깨지는지"**였어요 - 통화는 그냥 있으면 깨지고, 맵추천은
    #    일부러 하러 가야 해요. 그래서 **사람들이 이미 하는 활동**을 미션으로 얹어요.
    #    (실측 이용자: 낚시 16명 · 출석 23명 · 도박 12명)
    #
    # 🚨 **새 발행원이 아니에요.** 보상은 미션 1코인 그대로이고 하루 상한 3코인도 그대로예요.
    #    낚시는 하루 20캐스트 상한 안에서 도니 낚시 발행도 안 늘어요. 늘어나는 건
    #    "배정됐는데 못 깨서 안 나가던 코인"뿐이에요.
    "attend_check": {
        "kind": "server", "target": 1,
        "title": "출석하기",
        "desc": "`/출석`으로 오늘의 출석체크 하기",
        "unit": "회",
    },
    "catch_fish": {
        "kind": "server", "target": 3,
        "title": "세 마리 낚기",
        "desc": "`/낚시`로 물고기 3마리 낚기 (놓친 판은 안 세요)",
        "unit": "마리",
    },
    # 🔞 성인 전용이에요. 아래 ADULT_ONLY_KEYS를 꼭 같이 보세요.
    "play_gamble": {
        "kind": "server", "target": 1,
        "title": "한 판 걸어보기",
        "desc": "🔞 `/도박`에서 한 판 걸기 (성인 인증 필요)",
        "unit": "판",
    },
    # --- 발로란트 (라이엇 계정 연동자만) ---
    "val_play": {
        "kind": "valorant", "target": 1,
        "title": "한 판 하고 오기",
        "desc": "오늘 발로란트 1판 이상 플레이",
        "unit": "판",
    },
    "val_win": {
        "kind": "valorant", "target": 1,
        "title": "승리하기",
        "desc": "오늘 1승 이상",
        "unit": "승",
    },
    "val_kills15": {
        "kind": "valorant", "target": 1,
        "title": "학살자",
        "desc": "한 경기에서 15킬 이상",
        "unit": "회",
    },
    "val_kd1": {
        "kind": "valorant", "target": 1,
        "title": "본전은 하기",
        "desc": "한 경기에서 K/D 1.0 이상",
        "unit": "회",
    },
    "val_comp": {
        "kind": "valorant", "target": 1,
        "title": "경쟁전 돌기",
        "desc": "오늘 경쟁전 1판 이상",
        "unit": "판",
    },
}

SERVER_KEYS = [k for k, v in MISSIONS.items() if v["kind"] == "server"]
VALORANT_KEYS = [k for k, v in MISSIONS.items() if v["kind"] == "valorant"]

# 🔞 성인 역할이 없으면 **배정 자체를 안 해요.**
#
# 🚨 이게 없으면 `play_gamble`은 인증 없는 사람에게 **영구히 못 깨는 슬롯**이 돼요.
#    2026-10-23 실측으로 길드 54명 중 인증자는 27명(50%)이고, 그날 미션을 받은 27명
#    중 **10명이 인증이 없었어요.** 맵추천(2건)은 하려면 할 수 있지만 이쪽은 자격
#    자체가 없어서 더 나빠요. 발로 미션이 `linked`로 가르는 것과 같은 방식이에요.
ADULT_ONLY_KEYS = frozenset({"play_gamble"})


def server_keys_for(adult: bool) -> list[str]:
    """그 사람에게 배정할 수 있는 서버 미션. 🚨 성인이 아니면 🔞 미션을 빼요."""
    if adult:
        return list(SERVER_KEYS)
    return [k for k in SERVER_KEYS if k not in ADULT_ONLY_KEYS]

# 명령어 이름 -> 미션 키. on_app_command_completion에서 이 표를 보고 진행도를 올려요.
# 이렇게 해두면 각 cog를 건드리지 않아도 돼요.
COMMAND_MISSIONS = {
    "오상": "use_myshop",
    "전적": "use_rank",
    "맵추천": "use_map",
    "방만들기": "create_room",
}

# 1회성 미션 (하루 상한과 별개로, 평생 한 번만)
ONE_TIME_MISSIONS = {
    "link_riot": {
        "title": "라이엇 계정 연동",
        "desc": "`/전적`에서 본인 계정을 등록하면 발로란트 미션을 받을 수 있어요",
        "reward": 3,
    },
}


def today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def pick_missions(user_id, date_iso: str, linked: bool, adult: bool = False) -> list[str]:
    """그 사람의 그 날 미션을 고르는데, 같은 입력이면 항상 같은 결과가 나와요.

    🚨 `adult`의 기본값은 **False**(= 🔞 미션 제외)예요. 역할을 모르는 호출부가 있어도
    "못 깨는 미션이 배정되는" 쪽으로는 안 틀리게요. 반대로 두면 설정이 빠진 순간
    모두에게 도박 미션이 깔려요.

    ⚠️ 이 결과는 그날 문서를 **처음 만들 때 한 번만** 쓰여요(`_ensure_today_sync`가
    문서가 있으면 그대로 돌려줘요). 그래서 같은 날 두 경로가 서로 다른 `adult`로
    들어와도 먼저 만든 쪽으로 고정돼요 - 하루 중에 미션이 바뀌지는 않아요.
    """
    rng = random.Random(f"{user_id}:{date_iso}")
    server_pool = server_keys_for(adult)
    if linked:
        # 🔄 **발로 1 + 서버 2** (2026-10-23에 발로 2 + 서버 1에서 바꿨어요).
        #
        # ⭐ **왜 바꿨나**: 발로를 안 하는 날엔 서버 슬롯 수가 그날의 천장이었어요.
        #    전엔 1개 = 하루 1코인이 최대였고, `#🎯｜미션-내용`에 그 불만이 그대로
        #    남아 있었어요 - 2026-10-22에 두 사람이 "ㅈㄴ 어렵네 / 미션으로 받는
        #    코인양을 늘려야겠다", "미션이 이상해요 / 나 언랭인데,," 라고 했고, 그때
        #    배정이 둘 다 **발로 2 + 서버 1**이었어요(학살자 15킬 · 본전 K/D 1.0).
        # 🚨 발행 상한은 안 변해요. 하루 3개 · 개당 1코인 그대로예요. 바뀌는 건
        #    "못 깨서 안 나가던 코인"이 나가기 시작하는 것뿐이에요.
        picks = rng.sample(VALORANT_KEYS, 1) + rng.sample(server_pool, 2)
    else:
        picks = rng.sample(server_pool, DAILY_MISSION_COUNT)
    rng.shuffle(picks)
    return picks


def _blank_doc(user_id, date_iso: str, linked: bool, adult: bool = False) -> dict:
    return {
        "_id": str(user_id),
        "date": date_iso,
        "picks": pick_missions(user_id, date_iso, linked, adult),
        "progress": {},
        "done": [],
        "oneTimeDone": [],
    }


def _ensure_today_sync(user_id, linked: bool, adult: bool = False) -> dict:
    """오늘 미션 문서를 돌려줘요. 날짜가 바뀌었으면 새로 배정해요."""
    uid, date_iso = str(user_id), today_iso()
    doc = _missions.find_one({"_id": uid})

    if doc is None:
        doc = _blank_doc(uid, date_iso, linked, adult)
        _missions.insert_one(doc)
        return doc

    if doc.get("date") != date_iso:
        fresh = _blank_doc(uid, date_iso, linked, adult)
        # 1회성 미션 기록은 날짜가 바뀌어도 유지돼야 해요.
        fresh["oneTimeDone"] = doc.get("oneTimeDone", [])
        # 업적용 누적 카운터도 마찬가지예요. 여기서 안 옮기면 매일 0으로 리셋돼요.
        fresh["totalDone"] = doc.get("totalDone", 0)
        _missions.replace_one({"_id": uid}, fresh)
        return fresh

    return doc


def _progress_sync(user_id, key: str, amount: int = 1) -> bool:
    """진행도를 올리고, **이번 호출로 새로 완료됐으면** True를 돌려줘요.
    (이미 완료된 미션이면 False - 코인을 두 번 주지 않으려고요.)"""
    uid = str(user_id)
    doc = _missions.find_one({"_id": uid})
    if doc is None or doc.get("date") != today_iso():
        return False                      # 오늘 미션을 아직 안 받은 사람
    if key not in doc.get("picks", []):
        return False                      # 오늘 배정되지 않은 미션
    if key in doc.get("done", []):
        return False                      # 이미 깬 미션

    target = MISSIONS[key]["target"]
    new_value = doc.get("progress", {}).get(key, 0) + amount

    if new_value < target:
        _missions.update_one({"_id": uid}, {"$set": {f"progress.{key}": new_value}})
        return False

    # 완료 처리. `done`에 $addToSet이라 동시에 두 번 들어와도 한 번만 들어가요.
    #
    # `totalDone`은 업적("미션 50개 완료")용 누적 카운터예요. `done`은 날짜가 바뀌면
    # 통째로 비워지니까 여기서 따로 세지 않으면 누적을 알 방법이 없어요. 필터에 `$ne`가
    # 있어서 이 update가 성공한 순간에만 +1 되고, 동시에 두 번 들어와도 한 번만 올라가요.
    res = _missions.update_one(
        {"_id": uid, "done": {"$ne": key}},
        {
            "$set": {f"progress.{key}": new_value},
            "$addToSet": {"done": key},
            "$inc": {"totalDone": 1},
        },
    )
    # modified_count가 0이면 그 찰나에 다른 호출이 먼저 완료시킨 거예요 → 코인은 그쪽이 줘요.
    return res.modified_count == 1


def _reroll_sync(user_id, key: str, adult: bool = False) -> tuple[str | None, str]:
    """미션 하나를 **서버 미션**으로 바꿔요. (새 미션 키, 실패 사유) - 성공하면 사유는 "".

    ## 왜 꼭 서버 미션으로 바꾸는가

    연동자는 `pick_missions()`에서 **발로 1 + 서버 2**를 받아요(2026-10-23 전엔 발로 2 +
    서버 1이었고, 그때는 발로란트를 안 하는 날 3개 중 **1개만** 깰 수 있었어요 - 미션
    완료율이 14%에 머문 구조적 이유였고 유저 불만도 거기서 나왔어요). 리롤 수요는 정확히
    "오늘 발로 안 하는데 발로 미션이 뽑혔다"라서, 같은 종류로 바꿔주면 아무 의미가 없어요.
    그래서 교체는 늘 서버 미션 풀에서 골라요 - 이제 그 한 개까지 바꾸면 3개를 다 깰 수 있어요.
    비연동자는 어차피 서버 미션만 갖고 있어서 자연스럽게 같은 규칙으로 돌아가요
    (⚠️ 반대로 발로 미션을 주면 라이엇 연동이 없는 사람은 깰 방법이 없어요).

    실패 사유: no_doc(오늘 미션 없음) / not_assigned / already_done / limit(하루 한도) /
    exhausted(바꿀 서버 미션이 남지 않음) / race(그 찰나에 다른 리롤이 먼저 들어감)
    """
    uid, today = str(user_id), today_iso()
    doc = _missions.find_one({"_id": uid})
    if doc is None or doc.get("date") != today:
        return None, "no_doc"

    picks = list(doc.get("picks") or [])
    if key not in picks:
        return None, "not_assigned"
    if key in (doc.get("done") or []):
        return None, "already_done"
    if int(doc.get("rerolls") or 0) >= REROLL_LIMIT_PER_DAY:
        return None, "limit"

    # 🚨 **성인이 아니면 🔞 미션을 후보에서 빼요.** 안 그러면 2코인을 내고 리롤했는데
    #    `/도박`이 역할로 막혀 **못 깨는 미션**을 받아요 - 리롤의 목적과 정반대예요.
    candidates = [k for k in server_keys_for(adult) if k not in picks]
    if not candidates:
        return None, "exhausted"

    new_key = random.choice(candidates)
    new_picks = [new_key if p == key else p for p in picks]
    # 바뀐 미션의 진행도는 지워요. 안 그러면 "방 만들기 1/1"이 엉뚱한 미션에 남아있어요.
    progress = {k: v for k, v in (doc.get("progress") or {}).items() if k != key}

    # ⚠️ 필터에 **읽어온 picks를 그대로** 넣어요(낙관적 동시성). 그 사이 다른 리롤이
    #    먼저 들어갔으면 picks가 달라서 이 update가 안 맞고, 코인만 두 번 빠지는 걸 막아요.
    #    `rerolls`는 필드가 없을 수도 있어서 필터 조건으로 쓰면 안 돼요(`{"rerolls": 0}`은
    #    필드가 없는 문서를 못 잡아요).
    res = _missions.update_one(
        {"_id": uid, "date": today, "picks": picks},
        {"$set": {"picks": new_picks, "progress": progress}, "$inc": {"rerolls": 1}},
    )
    if res.modified_count != 1:
        return None, "race"
    return new_key, ""


def _rerolls_left_sync(user_id) -> int:
    doc = _missions.find_one({"_id": str(user_id)}, {"rerolls": 1, "date": 1})
    if doc is None or doc.get("date") != today_iso():
        return REROLL_LIMIT_PER_DAY      # 오늘 문서가 아직 없으면 아직 안 쓴 거예요
    return max(0, REROLL_LIMIT_PER_DAY - int(doc.get("rerolls") or 0))


def _claim_one_time_sync(user_id, key: str) -> bool:
    """1회성 미션을 처음 깼으면 True. 이미 받았으면 False.

    ⚠️ upsert를 쓰면 안 돼요. 이미 받은 사람은 필터(`$ne`)에 안 걸리는데, upsert가 켜져 있으면
    그때 같은 _id로 새 문서를 만들려다 중복 키 에러가 나요. 문서는 ensure_today()가 먼저
    만들어두니, 여기서는 없으면 그냥 False면 돼요."""
    res = _missions.update_one(
        {"_id": str(user_id), "oneTimeDone": {"$ne": key}},
        {"$addToSet": {"oneTimeDone": key}, "$inc": {"totalDone": 1}},
    )
    return res.modified_count == 1


# ------------------------------------------------------------------
# 공개 API - 전부 async예요. 반드시 await 하세요.
# (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요 - 2026-09-04 먹통 사고)
# ------------------------------------------------------------------
async def ensure_today(user_id, linked: bool, adult: bool = False) -> dict:
    """🚨 `adult`를 안 넘기면 🔞 미션은 **배정에서 빠져요**(안전한 쪽 기본값).
    역할을 알 수 있는 자리에서는 `utils.adult_check.is_adult(member)`를 넘겨주세요."""
    return await asyncio.to_thread(_ensure_today_sync, user_id, linked, adult)


async def progress(user_id, key: str, amount: int = 1) -> bool:
    """진행도를 올리고 이번에 새로 완료됐으면 True. 코인 지급은 호출한 쪽에서 해요."""
    return await asyncio.to_thread(_progress_sync, user_id, key, amount)


async def claim_one_time(user_id, key: str) -> bool:
    return await asyncio.to_thread(_claim_one_time_sync, user_id, key)


async def reroll(user_id, key: str, adult: bool = False) -> tuple[str | None, str]:
    """미션 하나를 서버 미션으로 교체해요. 코인 차감은 **부르는 쪽**에서 해요
    (실패 사유를 보고 환불할 수 있게 하려고 일부러 분리했어요).

    🚨 `adult`를 안 넘기면 🔞 미션은 교체 후보에서 빠져요 - 못 깨는 미션으로
    바꿔주는 게 제일 나쁜 결과니까요."""
    return await asyncio.to_thread(_reroll_sync, user_id, key, adult)


async def rerolls_left(user_id) -> int:
    return await asyncio.to_thread(_rerolls_left_sync, user_id)
