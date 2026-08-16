"""
관전 전용 통화방 입장권 기능이에요. (마이크 발언만 불가, 채팅은 가능)

- /관전입장권 치면 "관전입장권" 역할을 자동으로 만들어서(없으면) 부여해요.
- 지정된 관전 통화방들(여러 개 가능)을 자동으로 잠가요:
  @everyone은 입장 금지, "관전입장권" 역할은 입장은 가능하지만 마이크 발언만 금지 (채팅은 가능).
- /관전입장권취소로 직접 반납할 수도 있어요.
- ⚠️ 디스코드 권한 시스템은 "여러 역할 중 허용이 있으면 거부보다 허용이 이기는" 방식이라,
  다른 역할이 그 채널에서 마이크를 허용하고 있으면 역할 단위 거부만으로는 못 막아요.
  그래서 역할 부여와 별개로, 받은 사람 "개인"한테도 직접 거부 권한을 걸어둬요.
  개인 권한은 역할 권한보다 우선순위가 높아서 다른 역할이 뭘 허용하든 이게 이겨요.
  (단, 그 사람이 "관리자" 권한을 가진 역할이 있으면 이것조차 무시돼요 - 디스코드 자체 사양이라 못 막아요)
- 그 통화방 목록 안에서 다른 관전 통화방으로 이동하는 건 역할이 유지되고,
  목록에 없는 채널로 나가거나 완전히 퇴장하면 역할과 개인 권한이 자동으로 회수돼요.
- ⚠️ 받고 나서 아예 입장을 안 하면 "나가는" 이벤트 자체가 없어서 역할이 계속 남아있는 문제가 있었어요.
  그래서 입장권을 받고 TICKET_EXPIRE_SECONDS(기본 10분) 안에 그 통화방들 중 하나에도 들어가지 않으면
  자동으로 역할/개인 권한을 회수하도록 타이머를 걸어둬요. 봇이 재시작돼도 시작할 때 한 번 전체를 점검해요.

설정 방법:
1. 디스코드에서 관전용으로 쓸 통화방을 미리 만들어두세요. (권한은 굳이 미리 안 만져도 봇이 알아서 설정해요)
2. 채널 ID를 복사해서 .env 파일에 아래처럼 추가하세요. 여러 개면 쉼표(,)로 구분하면 돼요:
   SPECTATOR_VOICE_CHANNEL_ID=111111111111111111,222222222222222222,333333333333333333
"""
import asyncio
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils.channel_check import restrict_to_channel

ROLE_NAME = "관전입장권"
TICKET_EXPIRE_SECONDS = 600  # 10분 안에 통화방에 안 들어가면 자동으로 역할/개인 권한을 회수해요.


