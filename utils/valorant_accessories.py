"""
발로란트 장식상점(액세서리 상점: 건버디/스프레이/플레이어카드/칭호) 아이템
UUID -> 실제 이름/이미지를 찾기 위한 캐시예요. cogs/myshop.py(개인 오늘의 상점)가 써요.

valorant-api.com은 라이엇이 공식으로 공개한 정적 게임 데이터 API라 로그인이 필요
없어요. 건버디는 스킨처럼 levels가 있어서(레벨 UUID가 실제 상점 아이템 ID), 나머지
(스프레이/플레이어카드/칭호)는 uuid 자체가 상점 아이템 ID예요.
"""
from typing import Optional

import aiohttp

BUDDIES_ENDPOINT = "https://valorant-api.com/v1/buddies?language=ko-KR"
SPRAYS_ENDPOINT = "https://valorant-api.com/v1/sprays?language=ko-KR"
PLAYERCARDS_ENDPOINT = "https://valorant-api.com/v1/playercards?language=ko-KR"
TITLES_ENDPOINT = "https://valorant-api.com/v1/titles?language=ko-KR"

_lookup: dict[str, dict] = {}  # 아이템 UUID -> {"name", "icon", "category"}


async def _fetch_data(session: aiohttp.ClientSession, url: str) -> list[dict]:
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            payload = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        return []
    return payload.get("data") or []


async def load(session: aiohttp.ClientSession) -> int:
    """장식상점 아이템 매칭 캐시를 (다시) 불러와요. 불러온 개수를 반환해요(실패하면 0)."""
    global _lookup
    lookup: dict[str, dict] = {}

    for buddy in await _fetch_data(session, BUDDIES_ENDPOINT):
        name = buddy.get("displayName")
        fallback_icon = buddy.get("displayIcon")
        for level in buddy.get("levels") or []:
            level_uuid = level.get("uuid")
            if level_uuid:
                lookup[level_uuid] = {
                    "name": name,
                    "icon": level.get("displayIcon") or fallback_icon,
                    "category": "건 버디",
                }

    for spray in await _fetch_data(session, SPRAYS_ENDPOINT):
        uuid = spray.get("uuid")
        if uuid:
            lookup[uuid] = {
                "name": spray.get("displayName"),
                "icon": spray.get("fullTransparentIcon") or spray.get("displayIcon"),
                "category": "스프레이",
            }

    for card in await _fetch_data(session, PLAYERCARDS_ENDPOINT):
        uuid = card.get("uuid")
        if uuid:
            lookup[uuid] = {
                "name": card.get("displayName"),
                "icon": card.get("largeArt") or card.get("displayIcon"),
                "category": "플레이어 카드",
            }

    for title in await _fetch_data(session, TITLES_ENDPOINT):
        uuid = title.get("uuid")
        if uuid:
            lookup[uuid] = {
                "name": title.get("displayName"),
                "icon": None,  # 칭호는 텍스트뿐이라 이미지가 없어요.
                "category": "칭호",
            }

    _lookup = lookup
    return len(lookup)


def get(item_uuid: str) -> Optional[dict]:
    """{"name", "icon", "category"} 또는 아직 캐시가 없거나 못 찾으면 None."""
    return _lookup.get(item_uuid)


def is_loaded() -> bool:
    return bool(_lookup)
