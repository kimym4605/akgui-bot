"""
🔊 즉석 생성형 통화방 기능이에요. /방만들기 종류:OOO 로 원하는 종류의 방을 만들어요.

자세한 동작(초대/신청/자동삭제 등)은 utils/dynamic_room.py의 DynamicRoomEngine을 봐주세요.
여기서는 슬래시 명령어 정의 + 어떤 "종류"의 방이 있는지(ROOM_KINDS)만 다뤄요.

새 종류의 방을 추가하려면 ROOM_KINDS에 항목 하나만 추가하면 돼요. (필요하면 .env에
카테고리_ID 환경변수도 같이 추가 — 안 넣으면 서버 최상위에 방이 생성돼요)
"""
import logging
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils import room_store
from utils.channel_check import restrict_to_channel
from utils.dynamic_room import DynamicRoomEngine, SpeakGrantButton
from utils.room_panel import RoomPanelView, panel_embed

log = logging.getLogger(__name__)

# 예전에는 방 종류별로 파일이 따로 있었어요(rank_room_store.py, practice_room_store.py).
# 통합 시스템(room_store.py)으로 바뀌면서, 이미 만들어져 있던 방들이 관리 대상에서
# 빠지지 않도록 딱 한 번 옮겨줘요. (파일 자체는 코드에서 이제 안 쓰지만 예전 데이터라
# 남아있을 수 있어요)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LEGACY_STORES = {
    "rank": _DATA_DIR / "rank_rooms.json",
    "practice": _DATA_DIR / "practice_rooms.json",
}


def _migrate_legacy_stores():
    current = room_store.load_all()
    migrated = 0
    for kind, path in _LEGACY_STORES.items():
        if not path.exists():
            continue
        try:
            legacy = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for channel_id_str, owner_id in legacy.items():
            channel_id = int(channel_id_str)
            if channel_id not in current:
                room_store.add_room(channel_id, owner_id, kind)
                migrated += 1
        path.unlink(missing_ok=True)  # 다 옮겼으니 예전 파일은 정리해요.
    if migrated:
        log.info(f"🔁 예전 방 시스템에서 {migrated}개 방을 새 통합 시스템으로 옮겼어요.")

ROOM_KINDS: dict[str, dict] = {
    "rank": {
        "label": "랭크방",
        "emoji": "🔒",
        "category_env_key": "RANK_ROOM_CATEGORY_ID",
        "choice_name": "랭크방 (게임 랭크용)",
    },
    "practice": {
        "label": "폐관수련방",
        "emoji": "🥋",
        "category_env_key": "PRACTICE_ROOM_CATEGORY_ID",
        "choice_name": "폐관수련방 (혼자/같이 연습)",
    },
    "premier": {
        "label": "프리미어방",
        "emoji": "🏆",
        "category_env_key": "PREMIER_ROOM_CATEGORY_ID",
        "choice_name": "프리미어방 (발로란트 프리미어)",
    },
    "scrim": {
        "label": "내전방",
        "emoji": "⚔️",
        "category_env_key": "SCRIM_ROOM_CATEGORY_ID",
        "choice_name": "내전방 (팀 내전용)",
    },
}


