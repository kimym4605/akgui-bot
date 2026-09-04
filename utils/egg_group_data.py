"""포켓몬(종)별 알그룹/부화 카운터/알기술 데이터예요. data/egg_groups.json, data/hatch_cycles.json,
data/egg_moves.json은 웹(악귀포켓몬 개발) 쪽 캐시를 그대로 복사해온 거예요.
키우미집(daycare_store.py)에서만 써요."""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EGG_GROUPS_PATH = os.path.join(DATA_DIR, "egg_groups.json")
HATCH_CYCLES_PATH = os.path.join(DATA_DIR, "hatch_cycles.json")
EGG_MOVES_PATH = os.path.join(DATA_DIR, "egg_moves.json")

NO_EGGS_GROUP = "no-eggs"
DITTO_GROUP = "ditto"
DEFAULT_HATCH_COUNTER = 20


def _load(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else {}
    except (json.JSONDecodeError, OSError):
        return {}


_EGG_GROUPS_CACHE = _load(EGG_GROUPS_PATH)
_HATCH_CYCLES_CACHE = _load(HATCH_CYCLES_PATH)
_EGG_MOVES_CACHE = _load(EGG_MOVES_PATH)


def get_egg_groups(species_name: str) -> list[str]:
    return _EGG_GROUPS_CACHE.get(species_name, [NO_EGGS_GROUP])


def get_hatch_counter(species_name: str) -> int:
    return _HATCH_CYCLES_CACHE.get(species_name, DEFAULT_HATCH_COUNTER)


def get_egg_moves(species_name: str) -> list[str]:
    return _EGG_MOVES_CACHE.get(species_name, [])
