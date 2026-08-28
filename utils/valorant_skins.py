"""
발로란트 스킨 레벨 UUID -> 실제 이름/이미지/등급색을 찾기 위한 캐시예요.
cogs/store.py(오늘의번들)와 cogs/myshop.py(개인 오늘의 상점)가 같이 써요.

valorant-api.com은 라이엇이 공식으로 공개한 정적 게임 데이터 API라 로그인이 필요
없고, 스킨 목록이 패치마다 갱신돼요.
"""
from typing import Optional

import aiohttp

SKINS_ENDPOINT = "https://valorant-api.com/v1/weapons/skins?language=ko-KR"
TIERS_ENDPOINT = "https://valorant-api.com/v1/contenttiers?language=ko-KR"

_lookup: dict[str, dict] = {}  # 스킨 레벨 UUID -> {"name", "icon", "tier_color"}


async def _load_tiers(session: aiohttp.ClientSession) -> dict[str, int]:
    """등급(Select/Deluxe/Premium/Exclusive/Ultra) UUID -> Discord embed색(int)."""
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
        if len(hex_color) == 6:
            tiers[tier["uuid"]] = int(hex_color, 16)
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
        print(f"⚠️ 스킨 목록을 불러오지 못했어요: {error}")
        return 0

    lookup: dict[str, dict] = {}
    for skin in payload.get("data", []):
        name = skin.get("displayName")
        fallback_icon = skin.get("displayIcon")
        tier_color = tiers.get(skin.get("contentTierUuid"))
        for level in skin.get("levels") or []:
            level_uuid = level.get("uuid")
            if level_uuid:
                lookup[level_uuid] = {
                    "name": name,
                    "icon": level.get("displayIcon") or fallback_icon,
                    "tier_color": tier_color,
                }
    _lookup = lookup
    return len(lookup)


def get(level_uuid: str) -> Optional[dict]:
    """{"name", "icon", "tier_color"} 또는 아직 캐시가 없거나 못 찾으면 None."""
    return _lookup.get(level_uuid)


def is_loaded() -> bool:
    return bool(_lookup)
