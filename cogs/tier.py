from typing import Optional

import discord
from discord import app_commands

from utils.riot_account_store import delete_account, get_account, set_account
from utils.tier_roles import get_member_current_tier_roles


class TierGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="티어", description="발로란트 티어 역할 확인 및 계정 연동")

    @app_commands.command(
        name="계정등록",
        description="본인의 라이엇 계정을 등록해요. (등록해두면 /전적을 닉네임 없이 바로 쓸 수 있고, 이 계정 조회 시에만 티어 역할이 자동 갱신돼요)",
    )
    @app_commands.describe(
        닉네임="라이엇 아이디 (# 앞부분, 예: Henrik)",
        태그="태그 (# 뒷부분, 예: VALO)",
    )
    async def register_account(self, interaction: discord.Interaction, 닉네임: str, 태그: str):
        set_account(interaction.user.id, 닉네임, 태그)
        await interaction.response.send_message(
            f"✅ 라이엇 계정을 **{닉네임}#{태그}**(으)로 등록했어요.\n"
            f"이제 닉네임/태그 없이 `/전적`만 입력해도 본인 전적이 바로 조회되고, "
            f"이 계정을 조회할 때만 티어 역할이 자동으로 갱신돼요.",
            ephemeral=True,
        )

    @app_commands.command(name="계정삭제", description="등록해둔 라이엇 계정 연동을 해제해요.")
    async def delete_account_cmd(self, interaction: discord.Interaction):
        if delete_account(interaction.user.id):
            await interaction.response.send_message("계정 연동을 해제했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("등록된 계정이 없어요.", ephemeral=True)

    @app_commands.command(
        name="확인",
        description="현재 부여된 티어 역할을 확인해요. (역할은 등록된 본인 계정으로 /전적 실행할 때마다 자동 갱신돼요)",
    )
    async def check(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        target = 유저 or interaction.user

        if not isinstance(target, discord.Member):
            await interaction.response.send_message("❌ 서버 안에서만 사용할 수 있어요.", ephemeral=True)
            return

        tier_roles = get_member_current_tier_roles(target)
        tier_text = tier_roles[0].name if tier_roles else None

        account = get_account(target.id)
        account_text = f"{account[0]}#{account[1]}" if account else "등록된 계정 없음"

        embed = discord.Embed(
            title=f"{target.display_name}님의 티어",
            color=0x8B5CF6,
            description=tier_text or "아직 티어 역할이 없어요. `/전적`으로 전적을 조회하면 자동으로 부여돼요!",
        )
        embed.add_field(name="연동된 라이엇 계정", value=account_text, inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="티어 역할은 등록된 본인 계정으로 /전적 실행할 때마다 자동 갱신돼요.")

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    bot.tree.add_command(TierGroup())