"""🔔 경기가 끝나면 전적 카드를 채널에 올려요.

## 왜 (2026-10-18)

지금까지는 `/전적`을 **직접 쳐야만** 전적을 봤어요. 발로란트가 이 서버의 중심인데
(코인 로그 기준 발로 미션만 402건) 누가 방금 뭘 했는지는 아무도 몰랐어요.
경기가 끝나면 알아서 올라오면, 서로 반응할 거리가 생겨요.

## 🚨 전적을 **다시 부르지 않아요**

HenrikDev는 분당 30회를 키 하나로 나눠 써요(`utils/henrik_api.py`). 알림을 위해 별도
루프를 돌리면 호출이 두 배가 돼서 429가 나요. 그래서 **미션 자동판정 루프가 이미 가져온
경기 목록을 그대로 받아서** 씁니다. 추가 API 호출이 **0회**예요.

## 안 올리는 경우 (조용한 쪽이 기본)

- `/채널설정`으로 알림 채널을 안 정했으면 → 아무 데도 안 올려요
- 그 사람이 `/알림설정`에서 껐으면 → 안 올려요
- 이미 올린 경기면 → 안 올려요(`utils/match_feed_store.py`)
- `FEED_MAX_AGE_HOURS`보다 오래된 경기 → 안 올려요
- 🚨 그 사람을 **처음 보는 경우**도 안 올려요. 기능을 켜는 순간 등록된 전원의 오늘 경기가
  한꺼번에 쏟아지는 걸 막아요(21명 × 10경기 = 200개).

## 🚨 "패배만 올라온다" — 2026-10-19에 고친 두 가지

사용자 신고였고, 둘 다 **승패와 무관한 누락**이 승리에 더 많이 걸린 거예요.

1. **알림이 미션에 종속돼 있었어요.** `cogs/mission.py`가 그날 발로 미션을 다 깨면
   `_check_valorant`를 **안 불렀고**, 알림이 그 안에 있어서 같이 멈췄어요.
   `val_win`(승리하기)이 배정돼 있으면 **이기는 순간** 미션이 끝나니, 그 뒤의
   경기(대개 승리)가 영영 안 올라갔어요. → 이제 `pending`이 비어도 부르고 알림만 올려요.
2. **자정을 넘긴 경기가 유실됐어요.** 미션용 "오늘(KST)" 필터가 알림 범위까지 정하고
   있었거든요. 루프가 30분마다 도니 23:30~24:00 경기는 다음 실행 때 이미 '오늘'이
   아니었어요. 실측으로 `피카츄#PXG1` 님의 23:28·23:55 **승리 2건**이 날아갔어요
   (그날 실제 3승 3패 → 채널엔 1승 3패). → 이제 날짜가 아니라 `FEED_MAX_AGE_HOURS`로 봐요.

⚠️ 남겨둔 것: 팀이 `red`/`blue`가 아닌 신규 모드(예: `Gauntlet: Glitched`는 `Team_6`)는
`cogs/rank._extract_player_match_stats`가 승패를 못 가려서 **조용히 빠져요.** 그 모드엔
승패 개념을 매길 수가 없어서 일부러 뒀어요.
"""
from __future__ import annotations

import io
import logging
import time

import discord

from utils import match_feed_store, notify_prefs, stat_art, valorant_maps
from utils.channel_check import get_allowed_channel_id

log = logging.getLogger(__name__)

CHANNEL_GROUP = "match_feed"
CHANNEL_ENV = "MATCH_FEED_CHANNEL_ID"
NOTIFY_KEY = "match_feed"

WIN_COLOR, LOSE_COLOR, DRAW_COLOR = 0x22C55E, 0xEF4444, 0x9BA3AF

# 한 번에 너무 많이 올리면 채널이 묻혀요. 밀린 게 많아도 최신 것만 올려요.
# 🚨 2 였는데 4로 올렸어요(2026-10-19). 2면 한 사람이 연달아 세 판 하면 한 판이 다음
#    실행으로 밀리고, 그게 쌓이다가 **유실**됐어요(옛 날짜 필터와 겹쳐서).
MAX_POST_PER_RUN = 4

# ⏱ 이 시간보다 오래된 경기는 안 올려요.
#
# 🚨 **이게 자정 유실의 대체물이에요**(2026-10-19). 전엔 미션용 "오늘(KST)" 필터가
#    알림의 범위까지 정하고 있어서, 23:30~24:00 경기는 다음 실행(30분 뒤) 때 이미
#    '오늘'이 아니라 **영구히 사라졌어요**. 이제 알림은 날짜가 아니라 **경과 시간**으로
#    봐요 — 자정을 넘겨도 멀쩡합니다.
# ⚠️ 가드가 아예 없으면 안 돼요. `seen` 기록이 몇 건뿐인 기존 유저에게 API 창(최근
#    10경기)에 남아 있던 **며칠 전 경기가 되살아나** 쏟아져요.
# ⚠️ 봇이 이 시간보다 길게 죽어 있었다면 그 사이 경기는 포기해요(묻히는 것보다 나아요).
FEED_MAX_AGE_HOURS = 12


