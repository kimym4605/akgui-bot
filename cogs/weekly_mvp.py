"""🏅 주간 MVP — 지난주 악귀력 1위를 발표하고 역할을 줘요.

## 왜 (2026-10-18)

`agwi_weekly`에 주차별 점수·등급·전적이 이미 쌓이고 있는데(W40 13명 · W41 9명 · W42 4명)
아무도 그걸 **끝맺지** 않았어요. `/주간랭킹`을 쳐야만 보이고, 한 주가 끝나도 아무 일도
일어나지 않아요. 주마다 매듭이 지어지면 다음 주에 한 번 더 돌릴 이유가 생겨요.

## 🚨 역할 이름은 코드가 만들어요

디스코드에서 손으로 역할 이름을 바꾸면 **중복이 생겨요.** 이 저장소에서 반복된 사고예요.
역할을 찾을 때는 ID가 아니라 **이름으로 정확히 일치** 비교하고, 없으면 만들어요.

## 🚨 `@tasks.loop`은 예외 하나에 영구 정지해요

`@loop.error`에서 `restart()` 하지 않으면 어느 순간부터 조용히 발표가 멈춰요
(`/오상` 루프가 실제로 그렇게 죽었어요).

## 최소 경기 수를 두는 이유

한 판만 하고 운 좋게 높은 점수가 나온 사람이 MVP가 되면 아무도 납득하지 않아요.
`MIN_MATCHES`를 못 채우면 후보에서 빼요.
"""
from __future__ import annotations

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import agwi_weekly_store
from utils.channel_check import get_allowed_channel_id

log = logging.getLogger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))

ROLE_NAME = "🏅 주간 MVP"
ROLE_COLOR = discord.Color(0xFFD700)

# 발표는 주간랭킹과 같은 채널(프로필·업적 그룹)에 해요.
CHANNEL_GROUP = "profile"

# 월요일 아침에 지난주를 결산해요.
SEND_AT = datetime.time(hour=11, minute=0, tzinfo=KST)
SEND_WEEKDAY = 0  # 0 = 월요일

# 🚨 표본이 너무 적으면 MVP로 치지 않아요. 한 판 운으로 1위가 되면 아무도 납득 못 해요.
MIN_MATCHES = 3


def pick_mvp(rows: list[dict]) -> dict | None:
    """점수 1위를 고르되, 표본이 모자란 사람은 건너뛰어요."""
    for row in sorted(rows, key=lambda r: -(r.get("score") or 0)):
        matches = ((row.get("stats") or {}).get("matches")) or 0
        if matches >= MIN_MATCHES:
            return row
    return None


def build_embed(row: dict, week: str, display_name: str, total: int) -> discord.Embed:
    stats = row.get("stats") or {}
    embed = discord.Embed(
        title=f"🏅 {week} 주간 MVP — {display_name}",
        description=f"지난주 악귀력 **{row.get('score', 0):,.0f}점**"
                    + (f" · **{row['grade']}** 등급" if row.get("grade") else ""),
        color=ROLE_COLOR,
    )
    bits = []
    if stats.get("kd") is not None:
        bits.append(f"KD **{stats['kd']}**")
    if stats.get("winRate") is not None:
        bits.append(f"승률 **{stats['winRate']}%**")
    if stats.get("hs") is not None:
        bits.append(f"HS **{stats['hs']}%**")
    if stats.get("matches"):
        bits.append(f"**{stats['matches']}경기**")
    if bits:
        embed.add_field(name="지난주 성적", value=" · ".join(bits), inline=False)

    embed.add_field(
        name="어떻게 뽑나요",
        value=(f"그 주에 `/전적`을 돌린 사람 중 **악귀력 1위**예요 "
               f"(최소 {MIN_MATCHES}경기).\n"
               f"　└ 지난주에는 **{total}명**이 기록을 남겼어요"),
        inline=False,
    )
    embed.set_footer(text="역할은 다음 주 MVP가 나올 때까지 유지돼요")
    return embed


