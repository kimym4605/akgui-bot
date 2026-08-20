"""맵 랜덤 추천 기능이에요. 제외하고 싶은 맵을 고르면 남은 맵 중에서 하나를 뽑아줘요."""
import random

import discord
from discord import app_commands
from discord.ext import commands

# ⚠️ 발로란트 맵 로테이션은 시즌마다 바뀌어요. 새 맵이 추가되거나 빠지면 여기만 고치면 돼요.
MAPS = [
    "어센트", "바인드", "브리즈", "프랙처", "헤이븐",
    "아이스박스", "로터스", "펄", "스플릿", "선셋", "어비스", "코로드",
]

MAX_SELECT_OPTIONS = 25  # 디스코드 Select 컴포넌트 옵션 최대 개수예요.


class MapExcludeSelect(discord.ui.Select):
    def __init__(self, excluded: set[str]):
        options = [
            discord.SelectOption(label=name, value=name, default=(name in excluded))
            for name in MAPS[:MAX_SELECT_OPTIONS]
        ]
        super().__init__(
            placeholder="제외할 맵을 선택하세요 (안 골라도 돼요)",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "MapRecommendView" = self.view  # type: ignore
        view.excluded = set(self.values)
        new_view = MapRecommendView(excluded=view.excluded)
        await interaction.response.edit_message(embed=new_view.build_embed(), view=new_view)


class RollButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🎲 뽑기", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        view: "MapRecommendView" = self.view  # type: ignore
        pool = [m for m in MAPS if m not in view.excluded]

        if not pool:
            await interaction.response.send_message(
                "모든 맵을 제외했어요! 최소 1개는 남겨주세요.", ephemeral=True
            )
            return

        picked = random.choice(pool)

        result_embed = discord.Embed(
            title="🗺️ 맵 추천 결과",
            description=f"**{picked}**",
            color=0xF1C40F,
        )
        if view.excluded:
            result_embed.set_footer(text=f"제외한 맵: {', '.join(sorted(view.excluded))}")
        await interaction.response.edit_message(embed=result_embed, view=None)

        # 결과는 다들 볼 수 있게 채널에도 공개로 알려줘요. (제외 고르는 과정만 나만 보여요)
        await interaction.followup.send(f"🗺️ {interaction.user.mention}님이 뽑은 맵: **{picked}**")


class MapRecommendView(discord.ui.View):
    def __init__(self, excluded: set[str] | None = None):
        super().__init__(timeout=180)
        self.excluded = excluded or set()
        self.add_item(MapExcludeSelect(self.excluded))
        self.add_item(RollButton())

    def build_embed(self) -> discord.Embed:
        remaining = [m for m in MAPS if m not in self.excluded]
        embed = discord.Embed(
            title="🗺️ 맵 추천",
            description="제외할 맵을 고른 뒤 🎲 뽑기를 눌러주세요.",
            color=0x00B0F4,
        )
        embed.add_field(
            name=f"뽑힐 수 있는 맵 ({len(remaining)}개)",
            value="\n".join(f"• {m}" for m in remaining) or "없음",
            inline=False,
        )
        if self.excluded:
            embed.add_field(
                name=f"제외됨 ({len(self.excluded)}개)",
                value=", ".join(sorted(self.excluded)),
                inline=False,
            )
        return embed


class MapRecommend(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="맵추천",
        description="발로란트 맵 중 하나를 랜덤으로 추천해줘요. 원하지 않는 맵은 제외할 수 있어요.",
    )
    async def map_recommend(self, interaction: discord.Interaction):
        view = MapRecommendView()
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MapRecommend(bot))