def _mode_label(mode: str | None) -> str:
    table = {
        "competitive": "경쟁전",
        "unrated": "일반전",
        "swiftplay": "스위프트",
        "deathmatch": "데스매치",
        "spikerush": "스파이크 러시",
        "premier": "프리미어",
        "custom": "사용자 설정",
    }
    return table.get((mode or "").lower(), mode or "기타")


def _outcome(match: dict, stat: dict) -> tuple[str, int, str]:
    """(결과 '승리'/'패배'/'무승부', 임베드 색, '13 : 9'). 글 임베드와 📊 카드 그림이 같이 써요."""
    teams = match.get("teams") or {}
    my_team = None
    for side in ("red", "blue"):
        info = teams.get(side) or {}
        if info.get("has_won") == stat["won"] and info.get("rounds_won") is not None:
            my_team = side
            break
    mine = (teams.get(my_team) or {}) if my_team else {}
    won_rounds, lost_rounds = mine.get("rounds_won"), mine.get("rounds_lost")
    if won_rounds is not None and lost_rounds is not None:
        score = f"{won_rounds} : {lost_rounds}"
        if won_rounds == lost_rounds:
            return "무승부", DRAW_COLOR, score
        return ("승리", WIN_COLOR, score) if stat["won"] else ("패배", LOSE_COLOR, score)
    return ("승리", WIN_COLOR, "?") if stat["won"] else ("패배", LOSE_COLOR, "?")


CARD_FILE = "match_result.png"


def card_data(display_name: str, match: dict, stat: dict) -> dict:
    """📊 경기 결과 카드(`utils/stat_art.match_card`)에 넘길 값 (2026-11-23)."""
    from cogs.rank import AGENT_KOREAN_NAMES          # cogs.rank가 이 모듈 쪽을 부르므로 함수 안에서
    meta = match.get("metadata") or {}
    result, _, score = _outcome(match, stat)
    kills, deaths, assists = stat["kills"], stat["deaths"], stat["assists"]
    rounds = stat["total_rounds"] or 1
    shots = stat["headshots"] + stat["bodyshots"] + stat["legshots"]
    mode = (meta.get("mode") or "").lower()
    return {
        "name": display_name, "agent": stat["agent"], "agent_ko": AGENT_KOREAN_NAMES.get(stat["agent"], stat["agent"]),
        "result": result, "score": score, "map_en": meta.get("map"),
        "map_ko": valorant_maps.to_korean(meta.get("map")) or meta.get("map"), "mode": _mode_label(meta.get("mode")),
        "kills": kills, "deaths": deaths, "assists": assists, "kd": kills / max(deaths, 1),
        "acs": stat["score"] / rounds, "adr": stat["damage_made"] / rounds,
        "hs": (stat["headshots"] / shots * 100) if shots else 0.0,
        # 티어 엠블럼은 경쟁전에서만 (일반전 티어 값은 의미가 없어요)
        "tier_id": stat.get("tier") if mode == "competitive" else None,
    }


def build_embed(
    display_name: str, riot_id: str, match: dict, stat: dict
) -> discord.Embed:
    """경기 하나를 카드로. `stat`은 `cogs.rank._extract_player_match_stats` 결과예요."""
    meta = match.get("metadata") or {}
    teams = match.get("teams") or {}

    # 내 팀/상대 라운드. `stat`에는 합계만 있어서 여기서 다시 꺼내요.
    my_team = None
    for side in ("red", "blue"):
        info = teams.get(side) or {}
        if info.get("has_won") == stat["won"] and info.get("rounds_won") is not None:
            my_team = side
            break
    mine = (teams.get(my_team) or {}) if my_team else {}
    won_rounds = mine.get("rounds_won")
    lost_rounds = mine.get("rounds_lost")

    if won_rounds is not None and lost_rounds is not None:
        score = f"{won_rounds} : {lost_rounds}"
        if won_rounds == lost_rounds:
            result, color = "무승부", DRAW_COLOR
        elif stat["won"]:
            result, color = "승리", WIN_COLOR
        else:
            result, color = "패배", LOSE_COLOR
    else:
        score = "?"
        result, color = ("승리", WIN_COLOR) if stat["won"] else ("패배", LOSE_COLOR)

    kills, deaths, assists = stat["kills"], stat["deaths"], stat["assists"]
    kd = kills / max(deaths, 1)
    rounds = stat["total_rounds"] or 1
    adr = stat["damage_made"] / rounds
    acs = stat["score"] / rounds
    shots = stat["headshots"] + stat["bodyshots"] + stat["legshots"]
    hs = (stat["headshots"] / shots * 100) if shots else 0.0

    embed = discord.Embed(
        title=f"{'🏆' if result == '승리' else '💀' if result == '패배' else '🤝'} "
              f"{display_name} · {result} {score}",
        description=(
            f"**{valorant_maps.to_korean(meta.get('map')) or meta.get('map') or '?'}** · "
            f"{_mode_label(meta.get('mode'))} · {stat['agent']}"
        ),
        color=color,
    )
    embed.add_field(name="KDA", value=f"**{kills}** / {deaths} / {assists}  (KD {kd:.2f})",
                    inline=True)
    embed.add_field(name="ACS", value=f"{acs:.0f}", inline=True)
    embed.add_field(name="ADR", value=f"{adr:.0f}", inline=True)
    embed.set_footer(text=f"{riot_id} · 헤드샷 {hs:.0f}% · {rounds}라운드")
    return embed


