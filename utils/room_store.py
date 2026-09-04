"""
즉석 생성형 통화방(/방만들기) 소유자 정보를 파일에 저장하는 저장소예요.

만든 방의 "채널ID <-> {방장ID, 종류}" 관계를 여기에 저장해둬서,
봇이 재시작돼도 누가 어느 방의 방장인지, 어떤 종류의 방인지 잊어버리지 않게 해요.
"""
import json

from utils import atomic_json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "dynamic_rooms.json"


def _load() -> dict:
    """{채널ID(str): {"owner_id": int, "kind": str}} 형태로 반환해요."""
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    # 원자적 쓰기 - 도중에 죽어도 기존 파일이 안 깨져요. (utils/atomic_json.py 주석 참고)
    atomic_json.write_json(DATA_FILE, data)


def load_all() -> dict[int, dict]:
    """{채널ID(int): {"owner_id": int, "kind": str}} 형태로 반환해요. 봇 시작할 때 통째로 불러올 때 써요."""
    raw = _load()
    return {int(channel_id): info for channel_id, info in raw.items()}


def add_room(channel_id: int, owner_id: int, kind: str):
    data = _load()
    data[str(channel_id)] = {"owner_id": owner_id, "kind": kind}
    _save(data)


def remove_room(channel_id: int):
    data = _load()
    if str(channel_id) in data:
        del data[str(channel_id)]
        _save(data)
