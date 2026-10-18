"""📊 서버 주간 리포트 — 경제·활동 수치를 모아 AI 요약과 함께 운영자에게 보내요.

## 왜 (2026-10-18)

지금까지 경제 점검은 `scripts/report_economy.py`를 **사람이 손으로 돌려야** 했어요.
그래서 상점 구매가 0건인 걸 열흘 뒤에 알았어요. 주 1회 알아서 날아오면 그 지연이 없어져요.

- `/서버리포트` — 서버 소유자가 언제든 지금 수치를 봐요(ephemeral).
- 매주 월요일 아침, 소유자에게 DM으로 같은 리포트가 가요.

## 🚨 `@tasks.loop`은 예외 하나에 영구 정지해요

이 저장소에서 `/오상` 루프가 그렇게 죽은 적이 있어요. 로그 한 줄 없이 다시는 안 돌아요.
그래서 **`@loop.error`에서 반드시 restart** 해요. 그게 이 파일에서 제일 중요한 줄이에요.

## 🚨 숫자는 코드가 세고 해석만 AI가 해요

집계는 `utils/server_report.py`가 파이썬으로 하고, 모델에겐 계산된 표만 줘요.
AI가 실패하면 **표만 보내요** — 리포트 자체가 사라지면 안 되니까요.
"""
from __future__ import annotations

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import server_report

log = logging.getLogger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))

# 매일 이 시각에 깨어나서, 월요일일 때만 보내요.
# (`tasks.loop(time=...)`은 요일 조건을 못 받아서 안에서 걸러요.)
SEND_AT = datetime.time(hour=10, minute=0, tzinfo=KST)
SEND_WEEKDAY = 0  # 0 = 월요일


def build_embed(data: dict, note: str | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 서버 리포트 (최근 {data['days']}일)",
        color=0x9B59B6,
    )
    if note:
        embed.description = note

    embed.add_field(
        name="🪙 코인 흐름",
        value=(
            f"발행 **{data['issued']}** · 소각 **{data['burned']}**\n"
            f"소각률 **{data['burn_rate']:.1f}%** · 순증 **{data['net']:+}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 활동",
        value=(
            f"코인이 움직인 사람 **{data['active_people']}명**\n"
            f"지갑 {data['wallet_count']}개 · 총 **{data['wallet_total']}** · "
            f"중앙값 **{data['wallet_median']:.0f}**"
        ),
        inline=False,
    )

    if data["issue_by"]:
        embed.add_field(
            name="📈 발행처",
            value="\n".join(f"`{n}` {a}" for n, a in data["issue_by"]),
            inline=True,
        )
    if data["burn_by"]:
        embed.add_field(
            name="📉 소비처",
            value="\n".join(f"`{n}` {a}" for n, a in data["burn_by"]),
            inline=True,
        )
    if data["gamble_bet"]:
        embed.add_field(
            name="🎰 도박",
            value=(f"베팅 {data['gamble_bet']}코인 중 "
                   f"**{data['gamble_net']}코인**만 실제 소각"),
            inline=False,
        )

    embed.set_footer(text="숫자는 봇이 집계하고 해설만 AI가 써요 · 더 자세히는 scripts/report_economy.py")
    return embed


class OpsReport(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weekly_report.start()

    async def cog_unload(self):
        self.weekly_report.cancel()

    # ------------------------------------------------------------------
    @app_commands.command(
        name="서버리포트",
        description="[서버 소유자 전용] 최근 코인 경제·활동 수치를 봐요.",
    )
    @app_commands.describe(일수="며칠치를 볼지 (기본 7일)")
    async def report(self, interaction: discord.Interaction, 일수: int = 7):
        """🚨 집계가 Atlas를 여러 번 왕복해서 3초를 넘길 수 있어요. **먼저 defer.**"""
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send(
                "이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True
            )
            return

        days = max(1, min(일수, 90))
        data = await server_report.collect(days)
        note = await server_report.summarize(data)
        await interaction.followup.send(embed=build_embed(data, note), ephemeral=True)

    # ------------------------------------------------------------------
    @tasks.loop(time=SEND_AT)
    async def weekly_report(self):
        now = datetime.datetime.now(KST)
        if now.weekday() != SEND_WEEKDAY:
            return

        for guild in self.bot.guilds:
            owner = guild.owner
            if owner is None:
                continue
            try:
                data = await server_report.collect(7)
                note = await server_report.summarize(data)
                await owner.send(embed=build_embed(data, note))
                log.info("📊 주간 리포트를 %s 님에게 보냈어요.", owner.display_name)
            except discord.Forbidden:
                # DM이 막혀 있어도 다음 주에 또 시도해요(루프를 죽이지 않아요).
                log.info("📊 주간 리포트 DM이 막혀 있어요 (guild=%s)", guild.id)
            except Exception:  # noqa: BLE001
                log.warning("📊 주간 리포트 실패 (guild=%s)", guild.id, exc_info=True)

    @weekly_report.before_loop
    async def before_weekly(self):
        await self.bot.wait_until_ready()

    @weekly_report.error
    async def weekly_error(self, exc: BaseException):
        """🚨 **이게 없으면 루프가 영구 정지해요.**

        `@tasks.loop`은 처리되지 않은 예외가 하나만 나와도 다시는 안 돌아요. 로그도
        안 남아서 "어느 순간부터 리포트가 안 온다"가 돼요. 이 저장소에서 `/오상` 루프가
        실제로 그렇게 죽었어요."""
        log.error("📊 주간 리포트 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.weekly_report.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(OpsReport(bot))
