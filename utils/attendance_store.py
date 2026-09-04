import json
import os
from datetime import date

from utils import atomic_json

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "attendance.json")


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _read_all():
    # 깨진 파일이 이미 남아있어도 빈 dict로 살아나요(예전엔 여기서 그대로 터졌어요).
    return atomic_json.read_json(FILE_PATH, {})


def _write_all(data):
    # 원자적 쓰기 - 도중에 죽어도 기존 파일이 안 깨져요. (utils/atomic_json.py 주석 참고)
    atomic_json.write_json(FILE_PATH, data)


def check_in(user_id: int):
    """오늘의 출석체크를 시도해요.
    이미 오늘 출석했다면 (False, 누적횟수, 연속일수),
    새로 출석했다면 (True, 누적횟수, 연속일수)를 반환해요."""
    data = _read_all()
    key = str(user_id)
    record = data.get(key, {"count": 0, "last_date": None, "streak": 0})
    today = date.today()
    today_iso = today.isoformat()

    if record.get("last_date") == today_iso:
        return False, record["count"], record.get("streak", 0)

    last_date_str = record.get("last_date")
    if last_date_str:
        last_date = date.fromisoformat(last_date_str)
        if (today - last_date).days == 1:
            record["streak"] = record.get("streak", 0) + 1
        else:
            record["streak"] = 1
    else:
        record["streak"] = 1

    record["count"] += 1
    record["last_date"] = today_iso
    data[key] = record
    _write_all(data)
    return True, record["count"], record["streak"]


def get_leaderboard(limit: int = 10):
    data = _read_all()
    items = [(user_id, record["count"]) for user_id, record in data.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items[:limit]


def reset_user(user_id: int) -> bool:
    """해당 유저의 출석 기록을 완전히 삭제해요. 기록이 있었으면 True, 없었으면 False."""
    data = _read_all()
    key = str(user_id)
    if key in data:
        del data[key]
        _write_all(data)
        return True
    return False