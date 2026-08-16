"""음성채널 체류시간을 경험치로 환산해주는 기능이에요.
입장~퇴장(채널 이동은 세션 유지) 전체 시간을 계산해서, 퇴장하는 순간 한 번에 지급해요.
자정(한국시간 00:00)에는 그때까지 통화 중인 사람도 퇴장하지 않아도 그 시점까지의 시간을 먼저 정산하고,
그 시각부터 세션을 다시 시작해요 (하루 상한이 자정마다 갱신되는 것과 맞추기 위해서예요)."""
import datetime

import discord
from discord.ext import commands, tasks

from utils.move_ui import prompt_new_moves
from utils.pokemon_store import add_voice_exp

KST = datetime.timezone(datetime.timedelta(hours=9))


class VoiceExp(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {user_id: 입장 시각(UTC)} - 메모리에만 저장돼요 (봇 재시작 시 진행 중이던 세션은 유실돼요)
        self.sessions: dict[int, datetime.datetime] = {}
        self._credit_at_midnight.start()

    def cog_unload(self):
        self._credit_at_midnight.cancel()

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=KST))
    async def _credit_at_midnight(self):
        """자정에 통화 중인 사람들의 그때까지 시간을 정산하고 세션을 리셋해요."""
        now = datetime.datetime.now(datetime.timezone.utc)

        for user_id, joined_at in list(self.sessions.items()):
            duration = now - joined_at
            minutes = duration.total_seconds() / 60
            self.sessions[user_id] = now  # 자정부터 새 세션으로 이어서 계산해요

            if minutes < 1:
                continue

            result = add_voice_exp(user_id, minutes)
            if result is None:
                continue

            member = self.bot.get_user(user_id)
            if member is None:
                try:
                    member = await self.bot.fetch_user(user_id)
                except discord.NotFound:
                    continue

            await self._notify(member, result, minutes)

    @_credit_at_midnight.before_loop
    async def _before_credit_at_midnight(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        if before.channel is None and after.channel is not None:
            self.sessions[member.id] = datetime.datetime.now(datetime.timezone.utc)
            return

        if before.channel is not None and after.channel is not None:
            return  # 다른 채널로 이동 - 세션은 끊기지 않고 계속 이어져요

        if before.channel is not None and after.channel is None:
            joined_at = self.sessions.pop(member.id, None)
            if joined_at is None:
                return  # 세션 기록이 없으면(봇 재시작 등) 지급하지 않아요

            duration = datetime.datetime.now(datetime.timezone.utc) - joined_at
            minutes = duration.total_seconds() / 60
            if minutes < 1:
                return

            result = add_voice_exp(member.id, minutes)
            if result is None:
                return

            await self._notify(member, result, minutes)

    async def _notify(self, member: discord.Member | discord.User, result: dict, minutes: float):
        """DM으로 조용히 알려줘요. DM이 막혀있으면 그냥 무시해요."""
        trainer = result["trainer"]

        embed = discord.Embed(
            title="🎧 통화 경험치 획득!",
            description=f"이번 통화 시간: 약 **{int(minutes)}분**",
            color=0x57F287,
        )
        embed.add_field(name="획득 경험치", value=f"+{result['exp_gain']} EXP", inline=True)
        embed.add_field(name="내 포켓몬", value=f"{trainer['currentPokemon']} (Lv.{trainer['level']})", inline=True)

        if result["capped"]:
            embed.add_field(name="⚠️ 알림", value="오늘 통화 경험치 상한(4시간)에 도달해서 일부만 인정됐어요.", inline=False)

        if result["leveled_up"]:
            embed.add_field(
                name="⬆️ 레벨 업!",
                value=f"Lv.{result['before_level']} → **Lv.{trainer['level']}**",
                inline=False,
            )

        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            return

        if result["leveled_up"]:
            await prompt_new_moves(
                send=member.send,
                user_id=member.id,
                base_name=trainer["basePokemon"],
                before_level=result["before_level"],
                after_level=trainer["level"],
            )

        if result["pending_evolution"]:
            from cogs.attendance import EvolveConfirmView

            view = EvolveConfirmView(member.id)
            hint = result["pending_evolution"]["target_hint"]
            desc = f"**{trainer['currentPokemon']}**이(가) 진화할 수 있어요!"
            if hint:
                desc += f" (→ {hint})"
            try:
                await member.send(content=desc, view=view)
            except discord.Forbidden:
                return


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceExp(bot))