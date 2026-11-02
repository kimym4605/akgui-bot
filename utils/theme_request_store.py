"""📮 캐릭터 카드 테마 요청 보관 (2026-11-03).

🎴 캐릭터 테마는 **방장이 그림을 넣어야** 생겨요(`assets/card_themes/`). 그러니
"뭘 원하는지"를 모으는 자리가 필요해요. 여기가 그 자리예요.

## 🚨 하루 제한을 두는 이유

버튼 하나로 모달이 열리니 **장난으로 수십 개**를 넣을 수 있어요. 그러면 방장이
읽을 수가 없어서 기능 자체가 죽어요. 하루 몇 개까지만 받아요.

## ⚠️ 같은 캐릭터는 **중복으로 쌓지 않고 표를 세요**

열 명이 같은 캐릭터를 요청하면 열 줄이 아니라 "10표"로 보여야 뭘 먼저 그릴지
정할 수 있어요. 그래서 `_id`를 **정규화한 캐릭터 이름**으로 잡아요.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_requests = _db["theme_requests"]

KST = timezone(timedelta(hours=9))

# 한 사람이 하루에 넣을 수 있는 요청 수.
DAILY_LIMIT = 3


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def normalize(name: str) -> str:
    """같은 캐릭터를 한 줄로 모으려고 쓰는 키. 공백을 지우고 소문자로 맞춰요.
    ⚠️ 완벽하진 않아요("우사기" vs "うさぎ"). 사람이 보고 합치면 돼요."""
    return "".join(name.split()).lower()


def _add_sync(user_id, character: str, source: str, note: str) -> tuple[str, int]:
    """(결과, 지금 표 수). 결과는 ok / limit / dup_self."""
    uid, today = str(user_id), _today()

    used = _requests.count_documents({"voters.userId": uid, "voters.date": today})
    if used >= DAILY_LIMIT:
        return "limit", 0

    key = normalize(character)
    doc = _requests.find_one({"_id": key})
    if doc and any(v.get("userId") == uid for v in (doc.get("voters") or [])):
        return "dup_self", len(doc.get("voters") or [])

    vote = {"userId": uid, "date": today, "source": source, "note": note}
    # ⚠️ `$setOnInsert`로 **처음 적은 이름**을 보존해요. 나중 사람이 다르게 적어도
    #    표가 흩어지지 않게 하려고요(표시는 처음 이름으로 해요).
    res = _requests.find_one_and_update(
        {"_id": key},
        {
            "$setOnInsert": {"name": character.strip(), "firstAt": datetime.now(KST)},
            "$push": {"voters": vote},
        },
        upsert=True,
        return_document=True,
    )
    return "ok", len((res or {}).get("voters") or [])


def _top_sync(limit: int) -> list[dict]:
    rows = []
    for doc in _requests.find({}):
        voters = doc.get("voters") or []
        rows.append({
            "key": doc["_id"],
            "name": doc.get("name") or doc["_id"],
            "votes": len(voters),
            "sources": [v.get("source") for v in voters if v.get("source")],
            "notes": [v.get("note") for v in voters if v.get("note")],
        })
    rows.sort(key=lambda r: -r["votes"])
    return rows[:limit]


# ------------------------------------------------------------------
# 공개 API - 전부 async (동기 pymongo는 이벤트 루프를 멈춰요)
# ------------------------------------------------------------------
async def add(user_id, character: str, source: str = "", note: str = "") -> tuple[str, int]:
    return await asyncio.to_thread(_add_sync, user_id, character, source, note)


async def top(limit: int = 20) -> list[dict]:
    return await asyncio.to_thread(_top_sync, limit)
