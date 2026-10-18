"""💡 건의함 — 제안을 올리고 👍👎로 투표해요. 운영자가 처리 상태를 붙여요.

## 왜 (2026-10-18)

`💡｜기능-추천방` 채널이 **이미 있는데 봇 기능이 없었어요.** 채팅으로 흘러가면 묻히고,
운영자가 봤는지 제안자가 알 수 없고, 다른 사람이 동의하는지도 안 보여요.

## 🚨 영속 뷰 — `self`에 상태를 담지 마세요

투표 버튼은 봇이 재시작돼도 살아 있어야 해요(`timeout=None` + 고정 `custom_id` +
`bot.add_view`). 그런데 **영속 뷰는 봇 전체에 객체가 하나뿐**이라, 여기에 상태를 담으면
모든 건의가 그 하나를 공유해요. 그래서 상태는 전부 `utils/suggestion_store.py`에 두고
**누른 메시지의 id로** 읽고 써요. `cogs/team.py`가 같은 이유로 같은 구조예요.
(team.py는 이걸 어겨서 "9/22 배포 이후 내전 경기가 한 건도 기록되지 못한" 사고가 났어요.)
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import suggestion_store as store
from utils.channel_check import restrict_to_channel
from utils.staff_check import is_staff

log = logging.getLogger(__name__)

CHANNEL_GROUP = "suggestion"

MAX_LEN = 500
MIN_LEN = 5


def build_embed(doc: dict, author_name: str) -> discord.Embed:
    emoji, label = store.STATUS_LABEL.get(doc.get("status") or store.OPEN,
                                          store.STATUS_LABEL[store.OPEN])
    up = len(doc.get("up") or [])
    down = len(doc.get("down") or [])

    embed = discord.Embed(
        title=f"{emoji} {label}",
        description=doc.get("text") or "",
        color=store.STATUS_COLOR.get(doc.get("status") or store.OPEN, 0x6B7280),
    )
    embed.add_field(name="투표", value=f"👍 **{up}**　👎 **{down}**", inline=True)
    if doc.get("note"):
        embed.add_field(name="운영자 메모", value=doc["note"], inline=False)
    embed.set_footer(text=f"제안: {author_name}")
    return embed


class VoteView(discord.ui.View):
    """🚨 **상태를 들고 있지 않아요.** 봇 전체에 이 객체 하나만 등록돼요."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _vote(self, interaction: discord.Interaction, up: bool):
        # 🚨 DB 왕복이 3초를 넘을 수 있어요. **먼저 받아둬요.**
        await interaction.response.defer()

        doc = await store.vote(interaction.message.id, interaction.user.id, up)
        if doc is None:
            await interaction.followup.send(
                "이 건의를 찾지 못했어요. (봇이 올린 게 아니거나 기록이 지워졌어요)",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = guild.get_member(int(doc["userId"])) if guild else None
        name = member.display_name if member else "탈퇴한 사람"
        try:
            await interaction.message.edit(embed=build_embed(doc, name))
        except discord.HTTPException:
            log.warning("건의 화면 갱신 실패 (message=%s)", interaction.message.id)

    @discord.ui.button(label="찬성", emoji="👍", style=discord.ButtonStyle.success,
                       custom_id="akgui:suggest:up")
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, True)

    @discord.ui.button(label="반대", emoji="👎", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:suggest:down")
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, False)


