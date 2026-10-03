"""`/팀짜기` 화면의 상태를 **메시지별로** 저장해요. 버튼이 영속이라 이게 필요해요.

## 왜 메시지별로 저장하나

예전 `/팀짜기` 버튼은 10분 타임아웃이 있는 보통 View였어요. 그래서
  - 팀을 짜고 **게임에 들어가면 10분 만에 버튼이 전부 꺼졌고**(발로란트 한 판은 30~45분),
  - 봇을 재시작하면 눌러도 "상호작용 실패"가 났어요.
경기가 끝나고 돌아오면 승리 보고 버튼이 이미 죽어 있어서, **2026-09-22 배포 이후 내전
경기가 한 건도 기록되지 못했어요**(운영 DB에 `scrim_matches` 컬렉션이 아예 없었어요).

그래서 버튼을 영속(`timeout=None` + 고정 custom_id)으로 바꿨고, 영속 버튼은 상태를 들고
있을 수 없어요(봇이 재시작되면 파이썬 객체가 사라지니까요). 그래서 **누른 메시지의 id로
여기서 상태를 찾아 읽고, 바꾼 뒤 다시 써요.**

## 저장하는 것

참가자 전원(`players`)까지 저장해요 - 🔄 다시 섞기와 🎲 완전 랜덤은 "전체 명단"이 있어야
다시 계산할 수 있어요. 후보 편성(`candidates`)은 저장하지 않고 그때그때 다시 구해요
(같은 명단이면 같은 결과가 나오고, 파일만 커져요).

- 파일은 `data/` 안이에요. Fly 볼륨이 마운트되는 자리라 봇을 다시 띄워도 남아요.
  (⚠️ 반대로 저장소에 미리 넣어둔 `data/` 파일은 볼륨에 가려서 서버에 안 보여요.
   이 파일은 봇이 실행 중에 스스로 만드는 것이라 그 함정과는 무관해요)
- 무한정 쌓이지 않게 `prune()`이 오래된 것과 넘치는 것을 버려요.

`/팀보기`는 그 서버의 **가장 최근 세션**을 보여줘요(`latest_for_guild`).
"""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import atomic_json, team_balance

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FILE_PATH = DATA_DIR / "team_sessions.json"
KST = timezone(timedelta(hours=9))

# 편성을 어떻게 만들었는지. 화면 제목과 색이 이 값으로 갈려요.
MODE_BALANCED = "balanced"
MODE_RANDOM = "random"
MODE_MANUAL = "manual"

# 이보다 오래된 세션은 버려요. 며칠 지난 팀짜기 메시지를 되살릴 일은 없어요.
SESSION_TTL_DAYS = 7
# 그래도 넘치면 오래된 것부터 버려요(파일이 계속 커지면 볼륨을 먹어요).
MAX_SESSIONS = 300


def _load_all() -> dict:
    # 깨진 파일이 남아 있어도 빈 dict로 살아나요(atomic_json.read_json이 막아줘요).
    data = atomic_json.read_json(FILE_PATH, {}) or {}
    return data if isinstance(data, dict) else {}


