"""
/오상에서 "쿠키 등록"으로 저장하는, 디스코드 유저 <-> 라이엇 로그인 세션(쿠키) 저장소예요.

비밀번호는 절대 저장하지 않고, 이미 로그인된 세션을 이어갈 수 있는 쿠키(ssid) 값만
암호화(utils/crypto.py)해서 저장해요. 유저가 매번 로그인하는 번거로움을 줄이려고
선택적으로 쓰는 기능이라, 저장 자체를 원하지 않으면 그냥 매번 로그인+URL 붙여넣기만
쓰면 돼요. 그래도 "봇 서버가 뚫리면 이 쿠키가 유출될 수 있다"는 리스크는 남아있어요.
"""
import json
from pathlib import Path
from typing import Optional

from utils import crypto

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "riot_sessions.json"


def _load() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_session(discord_id: int, cookie_header: str):
    data = _load()
    data[str(discord_id)] = {"cookie": crypto.encrypt(cookie_header)}
    _save(data)


def get_session(discord_id: int) -> Optional[str]:
    """복호화된 cookie_header 문자열을 반환해요. 없거나 복호화 실패하면 None."""
    data = _load()
    entry = data.get(str(discord_id))
    if not entry:
        return None
    return crypto.decrypt(entry["cookie"])


def delete_session(discord_id: int) -> bool:
    data = _load()
    if str(discord_id) in data:
        del data[str(discord_id)]
        _save(data)
        return True
    return False


def has_session(discord_id: int) -> bool:
    return str(discord_id) in _load()


def all_discord_ids() -> list[int]:
    return [int(k) for k in _load().keys()]
