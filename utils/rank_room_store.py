"""
랭크방(즉석 생성형 통화방) 소유자 정보를 파일에 저장하는 저장소예요.

/랭크방 으로 만든 방의 "채널ID <-> 방장ID" 관계를 여기에 저장해둬서,
봇이 재시작돼도 누가 어느 방의 방장인지 잊어버리지 않게 해요.
"""
import json
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "rank_rooms.json"


def _load() -> dict:
    """{채널ID(str): 방장ID(int)} 형태로 반환해요."""
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all() -> dict[int, int]:
    """{채널ID(int): 방장ID(int)} 형태로 반환해요. 봇 시작할 때 통째로 불러올 때 써요."""
    raw = _load()
    return {int(channel_id): owner_id for channel_id, owner_id in raw.items()}


def add_room(channel_id: int, owner_id: int):
    data = _load()
    data[str(channel_id)] = owner_id
    _save(data)


def remove_room(channel_id: int):
    data = _load()
    if str(channel_id) in data:
        del data[str(channel_id)]
        _save(data)


def get_owner(channel_id: int) -> Optional[int]:
    data = _load()
    return data.get(str(channel_id))