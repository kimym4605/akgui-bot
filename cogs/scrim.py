"""
내전(내부 스크림) 모집 기능이에요. 흐름은 이래요:

1. 모집자가 /내전모집 명령어로 상대 팀장을 지목해요. (모집자 = 팀장1, 지목된 사람 = 팀장2 후보)
2. 지목된 사람한테 DM으로 수락/거절 버튼이 있는 팀장 제안 메시지가 가요.
   (DM이 막혀있는 경우에만 어쩔 수 없이 채널에 공개로 올라가고, 그래도 버튼은 상대팀장만 누를 수 있어요)
3. 수락하면 원래 채널에 @here과 함께 내전 모집 공지가 올라가고, "참여하기" 버튼으로 참가자를 모아요.
4. 팀장(둘 중 아무나)이 "모집 마감"을 누르면 드래프트 단계로 넘어가요.
5. 팀장끼리 번갈아가며 드롭다운으로 직접 인원을 뽑아요. (팀장1부터 시작)
6. 참가자를 다 뽑으면 최종 팀 명단이 떠요.

한 채널당 동시에 하나의 모집/드래프트만 진행되도록 제한해요.
"""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

MAX_POOL_SIZE = 25  # 디스코드 드롭다운(Select) 옵션 최대 개수 제한이에요.


class ScrimSession:
    def __init__(self, captain1: discord.Member, captain2: discord.Member):
        self.captain1 = captain1
        self.captain2 = captain2
        self.participants: dict[int, discord.Member] = {}  # 아직 안 뽑힌 참가자 풀
        self.team1: list[discord.Member] = []
        self.team2: list[discord.Member] = []
        self.turn = 1  # 1이면 팀장1 차례, 2면 팀장2 차례
        self.phase = "recruiting"  # "recruiting" -> "drafting" -> "done"

    @property
    def current_captain(self) -> discord.Member:
        return self.captain1 if self.turn == 1 else self.captain2


def build_recruit_embed(session: ScrimSession) -> discord.Embed:
    embed = discord.Embed(title="🎮 내전 모집 중!", color=0x00B0F4)
    embed.add_field(name="팀장 1", value=session.captain1.mention, inline=True)
    embed.add_field(name="팀장 2", value=session.captain2.mention, inline=True)
    participant_list = "\n".join(f"• {m.display_name}" for m in session.participants.values()) or "아직 없어요"
    embed.add_field(name=f"참가자 ({len(session.participants)}명)", value=participant_list, inline=False)
    embed.set_footer(text="✋ 참여하기 버튼으로 참가 신청! 팀장은 준비되면 🔒 모집 마감을 눌러주세요.")
    return embed


def build_draft_embed(session: ScrimSession) -> discord.Embed:
    embed = discord.Embed(
        title="🧩 팀 드래프트 진행 중",
        description=f"현재 차례: **{session.current_captain.display_name}** 팀장",
        color=0x9B59B6,
    )
    team1_list = "\n".join(f"• {m.display_name}" for m in session.team1) or "(아직 없음)"
    team2_list = "\n".join(f"• {m.display_name}" for m in session.team2) or "(아직 없음)"
    embed.add_field(name=f"🔴 {session.captain1.display_name} 팀", value=f"{session.captain1.mention}\n{team1_list}", inline=True)
    embed.add_field(name=f"🔵 {session.captain2.display_name} 팀", value=f"{session.captain2.mention}\n{team2_list}", inline=True)
    remaining = "\n".join(f"• {m.display_name}" for m in session.participants.values()) or "없음"
    embed.add_field(name=f"남은 인원 ({len(session.participants)}명)", value=remaining, inline=False)
    return embed


def build_final_embed(session: ScrimSession) -> discord.Embed:
    embed = discord.Embed(title="✅ 팀 구성 완료!", color=0x2ECC71)
    team1_list = "\n".join(f"• {m.display_name}" for m in session.team1) or "(없음)"
    team2_list = "\n".join(f"• {m.display_name}" for m in session.team2) or "(없음)"
    embed.add_field(name=f"🔴 {session.captain1.display_name} 팀", value=f"{session.captain1.mention}\n{team1_list}", inline=True)
    embed.add_field(name=f"🔵 {session.captain2.display_name} 팀", value=f"{session.captain2.mention}\n{team2_list}", inline=True)
    return embed


