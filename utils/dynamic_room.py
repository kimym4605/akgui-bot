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
- /방장넘기기 대상:@사람 으로 방 안에 있는 사람에게 방장을 넘길 수 있어요.
  (먼저 자리를 비워야 할 때 방이 닫히지 않게 하는 용도예요)
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
import logging
import asyncio
import os

import discord
from discord.ext import commands

from utils import room_store

log = logging.getLogger(__name__)

ROOM_EXPIRE_SECONDS = 600  # 방을 만들고 이 시간 안에 아무도 안 들어오면 자동 삭제해요.
REQUEST_TIMEOUT_SECONDS = 600  # 입장 신청 알림(수락/거절 버튼)이 유효한 시간
OWNER_LEAVE_GRACE_SECONDS = 10  # 방장이 나간 뒤 이 시간 뒤에 방을 자동으로 닫아요.
RENAME_WAIT_SECONDS = 2  # 방 이름이 이 시간 안에 바뀌면 "바꿨어요", 늦어지면 "곧 반영돼요"라고 안내해요.


def _engine_from(client: discord.Client) -> "DynamicRoomEngine | None":
    """살아있는 엔진 인스턴스를 가져와요. (cog를 못 찾으면 None)

    버튼 쪽 코드는 엔진을 직접 들고 있지 않을 수 있어서(DynamicItem은 봇 재시작 후
    custom_id만 가지고 되살아나요), 필요할 때 이렇게 꺼내 써요.
    """
    return getattr(client.get_cog("Room"), "engine", None)


