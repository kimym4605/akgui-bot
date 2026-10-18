"""🔔 경기 결과를 **이미 올렸는지** 기억해요. 같은 경기를 두 번 올리지 않으려고요.

## 왜 필요한가 (2026-10-18)

발로란트 미션 자동판정 루프가 30분마다 **오늘 경기 전체**를 가져와요(최근 10경기 중 오늘 것).
그 목록으로 알림을 올리면, 30분 뒤 같은 경기가 또 목록에 들어 있어서 **같은 경기를 하루에
수십 번 올리게** 돼요. 그래서 올린 `matchId`를 기억해요.

## 🚨 전부 기억하지 않아요

사람마다 최근 `KEEP` 개만 들고 있어요. 경기는 계속 쌓이는데 다 보관하면 문서가 무한히
커지고, 어차피 **오늘 경기만** 후보라서 옛 ID는 비교할 일이 없어요.

⚠️ `$push`에 `$slice: -KEEP`을 써서 **넣으면서 동시에 잘라요.** 읽고 자르고 쓰면 동시에
두 번 들어왔을 때 하나가 사라져요(코인 지갑과 같은 이유).
"""
import asyncio
import logging

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_feed = _db["match_feed"]

# 한 사람당 기억할 경기 수. 하루에 10경기를 넘기는 사람도 있어서 넉넉히 둬요.
KEEP = 30


def _uid(user_id) -> str:
    return str(user_id)


def _seen_sync(user_id) -> set[str]:
    doc = _feed.find_one({"_id": _uid(user_id)}, {"ids": 1})
    return set((doc or {}).get("ids") or [])


def _mark_sync(user_id, match_ids: list[str]) -> None:
    if not match_ids:
        return
    _feed.update_one(
        {"_id": _uid(user_id)},
        # ⚠️ 넣으면서 동시에 잘라요. 읽고-자르고-쓰면 경합에서 유실돼요.
        {"$push": {"ids": {"$each": match_ids, "$slice": -KEEP}}},
        upsert=True,
    )


def _prime_sync(user_id, match_ids: list[str]) -> bool:
    """처음 보는 사람이면 **지금 경기를 전부 '본 것'으로** 찍고 True.

    🚨 이게 없으면 기능을 켜는 순간, 등록된 모든 사람의 **오늘 경기가 한꺼번에** 쏟아져요.
    (21명 × 최대 10경기 = 200개가 넘는 메시지가 동시에 올라가요.)
    그래서 그 사람의 첫 조회 때는 올리지 않고 기준선만 잡아요."""
    doc = _feed.find_one({"_id": _uid(user_id)}, {"_id": 1})
    if doc is not None:
        return False
    _feed.update_one(
        {"_id": _uid(user_id)},
        {"$set": {"ids": match_ids[-KEEP:]}},
        upsert=True,
    )
    return True


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요)
# ------------------------------------------------------------------
async def seen(user_id) -> set[str]:
    try:
        return await asyncio.to_thread(_seen_sync, user_id)
    except Exception:  # noqa: BLE001
        # 🚨 조회 실패 시 **전부 본 것으로 간주**해요. 모르면 안 올리는 쪽이 안전해요
        #    (반대로 하면 DB가 삐끗할 때마다 같은 경기를 또 올려요).
        log.warning("경기 알림 기록 조회 실패 - 이번엔 건너뛰어요 (user=%s)", user_id)
        return _SENTINEL_ALL


async def mark(user_id, match_ids: list[str]) -> None:
    try:
        await asyncio.to_thread(_mark_sync, user_id, match_ids)
    except Exception:  # noqa: BLE001
        log.warning("경기 알림 기록 저장 실패 (user=%s)", user_id, exc_info=True)


async def prime(user_id, match_ids: list[str]) -> bool:
    """처음 보는 사람이면 기준선만 잡고 True(= 이번엔 올리지 마세요)."""
    try:
        return await asyncio.to_thread(_prime_sync, user_id, match_ids)
    except Exception:  # noqa: BLE001
        log.warning("경기 알림 기준선 설정 실패 (user=%s)", user_id, exc_info=True)
        return True  # 실패하면 안 올리는 쪽으로


class _AllSeen(frozenset):
    """`in` 검사에 항상 True를 주는 집합. 조회 실패 시 '전부 본 것'으로 쓰려고요."""

    def __contains__(self, item) -> bool:  # noqa: D105
        return True


_SENTINEL_ALL = _AllSeen()