class DraftPickSelect(discord.ui.Select):
    def __init__(self, session: ScrimSession):
        options = [
            discord.SelectOption(label=member.display_name, value=str(uid))
            for uid, member in list(session.participants.items())[:MAX_POOL_SIZE]
        ]
        super().__init__(placeholder="뽑을 인원을 선택하세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: "DraftView" = self.view  # type: ignore
        session = view.cog.sessions.get(view.channel_id)

        if session is None or session.phase != "drafting":
            await interaction.response.send_message("드래프트가 이미 종료됐어요.", ephemeral=True)
            return

        if interaction.user.id != session.current_captain.id:
            await interaction.response.send_message("지금은 당신 차례가 아니에요.", ephemeral=True)
            return

        picked_id = int(self.values[0])
        picked_member = session.participants.pop(picked_id, None)
        if picked_member is None:
            await interaction.response.send_message("이미 다른 팀장이 먼저 뽑았어요.", ephemeral=True)
            return

        if session.turn == 1:
            session.team1.append(picked_member)
            session.turn = 2
        else:
            session.team2.append(picked_member)
            session.turn = 1

        if session.participants:
            embed = build_draft_embed(session)
            new_view = DraftView(view.cog, view.channel_id)
            await interaction.response.edit_message(embed=embed, view=new_view)
        else:
            session.phase = "done"
            embed = build_final_embed(session)
            await interaction.response.edit_message(embed=embed, view=None)
            view.cog.sessions.pop(view.channel_id, None)


class DraftView(discord.ui.View):
    def __init__(self, cog: "Scrim", channel_id: int):
        super().__init__(timeout=600)  # 10분 넘게 아무도 안 뽑으면 만료돼요.
        self.cog = cog
        self.channel_id = channel_id
        session = cog.sessions.get(channel_id)
        if session is not None:
            self.add_item(DraftPickSelect(session))

    async def on_timeout(self):
        self.cog.sessions.pop(self.channel_id, None)


class RecruitmentView(discord.ui.View):
    def __init__(self, cog: "Scrim", channel_id: int):
        super().__init__(timeout=1800)  # 30분 넘게 마감 안 하면 자동 만료돼요.
        self.cog = cog
        self.channel_id = channel_id

    async def on_timeout(self):
        self.cog.sessions.pop(self.channel_id, None)

    @discord.ui.button(label="✋ 참여하기", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = self.cog.sessions.get(self.channel_id)
        if session is None or session.phase != "recruiting":
            await interaction.response.send_message("모집이 이미 종료됐어요.", ephemeral=True)
            return

        user = interaction.user
        if user.id in (session.captain1.id, session.captain2.id):
            await interaction.response.send_message("이미 팀장으로 참여하고 있어요.", ephemeral=True)
            return

        if user.id in session.participants:
            del session.participants[user.id]
        else:
            if len(session.participants) >= MAX_POOL_SIZE:
                await interaction.response.send_message(
                    f"참가 인원이 최대치({MAX_POOL_SIZE}명)에 도달했어요.", ephemeral=True
                )
                return
            session.participants[user.id] = user

        await interaction.response.edit_message(embed=build_recruit_embed(session), view=self)

    @discord.ui.button(label="🔒 모집 마감 및 드래프트 시작", style=discord.ButtonStyle.danger)
    async def close_and_draft(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = self.cog.sessions.get(self.channel_id)
        if session is None or session.phase != "recruiting":
            await interaction.response.send_message("모집이 이미 종료됐어요.", ephemeral=True)
            return

        if interaction.user.id not in (session.captain1.id, session.captain2.id):
            await interaction.response.send_message("팀장만 모집을 마감할 수 있어요.", ephemeral=True)
            return

        if not session.participants:
            await interaction.response.send_message("참가자가 한 명도 없어요.", ephemeral=True)
            return

        session.phase = "drafting"
        session.turn = 1
        embed = build_draft_embed(session)
        view = DraftView(self.cog, self.channel_id)
        await interaction.response.edit_message(embed=embed, view=view)


class ChallengeView(discord.ui.View):
    def __init__(self, cog: "Scrim", initiator: discord.Member, target: discord.Member, origin_channel: discord.abc.Messageable):
        super().__init__(timeout=300)  # 5분 안에 응답 없으면 만료돼요.
        self.cog = cog
        self.initiator = initiator
        self.target = target
        self.origin_channel = origin_channel
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("이 제안은 당신에게 온 게 아니에요.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        self.cog.pending.discard(self.origin_channel.id)
        if self.message is not None:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(content="⌛ 팀장 제안이 만료됐어요.", embed=None, view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="✅ 수락", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {self.target.display_name}님이 팀장 제안을 수락했어요! 내전 모집을 시작할게요.",
            embed=None,
            view=self,
        )
        self.cog.pending.discard(self.origin_channel.id)
        await self.cog.start_recruitment(self.origin_channel, self.initiator, self.target)
        self.stop()

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.target.display_name}님이 팀장 제안을 거절했어요.",
            embed=None,
            view=self,
        )
        self.cog.pending.discard(self.origin_channel.id)
        self.stop()


class Scrim(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, ScrimSession] = {}  # channel_id -> 진행 중인 모집/드래프트
        self.pending: set[int] = set()  # channel_id -> 응답 대기 중인 팀장 제안이 있는 채널

    @app_commands.command(name="내전모집", description="다른 유저를 상대 팀장으로 신청해서 내전 모집을 시작해요.")
    @app_commands.describe(상대팀장="함께 팀장을 맡아줄 유저를 선택해주세요.")
    async def scrim_recruit(self, interaction: discord.Interaction, 상대팀장: discord.Member):
        if 상대팀장.bot:
            await interaction.response.send_message("봇은 팀장으로 지정할 수 없어요.", ephemeral=True)
            return
        if 상대팀장.id == interaction.user.id:
            await interaction.response.send_message("본인을 상대 팀장으로 지정할 수 없어요.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 서버 안에서만 사용할 수 있어요.", ephemeral=True)
            return
        if interaction.channel_id in self.sessions or interaction.channel_id in self.pending:
            await interaction.response.send_message(
                "이미 이 채널에서 진행 중인 내전 신청/모집이 있어요. 끝난 뒤에 다시 시도해주세요.",
                ephemeral=True,
            )
            return

        self.pending.add(interaction.channel_id)

        embed = discord.Embed(
            title="⚔️ 내전 팀장 제안",
            description=f"{interaction.user.display_name}님이 **함께 내전 팀장**을 맡아달라고 제안했어요!",
            color=0xFFA500,
        )
        view = ChallengeView(self, interaction.user, 상대팀장, interaction.channel)

        try:
            dm_message = await 상대팀장.send(embed=embed, view=view)
            view.message = dm_message
            await interaction.response.send_message(
                f"✅ {상대팀장.mention}님에게 DM으로 팀장 제안을 보냈어요!", ephemeral=True
            )
        except discord.Forbidden:
            # DM이 막혀있으면 어쩔 수 없이 채널에 공개로 올려요. (버튼은 여전히 상대팀장만 누를 수 있어요)
            embed.description += "\n\n(⚠️ DM이 막혀있어서 채널에 대신 올렸어요)"
            await interaction.response.send_message(content=상대팀장.mention, embed=embed, view=view)
            view.message = await interaction.original_response()

    async def start_recruitment(self, channel: discord.abc.Messageable, captain1: discord.Member, captain2: discord.Member):
        session = ScrimSession(captain1, captain2)
        self.sessions[channel.id] = session
        embed = build_recruit_embed(session)
        view = RecruitmentView(self, channel.id)
        try:
            await channel.send(
                content="@here 🎮 내전 모집이 시작됐어요! 참여하려면 아래 버튼을 눌러주세요.",
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(everyone=True),
            )
        except discord.Forbidden:
            # 봇에게 @here 멘션 권한이 없으면, 멘션 없이라도 모집 공지는 올라가게 해요.
            await channel.send(
                content="🎮 내전 모집이 시작됐어요! (⚠️ 봇에게 @here 멘션 권한이 없어서 알림은 못 보냈어요)",
                embed=embed,
                view=view,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Scrim(bot))