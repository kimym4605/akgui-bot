"""키우미집(Day Care) 알 생성/부화 진행도를 디스코드 음성채널 잔류 시간으로도 채워줘요.

웹의 탐험 1회 = 1틱과 나란히, 음성채널 잔류 10분 = 1틱으로 daycare_store.tick_steps()를
호출해요(둘 중 하나만 채워도 진행 - 웹 explore와 이 봇이 같은 trainer["daycare"] 필드를
같이 채워나가는 구조). 슬래시 명령어는 없고 순수 백그라운드 리스너예요.

지금 맡겨둔 알이 있을 때만, 통화방을 나갈 때마다 이번 통화로 얼마나 진행됐는지 DM으로
알려줘요(알이 없으면 - 아직 궁합 맞는 짝을 안 맡겼거나 알 생성 진행 중이면 - 조용히 넘어가요).
DM이 막혀있는 유저는 discord.Forbidden을 조용히 무시해요.

웹 키우미집 화면에서 "실시간으로 차오르는" 느낌을 내기 위해, 통화 시작 시각을
trainer["daycare"]["voiceSessionStart"](UTC ISO 문자열)로 즉시 DB에 남겨요 - 실제 틱 반영은
여전히 나갈 때/5분 주기 flush 때만 하지만, 웹은 이 시작 시각만 보고도 매초 클라이언트에서
경과 시간을 계산해 진행바를 부드럽게 움직일 수 있어요. 통화가 끝나거나(나감) flush로 한 번
반영될 때마다 이 시각을 지우거나(끝) 지금 시각으로 갱신해요(계속 중)."""
import logging

import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone

from utils import daycare_store
from utils.pokemon_store import get_trainer, has_trainer, save_trainer

log = logging.getLogger(__name__)

VOICE_MINUTES_PER_TICK = 10
FLUSH_INTERVAL_MINUTES = 5  # 통화를 오래 켜놔도 나갈 때까지 안 기다리고 주기적으로 틱을 반영해요.


def _voice_channel(state: discord.VoiceState) -> discord.abc.Connectable | None:
    """AFK 채널에 있는 건 '통화 중'으로 안 쳐요."""
    channel = state.channel
    if channel is None:
        return None
    afk_channel = getattr(channel.guild, "afk_channel", None)
    if afk_channel is not None and channel.id == afk_channel.id:
        return None
    return channel


def _progress_bar(progress: int, needed: int, length: int = 10) -> str:
    if needed <= 0:
        return "🟩" * length
    filled = min(length, int(length * progress / needed))
    return "🟩" * filled + "⬜" * (length - filled)


class DaycareVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session_start: dict[int, datetime] = {}
        self.flush_sessions.start()

    def cog_unload(self):
        self.flush_sessions.cancel()

    async def _mark_session_start(self, user_id: int):
        """통화 시작 순간 즉시 DB에 시각을 남겨요 - 웹이 이걸 보고 실시간 진행바를 그려요."""
        if not await has_trainer(user_id):
            return
        trainer = await get_trainer(user_id)
        if trainer is None:
            return
        daycare = trainer.setdefault("daycare", {"slots": [None, None], "egg": None, "pairTicks": 0})
        daycare["voiceSessionStart"] = datetime.now(timezone.utc).isoformat()
        await save_trainer(user_id, trainer)

    async def _process(self, user_id: int, elapsed_minutes: float, still_in_voice: bool) -> dict | None:
        """진행 반영 후, 지금 맡겨둔 알이 있으면 알림용 정보를 돌려주고 없으면 None이에요.
        still_in_voice=True면(주기적 flush 도중) voiceSessionStart를 지금 시각으로 갱신해서
        웹의 실시간 표시가 끊기지 않게 하고, False면(진짜로 나감) 아예 지워요."""
        if not await has_trainer(user_id):
            return None
        trainer = await get_trainer(user_id)
        if trainer is None:
            return None
        daycare = trainer.setdefault("daycare", {"slots": [None, None], "egg": None, "pairTicks": 0})

        ticks = 0
        if elapsed_minutes > 0:
            carry = daycare.get("voiceCarryMinutes", 0) + elapsed_minutes
            ticks = int(carry // VOICE_MINUTES_PER_TICK)
            daycare["voiceCarryMinutes"] = carry - ticks * VOICE_MINUTES_PER_TICK
            for _ in range(ticks):
                daycare_store.tick_steps(trainer)

        daycare["voiceSessionStart"] = datetime.now(timezone.utc).isoformat() if still_in_voice else None
        await save_trainer(user_id, trainer)

        if ticks <= 0:
            return None
        egg = daycare.get("egg")
        if egg is None:
            return None
        return {
            "elapsedMinutes": elapsed_minutes,
            "species": egg["species"],
            "ticksProgress": egg["ticksProgress"],
            "ticksNeeded": egg["ticksNeeded"],
            "ready": egg["ticksProgress"] >= egg["ticksNeeded"],
        }

    async def _notify(self, member: discord.Member, info: dict):
        minutes = round(info["elapsedMinutes"])
        bar = _progress_bar(info["ticksProgress"], info["ticksNeeded"])
        lines = [f"🥚 통화 {minutes}분 함께해서 **{info['species']}** 알 부화가 진행됐어요!"]
        lines.append(f"{bar} {info['ticksProgress']}/{info['ticksNeeded']}")
        if info["ready"]:
            lines.append("✨ 부화 준비가 다 됐어요! 웹사이트 키우미집에서 알을 받아보세요.")
        try:
            await member.send("\n".join(lines))
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return

        was_in = _voice_channel(before) is not None
        is_in = _voice_channel(after) is not None

        if not was_in and is_in:
            self.session_start[member.id] = datetime.now(timezone.utc)
            try:
                await self._mark_session_start(member.id)
            except Exception:
                log.exception("통화 시작 기록 실패 (user_id=%s)", member.id)
        elif was_in and not is_in:
            start = self.session_start.pop(member.id, None)
            if start is not None:
                elapsed = (datetime.now(timezone.utc) - start).total_seconds() / 60
                try:
                    info = await self._process(member.id, elapsed, still_in_voice=False)
                except Exception:
                    log.exception("통화 종료 정산 실패 (user_id=%s)", member.id)
                    return
                if info is not None:
                    await self._notify(member, info)

    @tasks.loop(minutes=FLUSH_INTERVAL_MINUTES)
    async def flush_sessions(self):
        now = datetime.now(timezone.utc)
        for user_id, start in list(self.session_start.items()):
            elapsed = (now - start).total_seconds() / 60
            try:
                await self._process(user_id, elapsed, still_in_voice=True)
            except Exception:
                # 한 명이 실패해도 나머지 통화 인원 정산은 계속해요.
                # (실패하면 session_start를 갱신하지 않으니 다음 틱에 이어서 반영돼요.)
                log.exception("통화 진행도 flush 실패 (user_id=%s)", user_id)
                continue
            self.session_start[user_id] = now

    @flush_sessions.before_loop
    async def _before_flush(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(DaycareVoice(bot))
