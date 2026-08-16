import asyncio
import os
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from utils.channel_check import restrict_to_channel
from utils.rank_stats_store import get_kd_percentile, get_sample_size, record_stats
from utils.riot_account_store import get_account, is_matching_account
from utils.tier_roles import parse_korean_tier, sync_tier_role
from utils.position_roles import sync_position_role

# HenrikDev API (https://docs.henrikdev.xyz) : 라이엇 공식 파트너는 아니지만
# 활발히 유지보수되고 있는 서드파티(비공식) 발로란트 전적 API예요.
HENRIK_BASE = "https://api.henrikdev.xyz"
REGION_CHOICES = ["kr", "ap", "na", "eu", "latam", "br"]
DEFAULT_MATCH_COUNT = 10  # /전적 명령어에서 기본으로 채우려는 총 경기 수예요. (경쟁전 우선, 부족하면 일반전으로 채워요)
LOW_ACTIVITY_TARGET = 5   # 경쟁전 자체가 이 숫자 미만인 "저활동 계정"은 목표치를 이만큼으로 낮춰요. (일반전 추가 조회량을 줄여서 느려지는 걸 완화해요)

# API가 영문으로 주는 요원 이름을 한글로 보여주기 위한 매핑이에요.
# 목록에 없는(최신 패치로 새로 추가된) 요원은 영문 이름 그대로 표시돼요.
AGENT_KOREAN_NAMES = {
    "Brimstone": "브림스톤", "Viper": "바이퍼", "Omen": "오멘", "Killjoy": "킬조이",
    "Cypher": "사이퍼", "Sova": "소바", "Sage": "세이지", "Phoenix": "피닉스",
    "Jett": "제트", "Reyna": "레이나", "Raze": "레이즈", "Breach": "브리치",
    "Skye": "스카이", "Yoru": "요루", "Astra": "아스트라", "KAY/O": "케이/오",
    "Chamber": "체임버", "Neon": "네온", "Fade": "페이드", "Harbor": "하버",
    "Gekko": "게코", "Deadlock": "데드락", "Iso": "아이소", "Clove": "클로브",
    "Vyse": "바이스", "Waylay": "웨이레이",
}

# 요원 -> 포지션(4역할) 매핑이에요. AGENT_KOREAN_NAMES에 있는 요원 전부를 포함해요.
# 목록에 없는(최신 패치로 새로 추가된) 요원은 포지션 집계에서 자동으로 제외돼요.
AGENT_ROLE_MAP = {
    # 타격대 (듀얼리스트)
    "Jett": "타격대", "Phoenix": "타격대", "Raze": "타격대", "Reyna": "타격대",
    "Yoru": "타격대", "Neon": "타격대", "Iso": "타격대", "Waylay": "타격대",
    # 척후대 (이니시에이터)
    "Sova": "척후대", "Breach": "척후대", "Skye": "척후대",
    "KAY/O": "척후대", "Fade": "척후대", "Gekko": "척후대",
    # 전략가 (컨트롤러)
    "Brimstone": "전략가", "Viper": "전략가", "Omen": "전략가",
    "Astra": "전략가", "Harbor": "전략가", "Clove": "전략가",
    # 감시자 (센티널)
    "Killjoy": "감시자", "Cypher": "감시자", "Sage": "감시자",
    "Chamber": "감시자", "Deadlock": "감시자", "Vyse": "감시자",
}


# ============================================================
# 악귀 점수(자체 종합 성능 지표) - 2000점 만점
# ------------------------------------------------------------
# tracker.gg의 "Tracker Score"는 공개되지 않은 자체 알고리즘이라 그대로 가져올 수 없어요.
# 같은 개념(경기 지표를 하나의 점수로 종합)을 우리만의 방식으로 새로 설계했어요.
#
# 1) KD/ADR/HS%/승률 각각 기준값(1.0 / 130 / 20% / 50%)에서 얼마나 벗어났는지로 "성과 점수"를 구해요.
# 2) 그 성과 점수에 "티어 배수"를 곱해요. 같은 활약이어도 높은 티어일수록 점수가 훨씬 크게 뛰고,
#    낮은 티어면 깎이는 구조예요. 배수는 실버3(0RR)을 1.00배 기준점으로 잡은 지수식이에요:
#      배수 = 1.08 ^ (N - 9 + RR/100)
#      N: 티어 단계 인덱스 (아이언1=1, 아이언2=2, ... 레디언트=25)
#    레디언트는 RR이 100을 넘어갈 수 있어서(리더보드 RR), 그 경우도 그대로 지수에 반영돼요.
# 실제 서버 데이터 보면서 아래 가중치를 얼마든지 조절해도 돼요.
# ============================================================
AGWI_BASELINE = 500.0
AGWI_KD_WEIGHT = 200.0        # KD 1.0 기준, ±1당 ±200점
AGWI_ADR_WEIGHT = 2.0         # ADR 130 기준, ±1당 ±2점
AGWI_HS_WEIGHT = 8.0          # HS% 20% 기준, ±1%p당 ±8점
AGWI_WINRATE_WEIGHT = 3.0     # 승률 50% 기준, ±1%p당 ±3점

