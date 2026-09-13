"""
/오상에서 "쿠키 등록"으로 저장하는, 디스코드 유저 <-> 라이엇 로그인 세션(쿠키) 저장소예요.

비밀번호는 절대 저장하지 않고, 이미 로그인된 세션을 이어갈 수 있는 쿠키(ssid) 값만
암호화(utils/crypto.py)해서 저장해요. 유저가 매번 로그인하는 번거로움을 줄이려고
선택적으로 쓰는 기능이라, 저장 자체를 원하지 않으면 그냥 매번 로그인+URL 붙여넣기만
쓰면 돼요. 그래도 "봇 서버가 뚫리면 이 쿠키가 유출될 수 있다"는 리스크는 남아있어요.

## 한 사람이 계정 여러 개(본계/부계)를 등록할 수 있어요

예전엔 유저 한 명당 쿠키 하나만 저장했어요. 부계정을 등록하면 본계 쿠키를 덮어써버려서,
번갈아 보려면 매번 다시 등록해야 했어요. 그래서 슬롯 여러 개를 두는 구조로 바꿨어요.

저장 형태:

    {
      "<디스코드ID>": {
        "accounts": [
          {"key": "3f2a91c4", "riot_id": "홍길동#KR1", "cookie": "<암호문>", "added_at": "..."},
          ...
        ],
        "last_used": "3f2a91c4"
      }
    }

`key`는 슬롯을 가리키는 짧은 임의 문자열이에요. 라이엇 ID를 그대로 키로 쓰지 않는 이유는
두 가지예요. 등록 시점에 라이엇 ID를 못 읽는 경우가 있고(그래도 쿠키는 멀쩡해요),
사람이 라이엇 ID를 바꾸면 키가 통째로 달라져서 캐시·기본계정 지정이 다 끊기거든요.

**옛 형태(`{"<디스코드ID>": {"cookie": "<암호문>"}}`)도 그대로 읽을 수 있어요.** 읽을 때
슬롯 하나짜리로 변환해서 다루고(`_normalize`), 다음 저장 때 새 형태로 기록돼요. 그래서
따로 마이그레이션 스크립트를 돌릴 필요가 없어요.
"""
import json
import secrets
from datetime import datetime, timezone

from utils import atomic_json
from pathlib import Path
from typing import Optional

from utils import crypto

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "riot_sessions.json"

# 한 사람이 등록할 수 있는 계정 수예요. 새벽 4시 갱신 루프와 위시리스트 확인이 등록된
# 계정 수만큼 라이엇을 왕복하니까(프록시 경유라 왕복 한 번이 비싸요) 무제한은 곤란해요.
MAX_ACCOUNTS = 3


def _load() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    # 원자적 쓰기 - 도중에 죽어도 기존 파일이 안 깨져요. (utils/atomic_json.py 주석 참고)
    atomic_json.write_json(DATA_FILE, data)


# 옛 형태에서 넘어온 슬롯이 갖는 키예요. **반드시 고정값이어야 해요.**
# 여기서 랜덤 키를 만들면 파일을 읽을 때마다 키가 달라져요. 그러면 `/오상`이 방금 받아온
# 키로 다시 조회할 때 그런 계정이 없다고 나와서, 옛 유저의 조회가 통째로 깨져요.
# 새로 만드는 키는 8자리 16진수라 이 값과 겹칠 일이 없어요.
LEGACY_KEY = "legacy"


def _normalize(entry: dict | None) -> dict:
    """옛 형태({"cookie": ...})든 새 형태든 항상 새 형태로 돌려줘요."""
    if not entry:
        return {"accounts": [], "last_used": None}
    if "accounts" in entry:
        return {"accounts": entry.get("accounts") or [], "last_used": entry.get("last_used")}
    # 옛 형태: 쿠키 하나짜리
    cookie = entry.get("cookie")
    if not cookie:
        return {"accounts": [], "last_used": None}
    return {
        "accounts": [{"key": LEGACY_KEY, "riot_id": "", "cookie": cookie, "added_at": ""}],
        "last_used": None,
    }


def _new_key(existing: list[dict]) -> str:
    taken = {account.get("key") for account in existing}
    while True:
        key = secrets.token_hex(4)
        if key not in taken:
            return key


def _entry(data: dict, discord_id: int) -> dict:
    return _normalize(data.get(str(discord_id)))


def _pick(entry: dict, account_key: Optional[str]) -> Optional[dict]:
    """account_key가 없으면 '기본 계정'(마지막으로 쓴 계정, 없으면 맨 처음 등록한 계정)."""
    accounts = entry["accounts"]
    if not accounts:
        return None
    if account_key:
        for account in accounts:
            if account.get("key") == account_key:
                return account
        return None
    last_used = entry.get("last_used")
    if last_used:
        for account in accounts:
            if account.get("key") == last_used:
                return account
    return accounts[0]


def _label(account: dict, index: int) -> str:
    return account.get("riot_id") or f"계정 {index + 1}"


# ── 조회 ────────────────────────────────────────────────────────────────────

