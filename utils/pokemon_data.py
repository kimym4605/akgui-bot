"""1~2세대 포켓몬 데이터예요.
family/evolutions/types/baseStats/도감번호는 scripts/build_learnsets.py가 PokeAPI에서
받아와 캐싱한 data/evolution.json, data/species.json, data/name_to_id.json을 그대로 읽어요."""
import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EVOLUTION_PATH = os.path.join(DATA_DIR, "evolution.json")
SPECIES_PATH = os.path.join(DATA_DIR, "species.json")
NAME_TO_ID_PATH = os.path.join(DATA_DIR, "name_to_id.json")

DEX_ORDER = [
    "이상해씨", "이상해풀", "이상해꽃", "파이리", "리자드", "리자몽", "꼬부기", "어니부기", "거북왕",
    "캐터피", "단데기", "버터플", "뿔충이", "딱충이", "독침붕", "구구", "피죤", "피죤투", "꼬렛", "레트라",
    "깨비참", "깨비드릴조", "아보", "아보크", "피카츄", "라이츄", "모래두지", "고지", "니드런♀", "니드리나",
    "니드퀸", "니드런♂", "니드리노", "니드킹", "삐삐", "픽시", "식스테일", "나인테일", "푸린", "푸크린",
    "주뱃", "골뱃", "뚜벅쵸", "냄새꼬", "라플레시아", "파라스", "파라섹트", "콘팡", "도나리", "디그다",
    "닥트리오", "나옹", "페르시온", "고라파덕", "골덕", "망키", "성원숭", "가디", "윈디", "발챙이",
    "슈륙챙이", "강챙이", "캐이시", "윤겔라", "후딘", "알통몬", "근육몬", "괴력몬", "모다피", "우츠동",
    "우츠보트", "왕눈해", "독파리", "꼬마돌", "데구리", "딱구리", "포니타", "날쌩마", "야돈", "야도란",
    "코일", "레어코일", "파오리", "두두", "두트리오", "쥬쥬", "쥬레곤", "질퍽이", "질뻐기", "셀러",
    "파르셀", "고오스", "고우스트", "팬텀", "롱스톤", "슬리프", "슬리퍼", "크랩", "킹크랩", "찌리리공",
    "붐볼", "아라리", "나시", "탕구리", "텅구리", "시라소몬", "홍수몬", "내루미", "또가스", "또도가스",
    "뿔카노", "코뿌리", "럭키", "덩쿠리", "캥카", "쏘드라", "시드라", "콘치", "왕콘치", "별가사리",
    "아쿠스타", "마임맨", "스라크", "루주라", "에레브", "마그마", "쁘사이저", "켄타로스", "잉어킹",
    "갸라도스", "라프라스", "메타몽", "이브이", "샤미드", "쥬피썬더", "부스터", "폴리곤", "암나이트",
    "암스타", "투구", "투구푸스", "프테라", "잠만보", "프리져", "썬더", "파이어", "미뇽", "신뇽",
    "망나뇽", "뮤츠", "뮤",
]