TIER_MULT_BASE = 1.08     # 티어 배수 지수식의 밑
TIER_MULT_N_BASELINE = 9  # 실버 3 = 기준점(1.00배). N: 아이언1=1 ~ 레디언트=25

AGWI_MAX_SCORE = 2000.0  # 티어 배수가 커지면 1000점을 훌쩍 넘길 수 있어서 상한을 넉넉하게 잡았어요.

# (최소 점수, 등급, 임베드 색상) - 점수 높은 순으로 정렬돼 있어야 해요.
# 1000점 이하 구간은 기존 그대로 두고, 그 위로 SS/SSS 등급을 추가했어요.
AGWI_GRADE_THRESHOLDS = [
    (1500, "SSS", 0xFF1493), (1200, "SS", 0xFF8C00),
    (950, "S+", 0xFFD700), (900, "S", 0xFFC300),
    (800, "A+", 0x8B5CF6), (700, "A", 0x9B7BF0),
    (600, "B+", 0x00B0F4), (500, "B", 0x4FC3F7),
    (400, "C+", 0x2ECC71), (300, "C", 0x82E0AA),
    (150, "D", 0x95A5A6), (0, "F", 0x7F8C8D),
]


def tier_index_from_tier_id(tier_id: int) -> int:
    """HenrikDev의 tier.id(아이언1=3~레디언트=27)를 N(아이언1=1~레디언트=25)으로 바꿔요."""
    return tier_id - 2


def calculate_tier_multiplier(tier_id: Optional[int], rr: Optional[int]) -> Optional[float]:
    """실버3(0RR)=1.00배를 기준점으로, 배수 = 1.08^(N-9+RR/100)를 계산해요."""
    if tier_id is None:
        return None
    n = tier_index_from_tier_id(tier_id)
    rr_value = rr if rr is not None else 0
    exponent = (n - TIER_MULT_N_BASELINE) + (rr_value / 100.0)
    return TIER_MULT_BASE ** exponent


def calculate_agwi_score(
    kd: float, adr: float, hs_percent: float, win_rate: float, tier_multiplier: Optional[float] = None
) -> float:
    performance_delta = (
        (kd - 1.0) * AGWI_KD_WEIGHT
        + (adr - 130.0) * AGWI_ADR_WEIGHT
        + (hs_percent - 20.0) * AGWI_HS_WEIGHT
        + (win_rate - 50.0) * AGWI_WINRATE_WEIGHT
    )
    multiplier = tier_multiplier if tier_multiplier is not None else 1.0
    score = AGWI_BASELINE + performance_delta * multiplier
    return round(max(0.0, min(AGWI_MAX_SCORE, score)), 1)


def get_agwi_grade(score: float) -> tuple[str, int]:
    for threshold, grade, color in AGWI_GRADE_THRESHOLDS:
        if score >= threshold:
            return grade, color
    return "F", 0x7F8C8D


# ============================================================
# HenrikDev API 호출 헬퍼
# ============================================================
async def fetch_current_mmr(session: aiohttp.ClientSession, headers: dict, region: str, name: str, tag: str):
    url = f"{HENRIK_BASE}/valorant/v3/mmr/{region}/pc/{name}/{tag}"
    async with session.get(url, headers=headers) as resp:
        return resp.status, await resp.json()


async def fetch_matches_by_mode(
    session: aiohttp.ClientSession, headers: dict, region: str, name: str, tag: str, size: int, mode: str
):
    url = f"{HENRIK_BASE}/valorant/v3/matches/{region}/{name}/{tag}"
    params = {"mode": mode, "size": size}
    async with session.get(url, headers=headers, params=params) as resp:
        return resp.status, await resp.json()


