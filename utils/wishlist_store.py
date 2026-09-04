"""
/오상 위시리스트 저장소예요.

유저가 "이 스킨 뜨면 알려줘"라고 등록해둔 스킨 이름들을 담아둬요. 매일 상점이 갱신되면
cogs/myshop.py가 쿠키를 등록해둔 유저들의 상점을 대신 조회해서, 위시리스트에 있는 스킨이
떴으면 DM으로 알려줘요.

레벨 UUID가 아니라 **스킨 이름**으로 저장해요. 같은 스킨도 레벨 1~4가 전부 다른 UUID라
상점에 뜬 UUID와 등록해둔 UUID가 어긋날 수 있어서, 이름으로 맞추는 게 안전해요.

민감 정보가 아니라(쿠키와 달리) 암호화하지 않고 그대로 저장해요.

저장 형태:
  {"<discord_id>": {"skins": ["아라크니드 팬텀", ...], "last_notified": "2026-09-02"}}
"""
import json

from utils import atomic_json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "valorant_wishlist.json"

MAX_ITEMS = 20  # 한 사람이 등록할 수 있는 최대 개수예요.


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


def get_skins(discord_id: int) -> list[str]:
    entry = _load().get(str(discord_id)) or {}
    return list(entry.get("skins") or [])


def add_skin(discord_id: int, skin_name: str) -> tuple[bool, str]:
    """(성공여부, 안내메시지)를 돌려줘요."""
    data = _load()
    key = str(discord_id)
    entry = data.setdefault(key, {"skins": [], "last_notified": ""})
    skins = entry.setdefault("skins", [])

    if skin_name in skins:
        return False, f"**{skin_name}** 은(는) 이미 위시리스트에 있어요."
    if len(skins) >= MAX_ITEMS:
        return False, f"위시리스트는 최대 {MAX_ITEMS}개까지만 등록할 수 있어요. 먼저 몇 개 지워주세요."

    skins.append(skin_name)
    _save(data)
    return True, f"✅ **{skin_name}** 을(를) 위시리스트에 담았어요. ({len(skins)}/{MAX_ITEMS})"


def remove_skin(discord_id: int, skin_name: str) -> tuple[bool, str]:
    data = _load()
    entry = data.get(str(discord_id)) or {}
    skins = entry.get("skins") or []

    if skin_name not in skins:
        return False, f"**{skin_name}** 은(는) 위시리스트에 없어요."

    skins.remove(skin_name)
    _save(data)
    return True, f"🗑️ **{skin_name}** 을(를) 위시리스트에서 뺐어요. ({len(skins)}/{MAX_ITEMS})"


def clear(discord_id: int) -> int:
    """전부 비우고, 지운 개수를 돌려줘요."""
    data = _load()
    entry = data.get(str(discord_id)) or {}
    count = len(entry.get("skins") or [])
    if count:
        entry["skins"] = []
        _save(data)
    return count


def all_watchers() -> dict[int, list[str]]:
    """위시리스트가 비어있지 않은 유저만 {discord_id: [스킨이름...]}으로 돌려줘요."""
    result = {}
    for key, entry in _load().items():
        skins = (entry or {}).get("skins") or []
        if skins:
            try:
                result[int(key)] = list(skins)
            except ValueError:
                continue
    return result


def was_notified_today(discord_id: int, today: str) -> bool:
    """같은 날 두 번 알림이 가는 걸 막아요(봇 재시작 등으로 루프가 두 번 도는 경우 대비)."""
    entry = _load().get(str(discord_id)) or {}
    return entry.get("last_notified") == today


def mark_notified(discord_id: int, today: str):
    data = _load()
    entry = data.setdefault(str(discord_id), {"skins": [], "last_notified": ""})
    entry["last_notified"] = today
    _save(data)


def set_dm_blocked(discord_id: int, blocked: bool):
    """DM이 막혀서 알림을 못 보냈는지 기록해둬요.

    DM을 막아둔 유저는 알림이 영영 안 오는데도 본인은 그 사실을 모르고, 실패는 서버 로그에만
    남아요. 그래서 여기에 표시해뒀다가 /위시리스트 목록·추가 때 본인에게 알려줘요."""
    data = _load()
    entry = data.setdefault(str(discord_id), {"skins": [], "last_notified": ""})
    if blocked:
        entry["dm_blocked"] = True
    else:
        entry.pop("dm_blocked", None)
    _save(data)


def is_dm_blocked(discord_id: int) -> bool:
    entry = _load().get(str(discord_id)) or {}
    return bool(entry.get("dm_blocked"))