# ============================================================
# 발언 허용 버튼 UI (입장시 뮤트 옵션이 켜진 방에서 씀)
# ------------------------------------------------------------
# ⚠️ 왜 평범한 View가 아니라 DynamicItem인가:
# 이 버튼은 "방장이 눌러줄 때까지" 계속 살아있어야 하는데, 보통의 View는 봇이 재시작되면
# 메모리에서 사라져서 눌러도 "상호작용 실패"만 떠요. 그러면 뮤트를 풀 방법이 없어져요.
# DynamicItem은 버튼의 custom_id 문자열 자체에 필요한 정보를 다 박아두고, 눌린 순간
# 그걸 정규식으로 다시 꺼내 쓰는 방식이라 봇이 재시작돼도 그대로 동작해요.
# (그래서 엔진 인스턴스를 참조하지 않고, 방장 ID까지 custom_id에 같이 넣어요)
# ============================================================
class SpeakGrantButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"room:speak:(?P<channel_id>\d+):(?P<member_id>\d+):(?P<owner_id>\d+)",
):
    def __init__(self, channel_id: int, member_id: int, owner_id: int):
        super().__init__(
            discord.ui.Button(
                label="🔊 발언 허용",
                style=discord.ButtonStyle.success,
                custom_id=f"room:speak:{channel_id}:{member_id}:{owner_id}",
            )
        )
        self.channel_id = channel_id
        self.member_id = member_id
        self.owner_id = owner_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["channel_id"]), int(match["member_id"]), int(match["owner_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ⚠️ custom_id에 박혀있는 owner_id는 "이 버튼이 올라간 시점의 방장"이에요.
        # `/방장넘기기`로 방장이 바뀌면 그 값은 옛 방장이라, 새 방장이 눌러도 거절당해요.
        # 그래서 지금의 방장을 먼저 조회하고, 조회가 안 될 때만(봇이 방 기록을 잃은 경우)
        # 박아둔 값으로 판단해요.
        engine = _engine_from(interaction.client)
        current_owner_id = engine.channel_to_owner.get(self.channel_id) if engine else None
        allowed_id = current_owner_id if current_owner_id is not None else self.owner_id
        if interaction.user.id != allowed_id:
            await interaction.response.send_message("이 버튼은 방장만 누를 수 있어요.", ephemeral=True)
            return False
        return True

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        channel = guild.get_channel(self.channel_id) if guild else None
        member = guild.get_member(self.member_id) if guild else None

        if channel is None or member is None:
            await interaction.response.send_message(
                "⚠️ 방이 이미 닫혔거나 그 사람을 찾을 수 없어요.", ephemeral=True
            )
            return

        try:
            # 지금 걸려있는 개인 권한은 그대로 두고 speak만 켜요.
            # (overwrite 객체를 통째로 새로 만들면 connect/view_channel이 날아가서 튕겨나가요)
            current = channel.overwrites_for(member)
            current.update(speak=True)
            await channel.set_permissions(
                member, overwrite=current, reason=f"방장이 {member.display_name}님의 발언을 허용함"
            )
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ 권한이 없어서 풀어주지 못했어요.", ephemeral=True)
            return
        except discord.NotFound:
            await interaction.response.send_message("⚠️ 방이 이미 닫혔어요.", ephemeral=True)
            return

        # ⚠️ 여기가 핵심이에요. speak 권한만 풀면 이미 음성에 접속해 있는 사람은 계속
        # "마이크 사용 권한이 없다"고 떠요. 서버 음소거까지 풀어줘야 바로 말할 수 있어요.
        # (자세한 이유는 DynamicRoomEngine.apply_server_mute 주석 참고)
        engine = _engine_from(interaction.client)
        if engine is not None:
            if await engine.apply_server_mute(member, False, "방장이 발언을 허용함"):
                engine._mark_muted(channel.id, member.id, False)
        else:
            # cog를 못 찾는 건 사실상 없는 상황이지만, 그래도 음소거는 꼭 풀어줘야 해요.
            try:
                await member.edit(mute=False, reason="방장이 발언을 허용함")
            except discord.HTTPException:
                pass

        log.info(f"🔊 방장이 '{channel.name}'에서 {member.display_name}님의 발언을 허용했어요.")

        # 버튼을 눌린 상태로 굳혀요. (같은 사람한테 두 번 누를 일이 없게)
        view = discord.ui.View(timeout=None)
        done = discord.ui.Button(label="🔊 발언 허용됨", style=discord.ButtonStyle.secondary, disabled=True)
        view.add_item(done)
        try:
            await interaction.response.edit_message(
                content=f"🔊 **{member.display_name}**님의 발언이 허용됐어요. 이제 마이크를 쓸 수 있어요!",
                view=view,
            )
        except discord.HTTPException:
            pass


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
        # 신청이 온 뒤에 `/방장넘기기`로 방장이 바뀌었을 수 있어요. 그때는 **지금의 방장**이
        # 처리해야 맞아요. (이 알림이 방 채팅으로 갔다면 새 방장도 볼 수 있고, 옛 방장 DM으로
        # 갔다면 그 사람은 이제 방장이 아니니 누르지 못하게 막아야 해요)
        current_owner_id = self.engine.channel_to_owner.get(self.channel_id)
        allowed_id = current_owner_id if current_owner_id is not None else self.owner_id
        if interaction.user.id != allowed_id:
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
        # 방장이 "입장시뮤트"를 켜고 만든 방이면, 신청으로 들어오는 사람은 말하기를 막은 채로 들여보내요.
        # (방장이 나중에 🔊 발언 허용 버튼을 눌러줘야 풀려요)
        mute_on_join = self.engine.is_mute_on_join(channel.id)
        try:
            await channel.set_permissions(
                requester,
                connect=True,
                view_channel=True,
                speak=False if mute_on_join else None,
                reason=f"{room_label} 입장 신청 수락 (방장: {self.owner_id})",
            )
        except discord.Forbidden:
            await interaction.followup.send("⚠️ 권한이 없어서 수락하지 못했어요.", ephemeral=True)
            self.stop()
            return

        if mute_on_join:
            await self._edit_original(
                f"✅ **{requester.display_name}**님의 입장 신청을 수락했어요! "
                f"(🔇 마이크가 막힌 상태로 들어와요 — 입장하면 방 채팅에 뜨는 **🔊 발언 허용** 버튼으로 풀어주세요)"
            )
        else:
            await self._edit_original(f"✅ **{requester.display_name}**님의 입장 신청을 수락했어요!")

        mute_notice = (
            "\n🔇 이 방은 입장하면 마이크가 막혀 있어요. 방장이 발언을 허용해줄 때까지 기다려주세요!"
            if mute_on_join else ""
        )
        try:
            await requester.send(
                f"✅ {room_label} 입장 신청이 수락됐어요! {channel.mention}에 입장해보세요.{mute_notice}"
            )
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
        self.channel_to_mute: dict[int, bool] = {}  # channel_id -> 입장시뮤트 옵션 켜짐 여부
        self.channel_to_muted: dict[int, set[int]] = {}  # channel_id -> 봇이 서버 음소거를 걸어둔 사람들
        self.owner_leave_tasks: dict[int, asyncio.Task] = {}  # channel_id -> 방장 퇴장 후 자동 삭제 타이머
        self.rename_tasks: dict[int, asyncio.Task] = {}  # channel_id -> 방 이름 바꾸기 작업 (한도 때문에 오래 걸릴 수 있어요)

    # ============================================================
    # 헬퍼
    # ============================================================
    def label_for(self, channel_id: int) -> str:
        kind = self.channel_to_kind.get(channel_id)
        return self.room_kinds.get(kind, {}).get("label", "방")

    def is_mute_on_join(self, channel_id: int) -> bool:
        """이 방이 '입장시뮤트'를 켜고 만들어진 방인지 알려줘요."""
        return self.channel_to_mute.get(channel_id, False)

    async def apply_server_mute(self, member: discord.Member, muted: bool, reason: str) -> bool:
        """서버 음소거를 걸거나 풀어요. 성공하면 True.

        ⚠️ 왜 채널 권한(speak)만으로는 부족한가 (2026-09-15 "발언 허용했는데 마이크 권한이 없대요"):

        디스코드는 **이미 음성에 접속해 있는 사람에게는 speak 권한 변경을 실시간으로 반영하지
        않아요.** 말하기 권한이 없는 채로 들어가면 그 사람의 음성 세션이 억제된 상태로 굳는데,
        나중에 채널 권한에서 speak를 허용해줘도 그 세션은 그대로예요. (실제로 감사 로그상
        `deny: SPEAK -> -`, `allow: ... -> SPEAK`까지 정상 반영됐는데도 유저는 못 썼어요.)
        방을 나갔다 들어오면 풀리지만, 나가는 순간 입장 권한이 회수돼서 다시 신청해야 해요.

        서버 음소거는 음성 세션에 **즉시** 반영되는 디스코드 네이티브 기능이라 이 문제가 없어요.
        그래서 speak 권한(방 안에서의 확실한 차단)과 서버 음소거(즉시 효과)를 같이 써요.
        """
        try:
            await member.edit(mute=muted, reason=reason)
            return True
        except discord.Forbidden:
            log.warning("⚠️ 서버 음소거 권한이 없어서 %s님을 처리하지 못했어요.", member.display_name)
        except discord.HTTPException as error:
            # 음성에 연결돼 있지 않으면 디스코드가 거부해요(40032). 퇴장 처리 중엔 흔한 일이라
            # 조용히 넘어가고, 남은 음소거는 나중에 정리 로직이 치워줘요.
            log.debug("서버 음소거 변경 실패 (%s, muted=%s): %s", member.display_name, muted, error)
        return False

    def _mark_muted(self, channel_id: int, member_id: int, muted: bool):
        """봇이 음소거를 건 사람을 기억해둬요. (봇이 재시작돼도 풀어줄 수 있게 파일에도 적어요)"""
        current = self.channel_to_muted.setdefault(channel_id, set())
        if muted:
            current.add(member_id)
        else:
            current.discard(member_id)
        room_store.set_muted(channel_id, list(current))

    async def release_all_mutes(self, guild: discord.Guild, channel_id: int):
        """방이 닫히기 전에, 그 방에서 봇이 걸어둔 서버 음소거를 전부 풀어줘요.

        방이 사라지면 기록도 같이 사라지니까, **지우기 전에** 풀어야 해요.
        안 그러면 그 사람은 다른 통화방에 가서도 계속 말을 못 하게 돼요.
        """
        member_ids = self.channel_to_muted.pop(channel_id, set())
        for member_id in member_ids:
            member = guild.get_member(member_id) if guild else None
            if member is not None:
                await self.apply_server_mute(member, False, "방이 닫혀서 음소거 자동 해제")

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

    def _track(self, channel_id: int, owner_id: int, kind: str, mute_on_join: bool = False):
        """메모리 + 파일 둘 다에 기록해요."""
        self.owner_to_channel[owner_id] = channel_id
        self.channel_to_owner[channel_id] = owner_id
        self.channel_to_kind[channel_id] = kind
        self.channel_to_mute[channel_id] = mute_on_join
        room_store.add_room(channel_id, owner_id, kind, mute_on_join)

    def _cleanup_tracking(self, channel_id: int):
        """메모리 + 파일 둘 다에서 지워요."""
        owner_id = self.channel_to_owner.pop(channel_id, None)
        if owner_id is not None:
            self.owner_to_channel.pop(owner_id, None)
        self.channel_to_kind.pop(channel_id, None)
        self.channel_to_mute.pop(channel_id, None)
        self.channel_to_muted.pop(channel_id, None)
        room_store.remove_room(channel_id)

        for tasks in (self.owner_leave_tasks, self.rename_tasks):
            task = tasks.pop(channel_id, None)
            if task is not None and not task.done():
                task.cancel()

    def _retrack_owner(self, channel_id: int, old_owner_id: int, new_owner_id: int):
        """방장만 갈아끼워요. (메모리 + 파일 둘 다)

        `_cleanup_tracking` + `_track`을 쓰면 안 돼요 — 중간에 방 기록이 사라지면서
        음소거 기록(`channel_to_muted`)과 자동 삭제 타이머까지 날아가요.
        """
        self.owner_to_channel.pop(old_owner_id, None)
        self.owner_to_channel[new_owner_id] = channel_id
        self.channel_to_owner[channel_id] = new_owner_id
        room_store.set_owner(channel_id, new_owner_id)

    def _schedule_rename(self, channel: discord.VoiceChannel) -> asyncio.Task:
        """방 이름을 **지금의 방장** 이름으로 맞추는 작업을 띄워요.

        ⚠️ 왜 백그라운드로 돌리는가: 디스코드는 채널 이름 변경을 **10분에 2번**으로 묶어놨어요.
        한도에 걸리면 discord.py가 풀릴 때까지 조용히 기다리는데, 그동안 명령어 응답이 통째로
        멈춰버려요(최대 몇 분). 그래서 따로 떼어 돌리고, 명령어는 기다리지 않고 바로 응답해요.
        한도가 풀리면 알아서 바뀌니까 이름을 포기하지 않아도 돼요.

        짧은 시간에 방장을 여러 번 넘기면 앞선 작업은 취소하고 마지막 것만 남겨요.
        (이름은 작업이 시작될 때 방장 기록에서 다시 읽으니 항상 최신 방장 이름이 돼요)
        """
        existing = self.rename_tasks.pop(channel.id, None)
        if existing is not None and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._rename_to_current_owner(channel))
        self.rename_tasks[channel.id] = task
        return task

    async def _rename_to_current_owner(self, channel: discord.VoiceChannel) -> bool:
        """방 이름을 `{이모지}{방장 이름}의 {방 종류}`로 맞춰요. 실제로 바꿨으면 True."""
        try:
            owner_id = self.channel_to_owner.get(channel.id)
            if owner_id is None:
                return False
            owner = channel.guild.get_member(owner_id)
            if owner is None:
                return False

            desired = f"{self._emoji_for(channel.id)}{owner.display_name}의 {self.label_for(channel.id)}"
            if channel.name == desired:
                return False

            await channel.edit(name=desired, reason="방장이 바뀌어서 방 이름 갱신")
            log.info(f"✏️ 방 이름을 '{desired}'로 바꿨어요.")
            return True
        except asyncio.CancelledError:
            raise  # 방이 닫혔거나 방장이 또 바뀐 경우 — 새 작업이 대신 처리해요.
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            log.warning(f"⚠️ 방 이름을 바꾸지 못했어요: {error}")
            return False
        finally:
            # 내 뒤에 새 작업이 등록됐을 수도 있어서, 나 자신일 때만 지워요.
            if self.rename_tasks.get(channel.id) is asyncio.current_task():
                self.rename_tasks.pop(channel.id, None)

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

        # 방장이 나가서 닫는 경우엔 아직 안에 사람이 남아있을 수 있어요. 기록을 지우기 전에 음소거부터 풀어줘요.
        await self.release_all_mutes(guild, channel_id)
        self._cleanup_tracking(channel_id)
        try:
            await channel.delete(reason="방장 퇴장으로 자동 삭제")
            log.info(f"🗑️ '{channel.name}' {room_label}을 자동 삭제했어요. (방장 퇴장)")
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
            log.info(f"🗑️ '{channel.name}' {room_label}을 자동 삭제했어요. (미사용)")
        except (discord.Forbidden, discord.NotFound):
            pass

    # ============================================================
    # 재시작 시 저장된 방 목록 복구 + 정리 (cog의 on_ready에서 호출)
    # ============================================================
    async def on_ready_recover(self):
        stored = room_store.load_all()  # {channel_id: {"owner_id", "kind"}}
        recovered = 0
        cleaned = 0

        released = 0
        for channel_id, info in stored.items():
            owner_id = info["owner_id"]
            kind = info.get("kind")
            channel = self.bot.get_channel(channel_id)
            # 봇이 꺼져있는 동안 나간 사람은 음소거가 안 풀린 채로 남아있어요.
            # 서버 음소거는 서버 전체에 남는 상태라, 방이 어떻게 되든 여기서 꼭 정리해야 해요.
            muted_ids = set(info.get("muted") or [])
            self.channel_to_muted[channel_id] = muted_ids

            if channel is None or kind not in self.room_kinds:
                # 채널이 아예 사라졌거나(수동 삭제 등) 모르는 종류면 기록만 지워요.
                guild = self.bot.get_guild(int(os.getenv("GUILD_ID", 0) or 0))
                if muted_ids and guild is not None:
                    await self.release_all_mutes(guild, channel_id)
                    released += len(muted_ids)
                room_store.remove_room(channel_id)
                cleaned += 1
                continue

            if len(channel.members) == 0:
                # 봇이 꺼져있는 동안 다 나가서 방이 비어버린 경우, 그때 못 지운 거라 지금 정리해요.
                if muted_ids:
                    await self.release_all_mutes(channel.guild, channel_id)
                    released += len(muted_ids)
                room_store.remove_room(channel_id)
                try:
                    await channel.delete(reason="봇 재시작 시 정리 - 방이 비어있었음")
                except (discord.Forbidden, discord.NotFound):
                    pass
                cleaned += 1
                continue

            # 방은 살아있지만, 그 사이에 나가버린 사람의 음소거는 풀어줘야 해요.
            still_inside = {m.id for m in channel.members}
            for gone_id in list(muted_ids - still_inside):
                member = channel.guild.get_member(gone_id)
                if member is not None:
                    await self.apply_server_mute(member, False, "봇 재시작 정리 - 방을 이미 나간 사람")
                self._mark_muted(channel_id, gone_id, False)
                released += 1

            # 아직 사람이 있는 방은 계속 관리해요.
            self.owner_to_channel[owner_id] = channel_id
            self.channel_to_owner[channel_id] = owner_id
            self.channel_to_kind[channel_id] = kind
            # 이 기능이 생기기 전에 만들어진 방 기록에는 이 필드가 아예 없어요. 그땐 꺼진 걸로 봐요.
            self.channel_to_mute[channel_id] = info.get("mute_on_join", False)
            recovered += 1

            # 지금 방 안에 있는데 권한이 없는 사람을 여기서 같이 풀어줘요.
            # 봇이 꺼져있는 동안 끌어와졌거나, 이 기능이 생기기 전에 들어와 있던 사람들이에요.
            # (자세한 이유는 _grant_entry_on_join 주석 참고)
            for m in channel.members:
                if not m.bot:
                    await self._grant_entry_on_join(channel, m)

        log.info(
            f"🔊 즉석생성형 통화방 복구 완료: {recovered}개 복구, {cleaned}개 정리됨"
            f"{f', 남아있던 음소거 {released}건 해제' if released else ''}."
        )

    # ============================================================
    # 슬래시 명령어 로직 (cog가 그대로 호출)
    # ============================================================
    async def create_room(
        self, interaction: discord.Interaction, kind: str, 인원수: int | None, 입장시뮤트: bool = False
    ):
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
        category = self._get_category(interaction.guild, kind)

        # ⚠️ `overwrites=`를 직접 넘기면 디스코드가 **카테고리 권한 동기화를 대체**해버려요.
        # 그래서 예전엔 카테고리에 걸어둔 제한(예: 랭크방 카테고리의 `신입 역할 채널보기 차단`)이
        # 봇이 만든 방에는 안 걸려서, 신입도 방 목록을 볼 수 있었어요. (2026-09-05 수정)
        # 카테고리 권한을 먼저 그대로 물려받고, 그 위에 방 전용 권한을 얹어요.
        overwrites: dict = {}
        if category is not None:
            overwrites.update(category.overwrites)

        # @everyone: 목록에는 보이되 아무나 못 들어오게(잠금). 카테고리에 이미 @everyone 제한이
        # 있으면 그걸 지우지 않고 이 두 개만 덮어써요.
        everyone_ow = overwrites.get(everyone) or discord.PermissionOverwrite()
        everyone_ow.update(view_channel=True, connect=False)
        overwrites[everyone] = everyone_ow

        owner_ow = overwrites.get(interaction.user) or discord.PermissionOverwrite()
        owner_ow.update(view_channel=True, connect=True, speak=True, send_messages=True)
        overwrites[interaction.user] = owner_ow

        try:
            channel = await interaction.guild.create_voice_channel(
                name=f"{emoji}{interaction.user.display_name}의 {room_label}",
                category=category,
                overwrites=overwrites,
                user_limit=인원수 if 인원수 else 0,
                reason=f"/방만들기 {room_label} 사용 (방장: {interaction.user.display_name})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ 봇에게 채널 생성 권한이 없어서 방을 만들지 못했어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        self._track(channel.id, interaction.user.id, kind, 입장시뮤트)
        self._schedule_unused_check(channel)

        capacity_text = f" (최대 {인원수}명)" if 인원수 else ""
        minutes = ROOM_EXPIRE_SECONDS // 60
        mute_text = (
            "🔇 **입장시 뮤트**가 켜져 있어요. `/방신청`으로 들어오는 사람은 마이크가 막힌 채로 입장하고, "
            "방 채팅에 뜨는 **🔊 발언 허용** 버튼을 눌러줘야 말할 수 있어요. "
            "(`/방초대`로 직접 초대한 사람은 바로 말할 수 있어요)\n"
            if 입장시뮤트 else ""
        )
        await interaction.followup.send(
            f"{emoji} {room_label}을 만들었어요! {channel.mention}{capacity_text}\n"
            f"다른 사람들은 방을 볼 수는 있지만, `/방초대`로 직접 초대하거나 `/방신청`을 받아서 승인해야 들어올 수 있어요.\n"
            f"{mute_text}"
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
        # 안에 사람이 남아있는 채로 닫을 수 있으니, 기록을 지우기 전에 음소거부터 풀어줘요.
        await self.release_all_mutes(interaction.guild, channel_id)
        self._cleanup_tracking(channel_id)
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason="/방닫기 사용")
            except discord.Forbidden:
                await interaction.followup.send("⚠️ 채널 삭제 권한이 없어요. 관리자에게 문의해주세요.", ephemeral=True)
                return

        log.info(f"🗑️ {interaction.user.display_name}님이 {room_label}을 직접 닫았어요.")
        await interaction.followup.send(f"🗑️ {room_label}을 닫았어요.", ephemeral=True)

    async def transfer_owner(self, interaction: discord.Interaction, 대상: discord.Member):
        """방장을 방 안에 있는 다른 사람에게 넘겨요.

        먼저 자리를 비워야 할 때 쓰는 기능이에요. 방장이 나가면 10초 뒤에 방이 닫히니까,
        나가기 전에 넘겨두면 남은 사람들이 그대로 방을 계속 쓸 수 있어요.
        """
        await interaction.response.defer(ephemeral=True)

        channel_id = self.owner_to_channel.get(interaction.user.id)
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            if channel_id is not None:
                self._cleanup_tracking(channel_id)
            await interaction.followup.send("회원님이 방장인 방이 없어요. 방장만 넘길 수 있어요.", ephemeral=True)
            return

        room_label = self.label_for(channel.id)
        emoji = self._emoji_for(channel.id)

        if 대상.id == interaction.user.id:
            await interaction.followup.send("이미 회원님이 방장이에요.", ephemeral=True)
            return
        if 대상.bot:
            await interaction.followup.send("봇에게는 방장을 넘길 수 없어요.", ephemeral=True)
            return

        # "한 사람은 동시에 방 1개"라는 규칙을 넘기기로도 깨면 안 돼요.
        # (깨지면 그 사람의 /방초대·/방신청·/방닫기가 어느 방을 말하는지 모호해져요)
        target_room_id = self.owner_to_channel.get(대상.id)
        if target_room_id is not None:
            target_room = interaction.guild.get_channel(target_room_id)
            if target_room is not None:
                await interaction.followup.send(
                    f"{대상.display_name}님은 이미 자기 {self.label_for(target_room_id)}"
                    f"({target_room.mention})을 가지고 있어요.\n"
                    f"그 방을 먼저 `/방닫기`로 닫아야 넘길 수 있어요.",
                    ephemeral=True,
                )
                return
            self._cleanup_tracking(target_room_id)  # 이미 사라진 방의 낡은 기록

        # 방에 없는 사람에게 넘기면, 넘긴 즉시 "방장 없는 방"이 돼서 10초 뒤에 닫혀버려요.
        if 대상 not in channel.members:
            await interaction.followup.send(
                f"{대상.display_name}님이 지금 {channel.mention}에 없어요. **방 안에 있는 사람**에게만 넘길 수 있어요.",
                ephemeral=True,
            )
            return

        previous_owner = interaction.user
        self._retrack_owner(channel.id, previous_owner.id, 대상.id)

        # 방장이 이미 나가서 자동 삭제 타이머가 돌고 있었다면 취소해요. 새 방장이 안에 있으니까요.
        task = self.owner_leave_tasks.pop(channel.id, None)
        if task is not None and not task.done():
            task.cancel()

        # 새 방장에게 방장다운 권한을 확실히 보장해줘요.
        # (끌어와져서 들어온 사람은 speak가 막혀있을 수도 있어요)
        try:
            await channel.set_permissions(
                대상,
                view_channel=True,
                connect=True,
                speak=True,
                send_messages=True,
                reason=f"{room_label} 방장 위임 ({previous_owner.display_name} → {대상.display_name})",
            )
        except (discord.Forbidden, discord.NotFound):
            log.warning(f"⚠️ '{channel.name}' 새 방장 {대상.display_name}님의 권한을 손보지 못했어요.")

        # 입장시뮤트로 마이크가 막혀있던 사람이 방장이 되는 경우, 서버 음소거도 풀어줘야 해요.
        # (speak 권한만으로는 이미 접속한 사람에게 안 먹혀요 — apply_server_mute 주석 참고)
        if 대상.id in self.channel_to_muted.get(channel.id, set()):
            if await self.apply_server_mute(대상, False, f"{room_label} 방장이 되어 음소거 해제"):
                self._mark_muted(channel.id, 대상.id, False)

        # 방 이름도 새 방장 이름으로 바꿔줘요. 이름 변경은 한도에 걸리면 몇 분이 걸릴 수 있어서
        # 백그라운드로 돌리고(_schedule_rename 주석 참고), 여기서는 잠깐만 기다려봐요.
        # 그 안에 끝나면 "바꿨어요", 늦어지면 "곧 반영돼요"라고 안내가 갈라져요.
        rename_task = self._schedule_rename(channel)
        await asyncio.wait({rename_task}, timeout=RENAME_WAIT_SECONDS)
        renamed_now = rename_task.done() and not rename_task.cancelled() and rename_task.exception() is None

        log.info(
            f"👑 '{channel.name}' {room_label}의 방장이 {previous_owner.display_name}님에서 "
            f"{대상.display_name}님으로 넘어갔어요."
        )

        try:
            await channel.send(
                f"👑 이제 이 {room_label}의 방장은 {대상.mention}님이에요! "
                f"({previous_owner.display_name}님이 넘겨줬어요)\n"
                f"`/방초대`·`/방신청` 승인·`/방닫기`는 이제 {대상.display_name}님이 쓸 수 있어요."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        try:
            await 대상.send(
                f"{emoji} **{previous_owner.display_name}**님이 {room_label}({channel.mention}) 방장을 넘겨줬어요!\n"
                f"이제 `/방초대`로 사람을 부르거나 `/방신청`을 승인할 수 있고, 회원님이 나가면 "
                f"{OWNER_LEAVE_GRACE_SECONDS}초 뒤에 방이 닫혀요. 먼저 나가야 하면 `/방장넘기기`로 또 넘겨주세요."
            )
        except discord.Forbidden:
            pass

        rename_notice = (
            "" if renamed_now
            else "\n(✏️ 방 이름은 디스코드 변경 한도 때문에 조금 늦게 바뀌어요. 그냥 두면 알아서 반영돼요)"
        )
        await interaction.followup.send(
            f"👑 {대상.display_name}님에게 {room_label} 방장을 넘겼어요. 이제 회원님이 나가도 방은 유지돼요."
            f"{rename_notice}",
            ephemeral=True,
        )

    # ============================================================
    # 자동 삭제(방이 완전히 비면) + 퇴장 시 입장 권한 자동 회수 (cog의 on_voice_state_update에서 호출)
    # ============================================================
    async def _grant_entry_on_join(self, channel: discord.VoiceChannel, member: discord.Member):
        """방에 들어와 있는데 개인 권한이 없는 사람에게 입장 권한을 만들어줘요.

        ⚠️ 왜 필요한가 (2026-09-05 "랭크방에서 채팅을 못 불러와요" 신고):

        `/방초대`·`/방신청`을 거치지 않고도 방에 들어오는 경로가 하나 있어요 —
        **방장(또는 멤버 이동 권한이 있는 사람)이 다른 음성채널에서 끌어오는 경우**예요.
        이때는 봇을 안 거치니까 개인 오버라이드가 안 생겨요.

        그러면 그 사람에게는 방 생성 시 걸어둔 `@everyone: 연결(connect) 거부`가 그대로
        적용돼요. 음성으로는 이미 들어와 있으니 대화는 되는데, **디스코드는 연결 권한이 없으면
        그 음성채널의 채팅(text-in-voice)을 못 쓰게 막아요.** 그래서 "방 안에 있는데 채팅만
        안 불러와지는" 이상한 상태가 됐어요.

        실제로 신고 당시 `🔒피츄민영의 랭크방`에는 4명이 끌려 들어와 있었는데
        권한 목록에는 방장 1명뿐이었어요.

        나갈 때 회수하는 로직은 그대로라, 이 권한도 방을 나가면 같이 사라져요.
        """
        if channel.overwrites_for(member).connect:
            return  # 초대/신청으로 이미 권한이 있는 사람 (방장 포함)

        room_label = self.label_for(channel.id)
        try:
            await channel.set_permissions(
                member,
                view_channel=True,
                connect=True,
                speak=True,
                send_messages=True,
                reason=f"{room_label}에 이동으로 들어와서 입장 권한 자동 부여 (채팅 사용 가능하도록)",
            )
            log.info(
                f"🔑 {member.display_name}님이 권한 없이 '{channel.name}' {room_label}에 들어와 있어서 "
                f"입장 권한을 부여했어요. (끌어오기로 입장한 것으로 보임)"
            )
        except (discord.Forbidden, discord.NotFound):
            pass

    async def _post_speak_grant_button(self, channel: discord.VoiceChannel, member: discord.Member):
        """마이크가 막힌 채로 들어온 사람이 있으면, 방장이 풀어줄 버튼을 방 채팅에 올려요.

        판단 기준을 "이 방이 뮤트 방인가"가 아니라 **그 사람의 실제 speak 권한이 False인가**로 잡았어요.
        방장이 이미 한 번 풀어준 사람이 잠깐 나갔다 들어오는 경우까지 매번 버튼이 뜨면 시끄러운데,
        퇴장하면 개인 권한이 통째로 회수되니 재입장하면 다시 막힌 상태가 되는 게 맞고,
        반대로 `/방초대`로 들어온 사람(speak 제한 없음)에게는 버튼이 안 뜨게 돼요.
        """
        if channel.overwrites_for(member).speak is not False:
            return

        owner_id = self.channel_to_owner.get(channel.id)
        if owner_id is None:
            return

        # speak 권한만으로는 이미 접속한 사람의 마이크가 실제로 막히지 않아요.
        # 서버 음소거를 같이 걸어야 즉시 먹혀요. (apply_server_mute 주석 참고)
        if await self.apply_server_mute(member, True, f"{self.label_for(channel.id)} 입장시 뮤트"):
            self._mark_muted(channel.id, member.id, True)

        view = discord.ui.View(timeout=None)
        view.add_item(SpeakGrantButton(channel.id, member.id, owner_id))
        try:
            await channel.send(
                f"🔇 {member.mention}님이 입장했어요. 지금은 마이크가 막혀 있어요.\n"
                f"<@{owner_id}> 방장님, 아래 버튼으로 발언을 허용해주세요!",
                view=view,
            )
        except (discord.Forbidden, discord.HTTPException):
            # 방 채팅(text-in-voice)에 못 올리는 상황이면 조용히 넘어가요. 방장이 나중에 다시 신청받아도 되고,
            # 무엇보다 여기서 예외가 나면 입장 처리 전체가 멈춰버려요.
            log.warning(f"⚠️ '{channel.name}'에 발언 허용 버튼을 올리지 못했어요.")

    async def handle_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        # 방장이 자기 방으로 (다시) 들어오면, 걸려있던 자동 삭제 타이머를 취소해요.
        if after.channel is not None and self.channel_to_owner.get(after.channel.id) == member.id:
            task = self.owner_leave_tasks.pop(after.channel.id, None)
            if task is not None and not task.done():
                task.cancel()

        # 방에 새로 들어왔으면, 개인 권한이 없는 사람에게 만들어줘요. (아래 주석 참고)
        entered_room = (
            after.channel is not None
            and after.channel.id in self.channel_to_owner
            and (before.channel is None or before.channel.id != after.channel.id)
        )
        if entered_room and not member.bot:
            await self._grant_entry_on_join(after.channel, member)
            # 마이크가 막힌 채로 들어온 사람이면, 방장이 눌러서 풀어줄 버튼을 방 채팅에 띄워요.
            await self._post_speak_grant_button(after.channel, member)

        if before.channel is None or before.channel.id not in self.channel_to_owner:
            return

        if after.channel is not None and after.channel.id == before.channel.id:
            # 같은 방에 그대로 있음 (음소거/카메라/화면공유 등 상태 변경일 뿐 실제 퇴장이 아니에요)
            return

        channel = before.channel
        owner_id = self.channel_to_owner[channel.id]
        room_label = self.label_for(channel.id)

        # 이 방에서 봇이 걸어둔 서버 음소거는 나갈 때 꼭 풀어줘야 해요.
        # 서버 음소거는 채널이 아니라 **서버 전체에 남는 상태**라, 안 풀면 다른 통화방에 가서도
        # 계속 말을 못 해요. (운영진이 징계로 건 음소거는 우리가 기록해둔 대상이 아니라 건드리지 않아요)
        if member.id in self.channel_to_muted.get(channel.id, set()):
            await self.apply_server_mute(member, False, f"{room_label} 퇴장으로 음소거 자동 해제")
            self._mark_muted(channel.id, member.id, False)

        if len(channel.members) == 0:
            self._cleanup_tracking(channel.id)
            try:
                await channel.delete(reason=f"{room_label}에 아무도 없어서 자동 삭제")
                log.info(f"🗑️ '{channel.name}' {room_label}을 자동 삭제했어요. (인원 0명)")
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
                log.info(f"🚪 {member.display_name}님의 '{channel.name}' {room_label} 입장 권한을 회수했어요. (퇴장)")
            except (discord.Forbidden, discord.NotFound):
                pass