# ============================================================
# 티어 아이콘 이미지 (valorant-api.com - 인증 불필요한 공식 정적 데이터)
# ------------------------------------------------------------
# HenrikDev가 주는 tier.id(숫자)를 그대로 이 목록의 인덱스로 쓰면 해당 티어의 아이콘 URL이 나와요.
# 시즌이 바뀌어도 tier.id 체계 자체는 거의 안 바뀌어서, 봇 켜질 때 한 번만 받아서 캐싱해두고 계속 재사용해요.
# ============================================================
TIER_ICON_ENDPOINT = "https://valorant-api.com/v1/competitivetiers"


async def fetch_tier_icons(session: aiohttp.ClientSession) -> dict[int, str]:
    """{tier_id: 큰 아이콘 URL} 형태로 반환해요. 실패하면 빈 dict를 반환해요."""
    try:
        async with session.get(TIER_ICON_ENDPOINT) as resp:
            if resp.status != 200:
                return {}
            payload = await resp.json()
    except Exception as error:  # noqa: BLE001
        print(f"⚠️ 티어 아이콘 목록을 불러오지 못했어요: {error}")
        return {}

    seasons = payload.get("data", [])
    if not seasons:
        return {}

    latest_season = seasons[-1]  # 목록 맨 마지막이 가장 최신 시즌이에요.
    return {
        tier["tier"]: tier["largeIcon"]
        for tier in latest_season.get("tiers", [])
        if tier.get("largeIcon")
    }


def _extract_player_match_stats(match: dict, name: str, tag: str) -> Optional[dict]:
    """한 경기 데이터에서 이 유저 본인의 스탯만 뽑아내요. 못 찾으면 None을 반환해요."""
    all_players = match.get("players", {}).get("all_players", [])
    me = next(
        (
            p for p in all_players
            if p.get("name", "").lower() == name.lower() and p.get("tag", "").lower() == tag.lower()
        ),
        None,
    )
    if me is None:
        return None

    stats = me.get("stats", {})
    my_team = (me.get("team") or "").lower()  # "red" / "blue"
    my_team_info = match.get("teams", {}).get(my_team, {})

    rounds_won = my_team_info.get("rounds_won", 0) or 0
    rounds_lost = my_team_info.get("rounds_lost", 0) or 0

    return {
        "kills": stats.get("kills", 0) or 0,
        "deaths": stats.get("deaths", 0) or 0,
        "assists": stats.get("assists", 0) or 0,
        "headshots": stats.get("headshots", 0) or 0,
        "bodyshots": stats.get("bodyshots", 0) or 0,
        "legshots": stats.get("legshots", 0) or 0,
        "damage_made": me.get("damage_made", 0) or 0,
        "score": stats.get("score", 0) or 0,  # 라이엇 공식 전투 점수(라운드 누적) - ACS 계산용
        "total_rounds": rounds_won + rounds_lost,
        "won": bool(my_team_info.get("has_won", False)),
        "agent": me.get("character") or "알 수 없음",
    }


