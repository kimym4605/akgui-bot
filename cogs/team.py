import random

import discord
from discord import app_commands
from discord.ext import commands


class Team(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="팀짜기", description="지금 음성채널에 있는 인원을 랜덤으로 두 팀으로 나눠요.")
    async def team_split(self, interaction: discord.Interaction):
        voice_state = interaction.user.voice if isinstance(interaction.user, discord.Member) else None

        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "먼저 음성 채널에 입장한 뒤 사용해주세요.", ephemeral=True
            )
            return

        members = [m for m in voice_state.channel.members if not m.bot]

        if len(members) < 2:
            await interaction.response.send_message(
                "팀을 나누려면 음성 채널에 최소 2명은 있어야 해요.", ephemeral=True
            )
            return

        shuffled = members[:]
        random.shuffle(shuffled)
        half = (len(shuffled) + 1) // 2
        team_a, team_b = shuffled[:half], shuffled[half:]

        embed = discord.Embed(title="🎲 팀 나누기 결과", color=0x00B0F4)
        embed.add_field(
            name=f"팀 A ({len(team_a)}명)",
            value="\n".join(f"• {m.display_name}" for m in team_a),
            inline=True,
        )
        embed.add_field(
            name=f"팀 B ({len(team_b)}명)",
            value="\n".join(f"• {m.display_name}" for m in team_b),
            inline=True,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Team(bot))
