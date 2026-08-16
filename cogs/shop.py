"""상점(구매/아이템 사용)은 웹사이트로 옮겼어요. 여기 남은 건 안내용 명령어 하나뿐이에요."""
import discord
from discord import app_commands
from discord.ext import commands

from utils.channel_check import restrict_to_channel


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="상점", description="상점은 이제 웹사이트에서 이용할 수 있어요.")
    @restrict_to_channel("shop")
    async def shop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛒 포켓몬 상점",
            description="아이템 구매/사용은 이제 웹사이트에서 할 수 있어요!\n웹사이트에 로그인해서 상점 메뉴를 이용해주세요.",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
