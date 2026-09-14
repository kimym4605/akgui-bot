"""
즉석 생성형 통화방(/방만들기) 소유자 정보를 파일에 저장하는 저장소예요.

만든 방의 "채널ID <-> {방장ID, 종류, 입장시 뮤트 여부}" 관계를 여기에 저장해둬서,
봇이 재시작돼도 누가 어느 방의 방장인지, 어떤 종류의 방인지 잊어버리지 않게 해요.
"""
import json

from utils import atomic_json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "dynamic_rooms.json"


def _load() -> dict:
    """{채널ID(str): {"owner_id": int, "kind": str, "mute_on_join": bool}} 형태로 반환해요."""
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
    """{채널ID(int): {"owner_id": int, "kind": str, "mute_on_join": bool}} 형태로 반환해요.
    봇 시작할 때 통째로 불러올 때 써요.

    `mute_on_join`은 나중에 추가된 필드라, 그 전에 만들어진 방 기록에는 아예 없을 수 있어요.
    읽는 쪽에서 `.get("mute_on_join", False)`로 받아야 해요."""
    raw = _load()
    return {int(channel_id): info for channel_id, info in raw.items()}


def add_room(channel_id: int, owner_id: int, kind: str, mute_on_join: bool = False):
    data = _load()
    data[str(channel_id)] = {"owner_id": owner_id, "kind": kind, "mute_on_join": mute_on_join}
    _save(data)


def remove_room(channel_id: int):
    data = _load()
    if str(channel_id) in data:
        del data[str(channel_id)]
        _save(data)


def set_muted(channel_id: int, member_ids: list[int]):
    """이 방에서 **봇이 서버 음소거를 걸어둔 사람들**을 기록해요.

    ⚠️ 왜 굳이 기록해두는가: 서버 음소거는 채널 권한과 달리 **서버 전체에 남는 상태**라,
    방을 나가면 우리가 직접 풀어줘야 다른 통화방에서 말할 수 있어요. 그런데 "음소거된 사람을
    보이는 대로 풀어주는" 식으로 짜면, 운영진이 징계로 걸어둔 음소거까지 봇이 풀어버려요.
    그래서 **봇이 건 것만** 여기에 적어두고, 그 사람만 풀어줘요.
    """
    data = _load()
    room = data.get(str(channel_id))
    if room is None:
        return
    room["muted"] = sorted(set(member_ids))
    _save(data)


def get_muted(channel_id: int) -> list[int]:
    return list((_load().get(str(channel_id)) or {}).get("muted") or [])
