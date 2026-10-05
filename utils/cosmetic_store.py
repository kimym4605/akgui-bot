"""꾸미기 아이템 보관 - 지금은 프로필 카드 테마만 담아요. (`/악귀상점`에서 사요)

## 왜 "보유 목록 + 선택" 두 개인가

테마는 **사면 영구히 남고**, 그중 하나를 골라서 쓰는 식이에요. 그래서 산 것들(`themes`)과
지금 쓰는 것(`theme`)을 따로 담아요. 이렇게 하면 테마를 여러 개 모으는 사람이 생기고,
그게 코인이 계속 빠져나가는 유일한 구멍이에요(2026-10-05 기준 소비처가 칭호 하나뿐이라
add 662건 vs spend 6건이었어요 → [[project_akgui_coin_economy]]).

기본 테마는 사지 않아도 쓸 수 있어요. 문서가 없는 사람 = 기본 테마만 가진 사람이에요.
"""
import asyncio
import logging

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_cosmetics = _db["cosmetics"]

DEFAULT_THEME = "기본"


def _uid(user_id) -> str:
    return str(user_id)


def _get_sync(user_id) -> dict:
    doc = _cosmetics.find_one({"_id": _uid(user_id)}, {"themes": 1, "theme": 1}) or {}
    owned = list(doc.get("themes") or [])
    if DEFAULT_THEME not in owned:
        owned.insert(0, DEFAULT_THEME)   # 기본은 공짜라 저장하지 않아요
    return {"themes": owned, "theme": doc.get("theme") or DEFAULT_THEME}


def _grant_theme_sync(user_id, key: str) -> bool:
    """처음 사는 거면 True. 이미 갖고 있으면 False(중복 결제를 막는 자리예요).

    ⚠️ 필터에 `$ne`를 걸어서 **이미 가진 사람은 아예 안 맞게** 해요. 그러면 동시에 두 번
    들어와도 한 번만 들어가요. upsert는 켜두되 `$ne` 필터와 같이 쓰는 게 안전한 건
    `_id`가 고정이고 `$addToSet`이라 새 문서가 하나만 생기기 때문이에요."""
    res = _cosmetics.update_one(
        {"_id": _uid(user_id), "themes": {"$ne": key}},
        {"$addToSet": {"themes": key}},
        upsert=True,
    )
    return res.modified_count == 1 or res.upserted_id is not None


def _select_theme_sync(user_id, key: str) -> None:
    _cosmetics.update_one({"_id": _uid(user_id)}, {"$set": {"theme": key}}, upsert=True)


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요 - 2026-09-04 먹통 사고)
# ------------------------------------------------------------------
async def get(user_id) -> dict:
    return await asyncio.to_thread(_get_sync, user_id)


async def owned_themes(user_id) -> list[str]:
    return (await get(user_id))["themes"]


async def selected_theme(user_id) -> str:
    """프로필 카드를 그릴 때 써요. 조회가 실패하면 기본 테마로 물러나요
    (카드가 아예 안 그려지는 것보다 색이 기본인 게 낫잖아요)."""
    try:
        return (await get(user_id))["theme"]
    except Exception:  # noqa: BLE001
        log.warning("테마 조회 실패 - 기본으로 그려요 (user=%s)", user_id, exc_info=True)
        return DEFAULT_THEME


async def grant_theme(user_id, key: str) -> bool:
    return await asyncio.to_thread(_grant_theme_sync, user_id, key)


async def select_theme(user_id, key: str) -> None:
    await asyncio.to_thread(_select_theme_sync, user_id, key)
