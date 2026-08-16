import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "rules.json")


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _read_all():
    _ensure_file()
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_all(data):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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