import os

import discord
from discord import app_commands
from discord.ext import commands

from utils.rules_store import (
    get_rules,
    set_rules,
    get_description,
    set_description,
    get_guidance,
    set_guidance,
)

# ============================================================
# 1. 설정값 (.env에서 불러와요)
# ============================================================
def _get_int_env(key: str) -> int | None:
    value = os.getenv(key)
    return int(value) if value else None


def _get_int_list_env(key: str) -> list[int]:
    value = os.getenv(key, "")
    return [int(v.strip()) for v in value.split(",") if v.strip()]


NEWCOMER_ROLE_ID = _get_int_env("NEWCOMER_ROLE_ID")
MEMBER_ROLE_ID = _get_int_env("MEMBER_ROLE_ID")
MANAGER_CHANNEL_ID = _get_int_env("MANAGER_CHANNEL_ID")
MANAGER_ROLE_IDS = _get_int_list_env("MANAGER_ROLE_IDS")
SENIOR_ROLE_IDS = _get_int_list_env("SENIOR_ROLE_IDS")
DESCRIPTION_CHANNEL_ID = _get_int_env("DESCRIPTION_CHANNEL_ID")
RULES_CHANNEL_ID = _get_int_env("RULES_CHANNEL_ID")
ENTRY_CHANNEL_ID = _get_int_env("ENTRY_CHANNEL_ID")

ENTRY_START_CUSTOM_ID = "onboarding:entry_start"
GUIDANCE_CONFIRM_CUSTOM_ID = "onboarding:guidance_confirm"
DESCRIPTION_CONFIRM_CUSTOM_ID = "onboarding:description_confirm"
RULES_CONFIRM_CUSTOM_ID = "onboarding:rules_confirm"

MAX_RULES = 30  # 임베드 description 4096자 제한만 신경쓰면 돼요
MAX_DESCRIPTION_LINES = 80
MAX_GUIDANCE_LINES = 60


def _is_senior(member: discord.Member) -> bool:
    return bool({r.id for r in member.roles} & set(SENIOR_ROLE_IDS))


def _is_manager(member: discord.Member) -> bool:
    return bool({r.id for r in member.roles} & set(MANAGER_ROLE_IDS))


def _is_manager_or_senior(member: discord.Member) -> bool:
    return _is_manager(member) or _is_senior(member)


async def _resolve_member(guild: discord.Guild, user_id: int):
    """멤버 캐시에 없어도(특권 인텐트 없이도) 확실하게 멤버를 찾아와요."""
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


def _mention_seniors(guild: discord.Guild) -> str:
    roles = [guild.get_role(rid) for rid in SENIOR_ROLE_IDS]
    return " ".join(role.mention for role in roles if role) or "총매니저/방장"


def _mention_managers(guild: discord.Guild) -> str:
    roles = [guild.get_role(rid) for rid in MANAGER_ROLE_IDS]
    return " ".join(role.mention for role in roles if role) or "매니저"


async def _open_channel_for(guild: discord.Guild, channel_id: int, member: discord.Member, reason: str):
    """지정한 채널을 특정 멤버에게만 열어줘요. 채널이 없으면 None을 반환해요."""
    channel = guild.get_channel(channel_id)
    if channel is None:
        return None
    await channel.set_permissions(
        member,
        view_channel=True,
        read_message_history=True,
        reason=reason,
    )
    return channel


async def _send_guidance_prompt(interaction: discord.Interaction):
    """입장 정보 제출 후, 안내 글 + 확인 버튼을 그 유저에게만 보여줘요."""
    guild = interaction.guild
    guidance = get_guidance(guild.id)
    if not guidance:
        await interaction.followup.send(
            "✅ 입장 정보가 전달됐어요! (안내글이 아직 설정되지 않아 관리자에게 문의해주세요)", ephemeral=True
        )
        return

    guidance_text = "\n".join(guidance)
    embed = discord.Embed(
        title="👋 환영합니다!",
        description=(
            f"{guidance_text}\n\n"
            "다 읽으셨다면 아래 **'안내를 모두 확인했어요'** 버튼을 눌러주세요.\n"
            "누르면 서버 설명방이 열려요!"
        ),
        color=0xF1C40F,
    )
    await interaction.followup.send(embed=embed, view=GuidanceConfirmView(), ephemeral=True)