class SpectatorTicket(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_expiry: dict[int, asyncio.Task] = {}  # member_id -> 만료 체크 태스크

    def _get_configured_channel_ids(self) -> list[int]:
        """.env의 SPECTATOR_VOICE_CHANNEL_ID를 쉼표 기준으로 나눠서 숫자 ID 목록으로 반환해요."""
        raw = os.getenv("SPECTATOR_VOICE_CHANNEL_ID")
        if not raw:
            return []
        ids = []
        for piece in raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                ids.append(int(piece))
            except ValueError:
                print(f"⚠️ SPECTATOR_VOICE_CHANNEL_ID 안에 잘못된 값이 있어요(무시함): '{piece}'")
        return ids

    def _get_voice_channels(self, guild: discord.Guild) -> list[discord.VoiceChannel]:
        """설정된 ID들 중 이 서버에 실제로 존재하는 음성 채널만 반환해요."""
        channels = []
        for channel_id in self._get_configured_channel_ids():
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                channels.append(channel)
        return channels

    async def _get_or_create_role(self, guild: discord.Guild) -> discord.Role:
        role = discord.utils.get(guild.roles, name=ROLE_NAME)
        if role is None:
            role = await guild.create_role(
                name=ROLE_NAME, color=discord.Color.dark_gray(), reason="관전 입장권 역할 자동 생성"
            )
            print(f"🆕 '{ROLE_NAME}' 역할을 새로 만들었어요. (서버: {guild.name})")
        return role

    async def _ensure_channel_locked(self, channel: discord.VoiceChannel, role: discord.Role):
        """
        @everyone은 입장 금지, 관전입장권 역할은 입장은 가능하지만
        마이크 발언(speak)만 금지하도록 채널 권한을 맞춰요. (채팅은 허용)
        (이미 맞는 상태면 아무 것도 안 해요)
        """
        everyone = channel.guild.default_role
        overwrites = dict(channel.overwrites)
        changed = False

        everyone_ow = overwrites.get(everyone, discord.PermissionOverwrite())
        if everyone_ow.connect is not False:
            everyone_ow.connect = False
            overwrites[everyone] = everyone_ow
            changed = True

        role_ow = overwrites.get(role, discord.PermissionOverwrite())
        if role_ow.connect is not True or role_ow.speak is not False:
            role_ow.connect = True
            role_ow.speak = False  # 마이크로 말하기만 금지 (채팅은 건드리지 않음 = 허용)
            overwrites[role] = role_ow
            changed = True

        if changed:
            _t_edit = time.monotonic()
            try:
                await channel.edit(overwrites=overwrites, reason="관전 입장권 채널 잠금 설정")
                print(f"🔒 '{channel.name}' 통화방을 관전 전용(마이크 금지)으로 잠갔어요. ({time.monotonic() - _t_edit:.2f}초)")
            except discord.Forbidden:
                print(f"⚠️ '{channel.name}' 통화방 권한을 설정할 권한이 없어요. 봇 역할 권한을 확인해주세요.")
        else:
            print(f"🔓 '{channel.name}' 채널 권한이 이미 맞는 상태라 channel.edit() 호출 안 함")

    async def _ensure_member_muted(self, channel: discord.VoiceChannel, member: discord.Member):
        """
        역할 권한만으로는 다른 역할의 '허용'을 못 이길 수 있어서, 이 사람 개인한테도 직접
        마이크 거부 권한을 걸어둬요. 개인 권한은 역할 권한보다 우선순위가 높아요.
        (그 사람이 관리자 권한을 가진 역할이 있으면 이것도 무시돼요 - 디스코드 자체 사양)
        """
        current = channel.overwrites_for(member)
        if current.connect is True and current.speak is False:
            return  # 이미 딱 맞게 설정돼 있어요.
        try:
            await channel.set_permissions(
                member, connect=True, speak=False, reason="관전 입장권 - 개인 마이크 차단"
            )
        except discord.Forbidden:
            print(f"⚠️ '{channel.name}'에서 {member.display_name}님 개인 권한을 설정할 권한이 없어요.")

    async def _clear_member_override(self, channel: discord.VoiceChannel, member: discord.Member):
        """입장권 회수 시, 걸어뒀던 개인 권한 오버라이드를 지워요. (없으면 그냥 넘어가요)"""
        if member not in channel.overwrites:
            return
        try:
            await channel.set_permissions(member, overwrite=None, reason="관전 입장권 회수 - 개인 권한 정리")
        except discord.Forbidden:
            print(f"⚠️ '{channel.name}'에서 {member.display_name}님 개인 권한을 지울 권한이 없어요.")

    def _is_member_in_any(self, member: discord.Member, channel_ids: set[int]) -> bool:
        return (
            member.voice is not None
            and member.voice.channel is not None
            and member.voice.channel.id in channel_ids
        )

    def _schedule_expiry(self, member: discord.Member, role: discord.Role):
        """기존에 걸려있던 타이머가 있으면 취소하고, 새로 TICKET_EXPIRE_SECONDS 뒤 만료 체크를 예약해요."""
        existing = self.pending_expiry.get(member.id)
        if existing is not None and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._expire_after_delay(member.guild.id, member.id, role.id))
        self.pending_expiry[member.id] = task

    async def _expire_after_delay(self, guild_id: int, member_id: int, role_id: int):
        try:
            await asyncio.sleep(TICKET_EXPIRE_SECONDS)
        except asyncio.CancelledError:
            return

        self.pending_expiry.pop(member_id, None)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        member = guild.get_member(member_id)
        role = guild.get_role(role_id)
        if member is None or role is None or role not in member.roles:
            return

        channel_ids = set(self._get_configured_channel_ids())
        if self._is_member_in_any(member, channel_ids):
            return  # 방에 있으면 그냥 둬요. (나갈 때 정상적으로 회수돼요)

        for channel_id in channel_ids:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                await self._clear_member_override(channel, member)

        try:
            await member.remove_roles(role, reason=f"관전 입장권 미사용으로 자동 회수 ({TICKET_EXPIRE_SECONDS // 60}분 경과)")
            print(f"🎫 {member.display_name}님의 관전 입장권을 자동 회수했어요. (통화방 미입장)")
        except discord.Forbidden:
            print(f"⚠️ {member.display_name}님의 관전 입장권을 자동 회수할 권한이 없어요.")

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇이 재시작되면 메모리에 있던 타이머도 다 날아가니까, 시작할 때 한 번 전체를 점검해요.
        channel_ids = set(self._get_configured_channel_ids())
        for guild in self.bot.guilds:
            role = discord.utils.get(guild.roles, name=ROLE_NAME)
            if role is None:
                continue
            for member in role.members:
                if self._is_member_in_any(member, channel_ids):
                    continue  # 이미 방에 있으면 정상적으로 나갈 때 회수될 거예요.
                self._schedule_expiry(member, role)
        print("🎫 관전 입장권 미입장 회수 타이머 점검 완료.")

    @app_commands.command(name="관전입장권", description="관전 전용 통화방에 입장할 수 있는 역할을 받아요. (마이크만 불가, 채팅 가능)")
    @restrict_to_channel("rank_room")
    async def get_ticket(self, interaction: discord.Interaction):
        _t_start = time.monotonic()
        # 역할 생성 + 채널 권한 수정(API 호출 여러 번)이 3초를 넘길 수 있어서, 먼저 defer로 시간을 벌어요.
        await interaction.response.defer(ephemeral=True)
        print(f"⏱️ [관전입장권] defer 완료: {time.monotonic() - _t_start:.2f}초")

        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("❌ 서버 안에서만 사용할 수 있어요.", ephemeral=True)
            return

        voice_channels = self._get_voice_channels(interaction.guild)
        if not voice_channels:
            await interaction.followup.send(
                "⚠️ 관전 통화방이 설정되어 있지 않아요. 관리자에게 문의해주세요. "
                "(.env 파일에 SPECTATOR_VOICE_CHANNEL_ID가 필요해요)",
                ephemeral=True,
            )
            return

        _t1 = time.monotonic()
        role = await self._get_or_create_role(interaction.guild)
        print(f"⏱️ [관전입장권] 역할 조회/생성: {time.monotonic() - _t1:.2f}초")

        _t2 = time.monotonic()
        for channel in voice_channels:
            await self._ensure_channel_locked(channel, role)
        print(f"⏱️ [관전입장권] 채널 {len(voice_channels)}개 권한 확인/설정: {time.monotonic() - _t2:.2f}초")

        # 다른 역할이 허용하고 있어도 이기도록, 이 사람 개인한테 직접 거부 권한을 걸어둬요.
        _t_member = time.monotonic()
        for channel in voice_channels:
            await self._ensure_member_muted(channel, interaction.user)
        print(f"⏱️ [관전입장권] 개인 권한 설정: {time.monotonic() - _t_member:.2f}초")

        channel_mentions = ", ".join(c.mention for c in voice_channels)
        already_had = role in interaction.user.roles

        if not already_had:
            try:
                _t3 = time.monotonic()
                await interaction.user.add_roles(role, reason="/관전입장권 사용")
                print(f"⏱️ [관전입장권] 역할 부여(add_roles): {time.monotonic() - _t3:.2f}초")
            except discord.Forbidden:
                await interaction.followup.send(
                    "⚠️ 봇에게 역할 관리 권한이 없어서 입장권을 드리지 못했어요. 관리자에게 문의해주세요.",
                    ephemeral=True,
                )
                return

        # 새로 받았든 이미 갖고 있었든, 타이머는 항상 새로 갱신해요.
        self._schedule_expiry(interaction.user, role)
        minutes = TICKET_EXPIRE_SECONDS // 60

        if already_had:
            await interaction.followup.send(
                f"이미 관전 입장권을 갖고 있어요! {channel_mentions}에 입장할 수 있어요. (마이크는 안 되지만 채팅은 가능해요)\n"
                f"(⏳ {minutes}분 안에 입장하지 않으면 자동으로 회수돼요)",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"🎫 관전 입장권을 받았어요! 이제 {channel_mentions}에 입장할 수 있어요.\n"
                f"(마이크 발언은 막혀있지만 채팅은 가능해요 · 나가면 자동 회수 · ⏳ {minutes}분 안에 입장하지 않아도 자동으로 회수돼요)\n"
                f"⚠️ 참고: 관리자 권한을 가진 역할이 있는 사람은 이 제한이 적용되지 않아요. (디스코드 자체 사양)",
                ephemeral=True,
            )
        print(f"⏱️ [관전입장권] 전체 소요시간: {time.monotonic() - _t_start:.2f}초")

    @app_commands.command(name="관전입장권취소", description="갖고 있는 관전 입장권을 직접 반납해요.")
    @restrict_to_channel("rank_room")
    async def cancel_ticket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("❌ 서버 안에서만 사용할 수 있어요.", ephemeral=True)
            return

        role = discord.utils.get(interaction.guild.roles, name=ROLE_NAME)
        if role is None or role not in interaction.user.roles:
            await interaction.followup.send("관전 입장권을 갖고 있지 않아요.", ephemeral=True)
            return

        # 걸려있던 만료 타이머가 있으면 취소해요.
        task = self.pending_expiry.pop(interaction.user.id, None)
        if task is not None and not task.done():
            task.cancel()

        # 걸어뒀던 개인 채널 권한도 다 정리해요.
        for channel_id in self._get_configured_channel_ids():
            channel = interaction.guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                await self._clear_member_override(channel, interaction.user)

        try:
            await interaction.user.remove_roles(role, reason="/관전입장권취소 사용")
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ 봇에게 역할 관리 권한이 없어서 취소하지 못했어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        print(f"🗑️ {interaction.user.display_name}님이 관전 입장권을 직접 반납했어요.")
        await interaction.followup.send("🗑️ 관전 입장권을 반납했어요.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        channel_ids = set(self._get_configured_channel_ids())
        if not channel_ids:
            return

        # 방에 실제로 들어왔으면, 미입장 만료 타이머는 더 이상 필요 없으니 취소해요.
        if after.channel is not None and after.channel.id in channel_ids:
            task = self.pending_expiry.pop(member.id, None)
            if task is not None and not task.done():
                task.cancel()

        was_in_spectator = before.channel is not None and before.channel.id in channel_ids
        still_in_spectator = after.channel is not None and after.channel.id in channel_ids

        if not was_in_spectator or still_in_spectator:
            return  # 원래 관전방에 없었거나, 관전방 목록 안에서 이동한 경우엔 역할을 유지해요.

        role = discord.utils.get(member.guild.roles, name=ROLE_NAME)
        has_role = role is not None and role in member.roles

        # 개인 권한 오버라이드는 걸려있는 채널마다 정리해줘요.
        for channel_id in channel_ids:
            channel = member.guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                await self._clear_member_override(channel, member)

        if not has_role:
            return

        try:
            await member.remove_roles(role, reason="관전 통화방 퇴장으로 입장권 자동 회수")
            print(f"🎫 {member.display_name}님의 관전 입장권을 회수했어요. (통화방 퇴장)")
        except discord.Forbidden:
            print(f"⚠️ {member.display_name}님의 관전 입장권 역할을 제거할 권한이 없어요.")


async def setup(bot: commands.Bot):
    await bot.add_cog(SpectatorTicket(bot))