def _recent_enough(match: dict) -> bool:
    """`FEED_MAX_AGE_HOURS` 안에 시작한 경기인가. 왜 필요한지는 그 상수 주석에 있어요.

    ⚠️ `game_start`가 없으면 **올려요**(막지 않아요). 못 올린 건 `seen`에 안 남아서
    30분마다 영원히 다시 시도되는데, 판단할 수 없는 걸 그렇게 두면 로그만 쌓여요.
    v3 응답에는 사실상 항상 있어요."""
    started = (match.get("metadata") or {}).get("game_start")
    if not started:
        return True
    return (time.time() - float(started)) <= FEED_MAX_AGE_HOURS * 3600


async def post_new_matches(
    bot, user_id: int, riot_id: str, matches: list[dict], stats_of
) -> int:
    """아직 안 올린 경기를 올려요. 올린 개수를 돌려줘요.

    `stats_of(match)` 는 그 경기에서 이 사람의 스탯을 뽑는 함수예요
    (`cogs.rank._extract_player_match_stats`를 부분적용해서 넘겨요).

    🚨 **여기서 예외가 나면 미션 판정까지 같이 죽어요.** 부르는 쪽(mission.py)이 감싸고
    있지만, 이 함수도 자체적으로 조용히 실패하도록 짰어요. 알림은 부가 기능이라
    미션·코인 지급을 막아선 안 돼요.
    """
    channel_id = get_allowed_channel_id(CHANNEL_GROUP, CHANNEL_ENV)
    if not channel_id:
        return 0  # 채널을 안 정했으면 기능이 꺼진 거예요

    if not await notify_prefs.is_enabled(user_id, NOTIFY_KEY):
        return 0

    ids = [
        mid for mid in (
            ((m.get("metadata") or {}).get("matchid")) for m in matches
        ) if mid
    ]
    if not ids:
        return 0

    # 🚨 처음 보는 사람이면 기준선만 잡고 끝. 안 그러면 켜는 순간 폭탄이 터져요.
    if await match_feed_store.prime(user_id, ids):
        log.info("🔔 %s 님의 경기 알림 기준선을 잡았어요 (이번엔 안 올려요)", riot_id)
        return 0

    already = await match_feed_store.seen(user_id)
    fresh = [m for m in matches
             if ((m.get("metadata") or {}).get("matchid")) not in already
             and _recent_enough(m)]
    if not fresh:
        return 0

    # 최신 경기가 목록 앞쪽이에요. 밀린 게 많아도 최신 몇 개만 올려요.
    fresh = fresh[:MAX_POST_PER_RUN]

    channel = bot.get_channel(channel_id)
    if channel is None:
        log.info("🔔 경기 알림 채널(%s)을 못 찾았어요", channel_id)
        return 0

    member = None
    guild = getattr(channel, "guild", None)
    if guild is not None:
        member = guild.get_member(user_id)
    display = member.display_name if member else riot_id.split("#")[0]

    posted = []
    for match in fresh:
        stat = stats_of(match)
        if stat is None:
            continue
        embed = build_embed(display, riot_id, match, stat)
        # 📊 그림 카드(2026-11-23). 맵·요원·승패·KDA가 다 그림에 있어서 글 칸은 걷어내요.
        #    그림을 못 그리면 예전 글 임베드 그대로 — 알림 자체는 꼭 나가요.
        kw = {}
        try:
            png = await stat_art.match_card(card_data(display, match, stat))
        except Exception:                                # noqa: BLE001
            log.warning("🔔 경기 카드 데이터 실패 - 글로 보내요", exc_info=True)
            png = None
        if png is not None:
            embed.description = None
            embed.clear_fields()
            embed.set_image(url=f"attachment://{CARD_FILE}")
            kw["file"] = discord.File(io.BytesIO(png), filename=CARD_FILE)
        try:
            await channel.send(embed=embed, **kw)
        except discord.HTTPException:
            log.warning("🔔 경기 알림 전송 실패 (user=%s)", user_id, exc_info=True)
            break
        posted.append((match.get("metadata") or {}).get("matchid"))

    # 🚨 **올린 것만** 기록해요. 전송에 실패한 건 다음에 다시 시도해야 해요.
    await match_feed_store.mark(user_id, [p for p in posted if p])
    if posted:
        log.info("🔔 %s 님의 경기 %d건을 올렸어요", riot_id, len(posted))
    return len(posted)
