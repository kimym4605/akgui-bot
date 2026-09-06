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


def pick_missions(user_id, date_iso: str, linked: bool) -> list[str]:
    """그 사람의 그 날 미션을 고르는데, 같은 입력이면 항상 같은 결과가 나와요."""
    rng = random.Random(f"{user_id}:{date_iso}")
    if linked:
        # 발로 2 + 서버 1. 발로 미션끼리는 겹치지 않게 뽑아요.
        picks = rng.sample(VALORANT_KEYS, 2) + rng.sample(SERVER_KEYS, 1)
    else:
        picks = rng.sample(SERVER_KEYS, DAILY_MISSION_COUNT)
    rng.shuffle(picks)
    return picks


def _blank_doc(user_id, date_iso: str, linked: bool) -> dict:
    return {
        "_id": str(user_id),
        "date": date_iso,
        "picks": pick_missions(user_id, date_iso, linked),
        "progress": {},
        "done": [],
        "oneTimeDone": [],
    }


def _ensure_today_sync(user_id, linked: bool) -> dict:
    """오늘 미션 문서를 돌려줘요. 날짜가 바뀌었으면 새로 배정해요."""
    uid, date_iso = str(user_id), today_iso()
    doc = _missions.find_one({"_id": uid})

    if doc is None:
        doc = _blank_doc(uid, date_iso, linked)
        _missions.insert_one(doc)
        return doc

    if doc.get("date") != date_iso:
        fresh = _blank_doc(uid, date_iso, linked)
        # 1회성 미션 기록은 날짜가 바뀌어도 유지돼야 해요.
        fresh["oneTimeDone"] = doc.get("oneTimeDone", [])
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
    res = _missions.update_one(
        {"_id": uid, "done": {"$ne": key}},
        {"$set": {f"progress.{key}": new_value}, "$addToSet": {"done": key}},
    )
    # modified_count가 0이면 그 찰나에 다른 호출이 먼저 완료시킨 거예요 → 코인은 그쪽이 줘요.
    return res.modified_count == 1


def _claim_one_time_sync(user_id, key: str) -> bool:
    """1회성 미션을 처음 깼으면 True. 이미 받았으면 False.

    ⚠️ upsert를 쓰면 안 돼요. 이미 받은 사람은 필터(`$ne`)에 안 걸리는데, upsert가 켜져 있으면
    그때 같은 _id로 새 문서를 만들려다 중복 키 에러가 나요. 문서는 ensure_today()가 먼저
    만들어두니, 여기서는 없으면 그냥 False면 돼요."""
    res = _missions.update_one(
        {"_id": str(user_id), "oneTimeDone": {"$ne": key}},
        {"$addToSet": {"oneTimeDone": key}},
    )
    return res.modified_count == 1


# ------------------------------------------------------------------
# 공개 API - 전부 async예요. 반드시 await 하세요.
# (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요 - 2026-09-04 먹통 사고)
# ------------------------------------------------------------------
async def ensure_today(user_id, linked: bool) -> dict:
    return await asyncio.to_thread(_ensure_today_sync, user_id, linked)


async def progress(user_id, key: str, amount: int = 1) -> bool:
    """진행도를 올리고 이번에 새로 완료됐으면 True. 코인 지급은 호출한 쪽에서 해요."""
    return await asyncio.to_thread(_progress_sync, user_id, key, amount)


async def claim_one_time(user_id, key: str) -> bool:
    return await asyncio.to_thread(_claim_one_time_sync, user_id, key)