def aggregate_match_stats(
    matches: list, name: str, tag: str, tier_id: Optional[int] = None, rr: Optional[int] = None
) -> Optional[dict]:
    """여러 경기의 개인 스탯을 합산해서 KDA/승률/HS%/ADR/악귀 점수/선호 요원을 계산해요."""
    totals = {
        "kills": 0, "deaths": 0, "assists": 0,
        "headshots": 0, "bodyshots": 0, "legshots": 0,
        "damage_made": 0, "score": 0, "total_rounds": 0,
        "wins": 0, "matches_counted": 0,
    }
    agent_counts: dict[str, int] = {}
    position_counts: dict[str, int] = {}

    for match in matches:
        if not match:
            continue  # HenrikDev가 가끔 경기 데이터를 null로 내려줄 때가 있어요. 그런 항목은 건너뛰어요.

        stat = _extract_player_match_stats(match, name, tag)
        if stat is None:
            continue  # 이 유저 데이터를 못 찾은 경기는 건너뛰어요 (닉네임 변경 등)

        totals["kills"] += stat["kills"]
        totals["deaths"] += stat["deaths"]
        totals["assists"] += stat["assists"]
        totals["headshots"] += stat["headshots"]
        totals["bodyshots"] += stat["bodyshots"]
        totals["legshots"] += stat["legshots"]
        totals["damage_made"] += stat["damage_made"]
        totals["score"] += stat["score"]
        totals["total_rounds"] += stat["total_rounds"]
        totals["wins"] += 1 if stat["won"] else 0
        totals["matches_counted"] += 1

        agent_counts[stat["agent"]] = agent_counts.get(stat["agent"], 0) + 1

        position = AGENT_ROLE_MAP.get(stat["agent"])
        if position is not None:
            position_counts[position] = position_counts.get(position, 0) + 1

    if totals["matches_counted"] == 0:
        return None

    kd = totals["kills"] / max(totals["deaths"], 1)
    win_rate = (totals["wins"] / totals["matches_counted"]) * 100
    total_shots = totals["headshots"] + totals["bodyshots"] + totals["legshots"]
    hs_percent = (totals["headshots"] / total_shots * 100) if total_shots > 0 else 0.0
    adr = (totals["damage_made"] / totals["total_rounds"]) if totals["total_rounds"] > 0 else 0.0
    acs = (totals["score"] / totals["total_rounds"]) if totals["total_rounds"] > 0 else 0.0

    tier_multiplier = calculate_tier_multiplier(tier_id, rr)
    agwi_score = calculate_agwi_score(kd, adr, hs_percent, win_rate, tier_multiplier=tier_multiplier)
    grade, grade_color = get_agwi_grade(agwi_score)

    top_agents = sorted(agent_counts.items(), key=lambda item: item[1], reverse=True)[:2]
    top_position = max(position_counts, key=position_counts.get) if position_counts else None

    return {
        **totals,
        "kd": kd,
        "win_rate": win_rate,
        "hs_percent": hs_percent,
        "adr": adr,
        "acs": acs,
        "agwi_score": agwi_score,
        "agwi_grade": grade,
        "agwi_color": grade_color,
        "tier_id": tier_id,
        "tier_multiplier": tier_multiplier,
        "top_agents": top_agents,
        "position_counts": position_counts,
        "top_position": top_position,
    }


def build_summary_embed(
    닉네임: str, 태그: str, tier_name: str, rr: Optional[int], stats: dict,
    comp_count: int, used_fallback: bool, target: int,
) -> discord.Embed:
    n = stats["matches_counted"]

    kd_line = f"K/D 비율   : **{stats['kd']:.2f}**"
    percentile = get_kd_percentile(stats["kd"])
    if percentile is not None:
        kd_line += f" (봇 조회 유저 중 상위 {percentile:.0f}%)"

    agent_lines = " / ".join(
        f"{AGENT_KOREAN_NAMES.get(agent, agent)} ({count}경기)" for agent, count in stats["top_agents"]
    )
    position_line = ""
    if stats.get("top_position"):
        pos_count = stats["position_counts"][stats["top_position"]]
        position_line = f"\n주 포지션: **{stats['top_position']}** ({pos_count}/{n}경기)"

    if used_fallback:
        normal_count = n - comp_count
        match_summary_title = f"📊 최근 {n}경기 요약 통계 (경쟁전 {comp_count} + 일반전 {normal_count})"
    else:
        match_summary_title = f"📊 최근 경쟁전 {n}경기 요약 통계"

    divider = "━" * 32
    description = (
        f"{divider}\n"
        f"🏆 현재 티어: **{tier_name}**" + (f" ({rr} RR)" if rr is not None else "") + "\n"
        f"⚔️ 악귀 스코어: **{stats['agwi_score']:.0f}점 / {AGWI_MAX_SCORE:.0f}점** (**{stats['agwi_grade']}** 등급)\n"
        f"{divider}\n"
        f"{match_summary_title}\n"
        f"• {kd_line}\n"
        f"• 승률       : **{stats['win_rate']:.1f}%** ({stats['wins']}승 {n - stats['wins']}패)\n"
        f"• 헤드샷율   : **{stats['hs_percent']:.1f}%**\n"
        f"• 평균 딜량  : **{stats['adr']:.0f} ADR**\n"
        f"• 전투 점수  : **{stats['acs']:.0f} ACS**\n"
        f"{divider}\n"
        f"선호 요원: {agent_lines or '정보 없음'}"
        f"{position_line}"
    )

    if used_fallback:
        description += "\n\n⚠️ 경쟁전 표본이 적어(" + str(comp_count) + "경기) 일반전 기록도 함께 반영했어요."
    if n < target:
        description += f"\n⚠️ 목표 {target}경기 중 {n}경기만 찾았어요. (전체 플레이 기록 자체가 적을 수 있어요)"

    embed = discord.Embed(
        title=f"🎮 [{닉네임}#{태그}] 님의 발로란트 전적 리포트",
        description=description,
        color=stats["agwi_color"],
    )
    embed.set_footer(text="출처: HenrikDev API (비공식) · 악귀 스코어는 자체 산출 지표예요")
    return embed


