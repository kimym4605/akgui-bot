"""키우미집(Day Care) 진행도를 디스코드 통화(음성채널) 잔류 시간으로도 채워주는 모듈이에요.

맡기기/데려오기/알 받기 같은 조작은 전부 웹(악귀포켓몬 개발 backend/daycare_store.py)에서만
해요 - 이 파일은 그 웹이 만든 trainer["daycare"] 필드를 같은 방식으로 "진행"만 시켜요
(cogs/daycare_voice.py가 음성채널 잔류 10분당 1틱씩 tick_steps()를 호출해요).

봇의 utils/pokemon_data.py・ability_data.py・skill_data.py는 "1세대 위주"로 데이터가 더 적어서
(웹 로스터엔 있지만 봇엔 없는 진화 계열・특성・기술이 다수 있음), 알의 종/특성/기술을 정확히
계산하려면 웹과 동일한 전체 데이터가 필요해요. 그래서 이 파일 전용으로 웹 data/ 폴더를 그대로
복사해온 data/full_evolution.json・full_abilities.json・full_learnsets.json을 따로 읽어요
(봇의 기존 pokemon_data.EVOLUTION 등은 안 건드림 - 다른 기능에 영향 없게).
roll_iv/roll_nature/STAT_KEYS는 종에 안 무관한 로직이라 봇 기존 pokemon_data.py 걸 그대로 써요."""
import json
import os
import random

from utils.pokemon_data import STAT_KEYS, roll_iv, roll_nature
from utils.gender_data import roll_gender
from utils.egg_group_data import NO_EGGS_GROUP, get_egg_groups, get_egg_moves, get_hatch_counter

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

DITTO_SPECIES = "메타몽"
TICK_SCALE = 5
EGG_FORM_TICKS = 10
BREEDING_HIDDEN_ABILITY_CHANCE = 0.6
HATCH_SPEED_ABILITIES = {"불꽃몸", "용암갑옷"}


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else {}
    except (json.JSONDecodeError, OSError):
        return {}


_FULL_EVOLUTION = _load_json(os.path.join(DATA_DIR, "full_evolution.json"))
_FULL_ABILITIES = _load_json(os.path.join(DATA_DIR, "full_abilities.json"))
_FULL_LEARNSETS = _load_json(os.path.join(DATA_DIR, "full_learnsets.json"))

_NAME_TO_ROOT = {
    member: root
    for root, family in _FULL_EVOLUTION.items()
    for member in family.get("family", [])
    if not member.startswith("__")
}


def _family_names(species_name: str) -> list[str]:
    root = species_name if species_name in _FULL_EVOLUTION else _NAME_TO_ROOT.get(species_name, species_name)
    family = _FULL_EVOLUTION.get(root, {}).get("family")
    return family if family else [species_name]


def _ability_pool(species_name: str) -> dict:
    return _FULL_ABILITIES.get(species_name, {"normal": [], "hidden": None})


def _roll_ability(species_name: str, hidden_chance: float = 0.005) -> str:
    pool = _ability_pool(species_name)
    normal = pool.get("normal") or []
    hidden = pool.get("hidden")
    if hidden and random.random() < hidden_chance:
        return hidden
    if normal:
        return random.choice(normal)
    if hidden:
        return hidden
    return "미확인"


def _known_moves_at_level(species_name: str, level: int) -> list[str]:
    learnset = _FULL_LEARNSETS.get(species_name, {})
    known_moves = []
    for lvl in sorted((int(k) for k in learnset.keys()), reverse=True):
        if lvl > level:
            continue
        for move in learnset[str(lvl)]:
            if move not in known_moves:
                known_moves.append(move)
        if len(known_moves) >= 4:
            break
    return known_moves[:4] or learnset.get("1", [])[:4]


def _slot_source_key(source: dict) -> str:
    return "main" if source.get("type") == "main" else f"bag:{source.get('id')}"


def is_deposited(trainer: dict, source: dict) -> bool:
    key = _slot_source_key(source)
    slots = trainer.get("daycare", {}).get("slots", [None, None])
    return any(s is not None and s["sourceKey"] == key for s in slots)


