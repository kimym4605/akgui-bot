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
from utils.dynamic_room import DynamicRoomEngine

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

    @commands.Cog.listener()
    async def on_ready(self):
        _migrate_legacy_stores()
        await self.engine.on_ready_recover()

    @app_commands.command(name="방만들기", description="원하는 종류의 통화방을 새로 만들어요. (초대/신청해야 남이 입장 가능)")
    @app_commands.describe(종류="어떤 방을 만들지 선택하세요.", 인원수="방 최대 인원수 (선택, 안 정하면 무제한)")
    @app_commands.choices(
        종류=[app_commands.Choice(name=cfg["choice_name"], value=key) for key, cfg in ROOM_KINDS.items()]
    )
    @restrict_to_channel("room")
    async def create_room(
        self,
        interaction: discord.Interaction,
        종류: app_commands.Choice[str],
        인원수: app_commands.Range[int, 1, 99] = None,
    ):
        await self.engine.create_room(interaction, 종류.value, 인원수)

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

    @app_commands.command(name="방닫기", description="내가 연 방을 직접 닫아요.")
    @restrict_to_channel("room")
    async def close_room(self, interaction: discord.Interaction):
        await self.engine.close_room(interaction)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        await self.engine.handle_voice_state_update(member, before, after)


async def setup(bot: commands.Bot):
    await bot.add_cog(Room(bot))
