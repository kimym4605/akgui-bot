"""트레이너(유저)의 포켓몬 육성 데이터를 관리해요.

스타팅 선택(트레이너 생성)·진화·아이템 구매/사용(돌 사용, 변함없는돌, 특성리셋권, 이름변경표, 포켓몬리셋권 등)·
도감·랭킹은 전부 웹사이트에서 처리해요 — 이 파일(봇)에는 그 관련 함수가 없어요.
봇은 하루 1회 코인 지급(attend)만 담당해요. start_trainer()는 `/포켓몬설정`(서버 소유자 전용 테스트 명령어) 전용 폴백이에요.

저장 스키마 (MongoDB "trainers" 컬렉션, _id = 디스코드 user_id 문자열):
{
  "basePokemon": str, "currentPokemon": str, "evolutionStage": int,
  "level": int, "exp": int, "gold": int, "coin": int, "attendance": int,
  "attendanceStreak": int,  # 연속 출석일수(하루라도 빠지면 1로 리셋)
  "lastAttendanceDate": str | None, "voiceDate": str | None, "voiceMinutesToday": float,
  "moves": [str, ...], "stats": {...}, "iv": {...}, "nature": str, "ability": str,
  "pokedex": [str, ...], "nickname": str | None, "items": {아이템이름: 개수},
  "evolutionLocked": bool
}

"coin"(악귀코인)은 골드와 별개의 재화예요. /출석에서만 하루 1개씩 지급되고,
경험치/레벨업은 이제 웹(배틀·탐험)에서만 이루어져요 — 디스코드에서는 더 이상 EXP를 주지 않아요.

이 컬렉션은 웹(FastAPI backend)에서도 그대로 읽어서 씁니다. 필드를 바꿀 때는
backend 쪽 트레이너 조회 API도 같이 확인해주세요.

⚠️ 이 모듈의 공개 함수는 전부 **async**예요. 반드시 `await`를 붙여서 부르세요.
아래 "동기 pymongo 사고" 주석에 이유가 적혀 있어요.
"""
import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

from utils.pokemon_data import (
    CUSTOM_STARTERS,
    STARTER_POOL,
    calculate_stats,
    exp_needed,
    roll_iv,
    roll_nature,
)
from utils.ability_data import roll_ability
from utils.skill_data import get_learnset

log = logging.getLogger(__name__)

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "pokemon_game")

# ------------------------------------------------------------------
# ⚠️ 동기 pymongo 사고 (2026-09-04)
#
# 예전엔 `MongoClient(MONGODB_URI)`로 끝이었고, 아래 함수들도 전부 동기 함수라
# async 핸들러에서 그대로 불렸다. 문제가 두 겹이었다:
#
#  1) pymongo의 `socketTimeoutMS` 기본값은 **None = 무한 대기**다. 소켓이 한 번
#     멈추면(네트워크 블립, Atlas 페일오버, Fly NAT 끊김) 그 호출은 영원히 안 돌아온다.
#  2) 그 호출이 이벤트 루프 위에서 일어나니, 루프 전체가 같이 영구 정지한다.
#     → 봇이 통째로 먹통. 자체 복구 경로가 없어서 재시작만이 답이었다.
#
# 특히 `cogs/daycare_voice.py`는 음성 이벤트마다/5분마다 유저당 3회씩 이 함수들을
# 불러서, 통화 인원이 많을수록 루프가 막힐 확률이 올라갔다.
#
# 그래서 두 가지를 같이 고쳤다:
#  - 아래 타임아웃들로 "무한 대기"를 없앤다 (실패는 하되 멈추지는 않게).
#  - 공개 함수를 전부 async로 만들고 실제 DB 작업은 asyncio.to_thread로 넘긴다.
#    이제 DB가 느려도 이벤트 루프는 계속 돈다.
# ------------------------------------------------------------------
_client = MongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=5_000,   # 서버 못 찾으면 5초 만에 포기 (기본 30초)
    connectTimeoutMS=5_000,           # 연결 수립 5초 (기본 20초)
    socketTimeoutMS=10_000,           # ★ 핵심: 기본값 None(무한) → 10초
    retryWrites=True,                 # 일시적 네트워크 오류는 드라이버가 1회 재시도
)
_db = _client[MONGODB_DB_NAME]
_trainers = _db["trainers"]

COIN_PER_ATTENDANCE = 1

KST = timezone(timedelta(hours=9))


def _kst_today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _get_doc(user_id: int) -> dict | None:
    doc = _trainers.find_one({"_id": str(user_id)})
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def _save_doc(user_id: int, trainer: dict):
    doc = {**trainer, "_id": str(user_id)}
    _trainers.replace_one({"_id": str(user_id)}, doc, upsert=True)


def _save_trainer_sync(user_id: int, trainer: dict):
    _save_doc(user_id, trainer)


def _has_trainer_sync(user_id: int) -> bool:
    return _trainers.find_one({"_id": str(user_id)}, {"_id": 1}) is not None