def build_detail_embed(닉네임: str, 태그: str, stats: dict, comp_count: int, used_fallback: bool) -> discord.Embed:
    """'자세히 보기' 버튼을 눌렀을 때 계산에 쓰인 원본 수치를 보여줘요."""
    n = stats["matches_counted"]
    embed = discord.Embed(
        title=f"📎 {닉네임}#{태그} 상세 수치 (최근 {n}경기 합산)",
        color=stats["agwi_color"],
    )
    if used_fallback:
        embed.add_field(
            name="표본 구성",
            value=f"경쟁전 {comp_count}경기 + 일반전 {n - comp_count}경기 (경쟁전 표본 부족으로 일반전 보충)",
            inline=False,
        )
    embed.add_field(
        name="킬 / 데스 / 어시스트",
        value=f"{stats['kills']} / {stats['deaths']} / {stats['assists']}",
        inline=False,
    )
    embed.add_field(
        name="헤드샷 / 바디샷 / 레그샷",
        value=f"{stats['headshots']} / {stats['bodyshots']} / {stats['legshots']}",
        inline=False,
    )
    embed.add_field(name="총 가한 피해량", value=f"{stats['damage_made']:,}", inline=True)
    embed.add_field(name="총 전투 점수(Score)", value=f"{stats['score']:,}", inline=True)
    embed.add_field(name="총 플레이한 라운드 수", value=str(stats["total_rounds"]), inline=True)
    embed.add_field(name="승 / 패", value=f"{stats['wins']}승 {n - stats['wins']}패", inline=True)
    if stats.get("position_counts"):
        position_breakdown = " / ".join(
            f"{pos} {count}경기"
            for pos, count in sorted(stats["position_counts"].items(), key=lambda item: item[1], reverse=True)
        )
        embed.add_field(name="포지션별 플레이 횟수", value=position_breakdown, inline=False)
    embed.add_field(
        name="계산식",
        value=(
            "KD = 총 킬 ÷ 총 데스\n"
            "승률 = 승 ÷ 총 경기 수 × 100\n"
            "HS% = 헤드샷 ÷ (헤드샷+바디샷+레그샷) × 100\n"
            "ADR = 총 가한 피해량 ÷ 총 라운드 수\n"
            "ACS = 총 전투 점수 ÷ 총 라운드 수 (라이엇 공식 스탯)"
        ),
        inline=False,
    )

    kd_contrib = (stats["kd"] - 1.0) * AGWI_KD_WEIGHT
    adr_contrib = (stats["adr"] - 130.0) * AGWI_ADR_WEIGHT
    hs_contrib = (stats["hs_percent"] - 20.0) * AGWI_HS_WEIGHT
    wr_contrib = (stats["win_rate"] - 50.0) * AGWI_WINRATE_WEIGHT
    performance_delta = kd_contrib + adr_contrib + hs_contrib + wr_contrib
    tier_multiplier = stats.get("tier_multiplier")

    lines = [
        f"KD {stats['kd']:.2f} → ({stats['kd']:.2f} − 1.0) × {AGWI_KD_WEIGHT:.0f} = {kd_contrib:+.0f}점",
        f"ADR {stats['adr']:.0f} → ({stats['adr']:.0f} − 130) × {AGWI_ADR_WEIGHT:.0f} = {adr_contrib:+.0f}점",
        f"HS% {stats['hs_percent']:.1f}% → ({stats['hs_percent']:.1f} − 20) × {AGWI_HS_WEIGHT:.0f} = {hs_contrib:+.0f}점",
        f"승률 {stats['win_rate']:.1f}% → ({stats['win_rate']:.1f} − 50) × {AGWI_WINRATE_WEIGHT:.0f} = {wr_contrib:+.0f}점",
        "─────────────",
        f"성과 합계 = {performance_delta:+.0f}점",
    ]
    if tier_multiplier is not None:
        applied = performance_delta * tier_multiplier
        lines.append(f"티어 배수 = **×{tier_multiplier:.2f}** (실버3·0RR 기준 1.00배)")
        lines.append(f"반영값 = {performance_delta:+.0f} × {tier_multiplier:.2f} = {applied:+.0f}점")
    else:
        lines.append("티어 배수 = 정보 없음 (×1.00배로 계산됨)")
    lines.append(f"─────────────\n합계 = 기준점 {AGWI_BASELINE:.0f} + 반영값 = **{stats['agwi_score']:.0f}점** (0~{AGWI_MAX_SCORE:.0f} 범위로 제한)")

    embed.add_field(
        name="😈 악귀 스코어 상세 계산",
        value="\n".join(lines),
        inline=False,
    )
    embed.add_field(
        name="티어 배수 안내",
        value=(
            "배수 = 1.08 ^ (N − 9 + RR/100) · 실버3(0RR) = 1.00배 기준점\n"
            "N: 아이언1=1 ~ 레디언트=25 (단계별 인덱스) · 레디언트는 RR 100 초과도 그대로 반영돼요."
        ),
        inline=False,
    )
    sample_size = get_sample_size()
    embed.set_footer(text=f"상위 % 비교 표본: 이 봇에서 /전적을 조회한 {sample_size}명 기준")
    return embed


