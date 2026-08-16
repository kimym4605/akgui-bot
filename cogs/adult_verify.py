"""
성인 인증 기능이에요.

- /성인인증 치면 생년월일(YYYYMMDD)을 입력받는 모달이 떠요.
- 1차: 봇이 만 나이를 자동 계산해서 19세 미만이면 여기서 바로 안내하고 끝나요. (매니저한테 안 감)
- 2차: 19세 이상이면 매니저 관리방(MANAGER_CHANNEL_ID)에 요청이 올라가고,
  매니저/총매니저/방장이 버튼으로 승인하면 그때 "성인" 역할이 부여돼요.
- ⚠️ 자가 신고(생년월일 입력) 방식이라 100% 실제 나이를 보장하진 않아요.
  통신사 본인인증(PASS 등)은 사업자 등록/건당 비용이 필요해서 이 프로젝트 규모에는 맞지 않아
  "자동 계산 + 사람 검토" 이중 확인으로 최소한의 필터링을 해요.
"""
import datetime
import os
import re
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

KST = ZoneInfo("Asia/Seoul")
ADULT_AGE = 19


def _get_int_env(key: str) -> int | None:
    value = os.getenv(key)
    return int(value) if value else None


def _get_int_list_env(key: str) -> list[int]:
    value = os.getenv(key, "")
    return [int(v.strip()) for v in value.split(",") if v.strip()]


# 기존 온보딩 승인 요청과 같은 매니저 관리방/역할을 그대로 재사용해요.
MANAGER_CHANNEL_ID = _get_int_env("MANAGER_CHANNEL_ID")
MANAGER_ROLE_IDS = _get_int_list_env("MANAGER_ROLE_IDS")
SENIOR_ROLE_IDS = _get_int_list_env("SENIOR_ROLE_IDS")

# 승인 시 부여할 역할 ID - 서버에 미리 만들어둔 "성인" 역할을 그대로 사용해요.
ADULT_ROLE_ID = _get_int_env("ADULT_ROLE_ID")


def _is_manager_or_senior(member: discord.Member) -> bool:
    role_ids = {r.id for r in member.roles}
    return bool(role_ids & set(MANAGER_ROLE_IDS)) or bool(role_ids & set(SENIOR_ROLE_IDS))


def _calc_age(birth: datetime.date, today: datetime.date) -> int:
    age = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        age -= 1
    return age


async def _resolve_member(guild: discord.Guild, user_id: int):
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


def _get_adult_role(guild: discord.Guild) -> discord.Role | None:
    if ADULT_ROLE_ID is None:
        return None
    return guild.get_role(ADULT_ROLE_ID)


class AdultApprovalView(discord.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.success, custom_id="adult_verify:approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not _is_manager_or_senior(member):
            await interaction.response.send_message("❌ 매니저/총매니저/방장만 사용할 수 있어요.", ephemeral=True)
            return

        applicant = await _resolve_member(interaction.guild, self.applicant_id)
        if applicant is None:
            await interaction.response.send_message("⚠️ 신청자가 이미 서버를 나갔어요.", ephemeral=True)
            return

        role = _get_adult_role(interaction.guild)
        if role is None:
            await interaction.response.send_message(
                "⚠️ 성인 역할이 설정되어 있지 않아요. (.env의 ADULT_ROLE_ID를 확인해주세요)", ephemeral=True
            )
            return

        try:
            await applicant.add_roles(role, reason=f"{member}가 성인 인증 승인")
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇에게 역할 관리 권한이 없어요.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {member.mention}님이 **{applicant.mention}** 님의 성인 인증을 승인했어요! (**{role.name}** 역할 부여됨)",
            view=self,
        )
        try:
            await applicant.send("🎉 성인 인증이 승인됐어요! 역할이 부여됐어요.")
        except discord.Forbidden:
            pass

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger, custom_id="adult_verify:reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not _is_manager_or_senior(member):
            await interaction.response.send_message("❌ 매니저/총매니저/방장만 사용할 수 있어요.", ephemeral=True)
            return

        applicant = await _resolve_member(interaction.guild, self.applicant_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {member.mention}님이 **{applicant.mention if applicant else self.applicant_id}** 님의 성인 인증을 거절했어요.",
            view=self,
        )
        if applicant is not None:
            try:
                await applicant.send("🙏 성인 인증이 거절됐어요. 문의사항은 매니저에게 연락해주세요.")
            except discord.Forbidden:
                pass


class AdultVerifyModal(discord.ui.Modal, title="성인 인증"):
    birth = discord.ui.TextInput(
        label="생년월일 8자리 (예: 20040115)",
        style=discord.TextStyle.short,
        placeholder="YYYYMMDD",
        required=True,
        min_length=8,
        max_length=8,
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.birth.value.strip()
        if not re.fullmatch(r"\d{8}", raw):
            await interaction.response.send_message(
                "⚠️ 생년월일은 숫자 8자리로 입력해주세요. (예: 20040115)", ephemeral=True
            )
            return

        year, month, day = int(raw[:4]), int(raw[4:6]), int(raw[6:8])
        today = datetime.datetime.now(KST).date()
        try:
            birth_date = datetime.date(year, month, day)
        except ValueError:
            await interaction.response.send_message("⚠️ 실제 존재하지 않는 날짜예요. 다시 확인해주세요.", ephemeral=True)
            return

        if birth_date > today or year < 1900:
            await interaction.response.send_message("⚠️ 생년월일을 다시 확인해주세요.", ephemeral=True)
            return

        age = _calc_age(birth_date, today)

        if age < ADULT_AGE:
            await interaction.response.send_message(
                f"현재 만 나이는 **{age}세**로 확인돼요. 성인(만 {ADULT_AGE}세 이상)만 역할을 받을 수 있어요.",
                ephemeral=True,
            )
            return

        member = interaction.user
        adult_role = _get_adult_role(interaction.guild)
        if adult_role is not None and isinstance(member, discord.Member) and adult_role in member.roles:
            await interaction.response.send_message("이미 성인 역할을 갖고 있어요!", ephemeral=True)
            return

        if MANAGER_CHANNEL_ID is None:
            await interaction.response.send_message(
                "⚠️ 승인 요청을 보낼 관리방이 설정되어 있지 않아요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        manager_channel = interaction.guild.get_channel(MANAGER_CHANNEL_ID)
        if manager_channel is None:
            await interaction.response.send_message("⚠️ 관리방 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔞 성인 인증 요청",
            description=f"{member.mention} 님이 성인 인증을 요청했어요.\n(1차 자동 확인 결과: **통과 가능 나이예요**)",
            color=0xE67E22,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="유저", value=f"{member} ({member.id})", inline=False)

        mention_roles = [interaction.guild.get_role(rid) for rid in (MANAGER_ROLE_IDS + SENIOR_ROLE_IDS)]
        mention_text = " ".join(r.mention for r in mention_roles if r) or "매니저"

        await manager_channel.send(
            content=mention_text,
            embed=embed,
            view=AdultApprovalView(applicant_id=member.id),
        )
        await interaction.response.send_message(
            "✅ 1차 확인(만 나이)을 통과했어요! 관리진에게 최종 승인을 요청했으니 잠시만 기다려주세요.", ephemeral=True
        )


class AdultVerify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(AdultApprovalView(applicant_id=0))

    @app_commands.command(name="성인인증", description="생년월일을 입력해서 성인 역할을 요청해요.")
    async def verify(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AdultVerifyModal())


async def setup(bot: commands.Bot):
    await bot.add_cog(AdultVerify(bot))
