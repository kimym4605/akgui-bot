"""승리 보고를 누르면 그 내전의 **실제 경기 기록(KDA 등)**을 HenrikDev에서 찾아와요.

## 왜 이렇게 하나

`/팀짜기`가 남기는 건 "누가 이겼다"뿐이라 킬뎃이 없었어요. 그런데 사용자 설정 경기도
HenrikDev가 `mode=custom`으로 돌려주고, **경기 하나 응답에 참가자 10명 전원의 stats가
다 들어있어요.** 그래서 호출 **1회**로 한 판 전원의 KDA를 가져올 수 있어요(2026-10-03 실측).

## 조심할 것 (실측으로 확인한 함정들)

1. **`mode=custom`은 내전만 주지 않아요.** 사격장(Skirmish)·데스매치·팀데스매치가 전부
   섞여 나와요. 어떤 계정은 최근 10개가 **전부** 데스매치였어요. 그래서 `queue == "Standard"`
   + 인원 하한으로 걸러야 해요.
2. **그래도 "그 경기"인지는 모르죠.** 어제 돌린 내전도 Standard 사용자 설정이에요. 그래서
   ⒜우리 명단과 겹치는 사람이 몇 명인지 ⒝경기 시작이 보고 시각에서 얼마나 떨어졌는지
   둘 다 보고 고릅니다(`pick_match`).
3. **경기엔 Riot ID만 있어요.** `/티어 계정등록`을 한 사람만 디스코드 계정과 이어져요.
   미등록자는 이름만 남겨요(전적에는 안 들어가지만 화면엔 보여줘야 해요 — 같이 뛴 사람이니까).
4. **맵 이름이 영문**이라 한글로 바꿔 저장해요(utils/valorant_maps.py).
5. API는 분당 30회를 키 하나가 공유해요. 그래서 계정을 **최대 `MAX_LOOKUPS`개까지만**
   찔러보고 포기해요. 못 찾아도 경기 기록 자체는 이미 들어가 있으니 손해가 없어요.
"""
import logging
import os
import unicodedata

import aiohttp

from utils import henrik_api, riot_account_store, valorant_maps

log = logging.getLogger(__name__)

DEFAULT_REGION = os.getenv("VALORANT_REGION", "kr")

# 한 번 보고할 때 찔러볼 계정 수의 상한이에요. 보고한 사람이 그 경기를 안 뛰었을 수도 있어서
# 여러 명을 시도하지만, API 한도를 생각해 작게 잡아요.
MAX_LOOKUPS = 3
# 계정 하나당 받아올 사용자 설정 경기 수. 데스매치가 섞여 들어오니 넉넉히 봐요.
FETCH_SIZE = 10
# 5대5 내전으로 인정할 최소 인원. 9명/8명으로 돌리는 날도 있어서 10으로 못 박지 않아요.
MIN_PLAYERS = 8
# 우리 명단과 이만큼은 겹쳐야 "그 경기"로 봐요. (등록 안 한 사람이 많아서 숫자를 낮게 둬요)
MIN_ROSTER_OVERLAP = 3
# 보고 시각에서 이보다 더 떨어진 경기는 안 써요. 내전 한 판 + 보고 지연을 감안한 폭이에요.
MAX_AGE_SECONDS = 6 * 3600