def check_compatibility(slot0: dict, slot1: dict) -> tuple[bool, str | None]:
    groups0, groups1 = set(slot0["eggGroups"]), set(slot1["eggGroups"])
    if NO_EGGS_GROUP in groups0 or NO_EGGS_GROUP in groups1:
        return False, "이 포켓몬은 알을 낳을 수 없어요."

    is_ditto0, is_ditto1 = slot0["species"] == DITTO_SPECIES, slot1["species"] == DITTO_SPECIES
    if is_ditto0 and is_ditto1:
        return False, "메타몽끼리는 알을 낳을 수 없어요."
    if is_ditto0 or is_ditto1:
        return True, None

    if not (groups0 & groups1):
        return False, "이 둘은 알그룹이 달라서 궁합이 안 맞아요."
    g0, g1 = slot0.get("gender"), slot1.get("gender")
    if not g0 or not g1 or g0 == g1:
        return False, "암컷/수컷이 짝을 이뤄야 알을 낳을 수 있어요."
    return True, None


def _inherit_ability(donor_ability: str | None, offspring_species: str) -> str:
    if not donor_ability:
        return _roll_ability(offspring_species)
    pool = _ability_pool(offspring_species)
    if donor_ability == pool.get("hidden"):
        if random.random() < BREEDING_HIDDEN_ABILITY_CHANCE:
            return donor_ability
        return _roll_ability(offspring_species, hidden_chance=0)
    if donor_ability in (pool.get("normal") or []):
        return donor_ability
    return _roll_ability(offspring_species)


def _inherit_moves(offspring_species: str, father_moves: list[str]) -> list[str]:
    egg_move_pool = set(get_egg_moves(offspring_species))
    combined = [m for m in father_moves if m in egg_move_pool]
    for m in _known_moves_at_level(offspring_species, 1):
        if len(combined) >= 4:
            break
        if m not in combined:
            combined.append(m)
    return combined[:4]


def _create_egg(daycare: dict):
    slot0, slot1 = daycare["slots"]
    if slot0["species"] == DITTO_SPECIES:
        mother, father = slot1, slot0
    elif slot1["species"] == DITTO_SPECIES:
        mother, father = slot0, slot1
    elif slot0.get("gender") == "암컷":
        mother, father = slot0, slot1
    else:
        mother, father = slot1, slot0
    offspring_species = _family_names(mother["species"])[0]

    inherited_stats = random.sample(STAT_KEYS, 3)
    iv = roll_iv()
    for stat in inherited_stats:
        parent = random.choice([slot0, slot1])
        iv[stat] = parent["iv"][stat]

    everstone_parents = [s for s in (slot0, slot1) if s.get("natureLocked")]
    if everstone_parents:
        nature = mother["nature"] if mother in everstone_parents else everstone_parents[0]["nature"]
    else:
        nature = roll_nature()

    daycare["egg"] = {
        "species": offspring_species,
        "iv": iv,
        "nature": nature,
        "ability": _inherit_ability(mother.get("ability"), offspring_species),
        "gender": roll_gender(offspring_species),
        "moves": _inherit_moves(offspring_species, father.get("moves") or []),
        "ticksProgress": 0,
        "ticksNeeded": (get_hatch_counter(offspring_species) + 1) * TICK_SCALE,
    }


def _has_hatch_speed_ability(trainer: dict) -> bool:
    if not is_deposited(trainer, {"type": "main"}) and trainer.get("ability") in HATCH_SPEED_ABILITIES:
        return True
    for p in trainer.get("bag", []):
        if not p.get("inParty") or is_deposited(trainer, {"type": "bag", "id": p["id"]}):
            continue
        if p.get("ability") in HATCH_SPEED_ABILITIES:
            return True
    return False


def tick_steps(trainer: dict):
    """탐험 1회와 동일한 의미의 1틱을 진행시켜요(자체 저장은 안 함 - 호출부가 save_trainer)."""
    daycare = trainer.get("daycare")
    if not daycare:
        return
    egg = daycare.get("egg")
    if egg is None:
        slots = daycare.get("slots", [None, None])
        if slots[0] is None or slots[1] is None:
            return
        if not check_compatibility(slots[0], slots[1])[0]:
            return
        daycare["pairTicks"] = daycare.get("pairTicks", 0) + 1
        if daycare["pairTicks"] >= EGG_FORM_TICKS:
            _create_egg(daycare)
            daycare["pairTicks"] = 0
        return
    if egg["ticksProgress"] >= egg["ticksNeeded"]:
        return
    gain = 2 if _has_hatch_speed_ability(trainer) else 1
    egg["ticksProgress"] = min(egg["ticksNeeded"], egg["ticksProgress"] + gain)
