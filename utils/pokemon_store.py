"""트레이너(유저)의 포켓몬 육성 데이터를 관리해요.

스타팅 선택(트레이너 생성)·진화·아이템 구매/사용(돌 사용, 변함없는돌, 특성리셋권, 이름변경표, 포켓몬리셋권 등)·
도감·랭킹은 전부 웹사이트에서 처리해요 — 이 파일(봇)에는 그 관련 함수가 없어요.
봇은 하루 1회 코인 지급(attend)만 담당해요. start_trainer()는 `/포켓몬설정`(서버 소유자 전용 테스트 명령어) 전용 폴백이에요.

저장 스키마 (MongoDB "trainers" 컬렉션, _id = 디스코드 user_id 문자열):
{
  "basePokemon": str, "currentPokemon": str, "evolutionStage": int,
  "level": int, "exp": int, "gold": int, "coin": int, "attendance": int,
  "lastAttendanceDate": str | None, "voiceDate": str | None, "voiceMinutesToday": float,
  "moves": [str, ...], "stats": {...}, "iv": {...}, "nature": str, "ability": str,
  "pokedex": [str, ...], "nickname": str | None, "items": {아이템이름: 개수},
  "evolutionLocked": bool
}

"coin"(악귀코인)은 골드와 별개의 재화예요. /출석에서만 하루 1개씩 지급되고,
경험치/레벨업은 이제 웹(배틀·탐험)에서만 이루어져요 — 디스코드에서는 더 이상 EXP를 주지 않아요.

이 컬렉션은 웹(FastAPI backend)에서도 그대로 읽어서 씁니다. 필드를 바꿀 때는
backend 쪽 트레이너 조회 API도 같이 확인해주세요.
"""
import os
import random
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

from utils.pokemon_data import (
    STARTER_POOL,
    calculate_stats,
    exp_needed,
    roll_iv,
    roll_nature,
)
from utils.ability_data import roll_ability
from utils.skill_data import get_learnset

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "pokemon_game")

_client = MongoClient(MONGODB_URI)
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


def get_all_trainers() -> dict:
    return {doc["_id"]: {k: v for k, v in doc.items() if k != "_id"} for doc in _trainers.find()}


def save_trainer(user_id: int, trainer: dict):
    _save_doc(user_id, trainer)


def has_trainer(user_id: int) -> bool:
    return _trainers.find_one({"_id": str(user_id)}, {"_id": 1}) is not None


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


def start_trainer(user_id: int) -> dict:
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


def get_trainer(user_id: int) -> dict | None:
    trainer = _get_doc(user_id)
    if trainer is not None:
        trainer.setdefault("pokedex", [])
        trainer.setdefault("items", {})
        trainer.setdefault("nickname", None)
        trainer.setdefault("evolutionLocked", False)
        trainer.setdefault("coin", 0)
    return trainer


def attend(user_id: int):
    """/출석: 하루 1회(한국시간 자정 기준). 악귀코인 1개를 지급해요.
    경험치/레벨업은 이제 웹(배틀·탐험)에서만 이루어지고, 디스코드 출석은 코인 전용이에요.
    호출 전에 반드시 has_trainer()로 트레이너 존재를 확인해야 해요(없으면 웹에서 먼저 시작 필요)."""
    trainer = _get_doc(user_id)
    trainer.setdefault("pokedex", [])
    trainer.setdefault("items", {})
    trainer.setdefault("coin", 0)

    today_iso = _kst_today_iso()
    if trainer.get("lastAttendanceDate") == today_iso:
        return False, trainer

    trainer["attendance"] += 1
    trainer["lastAttendanceDate"] = today_iso
    trainer["coin"] += COIN_PER_ATTENDANCE

    _save_doc(user_id, trainer)

    return True, {
        "trainer": trainer,
        "coin_gain": COIN_PER_ATTENDANCE,
    }


def reset_user(user_id: int) -> bool:
    result = _trainers.delete_one({"_id": str(user_id)})
    return result.deleted_count > 0
