import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "birthdays.json")


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


def set_birthday(user_id: int, month: int, day: int):
    data = _read_all()
    data[str(user_id)] = {"month": month, "day": day}
    _write_all(data)


def get_birthday(user_id: int):
    return _read_all().get(str(user_id))


def delete_birthday(user_id: int) -> bool:
    data = _read_all()
    key = str(user_id)
    if key not in data:
        return False
    del data[key]
    _write_all(data)
    return True


def get_all_birthdays():
    """{user_id: {"month": int, "day": int}} 형태 전체를 반환해요."""
    return _read_all()
