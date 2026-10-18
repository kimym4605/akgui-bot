"""⏰ 연속 출석이 끊기기 전에 DM으로 알려줘요.

## 왜 (2026-10-18 실측)

출석 상위권은 55일·46일·26일로 꾸준한데, **누적 5회 이상인데 연속이 끊긴 사람이 6명**.
그중엔 누적 41회인데 연속 3일인 사람도 있어요. 끊겼다는 걸 알려주는 사람이 없었어요.

🚨 이게 **🧊 보호권이 열흘 넘게 0건**인 이유로도 보여요 — 보호권은 끊기기 **전에**
사둬야 쓸모 있는데, 사람들은 끊긴 뒤에야 아쉬워하거든요.

## 🚨 알림은 금방 미움받아요

`utils/attend_remind.py`가 대상을 좁게 잡아요(연속 3일 이상 · 최근 3일 안에 출석한 사람).
여기서는 거기에 더해:

- **하루에 한 번만** 돌아요(밤 10시).
- DM이 막혀 있으면 조용히 넘어가요. 채널에 대신 올리지 않아요 — 그건 더 거슬려요.
- `/알림설정`에서 끌 수 있어요.
- 🚨 `@loop.error`에서 **반드시 restart** — 안 그러면 예외 하나에 영구 정지해요.
"""
from __future__ import annotations

import asyncio
import datetime
import logging

import discord
from discord.ext import commands, tasks

from utils import attend_remind, inventory_store, notify_prefs

log = logging.getLogger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))

# 밤 10시. 자정 전에 여유가 있으면서, 자고 있을 시간은 아니에요.
SEND_AT = datetime.time(hour=22, minute=0, tzinfo=KST)

# DM을 연달아 쏘면 레이트리밋에 걸려요. 사이를 조금 띄워요.
SEND_GAP_SECONDS = 1.0

NOTIFY_KEY = "attend_remind"


class AttendRemind(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.remind_loop.start()

    async def cog_unload(self):
        self.remind_loop.cancel()

    async def run_once(self) -> tuple[int, int]:
        """(보낸 수, 대상 수). 테스트·수동 실행에서도 쓰려고 떼어뒀어요."""
        rows = await attend_remind.candidates()
        sent = 0

        for row in rows:
            uid = int(row["userId"])
            if not await notify_prefs.is_enabled(uid, NOTIFY_KEY):
                continue

            user = self.bot.get_user(uid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(uid)
                except discord.HTTPException:
                    continue

            protects = await inventory_store.protect_count(uid)
            try:
                await user.send(attend_remind.message_for(row["streak"], protects))
                sent += 1
            except discord.Forbidden:
                # DM을 막아둔 사람이에요. 채널에 대신 올리지 않아요 — 더 거슬려요.
                pass
            except discord.HTTPException:
                log.info("⏰ 출석 알림 DM 실패 (user=%s)", uid)
            await asyncio.sleep(SEND_GAP_SECONDS)

        if rows:
            log.info("⏰ 출석 리마인더: 대상 %d명 중 %d명에게 보냈어요", len(rows), sent)
        return sent, len(rows)

    @tasks.loop(time=SEND_AT)
    async def remind_loop(self):
        try:
            await self.run_once()
        except Exception:  # noqa: BLE001
            log.warning("⏰ 출석 리마인더 실패", exc_info=True)

    @remind_loop.before_loop
    async def before_remind(self):
        await self.bot.wait_until_ready()

    @remind_loop.error
    async def remind_error(self, exc: BaseException):
        """🚨 **이게 없으면 루프가 영구 정지해요.** 이 저장소에서 실제로 겪은 사고예요."""
        log.error("⏰ 출석 리마인더 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.remind_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(AttendRemind(bot))
