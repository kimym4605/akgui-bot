"""생일 저장소.

예전에는 `data/birthdays.json`에 넣었는데 두 가지가 걸렸어요.

1. Fly 볼륨이 `data/`를 통째로 덮어써서, 이 폴더의 파일은 서버에 반영되지 않아요.
   그래서 등록된 생일을 볼 방법이 sftp로 받아보는 것뿐이었어요.
2. 악귀 매니저(가계부 웹) 달력에 생일을 띄우려면 다른 앱에서도 읽을 수 있어야 하는데,
   볼륨 안 파일은 그 앱에서 건드릴 수가 없어요.

그래서 MongoDB로 옮겼어요. 같은 Atlas를 쓰니 웹에서는 읽기만 하면 돼요.
기존 JSON은 처음 한 번 자동으로 옮겨오고, 파일은 지우지 않고 그대로 둬요(되돌릴 일이 생길 수 있으니).

⚠️ pymongo는 동기 드라이버라 이벤트 루프 위에서 그냥 부르면 안 돼요. 공개 함수를 전부 async로
두고 실제 DB 작업은 `asyncio.to_thread`로 넘겨요 (2026-09-04 먹통 사고와 같은 이유,
utils/pokemon_store.py 위쪽 주석 참고).
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from utils import atomic_json
from utils.pokemon_store import client as _client

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 웹에서도 읽는 컬렉션이라 이름을 바꾸면 악귀 매니저 달력의 생일이 사라져요.
BIRTHDAY_DB_NAME = os.getenv("MONGODB_DB_NAME", "pokemon_game")
_col = _client[BIRTHDAY_DB_NAME]["birthdays"]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "birthdays.json")


def _doc_to_entry(doc: dict) -> dict:
    return {"month": doc["month"], "day": doc["day"], "name": doc.get("name", "")}


def _set_sync(user_id: int, month: int, day: int, name: str | None):
    fields = {"month": month, "day": day, "updated_at": datetime.now(KST).isoformat()}
    if name:
        fields["name"] = name
    _col.update_one({"_id": str(user_id)}, {"$set": fields}, upsert=True)


async def set_birthday(user_id: int, month: int, day: int, name: str | None = None):
    await asyncio.to_thread(_set_sync, user_id, month, day, name)


async def get_birthday(user_id: int):
    doc = await asyncio.to_thread(_col.find_one, {"_id": str(user_id)})
    return _doc_to_entry(doc) if doc else None


def _delete_sync(user_id: int) -> bool:
    return _col.delete_one({"_id": str(user_id)}).deleted_count > 0


async def delete_birthday(user_id: int) -> bool:
    return await asyncio.to_thread(_delete_sync, user_id)


def _all_sync() -> dict:
    return {doc["_id"]: _doc_to_entry(doc) for doc in _col.find({})}


async def get_all_birthdays() -> dict:
    """{user_id: {"month": int, "day": int, "name": str}} 형태 전체를 돌려줘요."""
    return await asyncio.to_thread(_all_sync)


def _update_name_sync(user_id: str, name: str):
    _col.update_one({"_id": user_id}, {"$set": {"name": name}})


async def update_name(user_id: str, name: str):
    """서버에서 읽어온 표시 이름을 채워둬요. 웹 달력이 이 이름을 그대로 써요."""
    await asyncio.to_thread(_update_name_sync, user_id, name)


def _migrate_sync() -> int:
    """예전 JSON에 있고 DB에 아직 없는 것만 옮겨요. 이미 옮긴 뒤엔 아무 일도 안 해요."""
    if not os.path.exists(FILE_PATH):
        return 0

    data = atomic_json.read_json(FILE_PATH, {})
    if not data:
        return 0

    moved = 0
    for user_id, entry in data.items():
        month, day = entry.get("month"), entry.get("day")
        if not month or not day:
            continue
        # upsert가 아니라 "없을 때만" 넣어요. DB 쪽이 최신이면 덮어쓰면 안 되니까요.
        result = _col.update_one(
            {"_id": str(user_id)},
            {"$setOnInsert": {"month": month, "day": day, "migrated_at": datetime.now(KST).isoformat()}},
            upsert=True,
        )
        if result.upserted_id is not None:
            moved += 1
    return moved


async def migrate_from_json() -> int:
    try:
        moved = await asyncio.to_thread(_migrate_sync)
        if moved:
            log.info(f"🎂 예전 파일에 있던 생일 {moved}건을 DB로 옮겼어요.")
        return moved
    except Exception as e:
        # 옮기기에 실패해도 봇은 떠야 해요. 다음 재시작 때 다시 시도해요.
        log.warning(f"⚠️ 생일 데이터를 옮기지 못했어요: {e}")
        return 0
