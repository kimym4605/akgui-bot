import discord
from discord import app_commands
from discord.ext import commands


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="핑", description="봇이 잘 살아있는지, 지연시간은 얼마인지 확인합니다.")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"퐁! 🏓 웹소켓 지연시간: {latency_ms}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
