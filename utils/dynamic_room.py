"""
즉석 생성형 통화방(/방만들기) 엔진이에요. cogs/room.py에서 이 엔진 하나로
"랭크방", "폐관수련방", "프리미어방" 등 여러 종류의 방을 한 명령어 세트로 관리해요.

- /방만들기 종류:OOO 를 치면 그 사람만의 새 통화방이 즉석에서 만들어져요.
  방은 "보이긴 하지만"(누가 들어가 있는지 다른 사람도 확인 가능) 아무나 바로 들어올 순 없어요.
  = @everyone: 채널은 보임(view_channel=True), 입장은 불가(connect=False)
- 방장은 두 가지 방법으로 사람을 들일 수 있어요:
  1. /방초대 @사람  → 방장이 바로 초대(즉시 입장 허용)
  2. /방신청 방장:@사람 → 아무나 입장 신청을 보낼 수 있고, 방장한테 수락/거절 버튼이 있는
     알림(DM 우선, DM이 막혀있으면 방 채팅)이 가서 방장이 눌러서 처리해요.
- /방닫기로 방장이 직접 방을 닫을 수 있어요.
- 한 사람은 종류에 상관없이 동시에 방 1개만 가질 수 있어요.
- 방에 아무도 없으면(모두 퇴장) 자동으로 삭제돼요.
- 방을 만들고 나서 아무도 10분 안에 안 들어오면(방장 본인도 포함) 그것도 자동 삭제돼요.
- 방장이 나가면(다른 사람이 남아있어도) 안내 문구를 올리고 10초 뒤 방을 자동으로 닫아요.
  단, 10초 안에 방장이 다시 들어오면 타이머가 취소돼요.
- 방 소유자/종류 정보(채널ID <-> {방장ID, 종류})를 utils/room_store.py를 통해
  data/dynamic_rooms.json에도 저장해요. 그래서 봇이 재시작돼도 초대/신청이 계속 작동해요.
  봇이 켜질 때 저장된 방들을 다시 불러오면서, 이미 사라진 채널이나 그 사이에 텅 비어버린
  방은 자동으로 정리해요.

새 종류의 방을 추가하려면 cogs/room.py의 ROOM_KINDS 딕셔너리에 항목 하나만 추가하면 돼요.
"""
import asyncio
import os

import discord
from discord.ext import commands

from utils import room_store

ROOM_EXPIRE_SECONDS = 600  # 방을 만들고 이 시간 안에 아무도 안 들어오면 자동 삭제해요.
REQUEST_TIMEOUT_SECONDS = 600  # 입장 신청 알림(수락/거절 버튼)이 유효한 시간
OWNER_LEAVE_GRACE_SECONDS = 10  # 방장이 나간 뒤 이 시간 뒤에 방을 자동으로 닫아요.


