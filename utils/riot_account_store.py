"""
디스코드 유저 <-> 본인 라이엇 계정(닉네임#태그) 연결 정보를 저장하는 저장소예요.

이게 필요한 이유: /전적으로 아무 닉네임이나 조회해도 티어 역할이 "조회한 사람"에게
그대로 붙어버리면, 남의 계정을 검색해서 엉뚱한 티어 역할을 받아가는 악용이 가능해져요.
그래서 "본인이 미리 등록해둔 계정을 조회할 때만" 역할이 갱신되도록, 등록 여부를 여기서 관리해요.
"""
import json

from utils import atomic_json
from pathlib import Path
from typing import Optional, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "riot_accounts.json"


def _load() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    # 원자적 쓰기 - 도중에 죽어도 기존 파일이 안 깨져요. (utils/atomic_json.py 주석 참고)
    atomic_json.write_json(DATA_FILE, data)


# 🌏 계정 지역을 모를 때 쓰는 값이에요.
#
# 🚨 예전엔 이 "kr"이 `cogs/rank.py`·`cogs/mission.py`·`utils/scrim_stats_fetch.py`에
#    따로따로 박혀 있었어요. 그래서 **아시아(ap) 서버 계정은 전적도, 발로 미션 자동판정도,
#    내전 KDA도 전부 조용히 실패**했어요.
#
# 🚨🚨 **틀린 지역의 실패 모양이 엔드포인트마다 달라요** (2026-11-03 실측):
#    · `v3/mmr`     → **404** `No MMR data available for this user` (= `/전적`의 티어·RR)
#    · `v3/matches` → **200 + 빈 목록** (= 미션 자동판정 · 내전 KDA)
#    matches 쪽이 더 고약해요 — 에러가 아니라 "오늘 경기가 없는 사람"처럼 보여서
#    **로그 한 줄 없이** 미션이 안 깨졌어요. 그래서 404만 보고 고치려 들면 안 돼요.
#
#    이제 지역은 계정마다 저장하고, 이 값은 **정말 모를 때의 마지막 기본값**일 뿐이에요.
DEFAULT_REGION = "kr"


def set_account(discord_id: int, name: str, tag: str, region: Optional[str] = None):
    """계정을 등록해요. `region`을 주면 같이 저장해요(없으면 나중에 자동으로 채워져요)."""
    data = _load()
    entry = {"name": name, "tag": tag}
    if region:
        entry["region"] = region
    data[str(discord_id)] = entry
    _save(data)


def get_account(discord_id: int) -> Optional[Tuple[str, str]]:
    """등록된 (닉네임, 태그)를 반환해요. 없으면 None.

    ⚠️ 지역은 여기 안 들어 있어요 — 부르는 쪽이 많아서 반환 모양을 안 바꿨어요.
    지역이 필요하면 `get_region()`을 같이 부르세요."""
    data = _load()
    entry = data.get(str(discord_id))
    if not entry:
        return None
    return entry["name"], entry["tag"]


def get_region(discord_id: int) -> Optional[str]:
    """등록해둔 계정 지역('ap'·'kr'…). **모르면 None** — 기본값으로 덮지 않아요.

    None과 'kr'을 구분하는 게 중요해요. "아직 안 알아봤다"와 "한국 계정이다"를 뭉개면,
    지역을 알아낼 기회(404 뒤 자동 판별)를 영영 놓쳐요."""
    entry = _load().get(str(discord_id))
    if not entry:
        return None
    return entry.get("region") or None


def set_region(discord_id: int, region: str) -> bool:
    """이미 등록된 계정의 지역만 고쳐요. 등록이 없으면 False.

    404를 맞고 진짜 지역을 알아냈을 때 불러요 — 한 번 고치면 다음부터는 바로 맞아요."""
    data = _load()
    entry = data.get(str(discord_id))
    if not entry:
        return False
    if entry.get("region") == region:
        return False
    entry["region"] = region
    _save(data)
    return True


def all_discord_ids() -> list[int]:
    """라이엇 계정을 연동해둔 사람들의 디스코드 id 전부.

    발로란트 미션 자동 판정 루프가 '누구 전적을 확인해야 하는지' 고를 때 써요.
    숫자로 못 바꾸는 키(과거 데이터가 깨진 경우)는 조용히 건너뛰어요."""
    ids = []
    for key in _load():
        try:
            ids.append(int(key))
        except (TypeError, ValueError):
            continue
    return ids


def delete_account(discord_id: int) -> bool:
    data = _load()
    if str(discord_id) in data:
        del data[str(discord_id)]
        _save(data)
        return True
    return False


def is_matching_account(discord_id: int, name: str, tag: str) -> bool:
    """이 유저가 등록해둔 계정과 (name, tag)가 같은 계정인지 (대소문자 무시) 확인해요."""
    account = get_account(discord_id)
    if account is None:
        return False
    reg_name, reg_tag = account
    return reg_name.lower() == name.lower() and reg_tag.lower() == tag.lower()