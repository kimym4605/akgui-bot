"""특정 명령어 그룹을 지정된 채널(및 그 안의 스레드)에서만 쓸 수 있게 제한하는 체크예요.
채널 지정은 /채널설정 명령어로 서버 소유자가 언제든 바꿀 수 있어요.
아직 채널을 지정 안 했으면(설정값이 없으면) 제한 없이 아무 채널에서나 동작해요."""
import discord
from discord import app_commands

from utils.settings_store import get_setting


def channel_key(group: str) -> str:
    return f"pokemonChannel:{group}"


def restrict_to_channel(group: str):
    """이 데코레이터를 붙인 명령어는 채널설정에서 지정한 채널(또는 그 채널 안의 스레드)에서만 동작해요.
    group 예시: "attendance"(출석/육성), "attend"(출석)"""

    async def predicate(interaction: discord.Interaction) -> bool:
        allowed_channel_id = get_setting(channel_key(group))
        if not allowed_channel_id:
            return True  # 아직 설정 안 함 -> 제한 없음

        channel = interaction.channel
        # 스레드 안이면 부모 채널 ID도 같이 확인해서, 허용된 채널 안의 스레드는 전부 허용해요.
        parent_id = getattr(channel, "parent_id", None)

        if interaction.channel_id == allowed_channel_id or parent_id == allowed_channel_id:
            return True

        await interaction.response.send_message(
            f"이 명령어는 <#{allowed_channel_id}> 채널(또는 그 안의 스레드)에서만 사용할 수 있어요.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)