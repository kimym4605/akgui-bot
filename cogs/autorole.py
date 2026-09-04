import logging
import os

import discord
from discord.ext import commands

log = logging.getLogger(__name__)


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role_id = os.getenv("AUTO_ROLE_ID")
        if not role_id:
            return

        role = member.guild.get_role(int(role_id))
        if role is None:
            log.warning(f"⚠️ AUTO_ROLE_ID({role_id})에 해당하는 역할을 서버에서 찾을 수 없어요.")
            return

        try:
            await member.add_roles(role, reason="신규 멤버 자동 역할 부여")
            log.info(f"➕ {member.display_name}님에게 '{role.name}' 역할을 자동으로 부여했어요.")
        except discord.Forbidden:
            log.warning(
                "⚠️ 역할을 부여할 권한이 없어요. "
                "서버 설정 > 역할에서 봇 역할이 부여하려는 역할보다 위에 있는지 확인해주세요."
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
