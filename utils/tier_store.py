import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "tiers.json")


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _read_all():
    _ensure_file()
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# 이 파일은 나중에 실제 데이터베이스(SQLite 등)로 손쉽게 교체할 수 있도록
# get_tier / set_tier 함수 형태로 감싸뒀어요. 호출하는 쪽(cogs/tier.py)은
# 내부 저장 방식이 JSON이든 DB든 신경 쓸 필요가 없어요.
def get_tier(user_id: int):
    return _read_all().get(str(user_id))


def set_tier(user_id: int, tier: str):
    data = _read_all()
    data[str(user_id)] = tier
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