class Suggestion(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # 🚨 재시작 뒤에도 버튼이 살아 있으려면 여기서 등록해야 해요.
        self.bot.add_view(VoteView())

    # ------------------------------------------------------------------
    @app_commands.command(name="건의", description="봇이나 서버에 바라는 점을 올려요. 다른 사람이 투표할 수 있어요.")
    @app_commands.describe(내용="건의할 내용을 적어주세요.")
    @restrict_to_channel(CHANNEL_GROUP)
    async def suggest(self, interaction: discord.Interaction, 내용: str):
        text = 내용.strip()
        if len(text) < MIN_LEN:
            await interaction.response.send_message(
                "조금 더 자세히 적어주세요.", ephemeral=True)
            return
        if len(text) > MAX_LEN:
            await interaction.response.send_message(
                f"{MAX_LEN}자 안쪽으로 줄여주세요. (지금 {len(text)}자)", ephemeral=True)
            return

        # 메시지를 **먼저 보내고** 그 id로 기록해요. id가 곧 건의 id라서 순서가 중요해요.
        await interaction.response.send_message("💡 건의를 올리는 중이에요...")
        message = await interaction.original_response()
        await store.create(message.id, interaction.user.id, text)

        doc = await store.get(message.id)
        await message.edit(
            content=None,
            embed=build_embed(doc, interaction.user.display_name),
            view=VoteView(),
        )

    # ------------------------------------------------------------------
    @app_commands.command(name="건의처리", description="[운영진] 건의의 처리 상태를 바꿔요.")
    @app_commands.describe(
        메시지id="건의 메시지의 ID (메시지 우클릭 → ID 복사)",
        상태="처리 결과",
        메모="덧붙일 말 (선택)",
    )
    @app_commands.choices(상태=[
        app_commands.Choice(name="💭 검토 중", value=store.OPEN),
        app_commands.Choice(name="✅ 채택", value=store.ACCEPTED),
        app_commands.Choice(name="🎉 반영 완료", value=store.DONE),
        app_commands.Choice(name="🙏 이번엔 보류", value=store.DECLINED),
    ])
    async def handle(
        self,
        interaction: discord.Interaction,
        메시지id: str,
        상태: app_commands.Choice[str],
        메모: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not is_staff(interaction.user):
            await interaction.followup.send(
                "이 명령어는 운영진만 쓸 수 있어요.", ephemeral=True)
            return

        raw = 메시지id.strip()
        if not raw.isdigit():
            await interaction.followup.send(
                "메시지 ID는 숫자예요. 메시지를 우클릭해서 **ID 복사**를 눌러주세요.",
                ephemeral=True)
            return

        doc = await store.set_status(raw, 상태.value, (메모 or "").strip() or None)
        if doc is None:
            await interaction.followup.send("그 건의를 찾지 못했어요.", ephemeral=True)
            return

        # 원본 메시지 화면도 같이 고쳐요. 못 고쳐도 상태 변경은 유효해요.
        note = ""
        try:
            channel = interaction.channel
            message = await channel.fetch_message(int(raw))
            member = interaction.guild.get_member(int(doc["userId"])) if interaction.guild else None
            await message.edit(embed=build_embed(doc, member.display_name if member else "탈퇴한 사람"))
        except (discord.HTTPException, AttributeError):
            note = "\n⚠️ 원본 메시지는 못 고쳤어요(다른 채널에 있으면 그 채널에서 실행해주세요)."

        await interaction.followup.send(
            f"**{상태.name}** 으로 바꿨어요.{note}", ephemeral=True)

    # ------------------------------------------------------------------
    @app_commands.command(name="건의목록", description="최근 건의를 모아 봐요.")
    @app_commands.describe(상태="특정 상태만 보려면 골라주세요.")
    @app_commands.choices(상태=[
        app_commands.Choice(name="💭 검토 중", value=store.OPEN),
        app_commands.Choice(name="✅ 채택", value=store.ACCEPTED),
        app_commands.Choice(name="🎉 반영 완료", value=store.DONE),
    ])
    @restrict_to_channel(CHANNEL_GROUP)
    async def listing(
        self, interaction: discord.Interaction, 상태: app_commands.Choice[str] | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        rows = await store.recent(10, 상태.value if 상태 else None)
        if not rows:
            await interaction.followup.send("아직 건의가 없어요.", ephemeral=True)
            return

        lines = []
        for doc in rows:
            emoji, label = store.STATUS_LABEL.get(doc.get("status") or store.OPEN,
                                                  store.STATUS_LABEL[store.OPEN])
            up, down = len(doc.get("up") or []), len(doc.get("down") or [])
            text = (doc.get("text") or "")[:60]
            lines.append(f"{emoji} `{label}` 👍{up} 👎{down} — {text}")

        embed = discord.Embed(
            title="💡 최근 건의",
            description="\n".join(lines),
            color=0x3B82F6,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Suggestion(bot))
