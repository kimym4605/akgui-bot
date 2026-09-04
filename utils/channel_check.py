"""특정 명령어 그룹을 지정된 채널(및 그 안의 스레드)에서만 쓸 수 있게 제한하는 체크예요.
채널 지정은 /채널설정 명령어로 서버 소유자가 언제든 바꿀 수 있어요.
아직 채널을 지정 안 했으면(설정값이 없으면) 제한 없이 아무 채널에서나 동작해요.

⚠️ 예전에는 /오상과 노래방만 .env(VALORANT_SHOP_CHANNEL_ID, KARAOKE_VOICE_CHANNEL_ID)로
채널을 지정했는데, 그러면 채널을 옮길 때마다 봇을 다시 배포해야 해서 운영이 번거로웠어요.
지금은 전부 /채널설정으로 통일하고, .env 값은 **설정이 없을 때만 쓰는 기본값**으로 남겨뒀어요
(이미 .env를 쓰고 있던 환경이 그대로 동작하게 하려고요)."""
import os

import discord
from discord import app_commands

from utils.settings_store import get_setting


def channel_key(group: str) -> str:
    return f"pokemonChannel:{group}"


def _env_channel_id(env_var: str | None) -> int | None:
    if not env_var:
        return None
    raw = os.getenv(env_var)
    if not raw or not raw.strip().isdigit():
        return None
    return int(raw.strip())


def get_allowed_channel_id(group: str, env_var: str | None = None) -> int | None:
    """이 그룹이 허용된 채널 ID예요. /채널설정 값이 우선이고, 없으면 .env 값을 써요.
    둘 다 없으면 None(=제한 없음)이에요."""
    configured = get_setting(channel_key(group))
    if configured:
        return int(configured)
    return _env_channel_id(env_var)


def restrict_to_channel(group: str, env_var: str | None = None):
    """이 데코레이터를 붙인 명령어는 채널설정에서 지정한 채널(또는 그 채널 안의 스레드)에서만 동작해요.
    group 예시: "attendance"(출석/육성), "attend"(출석), "valorant_shop"(/오상)
    env_var를 주면 /채널설정 값이 없을 때 그 환경변수를 기본값으로 써요."""

    async def predicate(interaction: discord.Interaction) -> bool:
        allowed_channel_id = get_allowed_channel_id(group, env_var)
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