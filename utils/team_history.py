"""`/팀짜기`가 **최근에 누구와 누가 같은 팀이었는지**를 기억해요.

## 왜 필요했나 (2026-10-31 사용자 불만)

`#📣｜내전모집`에서 서아가 방장을 직접 멘션해서 말했어요:

> *"너무 밸런스만 보고 팀을 구성하니까 **맨날 똑같은 팀**이야"*
> *"나 지금 내전 하면서 **재호랑 한번도 같은팀 된적이 없어**"*

코드를 보니 불만이 맞았어요. `team_balance.balanced_splits`는 실력 차이가 가장 작은
편성을 1등으로 돌려주고, **차이가 정확히 동률인 편성만** 섞었어요. 점수가 실수라
동률이 거의 안 나와서, **명단이 같으면 결과가 매번 똑같이** 재현됐어요.

그래서 "실력 차이가 거의 같은 편성들" 중에서 **최근에 같은 팀이었던 조합을 피하는**
쪽을 고르게 했고, 그 판단에 쓸 과거 편성을 이 파일이 들고 있어요.

## 왜 `team_store`를 그냥 안 썼나

`team_store`에도 편성이 저장되지만 **`SESSION_TTL_DAYS = 7`**이에요. 내전은 주 1회꼴로
열려서(2026-10월 기준) 7일이면 과거 편성이 한 판도 안 남을 수 있어요. 그래서 쌍 이력만
따로, **더 길게(60일)** 둬요. 대신 저장하는 건 **유저 id와 날짜뿐**이라 파일이 작아요.

## 저장 규칙

- 세션(메시지) 하나당 **한 줄**이에요. 🔄 다시 섞기로 편성이 바뀌면 그 줄을 덮어써요 —
  같은 내전이 섞은 횟수만큼 이력에 쌓이면 가중치가 망가져요.
- 파일은 `data/` 안이에요(Fly 볼륨). 봇이 실행 중에 스스로 만들어요.
  ⚠️ 저장소에 미리 넣어둔 `data/` 파일은 볼륨에 가려서 서버에 안 보이는데, 이 파일은
  그 함정과 무관해요.
- `remember()`는 `team_store.save_session()` **안에서** 불려요. 호출부마다 붙이면
  언젠가 한 곳을 빼먹어요(미션 훅에서 실제로 그랬어요).
"""
import math
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

from utils import atomic_json, team_balance

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FILE_PATH = DATA_DIR / "team_pairs.json"
KST = timezone(timedelta(hours=9))

# 이보다 오래된 편성은 버려요. 두 달 전에 같은 팀이었던 걸 피할 이유는 없어요.
HISTORY_TTL_DAYS = 60
# 그래도 넘치면 오래된 것부터 버려요(볼륨을 먹으면 안 돼요).
MAX_RECORDS = 200
# 가중치를 매길 때 보는 최근 편성 수. 이보다 오래된 건 이력에 남아도 0으로 봐요.
RECENT_SESSIONS = 10
# 한 칸 오래될수록 무게가 이 비율로 줄어요. 1.0 · 0.7 · 0.49 · 0.34 …
# ⭐ 바로 지난 판에서 같은 팀이었던 쌍을 가장 세게 피하고, 오래된 건 느슨하게 봐요.
RECENCY_DECAY = 0.7


def pair_key(left, right) -> str:
    """두 사람의 쌍을 나타내는 키. 순서를 바꿔도 같은 키가 나와요.

    🚨 **튜플이 아니라 문자열이에요.** JSON 키로도 쓰고 dict 키로도 쓰는데, 둘이
    다르면 저장했다 읽을 때 조용히 안 맞아요."""
    a, b = str(left), str(right)
    return f"{a}|{b}" if a <= b else f"{b}|{a}"


def _load_all() -> dict:
    data = atomic_json.read_json(FILE_PATH, {}) or {}
    return data if isinstance(data, dict) else {}