async def ensure_role(guild: discord.Guild) -> discord.Role | None:
    """MVP 역할을 찾거나 만들어요.

    🚨 **이름으로 정확히 일치** 비교해요. 디스코드에서 손으로 바꾸면 중복이 생기는데,
    `in` 비교를 쓰면 엉뚱한 역할을 집어요."""
    existing = discord.utils.find(lambda r: r.name == ROLE_NAME, guild.roles)
    if existing is not None:
        return existing
    try:
        return await guild.create_role(
            name=ROLE_NAME,
            color=ROLE_COLOR,
            hoist=False,
            mentionable=False,
            reason="주간 MVP 역할 자동 생성",
        )
    except discord.Forbidden:
        log.info("🏅 역할 생성 권한이 없어요 (guild=%s)", guild.id)
        return None


async def hand_over_role(guild: discord.Guild, winner: discord.Member) -> bool:
    """이전 보유자에게서 회수하고 새 MVP에게 줘요. 성공하면 True."""
    role = await ensure_role(guild)
    if role is None:
        return False

    try:
        # ⚠️ 먼저 회수해요. 주고 나서 회수하면 중간에 실패했을 때 두 명이 달고 있어요.
        for member in list(role.members):
            if member.id != winner.id:
                await member.remove_roles(role, reason="주간 MVP 교체")
        if role not in winner.roles:
            await winner.add_roles(role, reason="주간 MVP 선정")
        return True
    except discord.Forbidden:
        log.info("🏅 역할 부여 권한이 없어요 (guild=%s)", guild.id)
        return False


class WeeklyMVP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.announce_loop.start()

    async def cog_unload(self):
        self.announce_loop.cancel()

    # ------------------------------------------------------------------
    async def announce(self, guild: discord.Guild, week: str) -> str:
        """한 길드에 대해 MVP를 발표해요. 결과 설명을 돌려줘요(명령어가 그대로 보여줘요)."""
        rows = await agwi_weekly_store.top(week, limit=25)
        if not rows:
            return f"{week}에는 `/전적`을 돌린 사람이 없어서 MVP가 없어요."

        winner_row = pick_mvp(rows)
        if winner_row is None:
            return (f"{week}에는 **{MIN_MATCHES}경기 이상** 한 사람이 없어서 "
                    "MVP를 뽑지 않았어요.")

        member = guild.get_member(int(winner_row["userId"]))
        if member is None:
            return f"{week} 1위가 서버에 없어요(탈퇴했을 수 있어요)."

        given = await hand_over_role(guild, member)

        channel_id = get_allowed_channel_id(CHANNEL_GROUP)
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return (f"MVP는 **{member.display_name}** 님인데, 발표할 채널이 없어요. "
                    "`/채널설정 프로필·업적`으로 정해주세요.")

        embed = build_embed(winner_row, week, member.display_name, len(rows))
        await channel.send(content=f"🎉 {member.mention}", embed=embed)
        note = "" if given else "\n⚠️ 역할은 권한이 없어 못 줬어요."
        return f"{channel.mention}에 발표했어요 — **{member.display_name}** 님{note}"

    # ------------------------------------------------------------------
    @app_commands.command(
        name="주간mvp",
        description="[서버 소유자 전용] 지난주 MVP를 지금 발표해요.",
    )
    @app_commands.describe(주차="예: 2026-W41. 비우면 지난주예요.")
    async def mvp_now(self, interaction: discord.Interaction, 주차: str | None = None):
        """🚨 DB를 여러 번 왕복하니 **먼저 defer**."""
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send(
                "이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True
            )
            return

        week = (주차 or "").strip() or agwi_weekly_store.previous_week_key()
        result = await self.announce(interaction.guild, week)
        await interaction.followup.send(result, ephemeral=True)

    # ------------------------------------------------------------------
    @tasks.loop(time=SEND_AT)
    async def announce_loop(self):
        if datetime.datetime.now(KST).weekday() != SEND_WEEKDAY:
            return

        week = agwi_weekly_store.previous_week_key()
        for guild in self.bot.guilds:
            try:
                result = await self.announce(guild, week)
                log.info("🏅 주간 MVP: %s", result)
            except Exception:  # noqa: BLE001
                log.warning("🏅 주간 MVP 발표 실패 (guild=%s)", guild.id, exc_info=True)

    @announce_loop.before_loop
    async def before_announce(self):
        await self.bot.wait_until_ready()

    @announce_loop.error
    async def announce_error(self, exc: BaseException):
        """🚨 **이게 없으면 루프가 영구 정지해요.** 이 저장소에서 실제로 겪은 사고예요."""
        log.error("🏅 주간 MVP 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.announce_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyMVP(bot))