def _load_json(path: str, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else fallback
    except (json.JSONDecodeError, OSError):
        return fallback


_FALLBACK_EVOLUTION = {
    "이상해씨": {"family": ["이상해씨", "이상해풀", "이상해꽃"], "evolutions": [
        {"trigger": "level", "level": 16, "item": None}, {"trigger": "level", "level": 32, "item": None}
    ]},
    "파이리": {"family": ["파이리", "리자드", "리자몽"], "evolutions": [
        {"trigger": "level", "level": 16, "item": None}, {"trigger": "level", "level": 36, "item": None}
    ]},
    "꼬부기": {"family": ["꼬부기", "어니부기", "거북왕"], "evolutions": [
        {"trigger": "level", "level": 16, "item": None}, {"trigger": "level", "level": 36, "item": None}
    ]},
}
_FALLBACK_BASE_STATS = {"hp": 45, "attack": 49, "defense": 49, "spAttack": 65, "spDefense": 65, "speed": 45}
_FALLBACK_TYPES = ["노말"]
_FALLBACK_NAME_TO_ID = {name: idx + 1 for idx, name in enumerate(DEX_ORDER)}

EVOLUTION = _load_json(EVOLUTION_PATH, dict(_FALLBACK_EVOLUTION))
SPECIES = _load_json(SPECIES_PATH, {})
_CACHED_NAME_TO_ID = _load_json(NAME_TO_ID_PATH, {})
NAME_TO_ID = {**_FALLBACK_NAME_TO_ID, **_CACHED_NAME_TO_ID}

EEVEE_EVOLUTIONS = ["에브이", "블래키"]
EVOLUTION["이브이"] = {
    "family": ["이브이", "__EEVEE_EVO__"],
    "evolutions": [{"trigger": "level", "level": 25, "item": None}],
}

YOGARAN_EVOLUTIONS = ["시라소몬", "홍수몬"]
EVOLUTION["요가랑"] = {
    "family": ["요가랑", "__YOGARAN_EVO__"],
    "evolutions": [{"trigger": "level", "level": 20, "item": None}],
}

BRANCH_EVOLUTIONS = {
    "__EEVEE_EVO__": EEVEE_EVOLUTIONS,
    "__YOGARAN_EVO__": YOGARAN_EVOLUTIONS,
}

STARTER_POOL = list(EVOLUTION.keys())

# 웹(악귀포켓몬)의 정식 스타팅 3종이에요. 웹 `backend/pokemon_data.py`의 CUSTOM_STARTERS와
# 반드시 같은 값이어야 해요 — 여기가 어긋나면 "스타팅 골랐는데 안 골랐다고 나옴" 버그가 나요.
#
# 이게 왜 봇에도 필요하냐면: 정식 스타팅 제도가 생기기 전에 만들어진 계정들은 메인 포켓몬이
# **랜덤으로 배정된 것**(위 STARTER_POOL에서 뽑음)이라 본인이 고른 적이 없어요.
# 웹은 이런 계정을 `needsStarterChoice`로 판별해 스타팅 재선택을 띄우는데, 봇 `/프로필`만
# 그 규칙을 몰라서 고른 적 없는 포켓몬을 계속 보여주고 있었어요. (2026-09-04 수정)
CUSTOM_STARTERS = ["까멍이", "오로리", "타누비"]

STAT_KEYS = ["hp", "attack", "defense", "spAttack", "spDefense", "speed"]

NATURES = {
    "노력": {"boost": None, "cut": None},
    "외로움": {"boost": "attack", "cut": "defense"},
    "용감": {"boost": "attack", "cut": "speed"},
    "고집": {"boost": "attack", "cut": "spAttack"},
    "개구쟁이": {"boost": "attack", "cut": "spDefense"},
    "대담": {"boost": "defense", "cut": "attack"},
    "온순": {"boost": None, "cut": None},
    "무사태평": {"boost": "defense", "cut": "speed"},
    "장난꾸러기": {"boost": "defense", "cut": "spAttack"},
    "촐랑": {"boost": "defense", "cut": "spDefense"},
    "겁쟁이": {"boost": "speed", "cut": "attack"},
    "성급": {"boost": "speed", "cut": "defense"},
    "성실": {"boost": None, "cut": None},
    "명랑": {"boost": "speed", "cut": "spAttack"},
    "천진난만": {"boost": "speed", "cut": "spDefense"},
    "조심": {"boost": "spAttack", "cut": "attack"},
    "의젓": {"boost": "spAttack", "cut": "defense"},
    "냉정": {"boost": "spAttack", "cut": "speed"},
    "수줍음": {"boost": None, "cut": None},
    "덜렁": {"boost": "spAttack", "cut": "spDefense"},
    "차분": {"boost": "spDefense", "cut": "attack"},
    "얌전": {"boost": "spDefense", "cut": "defense"},
    "건방": {"boost": "spDefense", "cut": "speed"},
    "신중": {"boost": "spDefense", "cut": "spAttack"},
    "변덕": {"boost": None, "cut": None},
}


def get_family(base_name: str) -> dict:
    # 웹에는 있지만 봇 데이터셋(현재 1세대 위주)엔 없는 종(3세대+ 등)을 대비한 안전한 기본값.
    # 진화 정보 없이 "더 이상 진화 안 함" 상태로 취급해서 /출석 등이 죽지 않게 해요.
    return EVOLUTION.get(base_name, {"family": [base_name], "evolutions": []})


def get_evolutions(base_name: str) -> list:
    return get_family(base_name).get("evolutions", [])


def get_family_names(base_name: str) -> list:
    return get_family(base_name)["family"]


def get_types(species_name: str) -> list:
    return SPECIES.get(species_name, {}).get("types", _FALLBACK_TYPES)


def get_base_stats(species_name: str) -> dict:
    return SPECIES.get(species_name, {}).get("baseStats", _FALLBACK_BASE_STATS)


def roll_iv() -> dict:
    return {key: random.randint(0, 31) for key in STAT_KEYS}


def roll_nature() -> str:
    return random.choice(list(NATURES.keys()))


def exp_needed(level: int) -> int:
    return 100 + (level - 1) * 50


def calculate_stats(species_name: str, level: int, iv: dict, nature: str) -> dict:
    base = get_base_stats(species_name)
    stats = {}
    for key in STAT_KEYS:
        b, v = base[key], iv[key]
        if key == "hp":
            stats[key] = (2 * b + v) * level // 100 + level + 10
        else:
            stats[key] = (2 * b + v) * level // 100 + 5

    nat = NATURES[nature]
    if nat["boost"]:
        stats[nat["boost"]] = round(stats[nat["boost"]] * 1.1)
    if nat["cut"]:
        stats[nat["cut"]] = round(stats[nat["cut"]] * 0.9)
    return stats


def sprite_url(pokemon_name: str) -> str:
    dex_id = NAME_TO_ID.get(pokemon_name)
    if dex_id is None:
        return ""
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{dex_id}.png"