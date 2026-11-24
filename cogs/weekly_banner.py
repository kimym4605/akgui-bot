"""🖼️ 주간 서버 배너 — 매주 월요일 지난주 🏅 MVP와 🎣 낚시왕을 서버 배너에 걸어요 (2026-11-15).

## 왜

부스트 2레벨(BANNER 기능)이 생겼는데 배너가 비어 있었어요. 주간결산 발표는 채널에 들어가야
보이지만 배너는 서버를 여는 **모두가** 봐요. 상이 보여야 다음 주에 한 번 더 도전해요.

## 누구를 그리나

발표 cog와 **같은 규칙**으로 다시 뽑아요(`pick_mvp`, `fishing_week.top(by="size")`).
발표 결과를 저장해 두고 읽는 방식이 아니라서, 발표가 실패해도 배너는 따로 바뀌어요.

## 🚨 언제

월요일 11:40 — 🏅 MVP 발표(11:00)와 🎣 낚시 대회(11:30) **뒤에** 바꿔요.
발표 전에 배너가 먼저 바뀌면 스포일러예요.

## 🚨 손으로 올린 배너를 덮어써요

봇이 매주 덮어써요. 배너를 직접 꾸미고 싶으면 이 cog를 `bot.py`에서 빼야 해요.

## 🚨 `@tasks.loop`은 예외 하나에 영구 정지해요 → `@loop.error`에서 `restart()`.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.weekly_mvp import pick_mvp
from utils import agwi_weekly_store, fishing_week, server_banner, server_goal
from utils.fish_data import BY_KEY

log = logging.getLogger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))
SEND_AT = datetime.time(hour=11, minute=40, tzinfo=KST)
SEND_WEEKDAY = 0  # 월요일


async def _avatar(member: discord.Member) -> bytes | None:
    try:
        return await member.display_avatar.replace(size=256, static_format="png").read()
    except (discord.HTTPException, ValueError):
        return None


async def collect(guild: discord.Guild, week: str) -> list[server_banner.Slot]:
    """배너에 넣을 칸을 모아요. 서버에 없는 사람은 건너뛰어요."""
    slots: list[server_banner.Slot] = []

    row = pick_mvp(await agwi_weekly_store.top(week, limit=25))
    member = guild.get_member(int(row["userId"])) if row else None
    if member is not None:
        slots.append(server_banner.Slot(
            label="주간 MVP",
            name=server_banner.clean_name(member.display_name, member.name),
            line=f"악귀력 {row.get('score', 0):,.0f}점",
            avatar=await _avatar(member),
            color=server_banner.GOLD,
        ))

    big = await fishing_week.top(week, by="size", limit=1)
    member = guild.get_member(int(big[0]["userId"])) if big else None
    if member is not None:
        doc = big[0]
        fish = BY_KEY.get(doc.get("bestKey"), ("", "물고기"))[1]
        slots.append(server_banner.Slot(
            label="이주의 낚시왕",
            name=server_banner.clean_name(member.display_name, member.name),
            line=server_banner.clean_name(f"{fish} {doc.get('bestSize') or 0}cm", "최대어"),
            avatar=await _avatar(member),
            color=server_banner.BLUE,
        ))
    return slots


async def update_banner(guild: discord.Guild, week: str) -> tuple[str, bytes | None]:
    """배너를 그려서 걸어요. (결과 설명, 그린 PNG)"""
    if "BANNER" not in guild.features:
        return "이 서버는 배너를 쓸 수 없어요(부스트 2레벨 필요).", None
    slots = await collect(guild, week)
    # 🤝 지난주 공동 목표 결과 한 줄(2026-11-25). 못 읽어도 배너는 그대로 걸어요.
    try:
        footer = server_goal.banner_line(await server_goal.summary(week))
    except Exception:  # noqa: BLE001
        log.warning("🖼️ 배너: 공동 목표 결과를 못 읽었어요", exc_info=True)
        footer = None
    # 그림 그리기는 CPU 일이라 루프를 막지 않게 스레드로 보내요.
    png = await asyncio.to_thread(server_banner.render, week, slots, footer)
    try:
        await guild.edit(banner=png, reason=f"주간 배너 {week}")
    except discord.Forbidden:
        return "배너를 바꿀 권한(서버 관리)이 없어요.", png
    except discord.HTTPException as exc:
        return f"배너를 올리다 실패했어요: {exc}", png
    who = ", ".join(f"{s.label} {s.name}" for s in slots) or "주인공 없음"
    return f"{week} 배너로 바꿨어요 — {who}", png


class WeeklyBanner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.banner_loop.start()

    async def cog_unload(self):
        self.banner_loop.cancel()

    @app_commands.command(
        name="배너갱신",
        description="[서버 소유자 전용] 서버 배너를 지난주 MVP·낚시왕으로 지금 바꿔요.",
    )
    @app_commands.describe(주차="예: 2026-W45. 비우면 지난주예요.")
    async def refresh(self, interaction: discord.Interaction, 주차: str | None = None):
        # 🚨 DB·아바타·그림·업로드라 몇 초 걸려요 → 무조건 먼저 defer.
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return
        week = (주차 or "").strip() or agwi_weekly_store.previous_week_key()
        result, png = await update_banner(interaction.guild, week)
        files = [discord.File(io.BytesIO(png), "banner.png")] if png else []
        await interaction.followup.send(result, files=files, ephemeral=True)

    @tasks.loop(time=SEND_AT)
    async def banner_loop(self):
        if datetime.datetime.now(KST).weekday() != SEND_WEEKDAY:
            return
        week = agwi_weekly_store.previous_week_key()
        for guild in self.bot.guilds:
            try:
                result, _ = await update_banner(guild, week)
                log.info("🖼️ 주간 배너: %s", result)
            except Exception:  # noqa: BLE001
                log.warning("🖼️ 주간 배너 실패 (guild=%s)", guild.id, exc_info=True)

    @banner_loop.before_loop
    async def before_banner(self):
        await self.bot.wait_until_ready()

    @banner_loop.error
    async def banner_error(self, exc: BaseException):
        log.error("🖼️ 주간 배너 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.banner_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyBanner(bot))