# ============================================================
# 입장 신청 수락/거절 버튼 UI
# ============================================================
class JoinRequestView(discord.ui.View):
    def __init__(self, engine: "DynamicRoomEngine", guild_id: int, channel_id: int, requester_id: int, owner_id: int):
        super().__init__(timeout=REQUEST_TIMEOUT_SECONDS)
        self.engine = engine
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.requester_id = requester_id
        self.owner_id = owner_id
        self.message: discord.Message | None = None  # send 이후에 채워줘요. (버튼 처리 후 원본 메시지 수정용)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("이 요청은 방장만 처리할 수 있어요.", ephemeral=True)
            return False
        return True

    def _disable_all(self):
        for child in self.children:
            child.disabled = True

    async def _edit_original(self, content: str):
        if self.message is None:
            return
        try:
            await self.message.edit(content=content, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="✅ 수락", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = self.engine.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.followup.send("⚠️ 서버를 찾을 수 없어요.", ephemeral=True)
            return

        channel = guild.get_channel(self.channel_id)
        requester = guild.get_member(self.requester_id)
        self._disable_all()

        if channel is None or requester is None:
            await self._edit_original("⚠️ 방이 이미 닫혔거나 사용자를 찾을 수 없어서 처리하지 못했어요.")
            self.stop()
            return

        room_label = self.engine.label_for(channel.id)
        try:
            await channel.set_permissions(
                requester, connect=True, view_channel=True, reason=f"{room_label} 입장 신청 수락 (방장: {self.owner_id})"
            )
        except discord.Forbidden:
            await interaction.followup.send("⚠️ 권한이 없어서 수락하지 못했어요.", ephemeral=True)
            self.stop()
            return

        await self._edit_original(f"✅ **{requester.display_name}**님의 입장 신청을 수락했어요!")
        try:
            await requester.send(f"✅ {room_label} 입장 신청이 수락됐어요! {channel.mention}에 입장해보세요.")
        except discord.Forbidden:
            pass
        self.stop()

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = self.engine.bot.get_guild(self.guild_id)
        requester = guild.get_member(self.requester_id) if guild else None
        self._disable_all()

        await self._edit_original(
            f"❌ **{requester.display_name if requester else '알 수 없음'}**님의 입장 신청을 거절했어요."
        )
        if requester is not None:
            room_label = self.engine.label_for(self.channel_id)
            try:
                await requester.send(f"❌ 아쉽게도 {room_label} 입장 신청이 거절됐어요.")
            except discord.Forbidden:
                pass
        self.stop()

    async def on_timeout(self):
        self._disable_all()
        await self._edit_original("⌛ 신청 시간이 만료됐어요. (다시 신청해달라고 해주세요)")


class DynamicRoomEngine:
    """방 종류(랭크방/폐관수련방/프리미어방 등) 여러 개를 한꺼번에 관리하는 엔진이에요.
    cog는 이 엔진의 메서드를 그대로 호출하는 얇은 슬래시 명령어 껍데기만 정의하면 돼요."""

    def __init__(self, bot: commands.Bot, room_kinds: dict[str, dict]):
        self.bot = bot
        self.room_kinds = room_kinds  # kind_key -> {"label", "emoji", "category_env_key", "choice_name"}

        self.owner_to_channel: dict[int, int] = {}  # owner_id -> channel_id
        self.channel_to_owner: dict[int, int] = {}  # channel_id -> owner_id
        self.channel_to_kind: dict[int, str] = {}  # channel_id -> kind_key
        self.owner_leave_tasks: dict[int, asyncio.Task] = {}  # channel_id -> 방장 퇴장 후 자동 삭제 타이머

    # ============================================================
    # 헬퍼
    # ============================================================
    def label_for(self, channel_id: int) -> str:
        kind = self.channel_to_kind.get(channel_id)
        return self.room_kinds.get(kind, {}).get("label", "방")

    def _emoji_for(self, channel_id: int) -> str:
        kind = self.channel_to_kind.get(channel_id)
        return self.room_kinds.get(kind, {}).get("emoji", "🔒")

    def _get_category(self, guild: discord.Guild, kind: str) -> discord.CategoryChannel | None:
        category_env_key = self.room_kinds[kind]["category_env_key"]
        category_id = os.getenv(category_env_key)
        if not category_id or not category_id.isdigit():
            return None
        category = guild.get_channel(int(category_id))
        return category if isinstance(category, discord.CategoryChannel) else None

    def _track(self, channel_id: int, owner_id: int, kind: str):
        """메모리 + 파일 둘 다에 기록해요."""
        self.owner_to_channel[owner_id] = channel_id
        self.channel_to_owner[channel_id] = owner_id
        self.channel_to_kind[channel_id] = kind
        room_store.add_room(channel_id, owner_id, kind)

    def _cleanup_tracking(self, channel_id: int):
        """메모리 + 파일 둘 다에서 지워요."""
        owner_id = self.channel_to_owner.pop(channel_id, None)
        if owner_id is not None:
            self.owner_to_channel.pop(owner_id, None)
        self.channel_to_kind.pop(channel_id, None)
        room_store.remove_room(channel_id)

        task = self.owner_leave_tasks.pop(channel_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _schedule_owner_leave_deletion(self, channel: discord.VoiceChannel, owner_id: int):
        """방장이 나가고 아직 방에 다른 사람이 남아있을 때, OWNER_LEAVE_GRACE_SECONDS 뒤 방을 자동으로 닫아요."""
        existing = self.owner_leave_tasks.pop(channel.id, None)
        if existing is not None and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._delete_after_owner_leave(channel.guild.id, channel.id, owner_id))
        self.owner_leave_tasks[channel.id] = task

    async def _delete_after_owner_leave(self, guild_id: int, channel_id: int, owner_id: int):
        room_label = self.label_for(channel_id)
        try:
            await asyncio.sleep(OWNER_LEAVE_GRACE_SECONDS)
        except asyncio.CancelledError:
            return  # 방장이 다시 들어와서 취소된 경우

        self.owner_leave_tasks.pop(channel_id, None)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            self._cleanup_tracking(channel_id)
            return

        self._cleanup_tracking(channel_id)
        try:
            await channel.delete(reason="방장 퇴장으로 자동 삭제")
            print(f"🗑️ '{channel.name}' {room_label}을 자동 삭제했어요. (방장 퇴장)")
        except (discord.Forbidden, discord.NotFound):
            pass

    def _schedule_unused_check(self, channel: discord.VoiceChannel):
        """방을 만들고 ROOM_EXPIRE_SECONDS 안에 아무도 안 들어오면 자동으로 삭제해요."""
        asyncio.create_task(self._delete_if_still_unused(channel.guild.id, channel.id))

    async def _delete_if_still_unused(self, guild_id: int, channel_id: int):
        room_label = self.label_for(channel_id)
        await asyncio.sleep(ROOM_EXPIRE_SECONDS)

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            self._cleanup_tracking(channel_id)
            return
        if len(channel.members) > 0:
            return  # 누가 들어와 있으면 그냥 둬요.

        self._cleanup_tracking(channel_id)
        try:
            await channel.delete(reason=f"{room_label} 미사용으로 자동 삭제 ({ROOM_EXPIRE_SECONDS // 60}분 경과)")
            print(f"🗑️ '{channel.name}' {room_label}을 자동 삭제했어요. (미사용)")
        except (discord.Forbidden, discord.NotFound):
            pass

    # ============================================================
    # 재시작 시 저장된 방 목록 복구 + 정리 (cog의 on_ready에서 호출)
    # ============================================================
    async def on_ready_recover(self):
        stored = room_store.load_all()  # {channel_id: {"owner_id", "kind"}}
        recovered = 0
        cleaned = 0

        for channel_id, info in stored.items():
            owner_id = info["owner_id"]
            kind = info.get("kind")
            channel = self.bot.get_channel(channel_id)
            if channel is None or kind not in self.room_kinds:
                # 채널이 아예 사라졌거나(수동 삭제 등) 모르는 종류면 기록만 지워요.
                room_store.remove_room(channel_id)
                cleaned += 1
                continue

            if len(channel.members) == 0:
                # 봇이 꺼져있는 동안 다 나가서 방이 비어버린 경우, 그때 못 지운 거라 지금 정리해요.
                room_store.remove_room(channel_id)
                try:
                    await channel.delete(reason="봇 재시작 시 정리 - 방이 비어있었음")
                except (discord.Forbidden, discord.NotFound):
                    pass
                cleaned += 1
                continue

            # 아직 사람이 있는 방은 계속 관리해요.
            self.owner_to_channel[owner_id] = channel_id
            self.channel_to_owner[channel_id] = owner_id
            self.channel_to_kind[channel_id] = kind
            recovered += 1

        print(f"🔊 즉석생성형 통화방 복구 완료: {recovered}개 복구, {cleaned}개 정리됨.")

    # ============================================================
    # 슬래시 명령어 로직 (cog가 그대로 호출)
    # ============================================================
    async def create_room(self, interaction: discord.Interaction, kind: str, 인원수: int | None):
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("❌ 서버 안에서만 사용할 수 있어요.", ephemeral=True)
            return

        kind_cfg = self.room_kinds[kind]
        room_label = kind_cfg["label"]
        emoji = kind_cfg["emoji"]

        existing_channel_id = self.owner_to_channel.get(interaction.user.id)
        if existing_channel_id is not None:
            existing_channel = interaction.guild.get_channel(existing_channel_id)
            if existing_channel is not None:
                existing_label = self.label_for(existing_channel_id)
                await interaction.followup.send(
                    f"이미 열려있는 {existing_label}이 있어요: {existing_channel.mention}\n"
                    f"새로 만들려면 먼저 `/방닫기`로 닫아주세요.",
                    ephemeral=True,
                )
                return
            self._cleanup_tracking(existing_channel_id)  # 남아있던 오래된 기록 정리

        everyone = interaction.guild.default_role
        overwrites = {
            everyone: discord.PermissionOverwrite(view_channel=True, connect=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True, send_messages=True
            ),
        }

        try:
            channel = await interaction.guild.create_voice_channel(
                name=f"{emoji}{interaction.user.display_name}의 {room_label}",
                category=self._get_category(interaction.guild, kind),
                overwrites=overwrites,
                user_limit=인원수 if 인원수 else 0,
                reason=f"/방만들기 {room_label} 사용 (방장: {interaction.user.display_name})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ 봇에게 채널 생성 권한이 없어서 방을 만들지 못했어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        self._track(channel.id, interaction.user.id, kind)
        self._schedule_unused_check(channel)

        capacity_text = f" (최대 {인원수}명)" if 인원수 else ""
        minutes = ROOM_EXPIRE_SECONDS // 60
        await interaction.followup.send(
            f"{emoji} {room_label}을 만들었어요! {channel.mention}{capacity_text}\n"
            f"다른 사람들은 방을 볼 수는 있지만, `/방초대`로 직접 초대하거나 `/방신청`을 받아서 승인해야 들어올 수 있어요.\n"
            f"(⏳ {minutes}분 안에 아무도 안 들어오면 자동으로 사라져요 · 방이 완전히 비면 바로 사라져요 · "
            f"방장이 나가면 {OWNER_LEAVE_GRACE_SECONDS}초 후 자동으로 사라져요)",
            ephemeral=True,
        )

    async def invite(self, interaction: discord.Interaction, 대상: discord.Member):
        await interaction.response.defer(ephemeral=True)

        channel_id = self.owner_to_channel.get(interaction.user.id)
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            if channel_id is not None:
                self._cleanup_tracking(channel_id)
            await interaction.followup.send("먼저 `/방만들기`로 방을 만들어주세요.", ephemeral=True)
            return

        if 대상.id == interaction.user.id:
            await interaction.followup.send("자기 자신은 이미 입장할 수 있어요.", ephemeral=True)
            return

        try:
            await channel.set_permissions(
                대상, connect=True, view_channel=True, reason=f"{interaction.user.display_name}님이 초대함"
            )
        except discord.Forbidden:
            await interaction.followup.send("⚠️ 권한이 없어서 초대하지 못했어요.", ephemeral=True)
            return

        room_label = self.label_for(channel.id)
        emoji = self._emoji_for(channel.id)
        await interaction.followup.send(f"✅ {대상.mention}님을 초대했어요!", ephemeral=True)
        try:
            await 대상.send(
                f"{emoji} **{interaction.user.display_name}**님이 {room_label}에 초대했어요! {channel.mention}에 입장해보세요."
            )
        except discord.Forbidden:
            pass

    async def request_join(self, interaction: discord.Interaction, 방장: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if 방장.id == interaction.user.id:
            await interaction.followup.send("자기 방에는 신청할 필요 없이 바로 입장할 수 있어요.", ephemeral=True)
            return

        channel_id = self.owner_to_channel.get(방장.id)
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            if channel_id is not None:
                self._cleanup_tracking(channel_id)
            await interaction.followup.send(f"{방장.display_name}님은 지금 열려있는 방이 없어요.", ephemeral=True)
            return

        current_overwrite = channel.overwrites_for(interaction.user)
        if current_overwrite.connect:
            await interaction.followup.send(f"이미 입장 권한이 있어요! {channel.mention}에 바로 입장해보세요.", ephemeral=True)
            return

        room_label = self.label_for(channel.id)
        view = JoinRequestView(self, interaction.guild.id, channel.id, interaction.user.id, 방장.id)
        notice = (
            f"🙋 **{interaction.user.display_name}**님이 회원님의 {room_label}(**{channel.name}**)에 "
            f"입장 신청을 보냈어요!"
        )

        sent_message: discord.Message | None = None
        try:
            sent_message = await 방장.send(notice, view=view)
        except discord.Forbidden:
            try:
                sent_message = await channel.send(f"{방장.mention} {notice}", view=view)
            except discord.Forbidden:
                sent_message = None

        if sent_message is None:
            await interaction.followup.send(
                "⚠️ 방장에게 신청을 전달하지 못했어요. (DM이 막혀있고, 방 채팅 전송 권한도 없어요) 직접 연락해보세요.",
                ephemeral=True,
            )
            return

        view.message = sent_message
        await interaction.followup.send(f"📨 {방장.display_name}님에게 입장 신청을 보냈어요! 승인하면 알려드릴게요.", ephemeral=True)

    async def close_room(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel_id = self.owner_to_channel.get(interaction.user.id)
        if channel_id is None:
            await interaction.followup.send("열려있는 방이 없어요.", ephemeral=True)
            return

        room_label = self.label_for(channel_id)
        self._cleanup_tracking(channel_id)
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason="/방닫기 사용")
            except discord.Forbidden:
                await interaction.followup.send("⚠️ 채널 삭제 권한이 없어요. 관리자에게 문의해주세요.", ephemeral=True)
                return

        print(f"🗑️ {interaction.user.display_name}님이 {room_label}을 직접 닫았어요.")
        await interaction.followup.send(f"🗑️ {room_label}을 닫았어요.", ephemeral=True)

    # ============================================================
    # 자동 삭제(방이 완전히 비면) + 퇴장 시 입장 권한 자동 회수 (cog의 on_voice_state_update에서 호출)
    # ============================================================
    async def handle_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        # 방장이 자기 방으로 (다시) 들어오면, 걸려있던 자동 삭제 타이머를 취소해요.
        if after.channel is not None and self.channel_to_owner.get(after.channel.id) == member.id:
            task = self.owner_leave_tasks.pop(after.channel.id, None)
            if task is not None and not task.done():
                task.cancel()

        if before.channel is None or before.channel.id not in self.channel_to_owner:
            return

        if after.channel is not None and after.channel.id == before.channel.id:
            # 같은 방에 그대로 있음 (음소거/카메라/화면공유 등 상태 변경일 뿐 실제 퇴장이 아니에요)
            return

        channel = before.channel
        owner_id = self.channel_to_owner[channel.id]
        room_label = self.label_for(channel.id)

        if len(channel.members) == 0:
            self._cleanup_tracking(channel.id)
            try:
                await channel.delete(reason=f"{room_label}에 아무도 없어서 자동 삭제")
                print(f"🗑️ '{channel.name}' {room_label}을 자동 삭제했어요. (인원 0명)")
            except (discord.Forbidden, discord.NotFound):
                pass
            return

        if member.id == owner_id:
            # 방장이 나갔지만 아직 다른 사람이 남아있으면, 안내하고 유예시간 뒤에 방을 닫아요.
            try:
                await channel.send(f"⚠️ 방장이 퇴장해서 {OWNER_LEAVE_GRACE_SECONDS}초 후 이 {room_label}이 자동으로 사라져요.")
            except discord.Forbidden:
                pass
            self._schedule_owner_leave_deletion(channel, owner_id)
            return

        # 방장이 아닌데(초대/신청으로 들어왔던 사람) 방을 나가면, 다시 초대/신청해야 들어올 수 있도록
        # 개인 입장 권한을 자동으로 회수해요.
        current = channel.overwrites_for(member)
        if current.connect or current.view_channel:
            try:
                await channel.set_permissions(member, overwrite=None, reason=f"{room_label} 퇴장으로 입장 권한 자동 회수")
                print(f"🚪 {member.display_name}님의 '{channel.name}' {room_label} 입장 권한을 회수했어요. (퇴장)")
            except (discord.Forbidden, discord.NotFound):
                pass
