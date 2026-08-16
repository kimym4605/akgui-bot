"""트레이너(유저)의 포켓몬 육성 데이터를 관리해요.

진화는 자동이 아니에요:
- 레벨 조건 진화: 레벨 도달 시 "진화 가능" 상태가 되고, confirm_evolution()으로 확인해야 실제로 진화해요.
  (이브이는 이때 낮/밤에 따라 에브이/블래키로 갈려요)
  변함없는돌(evolutionLocked=True)을 채워두면 레벨 조건 진화 자체가 잠겨요.
- 돌 조건 진화: 레벨과 무관하게, use_stone()으로 알맞은 돌을 써야만 진화해요.
  (이브이는 불꽃돌/물의돌/번개돌을 쓰면 레벨 상관없이 즉시 부스터/샤미드/쥬피썬더로 진화해요.
   변함없는돌을 채운 상태에서도 돌 진화는 그대로 가능해요.)

저장 스키마 (MongoDB "trainers" 컬렉션, _id = 디스코드 user_id 문자열):
{
  "basePokemon": str, "currentPokemon": str, "evolutionStage": int,
  "level": int, "exp": int, "gold": int, "attendance": int,
  "lastAttendanceDate": str | None, "voiceDate": str | None, "voiceMinutesToday": float,
  "moves": [str, ...], "stats": {...}, "iv": {...}, "nature": str, "ability": str,
  "pokedex": [str, ...], "nickname": str | None, "items": {아이템이름: 개수},
  "evolutionLocked": bool
}

이 컬렉션은 웹(FastAPI backend)에서도 그대로 읽어서 씁니다. 필드를 바꿀 때는
backend 쪽 트레이너 조회 API도 같이 확인해주세요.
"""
import os
import random
from datetime import datetime, timedelta, timezone

from pymongo import DESCENDING, MongoClient

