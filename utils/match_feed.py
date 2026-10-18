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
- 🚨 그 사람을 **처음 보는 경우**도 안 올려요. 기능을 켜는 순간 등록된 전원의 오늘 경기가
  한꺼번에 쏟아지는 걸 막아요(21명 × 10경기 = 200개).
"""
from __future__ import annotations

import logging

import discord

from utils import match_feed_store, notify_prefs, valorant_maps
from utils.channel_check import get_allowed_channel_id

log = logging.getLogger(__name__)

CHANNEL_GROUP = "match_feed"
CHANNEL_ENV = "MATCH_FEED_CHANNEL_ID"
NOTIFY_KEY = "match_feed"

WIN_COLOR, LOSE_COLOR, DRAW_COLOR = 0x22C55E, 0xEF4444, 0x9BA3AF

# 한 번에 너무 많이 올리면 채널이 묻혀요. 밀린 게 많아도 최신 것만 올려요.
MAX_POST_PER_RUN = 2


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
             if ((m.get("metadata") or {}).get("matchid")) not in already]
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
        try:
            await channel.send(embed=build_embed(display, riot_id, match, stat))
        except discord.HTTPException:
            log.warning("🔔 경기 알림 전송 실패 (user=%s)", user_id, exc_info=True)
            break
        posted.append((match.get("metadata") or {}).get("matchid"))

    # 🚨 **올린 것만** 기록해요. 전송에 실패한 건 다음에 다시 시도해야 해요.
    await match_feed_store.mark(user_id, [p for p in posted if p])
    if posted:
        log.info("🔔 %s 님의 경기 %d건을 올렸어요", riot_id, len(posted))
    return len(posted)
