"""개인별 알림 설정 - "미션 깨질 때마다 알림이 떠서 방해된다"는 이야기 때문에 만들었어요.

## 왜 필요한가

봇이 사람에게 먼저 말을 거는 경로가 세 개 있어요.

1. **채널 공개 알림** - 명령어·통화방 미션을 깨면 그 채널에 "🎯 @유저 미션 완료!"가 떠요.
2. **발로란트 자동 판정 DM** - 30분마다 봇이 전적을 확인해서, 깼으면 본인에게 DM을 보내요.
   게임이 끝난 직후에 오니까 **다음 판 하는 중에 오버레이 알림으로 뜨는** 게 문제였어요.
3. **위시리스트 DM** - 새벽 4시에 원하는 스킨이 떴으면 DM을 보내요.

전부 "본인에게 좋은 소식"이라 켜두는 게 기본이지만, 방해된다는 사람에겐 끌 수단이 있어야죠.

## 저장 방식

`notify_prefs` 컬렉션에 **끈 것만** 목록으로 담아요(`{_id: "123", off: ["mission_dm"]}`).
켠 걸 담지 않는 게 핵심이에요 - 그러면 나중에 알림 종류를 추가해도 **기존 유저 전원이
자동으로 켜진 상태**가 돼요(켠 목록으로 담으면 새 알림이 전원 꺼진 채로 시작해요).

문서가 아예 없는 사람 = 아무것도 안 끈 사람이라, 설정을 한 번도 안 건드리면 쓰기도 안 일어나요.
"""
import asyncio
import logging

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_prefs = _db["notify_prefs"]

# 알림 종류. 여기에 한 줄 추가하면 `/알림설정` 버튼도 같이 늘어나요(전원 켜진 상태로 시작).
NOTIFY_KINDS: dict[str, dict] = {
    "mission_channel": {
        "emoji": "💬",
        "title": "채널 미션 완료 알림",
        "desc": "명령어·통화방 미션을 깼을 때 그 채널에 뜨는 축하 메시지예요.",
    },
    "mission_dm": {
        "emoji": "🎯",
        "title": "발로란트 미션 완료 DM",
        "desc": "봇이 전적을 대신 확인해서 미션을 깼을 때 보내는 DM이에요. "
                "게임 중에 알림이 떠서 방해되면 꺼두세요.",
    },
    "wishlist_dm": {
        "emoji": "⭐",
        "title": "위시리스트 DM",
        "desc": "새벽 4시에 위시리스트 스킨이 상점에 떴으면 알려주는 DM이에요.",
    },
    "match_feed": {
        "emoji": "🔔",
        "title": "경기 결과 자동 공개",
        "desc": "발로란트 경기가 끝나면 전적 카드를 채널에 올려요. "
                "내 전적을 공개하고 싶지 않으면 꺼두세요.",
    },
}


def _uid(user_id) -> str:
    return str(user_id)


def _off_keys_sync(user_id) -> set[str]:
    doc = _prefs.find_one({"_id": _uid(user_id)}, {"off": 1})
    return set((doc or {}).get("off") or [])


def _set_enabled_sync(user_id, key: str, enabled: bool):
    uid = _uid(user_id)
    if enabled:
        # 켜는 건 "끈 목록에서 빼기". 문서가 없으면 애초에 켜진 상태라 만들 필요도 없어요.
        _prefs.update_one({"_id": uid}, {"$pull": {"off": key}})
    else:
        _prefs.update_one({"_id": uid}, {"$addToSet": {"off": key}}, upsert=True)


# ------------------------------------------------------------------
# 여기부터 async (동기 pymongo를 그대로 부르면 이벤트 루프가 멈춰요 - 2026-09-04 먹통 사고)
# ------------------------------------------------------------------
async def is_enabled(user_id, key: str) -> bool:
    """이 알림을 보내도 되는지. 설정을 한 번도 안 건드린 사람은 전부 True예요.

    ⚠️ 조회가 실패하면 **보내는 쪽으로** 기울여요. 알림 하나 더 가는 건 불편이지만,
    DB가 잠깐 흔들렸다고 코인 지급 안내가 사라지면 "안 받았는데요"가 돼요."""
    try:
        return key not in await asyncio.to_thread(_off_keys_sync, user_id)
    except Exception:  # noqa: BLE001
        log.warning("알림 설정 조회 실패 - 보내는 쪽으로 처리해요 (user=%s key=%s)", user_id, key,
                    exc_info=True)
        return True


async def get_all(user_id) -> dict[str, bool]:
    """`/알림설정` 화면용. 알림 종류 전부에 대해 켜짐/꺼짐을 돌려줘요."""
    off = await asyncio.to_thread(_off_keys_sync, user_id)
    return {key: key not in off for key in NOTIFY_KINDS}


async def set_enabled(user_id, key: str, enabled: bool):
    await asyncio.to_thread(_set_enabled_sync, user_id, key, enabled)