def _save_all(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json.write_json(FILE_PATH, data)


# ------------------------------------------------------------------
# Rated <-> dict 변환 (저장 형식을 아는 곳을 이 파일 하나로 묶어둬요)
# ------------------------------------------------------------------
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


def _seq_of(record: dict) -> int:
    """저장 순번. 없는(예전) 기록은 0으로 봐서 가장 오래된 것으로 취급해요."""
    try:
        return int(record.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def _next_seq(data: dict) -> int:
    """파일 안에서 가장 큰 순번 + 1. 봇을 재시작해도 이어져요(파일에서 읽으니까요)."""
    return max((_seq_of(r) for r in data.values()), default=0) + 1


def _json_number(value) -> float | None:
    """`inf`/`nan`은 JSON 표준이 아니라 저장하지 않아요.

    한쪽 팀이 비면 `imbalance()`가 `inf`를 돌려주는데, 그대로 쓰면 다른 도구가 읽을 때
    깨지는 파일이 돼요. 못 재는 값은 그냥 `None`으로 두고 화면에서 생략해요."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


# ------------------------------------------------------------------
# 세션 읽기/쓰기
# ------------------------------------------------------------------
def save_session(
    message_id: int,
    *,
    guild_id: int | None,
    owner_id: int,
    players: list[team_balance.Rated],
    team_a: list[team_balance.Rated],
    team_b: list[team_balance.Rated],
    mode: str,
    diff: float | None,
    source_label: str,
    captains: tuple[int | None, int | None] = (None, None),
    map_name: str | None = None,
    message_url: str | None = None,
    winner: int | None = None,
    reported: bool = False,
    match_id: str | None = None,
) -> None:
    """그 메시지의 지금 상태를 저장해요(있으면 덮어써요).

    `winner`/`match_id`는 승리 보고가 들어간 뒤에만 채워져요."""
    data = _load_all()
    data[str(message_id)] = {
        "saved_at": datetime.now(KST).isoformat(timespec="seconds"),
        # ⚠️ 순서는 `saved_at`이 아니라 이 순번으로 재요. `saved_at`은 초 단위라 같은 초에
        # 두 번 저장되면 동률이 생겨서 "가장 최근"이 흔들리고, 상한 정리에서 **최신 세션이
        # 지워질 수도** 있어요(그러면 그 메시지 버튼이 죽어요).
        "seq": _next_seq(data),
        "guild_id": str(guild_id) if guild_id is not None else None,
        "owner_id": int(owner_id),
        "mode": mode,
        "diff": _json_number(diff),
        "source_label": source_label,
        "captains": [captains[0], captains[1]],
        "map": map_name or None,
        "message_url": message_url,
        "winner": winner,
        "reported": bool(reported),
        "match_id": match_id,
        "players": [player_to_dict(p) for p in players],
        "teams": [
            [player_to_dict(p) for p in team_a],
            [player_to_dict(p) for p in team_b],
        ],
    }
    _save_all(_pruned(data))


def get_session(message_id: int) -> dict | None:
    """그 메시지의 상태. 없거나 오래돼서 치워졌으면 None."""
    return _load_all().get(str(message_id))


def latest_for_guild(guild_id: int) -> dict | None:
    """그 서버에서 **가장 최근에 짠** 편성이에요(`/팀보기`가 써요)."""
    wanted = str(guild_id)
    rows = [r for r in _load_all().values() if r.get("guild_id") == wanted]
    if not rows:
        return None
    return max(rows, key=_seq_of)


def delete_session(message_id: int) -> None:
    data = _load_all()
    if data.pop(str(message_id), None) is not None:
        _save_all(data)


def _pruned(data: dict) -> dict:
    """오래된 세션과 넘치는 세션을 버려요."""
    cutoff = (datetime.now(KST) - timedelta(days=SESSION_TTL_DAYS)).isoformat()
    kept = {k: v for k, v in data.items() if (v.get("saved_at") or "") >= cutoff}
    if len(kept) > MAX_SESSIONS:
        # 최근 것부터 MAX_SESSIONS개만 남겨요. 순번으로 재야 해요 - `saved_at`은 초 단위라
        # 같은 초에 저장된 것끼리 동률이 되고, 그러면 **방금 만든 세션이 지워질 수 있어요.**
        newest = sorted(kept.items(), key=lambda kv: _seq_of(kv[1]), reverse=True)
        kept = dict(newest[:MAX_SESSIONS])
    return kept


def prune() -> int:
    """오래된 세션을 정리하고 몇 개 지웠는지 돌려줘요(봇 시작할 때 한 번 불러요)."""
    data = _load_all()
    kept = _pruned(data)
    removed = len(data) - len(kept)
    if removed:
        _save_all(kept)
    return removed


# ------------------------------------------------------------------
# 저장된 기록에서 꺼내 쓰기
# ------------------------------------------------------------------
def load_players(record: dict) -> list[team_balance.Rated]:
    return [player_from_dict(p) for p in record.get("players") or []]


def load_teams(record: dict) -> tuple[list[team_balance.Rated], list[team_balance.Rated]]:
    teams = record.get("teams") or [[], []]
    # 예전 형식이나 손으로 고친 파일이 들어와도 터지지 않게 두 칸을 보장해요.
    teams = list(teams)
    while len(teams) < 2:
        teams.append([])
    return (
        [player_from_dict(p) for p in teams[0]],
        [player_from_dict(p) for p in teams[1]],
    )


def load_captains(record: dict) -> tuple[int | None, int | None]:
    captains = list(record.get("captains") or [None, None])
    while len(captains) < 2:
        captains.append(None)
    return (
        int(captains[0]) if captains[0] is not None else None,
        int(captains[1]) if captains[1] is not None else None,
    )