from utils.pokemon_data import (
    BRANCH_EVOLUTIONS,
    EEVEE_STONE_MAP,
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

EXP_PER_ATTENDANCE = 100
GOLD_PER_ATTENDANCE = 100
MAX_LEVEL = 100
POKEDEX_LEVEL = 100

KST = timezone(timedelta(hours=9))

SHOP_ITEMS = {
    "불꽃돌": 300,
    "물의돌": 300,
    "번개돌": 300,
    "잎의돌": 300,
    "달의돌": 300,
    "변함없는돌": 500,
    "특성리셋권": 400,
    "이름변경표": 200,
    "포켓몬리셋권": 1000,
}


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


def use_stone(user_id: int, item_name: str):
    """상점에서 산 돌을 써서 진화시켜요.
    이브이는 불꽃돌/물의돌/번개돌이면 레벨/진화단계와 무관하게 즉시 해당 형태로 진화해요.
    변함없는돌을 채운 상태여도 돌 진화는 그대로 동작해요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        return False, "먼저 `/시작`으로 포켓몬을 받아주세요."

    trainer.setdefault("items", {})

    if trainer["items"].get(item_name, 0) <= 0:
        return False, f"{item_name}을(를) 갖고 있지 않아요. `/상점`에서 구매해주세요."

    if trainer["currentPokemon"] == "이브이" and item_name in EEVEE_STONE_MAP:
        trainer["items"][item_name] -= 1
        before_name = trainer["currentPokemon"]
        after_name = _advance_evolution_stage(trainer, forced_name=EEVEE_STONE_MAP[item_name])
        registered = _apply_pokedex_registration(trainer)

        _save_doc(user_id, trainer)

        return True, {"before": before_name, "after": after_name, "registered": registered, "trainer": trainer}

    step = get_next_evolution(trainer)
    if step is None or step["trigger"] != "stone" or step["item"] != item_name:
        return False, f"{trainer['currentPokemon']}은(는) {item_name}(으)로 진화하지 않아요."

    trainer["items"][item_name] -= 1
    before_name = trainer["currentPokemon"]
    after_name = _advance_evolution_stage(trainer)
    registered = _apply_pokedex_registration(trainer)

    _save_doc(user_id, trainer)

    return True, {"before": before_name, "after": after_name, "registered": registered, "trainer": trainer}


def lock_evolution(user_id: int):
    """변함없는돌을 사용해서 레벨 진화를 잠가요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        return False, "먼저 `/시작`으로 포켓몬을 받아주세요."
    trainer.setdefault("items", {})

    if trainer.get("evolutionLocked"):
        return False, "이미 변함없는돌을 갖고 있어요."
    if trainer["items"].get("변함없는돌", 0) <= 0:
        return False, "변함없는돌이 없어요. `/상점`에서 구매해주세요."

    trainer["items"]["변함없는돌"] -= 1
    trainer["evolutionLocked"] = True

    _save_doc(user_id, trainer)

    return True, f"{trainer['currentPokemon']}에게 변함없는돌을 채웠어요. 레벨로는 더 이상 진화하지 않아요. (돌 진화는 여전히 가능해요)"


def unlock_evolution(user_id: int):
    """변함없는돌을 해제해서 레벨 진화를 다시 가능하게 해요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        return False, "먼저 `/시작`으로 포켓몬을 받아주세요."

    if not trainer.get("evolutionLocked"):
        return False, "지금은 변함없는돌을 갖고 있지 않아요."

    trainer["evolutionLocked"] = False

    _save_doc(user_id, trainer)

    return True, f"{trainer['currentPokemon']}의 변함없는돌을 해제했어요. 다시 레벨로 진화할 수 있어요."


def reset_ability(user_id: int):
    """특성리셋권을 소모해서 현재 포켓몬의 특성을 다시 뽑아요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        return False, "먼저 `/시작`으로 포켓몬을 받아주세요."
    trainer.setdefault("items", {})

    if trainer["items"].get("특성리셋권", 0) <= 0:
        return False, "특성리셋권이 없어요. `/상점`에서 구매해주세요."

    trainer["items"]["특성리셋권"] -= 1
    old_ability = trainer["ability"]
    new_ability = roll_ability(trainer["currentPokemon"])
    trainer["ability"] = new_ability

    _save_doc(user_id, trainer)

    return True, f"{trainer['currentPokemon']}의 특성이 **{old_ability}** → **{new_ability}**(으)로 바뀌었어요!"


def reset_pokemon(user_id: int):
    """포켓몬리셋권을 소모해서 현재 포켓몬을 버리고 새로운 랜덤 포켓몬을 Lv.1부터 다시 키워요.
    골드/아이템/도감/출석 기록은 그대로 유지되고, 지금 키우던 포켓몬만 바뀌어요 (도감에는 등록 안 됨)."""
    trainer = _get_doc(user_id)
    if trainer is None:
        return False, "먼저 `/시작`으로 포켓몬을 받아주세요."
    trainer.setdefault("items", {})

    if trainer["items"].get("포켓몬리셋권", 0) <= 0:
        return False, "포켓몬리셋권이 없어요. `/상점`에서 구매해주세요."

    trainer["items"]["포켓몬리셋권"] -= 1
    before_name = trainer["currentPokemon"]
    _spawn_new_pokemon(trainer)

    _save_doc(user_id, trainer)

    return True, {"before": before_name, "after": trainer["currentPokemon"], "trainer": trainer}


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
    """/출석: 하루 1회(한국시간 자정 기준). 경험치+골드 지급, 레벨업/도감등록/능력치 갱신을 처리해요.
    진화는 자동으로 안 일어나요 — leveled_up이 True이고 이제 진화 가능하면 pending_evolution이 채워져요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        trainer = start_trainer(user_id)
    trainer.setdefault("pokedex", [])
    trainer.setdefault("items", {})

    today_iso = _kst_today_iso()
    if trainer.get("lastAttendanceDate") == today_iso:
        return False, trainer

    before_level = trainer["level"]

    trainer["exp"] += EXP_PER_ATTENDANCE
    trainer["gold"] += GOLD_PER_ATTENDANCE
    trainer["attendance"] += 1
    trainer["lastAttendanceDate"] = today_iso

    leveled_up = False
    while trainer["level"] < MAX_LEVEL and trainer["exp"] >= exp_needed(trainer["level"]):
        trainer["exp"] -= exp_needed(trainer["level"])
        trainer["level"] += 1
        leveled_up = True
    if trainer["level"] >= MAX_LEVEL:
        trainer["level"] = MAX_LEVEL
        trainer["exp"] = 0

    trainer["stats"] = calculate_stats(trainer["currentPokemon"], trainer["level"], trainer["iv"], trainer["nature"])

    _save_doc(user_id, trainer)

    pending = get_next_evolution(trainer) if has_pending_level_evolution(trainer) else None

    return True, {
        "trainer": trainer,
        "before_level": before_level,
        "leveled_up": leveled_up,
        "pending_evolution": pending,
        "exp_gain": EXP_PER_ATTENDANCE,
        "gold_gain": GOLD_PER_ATTENDANCE,
        "exp_needed": exp_needed(trainer["level"]),
    }


def add_voice_exp(user_id: int, minutes: float):
    """통화 체류시간(분)만큼 경험치를 지급해요. 하루(한국시간 자정 기준) 최대 240분(4시간)까지만 인정돼요."""
    trainer = _get_doc(user_id)
    if trainer is None:
        trainer = start_trainer(user_id)
    trainer.setdefault("pokedex", [])
    trainer.setdefault("items", {})

    today_iso = _kst_today_iso()
    if trainer.get("voiceDate") != today_iso:
        trainer["voiceDate"] = today_iso
        trainer["voiceMinutesToday"] = 0

    DAILY_CAP_MINUTES = 240
    EXP_PER_MINUTE = 0.3

    remaining = DAILY_CAP_MINUTES - trainer.get("voiceMinutesToday", 0)
    effective_minutes = max(0, min(minutes, remaining))
    if effective_minutes <= 0:
        return None

    exp_gain = round(effective_minutes * EXP_PER_MINUTE)
    if exp_gain <= 0:
        return None

    before_level = trainer["level"]

    trainer["voiceMinutesToday"] = trainer.get("voiceMinutesToday", 0) + effective_minutes
    trainer["exp"] += exp_gain

    leveled_up = False
    while trainer["level"] < MAX_LEVEL and trainer["exp"] >= exp_needed(trainer["level"]):
        trainer["exp"] -= exp_needed(trainer["level"])
        trainer["level"] += 1
        leveled_up = True
    if trainer["level"] >= MAX_LEVEL:
        trainer["level"] = MAX_LEVEL
        trainer["exp"] = 0

    trainer["stats"] = calculate_stats(trainer["currentPokemon"], trainer["level"], trainer["iv"], trainer["nature"])

    _save_doc(user_id, trainer)

    pending = get_next_evolution(trainer) if has_pending_level_evolution(trainer) else None

    return {
        "trainer": trainer,
        "before_level": before_level,
        "leveled_up": leveled_up,
        "pending_evolution": pending,
        "exp_gain": exp_gain,
        "minutes_credited": effective_minutes,
        "capped": effective_minutes < minutes,
    }


def buy_item(user_id: int, item_name: str, qty: int = 1):
    if item_name not in SHOP_ITEMS:
        return False, "상점에 없는 아이템이에요."
    if qty <= 0:
        return False, "수량은 1개 이상이어야 해요."

    trainer = _get_doc(user_id)
    if trainer is None:
        trainer = start_trainer(user_id)
    trainer.setdefault("items", {})

    total_price = SHOP_ITEMS[item_name] * qty
    if trainer["gold"] < total_price:
        return False, f"골드가 부족해요. (필요: {total_price}G, 보유: {trainer['gold']}G)"

    trainer["gold"] -= total_price
    trainer["items"][item_name] = trainer["items"].get(item_name, 0) + qty

    _save_doc(user_id, trainer)

    return True, f"{item_name} {qty}개를 구매했어요! (-{total_price}G)"


def set_nickname(user_id: int, nickname: str):
    if not (1 <= len(nickname) <= 12):
        return False, "별명은 1~12자로 입력해주세요."

    trainer = _get_doc(user_id)
    if trainer is None:
        return False, "먼저 `/시작`으로 포켓몬을 받아주세요."
    trainer.setdefault("items", {})

    if trainer["items"].get("이름변경표", 0) <= 0:
        return False, "이름변경표가 없어요. `/상점`에서 구매해주세요."

    trainer["items"]["이름변경표"] -= 1
    trainer["nickname"] = nickname

    _save_doc(user_id, trainer)

    return True, f"별명을 **{nickname}**(으)로 지어줬어요!"


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