class RankDetailView(discord.ui.View):
    """'자세히 보기' 버튼 하나를 가진 뷰예요. 누른 사람에게만(ephemeral) 상세 수치를 보여줘요."""

    def __init__(self, 닉네임: str, 태그: str, stats: dict, comp_count: int, used_fallback: bool):
        super().__init__(timeout=300)
        self.닉네임 = 닉네임
        self.태그 = 태그
        self.stats = stats
        self.comp_count = comp_count
        self.used_fallback = used_fallback

    @discord.ui.button(label="📊 자세히 보기", style=discord.ButtonStyle.secondary)
    async def show_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_detail_embed(self.닉네임, self.태그, self.stats, self.comp_count, self.used_fallback)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Rank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.tier_icons: dict[int, str] = {}

    async def cog_load(self):
        # 요청마다 새로 세션을 만들면 매번 TCP/TLS 핸드셰이크 시간이 붙어요.
        # 코그가 로드될 때 세션을 하나만 만들어서 계속 재사용해요.
        timeout = aiohttp.ClientTimeout(total=15)  # 15초 넘게 응답이 없으면 그냥 실패 처리
        self.session = aiohttp.ClientSession(timeout=timeout)

        # 티어 아이콘 목록은 자주 안 바뀌니까 봇 켜질 때 한 번만 받아서 캐싱해둬요.
        self.tier_icons = await fetch_tier_icons(self.session)
        print(f"🖼️ 티어 아이콘 {len(self.tier_icons)}개를 불러왔어요.")

    async def cog_unload(self):
        if self.session is not None:
            await self.session.close()

    @app_commands.command(name="전적", description="발로란트 전적을 조회합니다. 닉네임/태그를 비우면 등록된 내 계정으로 조회돼요.")
    @app_commands.describe(
        닉네임="라이엇 아이디 (# 앞부분). 비우면 등록된 내 계정을 사용해요.",
        태그="태그 (# 뒷부분). 비우면 등록된 내 계정을 사용해요.",
        지역="계정 지역 (기본값: kr)",
        경기수=f"통계에 반영할 총 경기 수 (기본값: {DEFAULT_MATCH_COUNT}, 경쟁전 우선하고 부족하면 일반전으로 채워요, 최대 20)",
    )
    @app_commands.choices(지역=[app_commands.Choice(name=r, value=r) for r in REGION_CHOICES])
    @restrict_to_channel("tier_lookup")
    async def rank(
        self,
        interaction: discord.Interaction,
        닉네임: Optional[str] = None,
        태그: Optional[str] = None,
        지역: Optional[app_commands.Choice[str]] = None,
        경기수: Optional[app_commands.Range[int, 1, 20]] = None,
    ):
        await interaction.response.defer()

        api_key = os.getenv("HENRIKDEV_API_KEY")
        if not api_key:
            await interaction.followup.send("HENRIKDEV_API_KEY가 설정되지 않았어요. .env 파일을 확인해주세요.")
            return

        # 계정을 등록 안 했으면 닉네임/태그를 입력했어도 일단 등록부터 유도해요.
        account = get_account(interaction.user.id)
        if account is None:
            await interaction.followup.send(
                "아직 라이엇 계정이 등록되어 있지 않아요.\n"
                "먼저 `/티어 계정등록`으로 본인 계정을 등록해주세요! (등록 후엔 `/전적`만 입력해도 바로 조회돼요)",
                ephemeral=True,
            )
            return

        # 닉네임/태그를 안 적으면 등록해둔 본인 계정을 써요.
        if not 닉네임 or not 태그:
            닉네임, 태그 = account

        # 티어 역할 자동 갱신은 "본인이 등록해둔 계정"을 조회할 때만 적용돼요.
        # (안 그러면 남의 닉네임을 검색해서 그 사람 티어 역할을 그대로 받아가는 악용이 가능해져요)
        is_self_query = is_matching_account(interaction.user.id, 닉네임, 태그)

        region = 지역.value if 지역 else "kr"
        match_count = 경기수 or DEFAULT_MATCH_COUNT
        headers = {"Authorization": api_key}

        try:
            # 티어 + 경쟁전 + 일반전 최근 경기를 전부 동시에 보내요.
            # 일반전은 경쟁전 표본이 부족할 때만 쓰지만, 그때 가서 순차로 한 번 더 요청하면
            # (HenrikDev 응답이 원래 느려서) 왕복이 하나 더 붙어 체감 속도가 크게 느려지길래
            # 필요 여부와 상관없이 항상 병렬로 미리 받아둬요.
            _t0 = time.monotonic()
            (
                (mmr_status, mmr_payload),
                (comp_status, comp_payload),
                (normal_status, normal_payload),
            ) = await asyncio.gather(
                fetch_current_mmr(self.session, headers, region, 닉네임, 태그),
                fetch_matches_by_mode(self.session, headers, region, 닉네임, 태그, match_count, mode="competitive"),
                fetch_matches_by_mode(self.session, headers, region, 닉네임, 태그, match_count, mode="unrated"),
            )
            print(f"⏱️ [{닉네임}#{태그}] 티어+경쟁전+일반전 동시조회: {time.monotonic() - _t0:.2f}초")
        except asyncio.TimeoutError:
            await interaction.followup.send("HenrikDev API 응답이 너무 느려서 시간 초과됐어요. 잠시 후 다시 시도해주세요.")
            return
        except Exception as error:  # noqa: BLE001
            print(error)
            await interaction.followup.send("조회 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.")
            return

        if mmr_status != 200 or "data" not in mmr_payload:
            errors = mmr_payload.get("errors") or [{}]
            message = errors[0].get("message", "조회에 실패했어요. 닉네임/태그/지역을 확인해주세요.")
            await interaction.followup.send(f"오류: {message}")
            return

        mmr_data = mmr_payload["data"]
        current = mmr_data.get("current", {})
        tier_name = current.get("tier", {}).get("name", "정보 없음")
        tier_id = current.get("tier", {}).get("id")
        rr = current.get("rr")

        # ---- 티어 역할 자동 동기화 ----
        # 등록된 본인 계정을 조회한 경우에만: 역할이 없으면 새로 부여, 있는데 다르면 교체, 이미 맞으면 그대로 둬요.
        role_sync_note = None
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        korean_tier = parse_korean_tier(tier_name)

        if is_self_query and member is not None and korean_tier is not None:
            # 새로 역할을 만들 때 이미지 아이콘으로 쓰려고, 티어 아이콘을 미리 다운로드해둬요.
            # (이미 있는 역할을 재사용하는 경우엔 안 쓰이지만, 매번 새로 판별하기보단 그냥 가볍게 받아둬요)
            icon_bytes = None
            icon_url = self.tier_icons.get(tier_id) if tier_id is not None else None
            if icon_url:
                try:
                    async with self.session.get(icon_url) as icon_resp:
                        if icon_resp.status == 200:
                            icon_bytes = await icon_resp.read()
                except Exception as error:  # noqa: BLE001
                    print(f"⚠️ 티어 아이콘 이미지를 다운로드하지 못했어요: {error}")

            try:
                sync_result = await sync_tier_role(member, korean_tier, icon_bytes=icon_bytes)
                if sync_result["status"] == "new":
                    role_sync_note = f"🏷️ 티어 역할을 **{sync_result['role'].name}**(으)로 새로 부여했어요."
                elif sync_result["status"] == "updated":
                    role_sync_note = (
                        f"🔄 티어 역할을 **{sync_result['previous']} → {sync_result['role'].name}**(으)로 갱신했어요."
                    )
                # status가 "unchanged"면 이미 맞는 상태라 별도 안내 없이 넘어가요.
            except discord.Forbidden:
                role_sync_note = "⚠️ 봇에게 역할 관리 권한이 없어서 티어 역할을 갱신하지 못했어요."

        comp_matches = (comp_payload.get("data") or []) if comp_status == 200 else []
        normal_matches = (normal_payload.get("data") or []) if normal_status == 200 else []
        comp_stats = aggregate_match_stats(comp_matches, 닉네임, 태그, tier_id=tier_id, rr=rr)
        comp_count = comp_stats["matches_counted"] if comp_stats else 0

        stats = comp_stats
        used_fallback = False

        # 경쟁전 자체가 적은 "저활동 계정"이면, 목표치를 낮춰서(최소 LOW_ACTIVITY_TARGET) 일반전 반영량을 줄여요.
        effective_target = match_count
        if comp_count < LOW_ACTIVITY_TARGET:
            effective_target = min(match_count, LOW_ACTIVITY_TARGET)

        # 경쟁전만으로 목표 경기 수를 못 채우면, 이미 받아둔 일반전 중 부족한 만큼만 합쳐요.
        if comp_count < effective_target:
            remaining = effective_target - comp_count
            combined_matches = comp_matches + normal_matches[:remaining]
            combined_stats = aggregate_match_stats(combined_matches, 닉네임, 태그, tier_id=tier_id, rr=rr)
            if combined_stats is not None and combined_stats["matches_counted"] > comp_count:
                stats = combined_stats
                used_fallback = True

        if stats is None:
            embed = discord.Embed(
                title=f"🎮 [{닉네임}#{태그}] 님의 발로란트 전적 리포트",
                description=(
                    f"🏆 현재 티어: **{tier_name}**" + (f" ({rr} RR)" if rr is not None else "") + "\n\n"
                    "최근 경기 기록을 찾지 못했어요. (경기 기록이 없거나 비공개일 수 있어요)"
                ),
                color=0xFF4655,
            )
            if tier_id is not None and tier_id in self.tier_icons:
                embed.set_thumbnail(url=self.tier_icons[tier_id])
            if role_sync_note:
                embed.add_field(name="티어 역할", value=role_sync_note, inline=False)
            embed.set_footer(text="출처: HenrikDev API (비공식)")
            await interaction.followup.send(embed=embed)
            return

        # "상위 %" 계산용으로 이번 조회 결과를 저장해둬요.
        record_stats(f"{닉네임}#{태그}", stats["kd"], stats["agwi_score"])

        # ---- 포지션 역할 자동 동기화 ----
        # 티어 역할과 동일하게, 등록된 본인 계정을 조회한 경우에만 적용돼요.
        position_sync_note = None
        top_position = stats.get("top_position")

        if is_self_query and member is not None and top_position is not None:
            try:
                pos_result = await sync_position_role(member, top_position)
                if pos_result["status"] == "new":
                    position_sync_note = f"🎯 포지션 역할을 **{pos_result['role'].name}**(으)로 새로 부여했어요."
                elif pos_result["status"] == "updated":
                    position_sync_note = (
                        f"🔀 포지션 역할을 **{pos_result['previous']} → {pos_result['role'].name}**(으)로 갱신했어요."
                    )
            except discord.Forbidden:
                position_sync_note = "⚠️ 봇에게 역할 관리 권한이 없어서 포지션 역할을 갱신하지 못했어요."

        embed = build_summary_embed(닉네임, 태그, tier_name, rr, stats, comp_count, used_fallback, effective_target)
        if tier_id is not None and tier_id in self.tier_icons:
            embed.set_thumbnail(url=self.tier_icons[tier_id])
        if role_sync_note:
            embed.add_field(name="티어 역할", value=role_sync_note, inline=False)
        if position_sync_note:
            embed.add_field(name="포지션 역할", value=position_sync_note, inline=False)
        view = RankDetailView(닉네임, 태그, stats, comp_count, used_fallback)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Rank(bot))