class Room(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = DynamicRoomEngine(bot, ROOM_KINDS)

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 패널 버튼을 눌러도 봇이 custom_id를 알아보지
        #    못해서 **아무 반응이 없어요**(에러도 안 나요).
        self.bot.add_view(RoomPanelView(self.engine, ROOM_KINDS))

    @commands.Cog.listener()
    async def on_ready(self):
        _migrate_legacy_stores()
        await self.engine.on_ready_recover()

    @app_commands.command(name="방만들기", description="원하는 종류의 통화방을 새로 만들어요. (초대/신청해야 남이 입장 가능)")
    @app_commands.describe(
        종류="어떤 방을 만들지 선택하세요.",
        인원수="방 최대 인원수 (선택, 안 정하면 무제한)",
        입장시뮤트="신청으로 들어오는 사람을 마이크 막힌 상태로 입장시켜요. (방장이 버튼으로 풀어줌)",
    )
    @app_commands.choices(
        종류=[app_commands.Choice(name=cfg["choice_name"], value=key) for key, cfg in ROOM_KINDS.items()]
    )
    @restrict_to_channel("room")
    async def create_room(
        self,
        interaction: discord.Interaction,
        종류: app_commands.Choice[str],
        인원수: app_commands.Range[int, 1, 99] = None,
        입장시뮤트: bool = False,
    ):
        await self.engine.create_room(interaction, 종류.value, 인원수, 입장시뮤트)

    @app_commands.command(name="방초대", description="내 방에 원하는 사람을 바로 초대해요.")
    @app_commands.describe(대상="초대할 사람을 선택하세요.")
    @restrict_to_channel("room")
    async def invite(self, interaction: discord.Interaction, 대상: discord.Member):
        await self.engine.invite(interaction, 대상)

    @app_commands.command(name="방신청", description="다른 사람의 방에 입장 신청을 보내요.")
    @app_commands.describe(방장="입장하고 싶은 방의 방장을 선택하세요.")
    @restrict_to_channel("room")
    async def request_join(self, interaction: discord.Interaction, 방장: discord.Member):
        await self.engine.request_join(interaction, 방장)

    @app_commands.command(name="방장넘기기", description="방 안에 있는 다른 사람에게 방장을 넘겨요. (먼저 나가야 할 때)")
    @app_commands.describe(대상="방장을 넘겨줄 사람을 선택하세요. (그 방에 들어와 있어야 해요)")
    @restrict_to_channel("room")
    async def transfer_owner(self, interaction: discord.Interaction, 대상: discord.Member):
        await self.engine.transfer_owner(interaction, 대상)

    @app_commands.command(name="방닫기", description="내가 연 방을 직접 닫아요.")
    @restrict_to_channel("room")
    async def close_room(self, interaction: discord.Interaction):
        await self.engine.close_room(interaction)

    @app_commands.command(
        name="방패널",
        description="[서버 소유자 전용] 이 채널에 통화방 패널을 박아둬요 (항상 떠 있어요).",
    )
    @app_commands.describe(종류="이 채널에 보여줄 방 종류 (안 고르면 전부)",
                           종류2="한 채널에 두 종류를 같이 올릴 때")
    @app_commands.choices(
        종류=[app_commands.Choice(name=cfg["choice_name"], value=key)
            for key, cfg in ROOM_KINDS.items()],
        종류2=[app_commands.Choice(name=cfg["choice_name"], value=key)
             for key, cfg in ROOM_KINDS.items()],
    )
    async def panel(
        self, interaction: discord.Interaction,
        종류: app_commands.Choice[str] | None = None,
        종류2: app_commands.Choice[str] | None = None,
    ):
        """🔊 상설 패널을 **지금 이 채널에** 올려요. (🎣 `/낚시패널`·🎴 `/카드패널`과 같은 방식)

        ⭐ `종류`를 고르면 **그 방 버튼만** 올라가요 — 모집 채널별로 나눠 박으려고
           만든 옵션이에요(사용자 지시: "방만들기 기능은 각 방에 나누는게 좋을 것 같다").
           관리 버튼(초대·신청·넘기기·닫기)은 **어느 패널에나** 들어가요.

        ⚠️ `/채널설정`을 쓰지 않아요 — 이건 "명령어를 어디서 쓸 수 있나"가 아니라
           **메시지를 한 번 박는** 일이에요. 옮기려면 옛 메시지를 지우고 다시 치면 돼요.
        📌 올린 뒤 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요."""
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "텍스트 채널에서 써주세요.", ephemeral=True
            )
            return

        # ⭐ 2026-11-01: `종류2`를 더했어요. 🏆프리미어방이 45일간 **방 생성 122건 중
        #    0건**이고 37개 채널을 훑어도 사람이 "프리미어"를 쓴 글이 0건이라, 전용
        #    채널을 지우고 **사람이 몰리는 랭크 채널 패널에 버튼만 얹기로** 했어요
        #    (사용자 결정). 기능은 남으니 프리미어 시즌이 오면 바로 쓸 수 있어요.
        #
        # 🚨 패널을 손으로 짜서 REST로 박지 않아요. `panel_embed`가 `ROOM_KINDS`에서
        #    글을 만드니 코드를 고치면 패널도 따라오지만, 손으로 박으면 그 자리에서
        #    **안내문이 갈려요**([[feedback_sync_discord_guides_after_deploy]]).
        # 같은 걸 두 번 고르면 버튼이 두 개 생겨요 — 순서는 지키면서 중복만 빼요.
        # 🚨 한 줄로 둬요. `picked`를 거쳐가면 `kinds =` 한 줄에 `종류`가 안 보여서
        #    "kinds를 종류에서 만든다"를 지키는 검사가 깨져요(test_room_panel [8]).
        kinds = list(dict.fromkeys(c.value for c in (종류, 종류2) if c)) or None
        label = (" + ".join(f"{ROOM_KINDS[k]['emoji']} {ROOM_KINDS[k]['label']}"
                            for k in kinds)
                 if kinds else "🔊 통화방 전체")
        await interaction.response.send_message(
            f"{channel.mention} 에 **{label}** 패널을 올렸어요.\n"
            "-# 메시지를 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요. "
            "옮기려면 그 메시지를 지우고 다른 채널에서 다시 치면 돼요.",
            ephemeral=True,
        )
        await channel.send(embed=panel_embed(ROOM_KINDS, kinds),
                           view=RoomPanelView(self.engine, ROOM_KINDS, kinds))
        log.info("🔊 통화방 패널 게시: 채널 %s · 종류 %s", channel.id, kinds or "전부")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        await self.engine.handle_voice_state_update(member, before, after)


async def setup(bot: commands.Bot):
    # "🔊 발언 허용" 버튼은 방장이 눌러줄 때까지 계속 살아있어야 해서, 봇이 재시작돼도
    # 다시 동작하도록 여기에 등록해둬요. (자세한 이유는 utils/dynamic_room.py의 SpeakGrantButton 주석 참고)
    bot.add_dynamic_items(SpeakGrantButton)
    await bot.add_cog(Room(bot))
