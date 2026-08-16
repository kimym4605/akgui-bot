"""기술(스킬) 정적 데이터예요.
실제 데이터는 scripts/build_learnsets.py로 PokeAPI에서 미리 받아와
data/learnsets.json, data/moves.json에 캐싱해두고, 여기서는 그 파일을 읽기만 해요."""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LEARNSETS_PATH = os.path.join(DATA_DIR, "learnsets.json")
MOVES_PATH = os.path.join(DATA_DIR, "moves.json")

# 캐시 파일이 없을 때(스크립트를 아직 안 돌렸을 때) 쓰는 최소 기본 기술표예요.
DEFAULT_LEARNSET = {
    "1": ["몸통박치기", "울음소리"],
    "10": ["할퀴기"],
    "20": ["돌진"],
    "35": ["몸통날리기"],
}

_FALLBACK_MOVES = {
    "몸통박치기": {"type": "노말", "power": 40, "accuracy": 100, "category": "물리", "pp": 35},
    "할퀴기": {"type": "노말", "power": 40, "accuracy": 100, "category": "물리", "pp": 35},
    "울음소리": {"type": "노말", "power": 0, "accuracy": 100, "category": "변화", "pp": 40},
    "돌진": {"type": "노말", "power": 90, "accuracy": 85, "category": "물리", "pp": 20},
    "몸통날리기": {"type": "노말", "power": 85, "accuracy": 100, "category": "물리", "pp": 15},
}


def _load_json(path: str, fallback: dict) -> dict:
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else fallback
    except (json.JSONDecodeError, OSError):
        return fallback


_LEARNSETS_CACHE = _load_json(LEARNSETS_PATH, {})
MOVES = _load_json(MOVES_PATH, _FALLBACK_MOVES)


def get_learnset(base_name: str) -> dict:
    """해당 계열의 실제(PokeAPI 기준) 기술표를 반환해요. 캐시에 없으면 기본 기술표를 써요."""
    return _LEARNSETS_CACHE.get(base_name, DEFAULT_LEARNSET)