def _save_all(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json.write_json(FILE_PATH, data)


def _seq_of(record: dict) -> int:
    try:
        return int(record.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def _ids_of(team) -> list[str]:
    """`Rated` 목록이든 id 목록이든 문자열 id 목록으로 바꿔요."""
    out = []
    for item in team or []:
        key = getattr(item, "key", item)
        if key is None:
            continue
        out.append(str(key))
    return out


def _pruned(data: dict) -> dict:
    cutoff = (datetime.now(KST) - timedelta(days=HISTORY_TTL_DAYS)).isoformat()
    kept = {k: v for k, v in data.items() if (v.get("at") or "") >= cutoff}
    if len(kept) > MAX_RECORDS:
        # 🚨 순번으로 재요. `at`은 초 단위라 같은 초에 두 번 저장되면 동률이 생기고,
        #    그러면 **방금 넣은 편성이 지워질 수** 있어요(team_store가 같은 함정을 설명해요).
        newest = sorted(kept.items(), key=lambda kv: _seq_of(kv[1]), reverse=True)
        kept = dict(newest[:MAX_RECORDS])
    return kept


def remember(message_id, guild_id, team_a, team_b) -> None:
    """그 세션의 편성을 기억해요(같은 세션이면 덮어써요).

    ⚠️ 이력이 깨져도 `/팀짜기` 자체는 멈추면 안 돼요 — 부르는 쪽
    (`team_store.save_session`)이 예외를 삼켜요.

    한 팀이 비어 있으면(1명 이하) 쌍이 안 생기니 **저장하지 않아요.**"""
    ids_a, ids_b = _ids_of(team_a), _ids_of(team_b)
    if len(ids_a) + len(ids_b) < 3:
        return                       # 2명 이하면 어떻게 나눠도 쌍이 하나뿐이에요
    key = str(message_id)
    data = _load_all()
    old = data.get(key)
    if old and old.get("teams") == [ids_a, ids_b]:
        return                       # 바뀐 게 없으면 파일을 안 건드려요
    data[key] = {
        "at": datetime.now(KST).isoformat(timespec="seconds"),
        # 이미 있던 줄을 덮어쓸 때는 **순번을 유지**해요. 새 번호를 주면 옛 내전이
        # (맵만 고쳐도) 최신으로 끼어들어서 가중치가 뒤집혀요.
        "seq": _seq_of(old) if old else max((_seq_of(r) for r in data.values()), default=0) + 1,
        "guild_id": str(guild_id) if guild_id is not None else None,
        "teams": [ids_a, ids_b],
    }
    _save_all(_pruned(data))


def recent_sessions(guild_id, *, exclude_message_id=None, limit: int = RECENT_SESSIONS) -> list[dict]:
    """그 서버의 최근 편성을 **새것부터** 돌려줘요."""
    wanted = str(guild_id) if guild_id is not None else None
    skip = str(exclude_message_id) if exclude_message_id is not None else None
    rows = [
        record for key, record in _load_all().items()
        if record.get("guild_id") == wanted and key != skip
    ]
    rows.sort(key=_seq_of, reverse=True)
    return rows[:limit]


def pair_weights(guild_id, *, exclude_message_id=None) -> dict[str, float]:
    """`{쌍 키: 무게}` — 최근에 같은 팀이었을수록 큰 값이에요.

    🚨 **지금 고치고 있는 세션은 빼야 해요**(`exclude_message_id`). 안 빼면 🔄 다시
    섞기를 누를 때 **자기 자신을 피하려 들어서** 매번 멀쩡한 편성을 버려요.
    """
    weights: dict[str, float] = {}
    for index, record in enumerate(
        recent_sessions(guild_id, exclude_message_id=exclude_message_id)
    ):
        weight = RECENCY_DECAY ** index
        for team in record.get("teams") or []:
            for left, right in combinations(sorted(str(x) for x in team), 2):
                key = pair_key(left, right)
                weights[key] = weights.get(key, 0.0) + weight
    return weights


def prune() -> int:
    """오래된 이력을 정리하고 몇 개 지웠는지 돌려줘요(봇 시작할 때 한 번 불러요)."""
    data = _load_all()
    kept = _pruned(data)
    removed = len(data) - len(kept)
    if removed:
        _save_all(kept)
    return removed


def describe(team_a, team_b, weights: dict[str, float]) -> str:
    """"이 편성에서 최근에 또 같은 팀이 된 쌍"을 사람이 읽을 문장으로 (디버깅·테스트용)."""
    cost = team_balance.repeat_cost(team_a, team_b, weights)
    repeats = []
    for team in (_ids_of(team_a), _ids_of(team_b)):
        for left, right in combinations(team, 2):
            if weights.get(pair_key(left, right)):
                repeats.append(f"{left}+{right}")
    if not math.isfinite(cost):
        return "측정 불가"
    return f"반복 비용 {cost:.2f} · 반복 쌍 {len(repeats)}개" + (
        f" ({', '.join(repeats[:6])})" if repeats else ""
    )
