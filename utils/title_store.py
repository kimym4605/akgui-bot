"""칭호(커스텀 역할) 보유 기록이에요.

누가 어떤 역할을 언제까지 갖는지만 저장해요. 역할을 실제로 만들고 지우는 건
cogs/title_shop.py가 해요.

⚠️ 만료 시각은 **UTC ISO 문자열**로 저장해요. 봇이 재시작돼도 유지돼야 하고, 로컬 시간대에
의존하면 서버 시간대가 바뀔 때 어긋나요.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_titles = _db["titles"]

TITLE_PRICE = 30       # 악귀코인 (한 달 개근 = 30개)
TITLE_DAYS = 30        # 유지 기간


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_sync(user_id) -> dict | None:
    return _titles.find_one({"_id": str(user_id)})


def _save_sync(user_id, guild_id: int, role_id: int, name: str, color: int, days: int = TITLE_DAYS) -> dict:
    """새로 사거나 연장해요. 이미 있으면 남은 기간에 이어붙여요."""
    uid = str(user_id)
    existing = _titles.find_one({"_id": uid})

    base = _now()
    if existing:
        try:
            current_end = datetime.fromisoformat(existing["expiresAt"])
            # 아직 안 끝났으면 그 끝에서부터 연장해요(남은 기간을 잃지 않게).
            base = max(base, current_end)
        except (KeyError, ValueError):
            pass

    doc = {
        "_id": uid,
        "guildId": str(guild_id),
        "roleId": str(role_id),
        "name": name,
        "color": color,
        "expiresAt": (base + timedelta(days=days)).isoformat(),
        "createdAt": _now().isoformat(),
    }
    _titles.replace_one({"_id": uid}, doc, upsert=True)
    return doc


def _delete_sync(user_id) -> bool:
    return _titles.delete_one({"_id": str(user_id)}).deleted_count == 1


def _expired_sync() -> list[dict]:
    """만료 시각이 지난 칭호들이에요."""
    now_iso = _now().isoformat()
    # ISO 8601 문자열은 사전순 비교가 시간순 비교와 같아서 $lt로 그냥 걸러져요.
    return list(_titles.find({"expiresAt": {"$lt": now_iso}}))


def _all_sync() -> list[dict]:
    return list(_titles.find({}))


def remaining_days(doc: dict) -> int:
    try:
        delta = datetime.fromisoformat(doc["expiresAt"]) - _now()
    except (KeyError, ValueError):
        return 0
    return max(0, delta.days)


# ------------------------------------------------------------------
# 공개 API - 전부 async예요 (동기 pymongo를 루프에서 직접 부르면 봇이 멈춰요)
# ------------------------------------------------------------------
async def get(user_id) -> dict | None:
    return await asyncio.to_thread(_get_sync, user_id)


async def save(user_id, guild_id: int, role_id: int, name: str, color: int, days: int = TITLE_DAYS) -> dict:
    return await asyncio.to_thread(_save_sync, user_id, guild_id, role_id, name, color, days)


async def delete(user_id) -> bool:
    return await asyncio.to_thread(_delete_sync, user_id)


async def expired() -> list[dict]:
    return await asyncio.to_thread(_expired_sync)


async def all_titles() -> list[dict]:
    return await asyncio.to_thread(_all_sync)
