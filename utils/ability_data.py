"""포켓몬(진화 단계)별 특성 데이터예요.
scripts/build_learnsets.py가 PokeAPI에서 받아와 data/abilities.json에 캐싱해두고,
여기서는 그 파일을 읽어서 실제 게임처럼 특성을 굴려주는 역할만 해요."""
import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ABILITIES_PATH = os.path.join(DATA_DIR, "abilities.json")

HIDDEN_ABILITY_CHANCE = 0.005  # 0.5%


def _load():
    if not os.path.exists(ABILITIES_PATH):
        return {}
    try:
        with open(ABILITIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else {}
    except (json.JSONDecodeError, OSError):
        return {}


_ABILITIES_CACHE = _load()


def get_ability_pool(species_name: str) -> dict:
    """해당 포켓몬(진화 단계)의 실제 특성 풀을 반환해요.
    {"normal": [...], "hidden": str|None}. 캐시에 없으면 빈 풀을 반환해요."""
    return _ABILITIES_CACHE.get(species_name, {"normal": [], "hidden": None})


def roll_ability(species_name: str, hidden_chance: float = HIDDEN_ABILITY_CHANCE) -> str:
    """해당 포켓몬의 특성을 하나 확률적으로 뽑아요.
    숨겨진 특성이 있으면 hidden_chance 확률로 그걸, 나머지는 일반 특성 중 랜덤 1개예요."""
    pool = get_ability_pool(species_name)
    normal = pool.get("normal") or []
    hidden = pool.get("hidden")

    if hidden and random.random() < hidden_chance:
        return hidden
    if normal:
        return random.choice(normal)
    if hidden:
        return hidden
    return "미확인"  # 캐시가 아직 없을 때(스크립트 실행 전)의 기본값