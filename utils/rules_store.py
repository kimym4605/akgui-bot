import json
import os

from utils import atomic_json

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "rules.json")


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _read_all():
    # 깨진 파일이 이미 남아있어도 빈 dict로 살아나요(예전엔 여기서 그대로 터졌어요).
    return atomic_json.read_json(FILE_PATH, {})


def _write_all(data):
    # 원자적 쓰기 - 도중에 죽어도 기존 파일이 안 깨져요. (utils/atomic_json.py 주석 참고)
    atomic_json.write_json(FILE_PATH, data)


def _migrate_entry(entry):
    """예전 형식들을 최신 형식으로 변환해요."""
    if isinstance(entry, list):
        return {"rules": entry, "description": [], "guidance": []}
    entry.setdefault("rules", [])
    entry.setdefault("description", [])
    entry.setdefault("guidance", [])
    return entry


def get_rules(guild_id: int) -> list[str]:
    data = _read_all()
    entry = _migrate_entry(data.get(str(guild_id), {}))
    return entry["rules"]


def set_rules(guild_id: int, rules: list[str]):
    data = _read_all()
    entry = _migrate_entry(data.get(str(guild_id), {}))
    entry["rules"] = rules
    data[str(guild_id)] = entry
    _write_all(data)


def get_description(guild_id: int) -> list[str]:
    data = _read_all()
    entry = _migrate_entry(data.get(str(guild_id), {}))
    return entry["description"]


def set_description(guild_id: int, description: list[str]):
    data = _read_all()
    entry = _migrate_entry(data.get(str(guild_id), {}))
    entry["description"] = description
    data[str(guild_id)] = entry
    _write_all(data)


def get_guidance(guild_id: int) -> list[str]:
    data = _read_all()
    entry = _migrate_entry(data.get(str(guild_id), {}))
    return entry["guidance"]


def set_guidance(guild_id: int, guidance: list[str]):
    data = _read_all()
    entry = _migrate_entry(data.get(str(guild_id), {}))
    entry["guidance"] = guidance
    data[str(guild_id)] = entry
    _write_all(data)