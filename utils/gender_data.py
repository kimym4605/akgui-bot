"""포켓몬(종)별 성별 데이터예요. data/gender_rates.json은 웹(악귀포켓몬 개발) 쪽 캐시를 그대로
복사해온 거예요(PokeAPI의 pokemon-species.gender_rate; -1=성별 없음, 0~8=암컷일 확률이 n/8).
키우미집(daycare_store.py)의 알 성별 결정에만 써요."""
import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GENDER_RATES_PATH = os.path.join(DATA_DIR, "gender_rates.json")


def _load():
    if not os.path.exists(GENDER_RATES_PATH):
        return {}
    try:
        with open(GENDER_RATES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else {}
    except (json.JSONDecodeError, OSError):
        return {}


_GENDER_RATES_CACHE = _load()


def roll_gender(species_name: str) -> str | None:
    rate = _GENDER_RATES_CACHE.get(species_name)
    if rate is None or rate < 0:
        return None
    return "암컷" if random.randint(0, 7) < rate else "수컷"
