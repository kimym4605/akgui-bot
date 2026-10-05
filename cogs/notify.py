"""`/알림설정` - 봇이 보내는 알림을 개인별로 끄고 켜요.

"미션을 깨면 알림이 떠서 방해된다"는 이야기에서 나온 기능이에요. 어떤 알림이 있고 왜
끌 수 있어야 하는지는 `utils/notify_prefs.py` 머리말에 적어뒀어요. 여기서는 화면만 다뤄요.

보내는 쪽(미션·위시리스트)에서 `notify_prefs.is_enabled()`를 확인하니까, 알림 종류를
추가할 때는 `NOTIFY_KINDS`에 한 줄 넣고 보내는 쪽에 확인을 한 줄 붙이면 돼요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import notify_prefs
from utils.notify_prefs import NOTIFY_KINDS

log = logging.getLogger(__name__)

ON_LABEL = "켜짐"
OFF_LABEL = "꺼짐"


def _build_embed(states: dict[str, bool]) -> discord.Embed:
    off_count = sum(1 for enabled in states.values() if not enabled)
    embed = discord.Embed(
        title="🔔 내 알림 설정",
        description=(
            "버튼을 누르면 바로 저장돼요. **이 설정은 나한테만 적용돼요.**\n"
            "알림을 꺼도 **코인과 미션 진행은 그대로 쌓여요** — `/미션`, `/코인`에서 확인할 수 있어요."
        ),
        color=0x5865F2 if off_count == 0 else 0x95A5A6,
    )
    for key, info in NOTIFY_KINDS.items():
        on = states.get(key, True)
        embed.add_field(
            name=f"{info['emoji']} {info['title']} — {'🔔 ' + ON_LABEL if on else '🔕 ' + OFF_LABEL}",
            value=info["desc"],
            inline=False,
        )
    embed.set_footer(
        text="라이엇 계정을 못 찾았을 때의 안내 DM은 설정과 무관하게 하루 한 번 가요 "
             "(그게 막히면 미션이 영영 안 깨져서요)."
    )
    return embed


class _ToggleButton(discord.ui.Button):
    def __init__(self, key: str, enabled: bool):
        self.key = key
        super().__init__(
            emoji=NOTIFY_KINDS[key]["emoji"],
            label=f"{NOTIFY_KINDS[key]['title']} {ON_LABEL if enabled else OFF_LABEL}",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
        )

    def refresh(self, enabled: bool):
        self.label = f"{NOTIFY_KINDS[self.key]['title']} {ON_LABEL if enabled else OFF_LABEL}"
        self.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        view: "NotifySettingsView" = self.view  # type: ignore[assignment]
        await view.toggle(interaction, self.key)


class NotifySettingsView(discord.ui.View):
    """본인 전용 설정 화면이라 ephemeral로 띄워요(다른 사람 눈에 안 보여요)."""

    def __init__(self, user_id: int, states: dict[str, bool]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.states = dict(states)
        self.message: discord.Message | None = None
        for key in NOTIFY_KINDS:
            self.add_item(_ToggleButton(key, self.states.get(key, True)))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ephemeral이라 사실상 본인만 누를 수 있지만, 남의 설정을 건드리는 경로는 아예 막아둬요.
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "본인 알림 설정만 바꿀 수 있어요. `/알림설정`을 직접 써주세요.", ephemeral=True
            )
            return False
        return True

    async def toggle(self, interaction: discord.Interaction, key: str):
        new_state = not self.states.get(key, True)
        try:
            await notify_prefs.set_enabled(self.user_id, key, new_state)
        except Exception:  # noqa: BLE001
            # 저장이 안 됐는데 버튼만 바뀌면 "껐는데 또 오네요"가 돼요. 화면을 그대로 두고 알려줘요.
            log.warning("알림 설정 저장 실패 (user=%s key=%s)", self.user_id, key, exc_info=True)
            await interaction.response.send_message(
                "⚠️ 설정을 저장하지 못했어요. 잠시 뒤에 다시 눌러주세요.", ephemeral=True
            )
            return

        self.states[key] = new_state
        for item in self.children:
            if isinstance(item, _ToggleButton):
                item.refresh(self.states.get(item.key, True))
        await interaction.response.edit_message(embed=_build_embed(self.states), view=self)

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except Exception:  # noqa: BLE001
            pass  # 이미 사라진 메시지면 그냥 넘어가요.


class Notify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="알림설정", description="봇이 보내는 알림(미션 완료·위시리스트)을 끄거나 켜요."
    )
    async def notify_settings(self, interaction: discord.Interaction):
        # 채널 제한을 걸지 않았어요. 알림이 시끄러워서 끄려는 사람한테 "그건 저쪽 채널에서
        # 하세요"라고 하면 그대로 포기해요. ephemeral이라 채널을 더럽히지도 않아요.
        await interaction.response.defer(ephemeral=True)
        states = await notify_prefs.get_all(interaction.user.id)
        view = NotifySettingsView(interaction.user.id, states)
        # followup이 돌려주는 메시지를 그대로 들고 있어요(타임아웃 때 버튼을 꺼야 해서).
        view.message = await interaction.followup.send(
            embed=_build_embed(states), view=view, ephemeral=True, wait=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Notify(bot))
