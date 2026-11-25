"""🧭 /패널 — 채널에 상설 패널을 박는 명령어 하나로 모았어요.

## 왜 (2026-11-26)

디스코드는 봇 하나에 **전역 슬래시 명령어를 100개까지만** 받아요. 100개를 꽉 채운 채로
명령어 2개(`/내작전판`·`/작전판패널`)를 더해 배포했다가 봇이 시작하다 꺼졌어요(`CommandLimitReached`).
그래서 서버 소유자만 가끔 쓰는 `/상점패널`·`/낚시패널`·`/카드패널`·`/방패널`·`/발로들패널`·
`/공동목표패널`·`/정모패널` 7개를 이 명령어 하나로 합쳐 **6자리**를 비웠어요.

## 구조

- 패널을 올리는 일은 **각 cog의 `panel(interaction, ...)` 함수가 그대로** 해요(소유자·운영진 검사, 응답,
  예전 패널 지우기까지). 여기서는 종류를 골라 그 함수를 불러 주기만 해요.
- 🚨 각 `panel`은 **응답을 스스로 해요**(`response.send_message` 또는 `ack`). 여기서 먼저 응답하면
  "이미 응답함" 오류가 나니 아무 응답도 하지 않고 넘겨요.
- 새 패널을 만들면 cog에 `panel(self, interaction)`을 두고 아래 `PANELS`에 한 줄만 더하세요.
  **새 슬래시 명령어를 만들지 마세요** — `python scripts/test_command_limit.py`가 막아요.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

import discord
from discord import app_commands
from discord.ext import commands

from cogs.room import ROOM_KINDS

log = logging.getLogger("akgui")


class Panel(NamedTuple):
    label: str      # 선택지에 보이는 이름
    module: str     # 그 패널을 가진 cog의 모듈 (`cogs.xxx`)


# 순서 = 선택지 순서. 키는 선택지 값이에요(테스트가 이 키로 봐요).
PANELS: dict[str, Panel] = {
    "shop": Panel("🪙 악귀상점", "cogs.akgui_shop"),
    "fishing": Panel("🎣 낚시", "cogs.fishing"),
    "card": Panel("🎴 악귀카드", "cogs.card_gacha"),
    "room": Panel("🔊 통화방 (방종류로 골라 올리기)", "cogs.room"),
    "balodle": Panel("🧩 발로들", "cogs.balodle"),
    "goal": Panel("🤝 서버 공동 목표", "cogs.server_goal"),
    "tactics": Panel("🗺️ 작전판", "cogs.tactics"),
    "meetup": Panel("🎿 정모 참가 신청 (운영진)", "cogs.meetup"),
}

ROOM_CHOICES = [app_commands.Choice(name=cfg["choice_name"], value=key) for key, cfg in ROOM_KINDS.items()]


class Panels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog_for(self, module: str) -> commands.Cog | None:
        """모듈 이름으로 cog를 찾아요(클래스 이름이 바뀌어도 안 깨지게)."""
        return next((cog for cog in self.bot.cogs.values() if type(cog).__module__ == module), None)

    @app_commands.command(
        name="패널",
        description="[서버 소유자] 이 채널에 상설 패널을 박아둬요 (상점·낚시·카드·방·발로들·공동목표·작전판·정모)",
    )
    @app_commands.describe(
        종류="올릴 패널",
        방종류="🔊 통화방 패널일 때만: 이 채널에 보여줄 방 종류 (안 고르면 전부)",
        방종류2="🔊 통화방 패널일 때만: 한 채널에 두 종류를 같이 올릴 때",
    )
    @app_commands.choices(
        종류=[app_commands.Choice(name=p.label, value=key) for key, p in PANELS.items()],
        방종류=ROOM_CHOICES,
        방종류2=ROOM_CHOICES,
    )
    async def panel(
        self, interaction: discord.Interaction,
        종류: app_commands.Choice[str],
        방종류: app_commands.Choice[str] | None = None,
        방종류2: app_commands.Choice[str] | None = None,
    ):
        spec = PANELS.get(종류.value)
        cog = self.cog_for(spec.module) if spec else None
        if cog is None or not hasattr(cog, "panel"):
            log.warning("🧭 /패널 %s: cog가 안 실려 있어요 (%s)", 종류.value, spec.module if spec else "?")
            await interaction.response.send_message("그 패널은 지금 쓸 수 없어요. 조금 뒤 다시 해 주세요.",
                                                    ephemeral=True)
            return
        if 종류.value == "room":
            await cog.panel(interaction, 방종류, 방종류2)
        else:
            await cog.panel(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Panels(bot))
