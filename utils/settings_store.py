import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "settings.json")


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


def get_setting(key: str):
    return _read_all().get(key)


def set_setting(key: str, value):
    data = _read_all()
    data[key] = value
    _write_all(data)
