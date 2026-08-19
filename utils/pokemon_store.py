"""트레이너(유저)의 포켓몬 육성 데이터를 관리해요.

진화는 자동이 아니에요:
- 레벨 조건 진화: 레벨 도달 시 "진화 가능" 상태가 되고, confirm_evolution()으로 확인해야 실제로 진화해요.
  (이브이는 이때 낮/밤에 따라 에브이/블래키로 갈려요)
  변함없는돌(evolutionLocked=True)을 채워두면 레벨 조건 진화 자체가 잠겨요.
- 돌 조건 진화: 레벨과 무관하게 알맞은 돌을 써야만 진화해요.

아이템 구매/사용(돌 사용, 변함없는돌, 특성리셋권, 이름변경표, 포켓몬리셋권 등)은
전부 웹사이트에서 처리해요 — 이 파일에는 그 관련 함수가 없어요(confirm_evolution()만 예외).

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

from pymongo import DESCENDING, MongoClient

from utils.pokemon_data import (
    BRANCH_EVOLUTIONS,
    STARTER_POOL,
    calculate_stats,
    exp_needed,
    get_evolutions,
    get_family_names,
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
MAX_LEVEL = 100
POKEDEX_LEVEL = 100

KST = timezone(timedelta(hours=9))


def _kst_today_iso() -> str:
    return datetime.now(KST).date().isoformat()


def _is_daytime_kst() -> bool:
    """한국시간 기준 06:00~17:59면 낮으로 쳐요."""
    hour = datetime.now(KST).hour
    return 6 <= hour < 18


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


def _resolve_branch_name(base_name: str, placeholder: str) -> str:
    """분기 진화의 실제 결과를 정해요. 이브이는 낮/밤으로, 나머지는 랜덤이에요."""
    if base_name == "이브이" and placeholder == "__EEVEE_EVO__":
        return "에브이" if _is_daytime_kst() else "블래키"
    return random.choice(BRANCH_EVOLUTIONS[placeholder])


def get_next_evolution(trainer: dict):
    """다음 진화 단계 정보를 반환해요. 더 진화할 게 없으면 None."""
    family = get_family_names(trainer["basePokemon"])
    evolutions = get_evolutions(trainer["basePokemon"])

    stage = trainer["evolutionStage"]
    if stage >= len(evolutions):
        return None

    step = evolutions[stage]
    next_name = family[stage + 1]
    target_hint = None if next_name in BRANCH_EVOLUTIONS else next_name

    return {"trigger": step["trigger"], "level": step["level"], "item": step["item"], "target_hint": target_hint}


def has_pending_level_evolution(trainer: dict) -> bool:
    if trainer.get("evolutionLocked"):
        return False
    step = get_next_evolution(trainer)
    if step is None or step["trigger"] != "level":
        return False
    return trainer["level"] >= step["level"]


def _advance_evolution_stage(trainer: dict, forced_name: str | None = None) -> str:
    """실제로 다음 단계로 진화시켜요. forced_name을 주면 그 이름으로 강제 지정해요 (이브이 돌 진화용)."""
    family = get_family_names(trainer["basePokemon"])
    trainer["evolutionStage"] += 1

    if forced_name:
        next_name = forced_name
    else:
        next_name = family[trainer["evolutionStage"]]
        if next_name in BRANCH_EVOLUTIONS:
            next_name = _resolve_branch_name(trainer["basePokemon"], next_name)

    trainer["currentPokemon"] = next_name
    trainer["ability"] = roll_ability(next_name)
    trainer["stats"] = calculate_stats(next_name, trainer["level"], trainer["iv"], trainer["nature"])
    return next_name


def confirm_evolution(user_id: int):
    """레벨 조건을 채운 진화를 실제로 확정해요. (이브이는 이 시점 낮/밤으로 결정돼요)"""
    trainer = _get_doc(user_id)
    if trainer is None or not has_pending_level_evolution(trainer):
        return None

    before_name = trainer["currentPokemon"]
    after_name = _advance_evolution_stage(trainer)
    registered = _apply_pokedex_registration(trainer)

    _save_doc(user_id, trainer)

    return {"before": before_name, "after": after_name, "registered": registered, "trainer": trainer}


def _spawn_new_pokemon(trainer: dict):
    base_name = random.choice(STARTER_POOL)
    for k, v in _new_pokemon_fields(base_name).items():
        trainer[k] = v


def _apply_pokedex_registration(trainer: dict) -> bool:
    if trainer["level"] < POKEDEX_LEVEL:
        return False

    trainer.setdefault("pokedex", [])
    current = trainer["currentPokemon"]
    if current not in trainer["pokedex"]:
        trainer["pokedex"].append(current)

    _spawn_new_pokemon(trainer)
    return True


def attend(user_id: int):
    """/출석: 하루 1회(한국시간 자정 기준). 악귀코인 1개를 지급해요.
    경험치/레벨업은 이제 웹(배틀·탐험)에서만 이루어지고, 디스코드 출석은 코인 전용이에요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        trainer = start_trainer(user_id)
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


def get_pokedex(user_id: int) -> list:
    trainer = get_trainer(user_id)
    if trainer is None:
        return []
    return trainer.get("pokedex", [])


def get_ranking(limit: int = 10) -> list:
    cursor = _trainers.find().sort(
        [("level", DESCENDING), ("exp", DESCENDING), ("attendance", DESCENDING)]
    ).limit(limit)
    return [(doc["_id"], {k: v for k, v in doc.items() if k != "_id"}) for doc in cursor]


def reset_user(user_id: int) -> bool:
    result = _trainers.delete_one({"_id": str(user_id)})
    return result.deleted_count > 0