def has_custom_starter(trainer: dict) -> bool:
    """이 트레이너가 **본인이 직접 고른** 정식 스타팅을 갖고 있는지 판별해요.

    정식 스타팅 제도 이전 계정은 메인 포켓몬이 랜덤 배정된 거라 "고른 적 없는 포켓몬"이에요.
    그런 계정은 웹에서 스타팅을 다시 고르게 되어 있고, 봇도 그때까지는 포켓몬 정보를 보여주면
    안 돼요(고르지도 않은 포켓몬을 자기 포켓몬처럼 보여주게 되니까요).

    ⚠️ 웹 `backend/pokemon_store.py`의 `has_custom_starter()`와 판정이 같아야 해요.
    메인만 보면 안 되는 이유: 웹에서 "메인으로 설정"을 하면 basePokemon이 그 포켓몬 걸로
    덮어써져서, 정상 계정도 구식으로 잘못 잡혀요. 그래서 가방(bag)까지 같이 봐요.

    DB에 안 붙는 순수 판정 함수라 동기 함수 그대로예요(await 불필요).
    """
    if trainer.get("basePokemon") in CUSTOM_STARTERS:
        return True
    return any(p.get("basePokemon") in CUSTOM_STARTERS for p in trainer.get("bag", []))


def _new_pokemon_fields(base_name: str) -> dict:
    iv = roll_iv()
    nature = roll_nature()
    ability = roll_ability(base_name)
    level = 1
    return {
        "basePokemon": base_name,
        "currentPokemon": base_name,
        "evolutionStage": 0,
        "level": level,
        "exp": 0,
        "moves": get_learnset(base_name).get("1", [])[:4],
        "iv": iv,
        "nature": nature,
        "ability": ability,
        "stats": calculate_stats(base_name, level, iv, nature),
        "nickname": None,
        "evolutionLocked": False,
    }


def _start_trainer_sync(user_id: int) -> dict:
    existing = _get_doc(user_id)
    if existing is not None:
        return existing

    base_name = random.choice(STARTER_POOL)
    trainer = {
        "gold": 0,
        "coin": 0,
        "attendance": 0,
        "lastAttendanceDate": None,
        "voiceDate": None,
        "voiceMinutesToday": 0,
        "pokedex": [],
        "items": {},
        **_new_pokemon_fields(base_name),
    }
    _save_doc(user_id, trainer)
    return trainer


def _get_trainer_sync(user_id: int) -> dict | None:
    trainer = _get_doc(user_id)
    if trainer is not None:
        trainer.setdefault("pokedex", [])
        trainer.setdefault("items", {})
        trainer.setdefault("nickname", None)
        trainer.setdefault("evolutionLocked", False)
        trainer.setdefault("coin", 0)
    return trainer


def _attend_sync(user_id: int):
    """/출석: 하루 1회(한국시간 자정 기준). 악귀코인 1개를 지급해요.
    경험치/레벨업은 이제 웹(배틀·탐험)에서만 이루어지고, 디스코드 출석은 코인 전용이에요.
    호출 전에 반드시 has_trainer()로 트레이너 존재를 확인해야 해요(없으면 웹에서 먼저 시작 필요)."""
    trainer = _get_doc(user_id)
    trainer.setdefault("pokedex", [])
    trainer.setdefault("items", {})
    trainer.setdefault("coin", 0)
    trainer.setdefault("attendanceStreak", 0)

    today_iso = _kst_today_iso()
    if trainer.get("lastAttendanceDate") == today_iso:
        return False, trainer

    yesterday_iso = (datetime.now(KST).date() - timedelta(days=1)).isoformat()
    # 어제 출석했으면 연속 기록에 이어붙이고, 하루라도 빠졌으면(또는 첫 출석이면) 1부터 다시 세요.
    trainer["attendanceStreak"] = trainer["attendanceStreak"] + 1 if trainer.get("lastAttendanceDate") == yesterday_iso else 1

    trainer["attendance"] += 1
    trainer["lastAttendanceDate"] = today_iso
    trainer["coin"] += COIN_PER_ATTENDANCE

    _save_doc(user_id, trainer)

    return True, {
        "trainer": trainer,
        "coin_gain": COIN_PER_ATTENDANCE,
    }


def _reset_user_sync(user_id: int) -> bool:
    result = _trainers.delete_one({"_id": str(user_id)})
    return result.deleted_count > 0


# ------------------------------------------------------------------
# 🔓 공개 API — 전부 async
#
# 위의 `_*_sync` 함수들이 실제 DB 작업이고, 여기서는 그걸 별도 스레드로 넘겨요.
# DB가 느리거나 멈춰도 이벤트 루프는 계속 돌아요. (호출부는 반드시 `await`)
# ------------------------------------------------------------------
async def save_trainer(user_id: int, trainer: dict):
    return await asyncio.to_thread(_save_trainer_sync, user_id, trainer)


async def has_trainer(user_id: int) -> bool:
    return await asyncio.to_thread(_has_trainer_sync, user_id)


async def start_trainer(user_id: int) -> dict:
    return await asyncio.to_thread(_start_trainer_sync, user_id)


async def get_trainer(user_id: int) -> dict | None:
    return await asyncio.to_thread(_get_trainer_sync, user_id)


async def attend(user_id: int):
    return await asyncio.to_thread(_attend_sync, user_id)


async def reset_user(user_id: int) -> bool:
    return await asyncio.to_thread(_reset_user_sync, user_id)


async def ping_db() -> bool:
    """DB가 살아있는지 가볍게 확인해요. 부팅 때 한 번 불러서 설정 오류를 일찍 잡아요."""
    try:
        await asyncio.to_thread(_db.command, "ping")
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("MongoDB ping 실패: %s", e)
        return False
