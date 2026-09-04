"""
발로란트 스킨 레벨 UUID -> 실제 이름/이미지/등급색을 찾기 위한 캐시예요.
cogs/store.py(오늘의번들)와 cogs/myshop.py(개인 오늘의 상점)가 같이 써요.

valorant-api.com은 라이엇이 공식으로 공개한 정적 게임 데이터 API라 로그인이 필요
없고, 스킨 목록이 패치마다 갱신돼요.
"""
import logging
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

SKINS_ENDPOINT = "https://valorant-api.com/v1/weapons/skins?language=ko-KR"
TIERS_ENDPOINT = "https://valorant-api.com/v1/contenttiers?language=ko-KR"

_lookup: dict[str, dict] = {}  # 스킨 레벨 UUID -> {"name", "icon", "tier_color", "tier_icon"}
_names: list[str] = []  # 중복 제거한 스킨 이름 목록(위시리스트 자동완성용)


async def _load_tiers(session: aiohttp.ClientSession) -> dict[str, dict]:
    """등급(Select/Deluxe/Premium/Exclusive/Ultra) UUID -> {"color": int, "icon": str}.
    icon은 제트봇처럼 스킨 이름 앞에 붙이는 작은 다이아 모양 등급 아이콘이에요."""
    try:
        async with session.get(TIERS_ENDPOINT) as resp:
            if resp.status != 200:
                return {}
            payload = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        return {}

    tiers = {}
    for tier in payload.get("data", []):
        # highlightColor는 "RRGGBBAA" 형식의 8자리 hex예요. 앞 6자리(RGB)만 써요.
        hex_color = (tier.get("highlightColor") or "")[:6]
        color = int(hex_color, 16) if len(hex_color) == 6 else None
        tiers[tier["uuid"]] = {"color": color, "icon": tier.get("displayIcon")}
    return tiers


async def load(session: aiohttp.ClientSession) -> int:
    """스킨 매칭 캐시를 (다시) 불러와요. 불러온 개수를 반환해요(실패하면 0)."""
    global _lookup
    tiers = await _load_tiers(session)

    try:
        async with session.get(SKINS_ENDPOINT) as resp:
            if resp.status != 200:
                return 0
            payload = await resp.json(content_type=None)
    except Exception as error:  # noqa: BLE001
        log.warning(f"⚠️ 스킨 목록을 불러오지 못했어요: {error}")
        return 0

    lookup: dict[str, dict] = {}
    for skin in payload.get("data", []):
        name = skin.get("displayName")
        fallback_icon = skin.get("displayIcon")
        tier = tiers.get(skin.get("contentTierUuid")) or {}
        for level in skin.get("levels") or []:
            level_uuid = level.get("uuid")
            if level_uuid:
                lookup[level_uuid] = {
                    "name": name,
                    "icon": level.get("displayIcon") or fallback_icon,
                    "tier_color": tier.get("color"),
                    "tier_icon": tier.get("icon"),
                }
    _lookup = lookup

    # 위시리스트는 레벨 UUID가 아니라 "스킨 이름"으로 저장해요. 같은 스킨의 레벨 1~4가
    # 전부 다른 UUID라, 상점에 뜬 UUID와 등록해둔 UUID가 어긋나는 걸 피하려고요.
    global _names
    _names = sorted({entry["name"] for entry in lookup.values() if entry.get("name")})
    return len(lookup)


def get(level_uuid: str) -> Optional[dict]:
    """{"name", "icon", "tier_color"} 또는 아직 캐시가 없거나 못 찾으면 None."""
    return _lookup.get(level_uuid)


def is_loaded() -> bool:
    return bool(_lookup)


def all_names() -> list[str]:
    """등록된 모든 스킨 이름(중복 제거, 가나다/알파벳순)이에요. 위시리스트 자동완성용."""
    return _names


def search_names(query: str, limit: int = 25) -> list[str]:
    """이름에 query가 들어간 스킨 이름들을 찾아요. 앞부분이 일치하는 걸 먼저 보여줘요."""
    query = (query or "").strip().lower()
    if not query:
        return _names[:limit]

    starts, contains = [], []
    for name in _names:
        lowered = name.lower()
        if lowered.startswith(query):
            starts.append(name)
        elif query in lowered:
            contains.append(name)
        if len(starts) >= limit:
            break
    return (starts + contains)[:limit]


def icon_for_name(name: str) -> Optional[dict]:
    """스킨 이름으로 대표 정보({"name","icon","tier_color","tier_icon"})를 찾아요."""
    for entry in _lookup.values():
        if entry.get("name") == name:
            return entry
    return None
