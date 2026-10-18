"""🎙️ 음성 활동 레벨 — `/음성레벨` · `/음성랭킹`, 레벨업 역할 부여.

## 왜 (2026-10-18)

통화방이 서버에서 **참여가 가장 넓은 활동**인데(실측 36명 / 지갑 58개 중 62%) 보상이
하루 1코인뿐이라, 두 시간을 있든 삼십 분을 있든 같았어요. 쌓인 시간이 보이면
이미 하던 행동에 의미가 붙어요.

## 🚨 코인은 안 줘요

낚시가 이미 발행의 70%예요. 통화에까지 코인을 얹으면 경제가 또 기울어요.
레벨은 **역할과 숫자만** 줘요(경제는 코인, 명예는 레벨).

## 🚨 시간 측정은 `cogs/mission.py`가 해요

입·퇴장 감지와 5분 중간 정산, 혼자 접속 어뷰징 차단이 **이미 거기 있어요.**
여기서 또 추적하면 두 벌이 되어 어긋나요. 거기서 정산할 때 이 cog의 적립을 같이 불러요.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import voice_level

log = logging.getLogger(__name__)

MEDALS = ("🥇", "🥈", "🥉")


async def sync_role(member: discord.Member, level: int) -> str | None:
    """레벨에 맞는 역할만 남겨요. 새로 붙인 역할 이름을 돌려줘요(없으면 None).

    🚨 역할 이름은 **코드가 만들어요.** 디스코드에서 손으로 바꾸면 중복이 생겨서,
    이름으로 정확히 일치 비교하고 없으면 만들어요(이 저장소에서 반복된 사고예요)."""
    target = voice_level.role_for(level)
    guild = member.guild

    # 지금 달고 있는 통화 역할 중 target이 아닌 건 떼요.
    # ⚠️ **떼는 걸 먼저** 해요. 붙이고 떼면 중간에 실패했을 때 두 개가 달려요.
    for role in list(member.roles):
        if role.name in voice_level.ROLE_NAMES and role.name != target:
            try:
                await member.remove_roles(role, reason="음성 레벨 변경")
            except discord.Forbidden:
                return None

    if target is None:
        return None
    if any(r.name == target for r in member.roles):
        return None  # 이미 달고 있어요

    role = discord.utils.find(lambda r: r.name == target, guild.roles)
    try:
        if role is None:
            role = await guild.create_role(
                name=target, colour=discord.Colour(0x5865F2),
                hoist=False, mentionable=False,
                reason="음성 레벨 역할 자동 생성",
            )
        await member.add_roles(role, reason="음성 레벨 달성")
    except discord.Forbidden:
        log.info("🎙️ 역할 권한이 없어요 (guild=%s)", guild.id)
        return None
    return target


async def on_minutes_added(member: discord.Member, minutes: int, channel) -> None:
    """미션 정산이 끝난 뒤 불려요. 적립하고, 레벨이 올랐으면 알려줘요.

    🚨 **여기서 예외가 나도 미션·코인은 이미 끝난 뒤여야** 해요. 부르는 쪽이 감싸지만
    이 함수도 조용히 실패하도록 짰어요."""
    before, after, total, _week = await voice_level.add_minutes(member.id, minutes)
    if after <= before:
        return  # 레벨 그대로

    new_role = await sync_role(member, after)

    text = (f"🎙️ {member.mention} 음성 레벨 **{after}** 달성! "
            f"(누적 {voice_level.format_minutes(total)})")
    if new_role:
        text += f"\n　└ 역할 **{new_role}** 을 받았어요"
    try:
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, AttributeError):
        log.info("🎙️ 레벨업 알림 실패 (user=%s)", member.id)


class VoiceRank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="음성레벨", description="통화방에 머문 시간과 레벨을 봐요.")
    @app_commands.describe(유저="다른 사람 걸 보려면 지정하세요.")
    async def my_level(
        self, interaction: discord.Interaction, 유저: discord.Member | None = None
    ):
        await interaction.response.defer()
        target = 유저 or interaction.user
        data = await voice_level.get(target.id)
        level, done, need = voice_level.progress(data["minutes"])

        filled = int(10 * done / need) if need else 0
        bar = "▓" * filled + "░" * (10 - filled)

        embed = discord.Embed(
            title=f"🎙️ {target.display_name} 님의 음성 활동",
            color=0x5865F2,
        )
        embed.add_field(name="레벨", value=f"**Lv.{level}**", inline=True)
        embed.add_field(name="누적", value=voice_level.format_minutes(data["minutes"]),
                        inline=True)
        embed.add_field(name="이번 주", value=voice_level.format_minutes(data["weekMinutes"]),
                        inline=True)
        embed.add_field(
            name="다음 레벨까지",
            value=f"`{bar}` {voice_level.format_minutes(need - done)} 남음",
            inline=False,
        )
        role = voice_level.role_for(level)
        if role:
            embed.add_field(name="역할", value=role, inline=False)
        else:
            next_need, next_name = voice_level.ROLE_TIERS[-1]
            embed.add_field(
                name="역할",
                value=f"**Lv.{next_need}** 부터 {next_name} 역할을 받아요",
                inline=False,
            )
        embed.set_footer(text="혼자 있는 시간은 세지 않아요 (2명 이상일 때만)")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="음성랭킹", description="통화방에 오래 머문 사람 순위를 봐요.")
    @app_commands.describe(기간="이번 주만 볼지, 누적으로 볼지")
    @app_commands.choices(기간=[
        app_commands.Choice(name="📅 이번 주", value="week"),
        app_commands.Choice(name="🏆 누적", value="total"),
    ])
    async def ranking(
        self, interaction: discord.Interaction,
        기간: app_commands.Choice[str] | None = None,
    ):
        await interaction.response.defer()
        weekly = (기간.value if 기간 else "week") == "week"
        rows = await voice_level.top(10, weekly=weekly)

        if not rows:
            await interaction.followup.send(
                "아직 기록이 없어요. 통화방에서 **2명 이상** 있으면 시간이 쌓여요.")
            return

        lines = []
        for i, row in enumerate(rows):
            mark = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            lines.append(
                f"{mark} <@{row['userId']}> **{voice_level.format_minutes(row['minutes'])}**"
                f"　`Lv.{row['level']}`"
            )

        embed = discord.Embed(
            title=f"🎙️ 음성 활동 {'이번 주' if weekly else '누적'} 순위",
            description="\n".join(lines),
            color=0x5865F2,
        )
        embed.set_footer(text="혼자 있는 시간은 세지 않아요 · 5분마다 정산돼요")
        await interaction.followup.send(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceRank(bot))
