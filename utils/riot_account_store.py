"""
디스코드 유저 <-> 본인 라이엇 계정(닉네임#태그) 연결 정보를 저장하는 저장소예요.

이게 필요한 이유: /전적으로 아무 닉네임이나 조회해도 티어 역할이 "조회한 사람"에게
그대로 붙어버리면, 남의 계정을 검색해서 엉뚱한 티어 역할을 받아가는 악용이 가능해져요.
그래서 "본인이 미리 등록해둔 계정을 조회할 때만" 역할이 갱신되도록, 등록 여부를 여기서 관리해요.
"""
import json
from pathlib import Path
from typing import Optional, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "riot_accounts.json"


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


def set_account(discord_id: int, name: str, tag: str):
    data = _load()
    data[str(discord_id)] = {"name": name, "tag": tag}
    _save(data)


def get_account(discord_id: int) -> Optional[Tuple[str, str]]:
    """등록된 (닉네임, 태그)를 반환해요. 없으면 None."""
    data = _load()
    entry = data.get(str(discord_id))
    if not entry:
        return None
    return entry["name"], entry["tag"]


def delete_account(discord_id: int) -> bool:
    data = _load()
    if str(discord_id) in data:
        del data[str(discord_id)]
        _save(data)
        return True
    return False


def is_matching_account(discord_id: int, name: str, tag: str) -> bool:
    """이 유저가 등록해둔 계정과 (name, tag)가 같은 계정인지 (대소문자 무시) 확인해요."""
    account = get_account(discord_id)
    if account is None:
        return False
    reg_name, reg_tag = account
    return reg_name.lower() == name.lower() and reg_tag.lower() == tag.lower()