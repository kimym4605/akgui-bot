import json
import os

from utils import atomic_json

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "settings.json")


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


def get_setting(key: str):
    return _read_all().get(key)


def set_setting(key: str, value):
    data = _read_all()
    data[key] = value
    _write_all(data)
