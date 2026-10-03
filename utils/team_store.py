"""`/팀보기`가 읽는 '마지막 팀 편성' 저장소예요.

`/팀짜기`는 버튼이 10분 뒤에 꺼지고 메시지도 채팅에 묻혀서, 한참 뒤에 "우리 팀 뭐였지?"를
다시 볼 방법이 없었어요. 그래서 편성이 바뀔 때마다(처음 짤 때 · 다시 섞기 · 완전 랜덤 ·
직접 조정 · 팀장 지정 · 결과 보고) **서버별로 마지막 편성 하나만** 덮어써 둬요.

- 파일은 `data/` 안에 둬요. Fly 볼륨이 마운트되는 자리라 봇을 다시 띄워도 남아요.
  (⚠️ 반대로 저장소에 미리 넣어둔 `data/` 파일은 볼륨에 가려서 서버에 안 보여요.
   이 파일은 봇이 실행 중에 스스로 만드는 것이라 그 함정과는 무관해요.)
- 과거 이력은 일부러 쌓지 않아요. 요청이 '마지막 편성 다시 보기'였고, 서버마다 무한정
  쌓이면 볼륨을 먹어요. 경기 결과 자체는 이미 `scrim_record_store`에 쌓이고 있어요.

`Rated`(utils/team_balance.py)를 그대로 넣고 꺼낼 수 있게 변환까지 여기서 담당해요.
그래야 저장 형식을 아는 곳이 이 파일 하나로 끝나요.
"""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import atomic_json, team_balance

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FILE_PATH = DATA_DIR / "last_teams.json"
KST = timezone(timedelta(hours=9))

# 편성을 어떻게 만들었는지. 화면 제목과 색이 이 값으로 갈려요.
MODE_BALANCED = "balanced"
MODE_RANDOM = "random"
MODE_MANUAL = "manual"


def _load() -> dict:
    # 깨진 파일이 남아 있어도 빈 dict로 살아나요(atomic_json.read_json이 막아줘요).
    return atomic_json.read_json(FILE_PATH, {}) or {}


def _save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json.write_json(FILE_PATH, data)


def player_to_dict(player: team_balance.Rated) -> dict:
    return {
        "id": player.key,
        "label": player.label,
        "rating": player.rating,
        "tier_index": player.tier_index,
        "agwi_score": player.agwi_score,
        "estimated": player.estimated,
    }


def player_from_dict(raw: dict) -> team_balance.Rated:
    """저장해둔 한 줄을 `Rated`로 되돌려요.

    이름(`label`)까지 저장해두는 이유: 저장한 뒤에 서버를 나간 사람이 있으면 id로는
    이름을 못 찾아요. 그때도 "누구랑 한 팀이었는지"는 보여야 하니까요."""
    user_id = int(raw["id"])
    rating = raw.get("rating")
    return team_balance.Rated(
        key=user_id,
        label=raw.get("label") or str(user_id),
        rating=float(rating) if rating is not None else float(team_balance.FALLBACK_TIER_INDEX),
        tier_index=raw.get("tier_index"),
        agwi_score=raw.get("agwi_score"),
        estimated=bool(raw.get("estimated")),
    )


def _json_number(value) -> float | None:
    """`inf`/`nan`은 JSON 표준이 아니라 저장하지 않아요.

    한쪽 팀이 비면 `imbalance()`가 `inf`를 돌려주는데, 그대로 쓰면 다른 도구가 읽을 때
    깨지는 파일이 돼요. 못 재는 값은 그냥 `None`으로 두고 화면에서 생략해요."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def save_split(
    guild_id: int,
    *,
    team_a: list[team_balance.Rated],
    team_b: list[team_balance.Rated],
    mode: str,
    diff: float | None,
    source_label: str,
    captains: tuple[int | None, int | None] = (None, None),
    map_name: str | None = None,
    message_url: str | None = None,
    winner: int | None = None,
) -> None:
    """지금 화면에 떠 있는 편성을 그 서버의 '마지막 편성'으로 덮어써요.

    `winner`는 승리 보고가 들어간 뒤에만 0(A팀)/1(B팀)이 들어가요."""
    data = _load()
    data[str(guild_id)] = {
        "saved_at": datetime.now(KST).isoformat(timespec="seconds"),
        "mode": mode,
        "diff": _json_number(diff),
        "source_label": source_label,
        "captains": [captains[0], captains[1]],
        "map": map_name or None,
        "message_url": message_url,
        "winner": winner,
        "teams": [
            [player_to_dict(p) for p in team_a],
            [player_to_dict(p) for p in team_b],
        ],
    }
    _save(data)


def get_split(guild_id: int) -> dict | None:
    """그 서버의 마지막 편성. 한 번도 안 짰으면 None."""
    return _load().get(str(guild_id))


def load_teams(record: dict) -> tuple[list[team_balance.Rated], list[team_balance.Rated]]:
    teams = record.get("teams") or [[], []]
    # 예전 형식이나 손으로 고친 파일이 들어와도 터지지 않게 두 칸을 보장해요.
    while len(teams) < 2:
        teams.append([])
    return (
        [player_from_dict(p) for p in teams[0]],
        [player_from_dict(p) for p in teams[1]],
    )


def load_captains(record: dict) -> tuple[int | None, int | None]:
    captains = record.get("captains") or [None, None]
    while len(captains) < 2:
        captains.append(None)
    return (
        int(captains[0]) if captains[0] is not None else None,
        int(captains[1]) if captains[1] is not None else None,
    )


def clear_split(guild_id: int) -> None:
    data = _load()
    if data.pop(str(guild_id), None) is not None:
        _save(data)