# ============================================================
# 2. 최종 승인 단계 (총매니저/방장 전용)
# ============================================================
class FinalApprovalView(discord.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    async def _grant_role(self, guild, applicant, approver):
        newcomer_role = guild.get_role(NEWCOMER_ROLE_ID)
        member_role = guild.get_role(MEMBER_ROLE_ID)
        if newcomer_role and newcomer_role in applicant.roles:
            await applicant.remove_roles(newcomer_role, reason=f"{approver}가 최종 승인")
        if member_role:
            await applicant.add_roles(member_role, reason=f"{approver}가 최종 승인")
        return member_role

    @discord.ui.button(label="🏆 최종 승인", style=discord.ButtonStyle.success, custom_id="onboarding:final_approve")
    async def final_approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not _is_senior(interaction.user):
            await interaction.response.send_message("❌ 총매니저/방장만 최종 승인할 수 있어요.", ephemeral=True)
            return
        guild = interaction.guild
        applicant = await _resolve_member(guild, self.applicant_id)
        if applicant is None:
            await interaction.response.send_message("⚠️ 신청자가 이미 서버를 나갔어요.", ephemeral=True)
            return
        try:
            member_role = await self._grant_role(guild, applicant, interaction.user)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇에게 역할 관리 권한이 없어요.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"🏆 {interaction.user.mention}님이 **{applicant.mention}** 님을 최종 승인했어요!", view=self
        )
        try:
            role_name = member_role.name if member_role else "신규"
            await applicant.send(f"🎉 최종 승인됐어요! **{role_name}** 역할이 부여됐어요.")
        except discord.Forbidden:
            pass

    @discord.ui.button(label="❌ 최종 거절", style=discord.ButtonStyle.danger, custom_id="onboarding:final_reject")
    async def final_reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not _is_senior(interaction.user):
            await interaction.response.send_message("❌ 총매니저/방장만 최종 거절할 수 있어요.", ephemeral=True)
            return
        guild = interaction.guild
        applicant = await _resolve_member(guild, self.applicant_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {interaction.user.mention}님이 **{applicant.mention if applicant else self.applicant_id}** 님을 최종 거절했어요.",
            view=self,
        )
        if applicant is not None:
            try:
                await applicant.send("🙏 아직 승인되지 않았어요. 매니저에게 문의해주세요.")
            except discord.Forbidden:
                pass


