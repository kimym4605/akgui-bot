"""
/전적 명령어로 계산된 KD, 악귀 점수를 로컬에 기록해두는 저장소예요.
"상위 X%" 같은 상대 비교 지표를 계산할 때 쓰여요.

⚠️ 주의: 여기 쌓이는 건 "이 봇으로 /전적을 조회해본 사람들"의 데이터일 뿐,
발로란트 전체 유저 데이터가 아니에요. 그래서 표시할 때도 반드시
"이 서버에서 조회된 유저 중 상위 X%" 처럼 모수를 명시해야 해요.
"""
import json

from utils import atomic_json
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "rank_stats.json"

# 표본이 이 숫자보다 적으면 퍼센타일을 보여주지 않아요. (너무 적으면 의미가 없어서)
MIN_SAMPLE_SIZE = 5


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


def record_stats(riot_id: str, kd: float, agwi_score: float):
    """riot_id 예: '악귀#KR1'. 조회할 때마다 최신 값으로 덮어써요."""
    data = _load()
    data[riot_id] = {"kd": kd, "agwi_score": agwi_score}
    _save(data)


def get_stats(riot_id: str) -> Optional[dict]:
    """그 계정의 마지막 `/전적` 기록({"kd", "agwi_score"}). 조회한 적이 없으면 None.

    /팀짜기 밸런싱이 써요. 여기 없으면 그 사람은 티어 역할만으로 점수를 매겨요.

    키는 `/전적`에 **입력된 표기 그대로** 저장돼요(예: `OwO#0583`, `악귀#kr1`). 그래서
    연동해둔 계정 표기와 대소문자가 어긋나면 그냥 못 찾아요. 그건 실력 점수를 놓치는
    것뿐이라 조용히 지나가버리니, 여기서 대소문자·공백을 무시하고 한 번 더 찾아봐요."""
    data = _load()
    entry = data.get(riot_id)
    if not isinstance(entry, dict):
        target = (riot_id or "").strip().lower()
        if not target:
            return None
        for key, value in data.items():
            if key.strip().lower() == target and isinstance(value, dict):
                return value
        return None
    return entry


def get_kd_percentile(kd: float) -> Optional[float]:
    """이 KD보다 낮은 사람이 몇 %인지 반환해요. 표본이 부족하면 None."""
    data = _load()
    all_kds = [entry["kd"] for entry in data.values()]

    if len(all_kds) < MIN_SAMPLE_SIZE:
        return None

    lower_count = sum(1 for other in all_kds if other <= kd)
    percentile_from_bottom = (lower_count / len(all_kds)) * 100
    return round(100 - percentile_from_bottom, 1)  # "상위 X%"로 쓰기 좋게 뒤집어서 반환


def get_sample_size() -> int:
    return len(_load())