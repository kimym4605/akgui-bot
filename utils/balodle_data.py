"""🧩 발로들 정적 데이터 — `config/balodle/*.json`을 **시작할 때 한 번** 읽어서 나눠줘요.

- `AGENTS`     요원키 → 이름·역할군·출신·대륙·출시일·성별·별칭 (`agents.json`)
- `ABILITIES`  `"jett:E"` → 요원·키·이름·아이콘 파일 (`abilities.json`)
- `SETTINGS`   보상·기회·🟨 기준·알림 시각·칭호 (`settings.json`, 빠진 값은 아래 기본값)
- 맵 목록은 따로 두지 않고 `utils/valorant_maps.MAPS`(5대5 맵)를 그대로 써요.

🚨 `config/`에 두는 이유: `data/`는 Fly 볼륨이 가려서 배포해도 서버에 안 올라가요.
값을 바꾸려면 JSON을 고치고 배포하면 돼요(코드 수정 없음).

재료는 `scripts/build_balodle_assets.py`가 만들어요. 파일이 없으면 빈 값으로 살아나고 경고만 남겨요
— 발로들 때문에 봇 전체가 못 뜨면 안 되니까요.
"""
import json
import logging
import os
import re

from utils import balodle_logic, valorant_maps

log = logging.getLogger(__name__)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BOT_DIR, "config", "balodle")
ASSET_DIR = os.path.join(BOT_DIR, "assets", "valorant", "balodle")

DEFAULT_SETTINGS = {
    "start_date": "2026-11-24",
    "max_attempts": {"agent": 6, "ability": 6, "map": 6},
    "rewards": [[1, 3], [3, 2], [6, 1]],
    "streak_bonus": 0,
    "release_mode": "order",
    "year_close": 1,
    "order_close": 2,
    "no_repeat_days": {"agent": 14, "ability": 30, "map": 5},
    "zoom_steps": [0.15, 0.21, 0.29, 0.40, 0.55, 0.75],
    "notify_time": "09:00",
    "titles": {"7": "발로들 단골", "30": "발로들 박사"},
}


def _load(name: str) -> dict:
    path = os.path.join(CONFIG_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning("🧩 발로들 재료가 없어요: %s (scripts/build_balodle_assets.py를 돌려주세요)", path)
    except ValueError:
        log.error("🧩 발로들 재료를 읽지 못했어요(JSON 오류): %s", path, exc_info=True)
    return {}


AGENTS: dict = _load("agents.json")
ABILITIES: dict = _load("abilities.json")
SETTINGS: dict = {**DEFAULT_SETTINGS, **_load("settings.json")}

NAME_INDEX: dict = balodle_logic.build_name_index(AGENTS)
RELEASE_RANK: dict = balodle_logic.release_rank(AGENTS)

# 한글 맵 이름 → 그림 파일 키(소문자 영문). `어센트` → `ascent`
_MAP_KEY = {
    ko: re.sub(r"[^a-z0-9]", "", en.lower())
    for en, ko in valorant_maps.EN_TO_KO.items() if ko in valorant_maps.MAPS
}


def agent_candidates() -> list[str]:
    """요원 문제의 정답 후보 — 속성 칸이 다 채워진 요원만."""
    return [key for key, agent in AGENTS.items() if balodle_logic.is_complete(agent)]


def ability_candidates() -> list[str]:
    """스킬 문제의 정답 후보 — 아이콘 파일이 실제로 있는 스킬만."""
    return [key for key, ab in ABILITIES.items()
            if ab.get("agent") in AGENTS and os.path.exists(ability_icon_path(key))]


def map_candidates() -> list[str]:
    """맵 문제의 정답 후보 — 고화질 그림이 실제로 있는 5대5 맵만."""
    return [name for name in valorant_maps.MAPS if os.path.exists(map_path(name))]


def map_choices() -> list[str]:
    """선택 메뉴에 띄우는 맵 목록 (5대5 맵 전부)."""
    return list(valorant_maps.MAPS)


def agent_name(key: str) -> str:
    return (AGENTS.get(key) or {}).get("ko") or key


def ability_icon_path(key: str) -> str:
    return os.path.join(ASSET_DIR, "abilities", (ABILITIES.get(key) or {}).get("icon", "_"))


# 🗺️ 맵 그림 종류 (2026-11-24). "" = 하늘에서 본 로딩 화면, "_scene" = 맵 안 눈높이 장면.
#    맵마다 한 장뿐이라 금방 외워져서 늘렸어요. 장면 그림이 없는 맵(헤이븐)은 로딩 화면만 써요.
MAP_VARIANTS = ("", "_scene")


def map_path(name: str, variant: str = "") -> str:
    return os.path.join(ASSET_DIR, "maps", f"{_MAP_KEY.get(name, '_')}{variant}.webp")


def map_variants(name: str) -> list[str]:
    """그 맵에서 실제로 파일이 있는 그림 종류."""
    return [v for v in MAP_VARIANTS if os.path.exists(map_path(name, v))]


def ui_path(name: str) -> str:
    """디자이너가 만든 그림(`assets/valorant/balodle/ui/`). 없을 수도 있어요 — 쓰는 쪽이 확인해요."""
    return os.path.join(ASSET_DIR, "ui", name)