# ============================================================
# 3. 1차 요청 단계 (매니저는 추천만, 총매니저/방장은 즉시 확정)
# ============================================================
class RequestApprovalView(discord.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    async def _finalize_as_senior(self, interaction: discord.Interaction, approve: bool):
        guild = interaction.guild
        applicant = await _resolve_member(guild, self.applicant_id)
        if applicant is None:
            await interaction.response.send_message("⚠️ 신청자가 이미 서버를 나갔어요.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        if approve:
            try:
                newcomer_role = guild.get_role(NEWCOMER_ROLE_ID)
                member_role = guild.get_role(MEMBER_ROLE_ID)
                if newcomer_role and newcomer_role in applicant.roles:
                    await applicant.remove_roles(newcomer_role, reason=f"{interaction.user}가 즉시 승인")
                if member_role:
                    await applicant.add_roles(member_role, reason=f"{interaction.user}가 즉시 승인")
            except discord.Forbidden:
                await interaction.response.send_message("❌ 봇에게 역할 관리 권한이 없어요.", ephemeral=True)
                return
            await interaction.response.edit_message(
                content=f"🏆 {interaction.user.mention}님(총매니저/방장)이 **{applicant.mention}** 님을 바로 승인했어요!",
                view=self,
            )
            try:
                await applicant.send("🎉 승인됐어요! 즐거운 서버 생활 되세요!")
            except discord.Forbidden:
                pass
        else:
            await interaction.response.edit_message(
                content=f"❌ {interaction.user.mention}님(총매니저/방장)이 **{applicant.mention}** 님을 바로 거절했어요.",
                view=self,
            )
            try:
                await applicant.send("🙏 아직 승인되지 않았어요. 매니저에게 문의해주세요.")
            except discord.Forbidden:
                pass

    async def _recommend_as_manager(self, interaction: discord.Interaction, approve: bool):
        guild = interaction.guild
        applicant = await _resolve_member(guild, self.applicant_id)
        action_text = "승인 추천 ✅" if approve else "거절 추천 ❌"
        senior_mentions = _mention_seniors(guild)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=(
                f"🔔 매니저 {interaction.user.mention}님이 **{applicant.mention if applicant else self.applicant_id}** 님을 "
                f"**{action_text}**했어요.\n{senior_mentions} 최종 확인 부탁드려요!"
            ),
            view=self,
        )
        await interaction.channel.send(content=senior_mentions, view=FinalApprovalView(applicant_id=self.applicant_id))

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.success, custom_id="onboarding:request_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not _is_manager_or_senior(member):
            await interaction.response.send_message("❌ 매니저/총매니저/방장만 사용할 수 있어요.", ephemeral=True)
            return
        if _is_senior(member):
            await self._finalize_as_senior(interaction, approve=True)
        else:
            await self._recommend_as_manager(interaction, approve=True)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger, custom_id="onboarding:request_reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not _is_manager_or_senior(member):
            await interaction.response.send_message("❌ 매니저/총매니저/방장만 사용할 수 있어요.", ephemeral=True)
            return
        if _is_senior(member):
            await self._finalize_as_senior(interaction, approve=False)
        else:
            await self._recommend_as_manager(interaction, approve=False)


# ============================================================
# 4. 규칙방: 규칙 전체 안내 + 확인 버튼 → 매니저 승인 요청
# ============================================================
class RulesConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 규칙을 모두 확인했어요", style=discord.ButtonStyle.success, custom_id=RULES_CONFIRM_CUSTOM_ID)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user

        manager_channel = guild.get_channel(MANAGER_CHANNEL_ID)
        if manager_channel is None:
            await interaction.response.send_message("⚠️ 알림 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        mention_text = _mention_managers(guild)

        embed = discord.Embed(
            title="🙋 신입 승인 요청",
            description=f"{member.mention} 님이 모든 규칙을 확인했어요. 승인 여부를 결정해주세요.",
            color=0x5865F2,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="유저", value=f"{member} ({member.id})")

        await manager_channel.send(content=mention_text, embed=embed, view=RequestApprovalView(applicant_id=member.id))
        await interaction.response.send_message("✅ 관리진에게 확인 요청을 보냈어요. 조금만 기다려주세요!", ephemeral=True)


# ============================================================
# 5. 서버설명방: 설명 안내 + 확인 버튼 → 규칙방 열기
# ============================================================
class DescriptionConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 설명을 모두 확인했어요", style=discord.ButtonStyle.primary, custom_id=DESCRIPTION_CONFIRM_CUSTOM_ID)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user

        try:
            rules_channel = await _open_channel_for(
                guild, RULES_CHANNEL_ID, member, reason=f"{member} 설명글 확인 완료 → 규칙방 열람 허용"
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇에게 채널 권한 관리 권한이 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        if rules_channel is None:
            await interaction.response.send_message("⚠️ 규칙 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ 확인 완료! {rules_channel.mention} 채널이 열렸어요. 이제 규칙을 확인해주세요!", ephemeral=True
        )


# ============================================================
# 6. 신입유도방 - 확인 버튼 → 서버설명방 열기
# ============================================================
class GuidanceConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 안내를 모두 확인했어요", style=discord.ButtonStyle.primary, custom_id=GUIDANCE_CONFIRM_CUSTOM_ID)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user

        try:
            description_channel = await _open_channel_for(
                guild, DESCRIPTION_CHANNEL_ID, member, reason=f"{member} 신입유도 확인 완료 → 서버설명방 열람 허용"
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇에게 채널 권한 관리 권한이 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        if description_channel is None:
            await interaction.response.send_message("⚠️ 설명 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ 확인 완료! {description_channel.mention} 채널이 열렸어요. 다음으로 서버 소개를 확인해주세요!",
            ephemeral=True,
        )


# ============================================================
# 7. 신입 입장 정보 입력 모달 + 시작 버튼
# ============================================================
class EntryInfoModal(discord.ui.Modal, title="겜악귀 입장 정보"):
    nickname = discord.ui.TextInput(
        label="겜악귀 서버에서 사용할 닉네임",
        style=discord.TextStyle.short,
        placeholder="예) 동준",
        required=True,
        max_length=32,
    )
    age = discord.ui.TextInput(
        label="나이",
        style=discord.TextStyle.short,
        placeholder="예) 20",
        required=True,
        max_length=3,
    )
    referrer = discord.ui.TextInput(
        label="추천한 사람 (없으면 '없음')",
        style=discord.TextStyle.short,
        placeholder="예) 홍길동 / 없음",
        required=True,
        max_length=50,
    )
    main_game = discord.ui.TextInput(
        label="주로 하는 게임",
        style=discord.TextStyle.short,
        placeholder="예) 롤, 발로란트",
        required=True,
        max_length=100,
    )
    # 나중에 항목을 더 추가하고 싶으면 discord.ui.TextInput()을 여기 하나 더 선언하면 돼요.
    # 단, 모달 한 개당 항목은 최대 5개까지만 가능해요.

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        entry_channel = guild.get_channel(ENTRY_CHANNEL_ID)
        if entry_channel is None:
            await interaction.response.send_message(
                "⚠️ 입장 정보를 보낼 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📝 신입 입장 정보",
            color=0x9B59B6,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="유저", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="닉네임", value=self.nickname.value, inline=True)
        embed.add_field(name="나이", value=self.age.value, inline=True)
        embed.add_field(name="추천인", value=self.referrer.value, inline=True)
        embed.add_field(name="주로 하는 게임", value=self.main_game.value, inline=False)

        await entry_channel.send(embed=embed)

        try:
            description_channel = await _open_channel_for(
                guild, DESCRIPTION_CHANNEL_ID, member, reason=f"{member} 입장 정보 제출 완료 → 서버설명방 열람 허용"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 봇에게 채널 권한 관리 권한이 없어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        if description_channel is None:
            await interaction.response.send_message(
                "⚠️ 설명 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ 입장 정보가 전달됐어요! {description_channel.mention} 채널이 열렸어요. 서버 소개를 확인해주세요!",
            ephemeral=True,
        )


class EntryStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 입장 정보 입력하기", style=discord.ButtonStyle.success, custom_id=ENTRY_START_CUSTOM_ID)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EntryInfoModal())


# ============================================================
# 8. 안내/설명/규칙 입력용 모달 (관리자 전용)
# ============================================================
class GuidanceModal(discord.ui.Modal, title="신입유도 안내 입력"):
    guidance_input = discord.ui.TextInput(
        label="신입에게 처음 보여줄 안내 문구를 입력해주세요",
        style=discord.TextStyle.paragraph,
        placeholder="예)\n환영합니다! 순서대로 확인하면 서버 이용이 시작돼요.",
        required=True,
        max_length=4000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        lines = [line for line in self.guidance_input.value.split("\n")]
        if len(lines) > MAX_GUIDANCE_LINES:
            await interaction.response.send_message(
                f"⚠️ 안내글은 최대 {MAX_GUIDANCE_LINES}줄까지 가능해요. (지금 {len(lines)}줄이에요)", ephemeral=True
            )
            return
        set_guidance(interaction.guild.id, lines)
        await interaction.response.send_message("✅ 신입유도 안내글이 저장됐어요!", ephemeral=True)


class DescriptionModal(discord.ui.Modal, title="서버 설명글 입력"):
    description_input = discord.ui.TextInput(
        label="서버 소개/설명을 입력해주세요",
        style=discord.TextStyle.paragraph,
        placeholder="예)\n겜악귀는 어떤 서버인지, 분위기, 특징 등을 자유롭게 적어주세요.",
        required=True,
        max_length=4000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        lines = [line for line in self.description_input.value.split("\n")]
        if len(lines) > MAX_DESCRIPTION_LINES:
            await interaction.response.send_message(
                f"⚠️ 설명글은 최대 {MAX_DESCRIPTION_LINES}줄까지 가능해요. (지금 {len(lines)}줄이에요)", ephemeral=True
            )
            return
        set_description(interaction.guild.id, lines)
        await interaction.response.send_message("✅ 설명글이 저장됐어요!", ephemeral=True)


class RulesModal(discord.ui.Modal, title="서버 규칙 입력"):
    rules_input = discord.ui.TextInput(
        label="규칙을 한 줄에 하나씩 입력해주세요",
        style=discord.TextStyle.paragraph,
        placeholder="예)\n욕설과 비방 금지\n광고/스팸 금지\n타인을 존중해주세요",
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        lines = [line.strip() for line in self.rules_input.value.split("\n") if line.strip()]
        if len(lines) > MAX_RULES:
            await interaction.response.send_message(
                f"⚠️ 규칙은 최대 {MAX_RULES}개까지 가능해요. (지금 {len(lines)}개 입력하셨어요)", ephemeral=True
            )
            return
        set_rules(interaction.guild.id, lines)
        await interaction.response.send_message(f"✅ 규칙 {len(lines)}개가 저장됐어요!", ephemeral=True)


# ============================================================
# 9. Cog 본체
# ============================================================
class Onboarding(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(EntryStartView())
        self.bot.add_view(GuidanceConfirmView())
        self.bot.add_view(DescriptionConfirmView())
        self.bot.add_view(RulesConfirmView())
        self.bot.add_view(RequestApprovalView(applicant_id=0))
        self.bot.add_view(FinalApprovalView(applicant_id=0))

    # ---- 신입유도방 ----
    @app_commands.command(name="안내설정", description="[관리자] 입장 정보 입력 후 보여줄 안내글을 입력/수정해요.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_guidance_command(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GuidanceModal())

    @app_commands.command(name="안내게시", description="[관리자] 이 채널(신입유도방)에 입장 정보 입력 버튼을 게시해요.")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_guidance(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="👋 환영합니다!",
            description=(
                "겜악귀 서버에 오신 걸 환영해요!\n"
                "아래 **'입장 정보 입력하기'** 버튼을 눌러서 간단한 정보를 알려주세요.\n"
                "제출하면 이어서 안내 글이 보여요."
            ),
            color=0xF1C40F,
        )
        await interaction.channel.send(embed=embed, view=EntryStartView())
        await interaction.response.send_message("✅ 입장 정보 입력 버튼을 게시했어요.", ephemeral=True)

    # ---- 서버설명방 ----
    @app_commands.command(name="설명설정", description="[관리자] 서버 설명글을 입력/수정해요.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_description_command(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DescriptionModal())

    @app_commands.command(name="설명안내", description="[관리자] 이 채널(서버설명방)에 설명글과 확인 버튼을 게시해요.")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_description(self, interaction: discord.Interaction):
        description = get_description(interaction.guild.id)
        if not description:
            await interaction.response.send_message(
                "⚠️ 먼저 `/설명설정`으로 설명글을 입력해주세요.", ephemeral=True
            )
            return

        description_text = "\n".join(description)
        embed = discord.Embed(
            title="📖 서버 소개",
            description=(
                f"{description_text}\n\n"
                "다 읽으셨다면 아래 **'설명을 모두 확인했어요'** 버튼을 눌러주세요.\n"
                "누르면 규칙방이 열려요!"
            ),
            color=0x3498DB,
        )
        await interaction.channel.send(embed=embed, view=DescriptionConfirmView())
        await interaction.response.send_message("✅ 설명글 안내 메시지를 게시했어요.", ephemeral=True)

    # ---- 규칙방 ----
    @app_commands.command(name="규칙설정", description="[관리자] 서버 규칙을 입력/수정해요.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_rules_command(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RulesModal())

    @app_commands.command(name="규칙안내", description="[관리자] 이 채널(규칙방)에 규칙 전체와 확인 버튼을 게시해요.")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_rules(self, interaction: discord.Interaction):
        rules = get_rules(interaction.guild.id)
        if not rules:
            await interaction.response.send_message(
                "⚠️ 먼저 `/규칙설정`으로 규칙을 입력해주세요.", ephemeral=True
            )
            return

        rules_text = "\n".join(rules)
        embed = discord.Embed(
            title="📜 서버 규칙 안내",
            description=(
                f"{rules_text}\n\n"
                "규칙을 모두 읽으셨다면 아래 **'규칙을 모두 확인했어요'** 버튼을 눌러주세요.\n"
                "누르면 매니저가 확인하고, 총매니저/방장이 최종 승인해드려요!"
            ),
            color=0x2ECC71,
        )
        await interaction.channel.send(embed=embed, view=RulesConfirmView())
        await interaction.response.send_message("✅ 규칙 안내 메시지를 게시했어요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Onboarding(bot))