def _norm(text: str | None) -> str:
    """Riot ID 비교용으로 다듬어요.

    ⚠️ 대소문자·공백이 어긋나면 조용히 못 찾아요(`최 강`처럼 공백이 든 이름이 실제로 있어요).
    유니코드 정규화(NFKC)까지 하는 건 한글 자모가 분리된 형태로 들어오는 경우가 있어서예요."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).replace(" ", "").casefold()


def _riot_key(name: str | None, tag: str | None) -> str:
    return f"{_norm(name)}#{_norm(tag)}"


def build_riot_index(discord_ids: list[int]) -> dict[str, int]:
    """`{'owo#0583': 디스코드id}` 표를 만들어요. 등록 안 한 사람은 빠져요."""
    index: dict[str, int] = {}
    for discord_id in discord_ids:
        account = riot_account_store.get_account(discord_id)
        if account:
            index[_riot_key(account[0], account[1])] = discord_id
    return index


def is_scrim_like(match: dict) -> bool:
    """5대5 사용자 설정으로 보이는 경기인지. (데스매치·난투를 걸러내요)"""
    meta = match.get("metadata") or {}
    players = (match.get("players") or {}).get("all_players") or []
    return meta.get("queue") == "Standard" and len(players) >= MIN_PLAYERS


def roster_overlap(match: dict, riot_index: dict[str, int]) -> set[int]:
    """그 경기 참가자 중 우리 명단에 있는 사람들의 디스코드 id."""
    found = set()
    for player in (match.get("players") or {}).get("all_players") or []:
        discord_id = riot_index.get(_riot_key(player.get("name"), player.get("tag")))
        if discord_id is not None:
            found.add(discord_id)
    return found


def pick_match(
    matches: list[dict], riot_index: dict[str, int], roster: set[int], reported_at: float
) -> tuple[dict, set[int]] | None:
    """후보 경기들 중 '방금 한 그 내전'을 골라요. 없으면 None.

    고르는 기준은 **겹치는 사람 수 → 보고 시각에 가까운 순**이에요. 시간만 보면 바로 전에
    한 다른 내전이 뽑히고, 겹침만 보면 어제 같은 멤버로 한 판이 뽑혀요."""
    scored = []
    for match in matches:
        if not is_scrim_like(match):
            continue
        overlap = roster_overlap(match, riot_index) & roster
        if len(overlap) < MIN_ROSTER_OVERLAP:
            continue
        started = (match.get("metadata") or {}).get("game_start") or 0
        age = abs(reported_at - started)
        if age > MAX_AGE_SECONDS:
            continue
        scored.append((len(overlap), -age, match, overlap))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = scored[0]
    return best[2], best[3]


def extract_stats(match: dict, riot_index: dict[str, int]) -> dict:
    """경기 응답에서 우리가 저장할 것만 뽑아요.

    응답에는 스킬 사용 횟수·크레딧·플레이어 카드 이미지까지 들어있는데, 그걸 다 저장하면
    문서가 몇십 KB가 돼요. 화면에 쓸 것만 남겨요."""
    meta = match.get("metadata") or {}
    rounds_played = meta.get("rounds_played") or 0
    teams = match.get("teams") or {}

    players = []
    for player in (match.get("players") or {}).get("all_players") or []:
        stats = player.get("stats") or {}
        hs = stats.get("headshots") or 0
        bs = stats.get("bodyshots") or 0
        ls = stats.get("legshots") or 0
        shots = hs + bs + ls
        players.append({
            "userId": str(riot_index[_riot_key(player.get("name"), player.get("tag"))])
            if _riot_key(player.get("name"), player.get("tag")) in riot_index else None,
            "name": player.get("name"),
            "tag": player.get("tag"),
            "team": (player.get("team") or "").lower() or None,
            "agent": player.get("character"),
            "kills": stats.get("kills") or 0,
            "deaths": stats.get("deaths") or 0,
            "assists": stats.get("assists") or 0,
            "score": stats.get("score") or 0,
            "headshots": hs,
            "shots": shots,
            # damage_made는 문자열로 올 때가 있어서 숫자로 맞춰둬요.
            "damage": _as_int(player.get("damage_made")),
            "damageTaken": _as_int(player.get("damage_received")),
        })

    return {
        "source": "henrik-custom",
        "matchId": meta.get("matchid"),
        "map": valorant_maps.to_korean(meta.get("map")),
        "startedAt": meta.get("game_start"),
        "roundsPlayed": rounds_played,
        "rounds": {
            "red": (teams.get("red") or {}).get("rounds_won"),
            "blue": (teams.get("blue") or {}).get("rounds_won"),
        },
        # 어느 팀이 이겼는지. 우리가 보고한 승자와 교차검증할 때 써요.
        "wonTeam": "red" if (teams.get("red") or {}).get("has_won") else (
            "blue" if (teams.get("blue") or {}).get("has_won") else None
        ),
        "players": players,
    }


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def per_round(value: int, rounds_played: int) -> float | None:
    """ADR·ACS처럼 '라운드당' 값을 내요. 라운드 수를 모르면 None."""
    if not rounds_played:
        return None
    return value / rounds_played


def headshot_rate(headshots: int, shots: int) -> float | None:
    if not shots:
        return None
    return headshots / shots * 100


async def fetch_for_match(
    session: aiohttp.ClientSession,
    roster: set[int],
    reported_at: float,
    *,
    prefer: int | None = None,
    region: str = DEFAULT_REGION,
) -> dict | None:
    """그 내전의 경기 기록을 찾아와요. 못 찾으면 None(조용히 포기해요).

    `prefer`는 먼저 찔러볼 디스코드 id(보고한 사람)예요. 그 사람이 그 경기를 안 뛰었으면
    명단의 다른 사람으로 넘어가요. 계정이 등록된 사람만 조회할 수 있어요."""
    api_key = os.getenv("HENRIKDEV_API_KEY")
    if not api_key:
        log.info("HENRIKDEV_API_KEY가 없어서 내전 KDA를 못 가져와요.")
        return None

    riot_index = build_riot_index(sorted(roster))
    if len(riot_index) < MIN_ROSTER_OVERLAP:
        log.info(
            "내전 KDA 건너뜀: 명단 %d명 중 라이엇 계정이 등록된 사람이 %d명뿐이에요(최소 %d명).",
            len(roster), len(riot_index), MIN_ROSTER_OVERLAP,
        )
        return None

    # 보고한 사람을 먼저, 그다음은 명단 순서대로. 등록 안 한 사람은 조회 자체가 안 돼요.
    candidates = [uid for uid in ([prefer] if prefer in roster else []) if uid is not None]
    candidates += [uid for uid in sorted(roster) if uid not in candidates]
    lookups = [uid for uid in candidates if riot_account_store.get_account(uid)][:MAX_LOOKUPS]

    headers = {"Authorization": api_key}
    for discord_id in lookups:
        name, tag = riot_account_store.get_account(discord_id)
        status, payload = await henrik_api.request(
            session,
            f"/valorant/v3/matches/{region}/{name}/{tag}",
            headers=headers,
            params={"mode": "custom", "size": FETCH_SIZE},
        )
        if status != 200:
            log.info("내전 KDA 조회 실패(%s#%s): HTTP %s", name, tag, status)
            continue

        picked = pick_match(payload.get("data") or [], riot_index, roster, reported_at)
        if picked is None:
            continue
        match, overlap = picked
        stats = extract_stats(match, riot_index)
        log.info(
            "🗡️ 내전 경기 기록을 찾았어요: %s (%s, 명단 %d명 일치, %s#%s 기준)",
            stats["matchId"], stats["map"], len(overlap), name, tag,
        )
        return stats

    log.info("내전 KDA를 못 찾았어요(계정 %d개 조회). 사용자 설정 경기가 아직 안 올라왔을 수 있어요.",
             len(lookups))
    return None