def list_accounts(discord_id: int) -> list[dict]:
    """등록된 계정들을 등록 순서대로 돌려줘요. 쿠키 값은 빼고 표시용 정보만 담아요.
    각 항목: {"key", "riot_id", "label", "added_at", "is_default"}"""
    entry = _entry(_load(), discord_id)
    default = _pick(entry, None)
    default_key = default.get("key") if default else None
    return [
        {
            "key": account.get("key", ""),
            "riot_id": account.get("riot_id") or "",
            "label": _label(account, index),
            "added_at": account.get("added_at") or "",
            "is_default": account.get("key") == default_key,
        }
        for index, account in enumerate(entry["accounts"])
    ]


def account_count(discord_id: int) -> int:
    return len(_entry(_load(), discord_id)["accounts"])


def default_account_key(discord_id: int) -> Optional[str]:
    account = _pick(_entry(_load(), discord_id), None)
    return account.get("key") if account else None


def get_session(discord_id: int, account_key: Optional[str] = None) -> Optional[str]:
    """복호화된 cookie_header 문자열을 반환해요. 없거나 복호화 실패하면 None.
    account_key를 안 주면 기본 계정(마지막으로 쓴 계정)을 써요."""
    account = _pick(_entry(_load(), discord_id), account_key)
    if not account:
        return None
    return crypto.decrypt(account["cookie"])


def has_session(discord_id: int) -> bool:
    return bool(_entry(_load(), discord_id)["accounts"])


def all_discord_ids() -> list[int]:
    return [int(key) for key in _load().keys()]


def all_sessions() -> list[tuple[int, str, str]]:
    """(디스코드ID, 계정키, 복호화된 쿠키) 전부. 새벽 4시 갱신 루프가 써요.
    복호화에 실패한 슬롯은 조용히 건너뛰어요(어차피 쓸 수 없는 값이에요)."""
    rows = []
    for raw_id, raw_entry in _load().items():
        entry = _normalize(raw_entry)
        for account in entry["accounts"]:
            cookie = crypto.decrypt(account["cookie"])
            if cookie:
                rows.append((int(raw_id), account.get("key", ""), cookie))
    return rows


# ── 저장 ────────────────────────────────────────────────────────────────────

def save_session(
    discord_id: int,
    cookie_header: str,
    riot_id: str = "",
    account_key: Optional[str] = None,
) -> Optional[str]:
    """쿠키를 저장하고 그 슬롯의 key를 돌려줘요. 슬롯이 꽉 차서 못 넣으면 None.

    어느 슬롯에 넣을지는 이 순서로 정해요.
      1. account_key를 줬으면 그 슬롯 (이미 아는 계정을 갱신하는 경우)
      2. riot_id가 같은 슬롯이 있으면 그 슬롯 (같은 계정을 다시 등록/재인증한 경우)
      3. 새 슬롯 추가. 단 riot_id를 모르면(=어느 계정인지 특정 불가) 새로 만들지 않고
         기본 계정 슬롯을 갱신해요.

    ⚠️ 3번의 단서가 중요해요. riot_id를 모를 때 무조건 새 슬롯을 만들면, 재인증할 때마다
    같은 계정이 슬롯을 하나씩 잡아먹어서 금방 한도를 채워버려요."""
    data = _load()
    entry = _entry(data, discord_id)
    accounts = entry["accounts"]
    encrypted = crypto.encrypt(cookie_header)

    target = None
    if account_key:
        target = next((a for a in accounts if a.get("key") == account_key), None)
    if target is None and riot_id:
        target = next((a for a in accounts if a.get("riot_id") == riot_id), None)
    if target is None and not riot_id:
        target = _pick(entry, None)

    if target is None:
        if len(accounts) >= MAX_ACCOUNTS:
            return None
        target = {
            "key": _new_key(accounts),
            "riot_id": riot_id,
            "cookie": encrypted,
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        accounts.append(target)
    else:
        target["cookie"] = encrypted
        # 라이엇 ID를 나중에 알게 된 경우(옛 데이터에서 넘어온 슬롯 등) 채워줘요.
        if riot_id:
            target["riot_id"] = riot_id

    entry["last_used"] = target["key"]
    data[str(discord_id)] = entry
    _save(data)
    return target["key"]


def touch(discord_id: int, account_key: str):
    """이 계정을 '마지막으로 쓴 계정'으로 표시해요. 다음에 /오상을 그냥 부르면 이게 떠요."""
    data = _load()
    entry = _entry(data, discord_id)
    if not any(account.get("key") == account_key for account in entry["accounts"]):
        return
    if entry.get("last_used") == account_key:
        return
    entry["last_used"] = account_key
    data[str(discord_id)] = entry
    _save(data)


# ── 삭제 ────────────────────────────────────────────────────────────────────

def delete_session(discord_id: int, account_key: Optional[str] = None) -> bool:
    """계정 하나를 지워요. account_key를 안 주면 기본 계정을 지워요."""
    data = _load()
    entry = _entry(data, discord_id)
    target = _pick(entry, account_key)
    if target is None:
        return False

    entry["accounts"] = [a for a in entry["accounts"] if a.get("key") != target.get("key")]
    if entry.get("last_used") == target.get("key"):
        entry["last_used"] = None
    if entry["accounts"]:
        data[str(discord_id)] = entry
    else:
        data.pop(str(discord_id), None)
    _save(data)
    return True


def delete_all_sessions(discord_id: int) -> int:
    """등록해둔 계정을 전부 지우고, 지운 개수를 돌려줘요."""
    data = _load()
    count = len(_entry(data, discord_id)["accounts"])
    if not count:
        return 0
    data.pop(str(discord_id), None)
    _save(data)
    return count
