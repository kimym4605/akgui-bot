"""📅 일정 예약 — "토요일 9시 내전" 약속을 잡고, 참가자를 모으고, 시작 전에 알려줘요.

## 왜 (2026-10-18)

`scrim_matches`가 **3건뿐**이에요. `/내전모집`은 "지금 모여"라서, 사람이 그 순간
안 모이면 그걸로 끝이에요. 미리 약속을 잡아두면 모이는 일 자체가 쉬워져요.

## 🚨 영속 뷰 — `self`에 상태를 담지 마세요

며칠 뒤 일정이라 그 사이 봇이 몇 번이나 재시작돼요. 버튼은 `timeout=None` + 고정
`custom_id` + `bot.add_view`로 살려두고, 상태는 전부 `utils/event_store.py`에 둬요.
`cogs/team.py`가 이걸 어겨서 "9/22 배포 이후 내전 경기가 한 건도 기록되지 못한"
사고가 났어요.

## 🚨 리마인더 루프

1분마다 돌면서 **시작 30분 전**인 일정을 찾아 참가자를 멘션해요.
- `remindedAt`을 남겨서 같은 일정을 두 번 알리지 않아요.
- `@loop.error`에서 **반드시 restart** — 안 그러면 예외 하나에 영구 정지해요.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import event_store, when_parser
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

CHANNEL_GROUP = "event"

MAX_TITLE = 80
REMIND_CHECK_SECONDS = 60


def build_embed(doc: dict, names: dict[str, str]) -> discord.Embed:
    start = doc["startAt"]
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    going = doc.get("going") or []
    declined = doc.get("declined") or []
    cap = doc.get("capacity")
    canceled = bool(doc.get("canceledAt"))

    if canceled:
        title, color = f"🚫 {doc['title']} (취소됨)", 0x9BA3AF
    else:
        title, color = f"📅 {doc['title']}", 0x5865F2

    embed = discord.Embed(title=title, color=color)
    embed.add_field(
        name="언제",
        value=(f"{when_parser.discord_timestamp(start, 'F')}\n"
               f"　└ {when_parser.discord_timestamp(start, 'R')}"),
        inline=False,
    )
    embed.add_field(
        name="인원",
        value=f"**{len(going)}**" + (f" / {cap}" if cap else "명"),
        inline=True,
    )
    host = names.get(str(doc.get("hostId")), "알 수 없음")
    embed.add_field(name="주최", value=host, inline=True)

    if going:
        listed = " · ".join(names.get(uid, "알 수 없음") for uid in going[:15])
        if len(going) > 15:
            listed += f" 외 {len(going) - 15}명"
        embed.add_field(name="✅ 간다", value=listed, inline=False)
    if declined:
        embed.add_field(name="❌ 못 감", value=f"{len(declined)}명", inline=False)

    if not canceled:
        embed.set_footer(
            text=f"시작 {event_store.REMIND_BEFORE_MINUTES}분 전에 참가자에게 알려드려요")
    return embed


def collect_names(guild: discord.Guild | None, doc: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for uid in (doc.get("going") or []) + (doc.get("declined") or []) + [doc.get("hostId")]:
        if uid is None or str(uid) in names:
            continue
        member = guild.get_member(int(uid)) if guild else None
        names[str(uid)] = member.display_name if member else "탈퇴한 사람"
    return names


class RsvpView(discord.ui.View):
    """🚨 **상태를 들고 있지 않아요.** 봇 전체에 이 객체 하나만 등록돼요."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _refresh(self, interaction: discord.Interaction, doc: dict):
        names = collect_names(interaction.guild, doc)
        try:
            await interaction.message.edit(embed=build_embed(doc, names))
        except discord.HTTPException:
            log.warning("일정 화면 갱신 실패 (message=%s)", interaction.message.id)

    async def _rsvp(self, interaction: discord.Interaction, going: bool):
        # 🚨 DB 왕복이 3초를 넘을 수 있어요. **먼저 받아둬요.**
        await interaction.response.defer()

        before = await event_store.get(interaction.message.id)
        doc = await event_store.rsvp(interaction.message.id, interaction.user.id, going)
        if doc is None:
            await interaction.followup.send(
                "이 일정을 찾지 못했어요(취소됐을 수 있어요).", ephemeral=True)
            return

        # 정원이 차서 아무것도 안 바뀐 경우를 알려줘요.
        if (going and before and doc.get("capacity")
                and str(interaction.user.id) not in (doc.get("going") or [])
                and len(doc.get("going") or []) >= doc["capacity"]):
            await interaction.followup.send(
                f"정원({doc['capacity']}명)이 찼어요. 누가 빠지면 들어올 수 있어요.",
                ephemeral=True)
            return

        await self._refresh(interaction, doc)

    @discord.ui.button(label="간다", emoji="✅", style=discord.ButtonStyle.success,
                       custom_id="akgui:event:going")
    async def going(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rsvp(interaction, True)

    @discord.ui.button(label="못 감", emoji="❌", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:event:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rsvp(interaction, False)

    @discord.ui.button(label="취소", emoji="🚫", style=discord.ButtonStyle.danger,
                       custom_id="akgui:event:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        doc = await event_store.cancel(interaction.message.id, interaction.user.id)
        if doc is None:
            await interaction.followup.send(
                "주최자만 취소할 수 있어요.", ephemeral=True)
            return
        names = collect_names(interaction.guild, doc)
        try:
            # 취소된 일정은 버튼을 떼요(되살릴 방법이 없으니 눌러도 의미가 없어요).
            await interaction.message.edit(embed=build_embed(doc, names), view=None)
        except discord.HTTPException:
            pass


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.remind_loop.start()

    async def cog_load(self):
        # 🚨 재시작 뒤에도 버튼이 살아 있으려면 여기서 등록해야 해요.
        self.bot.add_view(RsvpView())

    async def cog_unload(self):
        self.remind_loop.cancel()

    # ------------------------------------------------------------------
    @app_commands.command(name="일정", description="약속을 잡고 참가자를 모아요. (예: 토요일 21시 내전)")
    @app_commands.describe(
        제목="무슨 일정인가요? (예: 내전, 랭크 파티)",
        언제="예: `토요일 21시` · `내일 9시` · `10/25 21:00`",
        인원="정원 (비우면 제한 없음)",
    )
    @restrict_to_channel(CHANNEL_GROUP)
    async def create_event(
        self,
        interaction: discord.Interaction,
        제목: str,
        언제: str,
        인원: int | None = None,
    ):
        title = 제목.strip()[:MAX_TITLE]
        if not title:
            await interaction.response.send_message("제목을 적어주세요.", ephemeral=True)
            return

        try:
            start = when_parser.parse(언제)
        except when_parser.ParseError as exc:
            # 사유를 그대로 보여줘요. 뭘 고쳐야 하는지 알 수 있게요.
            await interaction.response.send_message(f"⏰ {exc}", ephemeral=True)
            return

        if 인원 is not None and 인원 < 2:
            await interaction.response.send_message(
                "정원은 2명 이상이어야 해요. (혼자 하는 건 일정이 아니죠)", ephemeral=True)
            return

        # 메시지를 **먼저 보내고** 그 id로 기록해요. id가 곧 일정 id예요.
        await interaction.response.send_message("📅 일정을 만드는 중이에요...")
        message = await interaction.original_response()
        await event_store.create(
            message.id, interaction.guild_id, interaction.channel_id,
            interaction.user.id, title, start, 인원,
        )

        doc = await event_store.get(message.id)
        names = collect_names(interaction.guild, doc)
        await message.edit(content=None, embed=build_embed(doc, names), view=RsvpView())

    # ------------------------------------------------------------------
    @app_commands.command(name="일정목록", description="앞으로 잡힌 일정을 봐요.")
    @restrict_to_channel(CHANNEL_GROUP)
    async def listing(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await event_store.upcoming(interaction.guild_id, 10)
        if not rows:
            await interaction.followup.send(
                "잡힌 일정이 없어요. `/일정`으로 하나 만들어보세요!")
            return

        lines = []
        for doc in rows:
            start = doc["startAt"]
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            going = len(doc.get("going") or [])
            cap = f"/{doc['capacity']}" if doc.get("capacity") else ""
            lines.append(
                f"**{doc['title']}** — {when_parser.discord_timestamp(start, 'R')} "
                f"· ✅ {going}{cap}"
            )

        embed = discord.Embed(
            title="📅 앞으로의 일정",
            description="\n".join(lines),
            color=0x5865F2,
        )
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    @tasks.loop(seconds=REMIND_CHECK_SECONDS)
    async def remind_loop(self):
        for doc in await event_store.due():
            # 🚨 **먼저 보냈다고 찍어요.** 전송 중에 루프가 또 돌면 두 번 알려요.
            await event_store.mark_reminded(doc["_id"])
            try:
                channel = self.bot.get_channel(int(doc["channelId"]))
                if channel is None:
                    continue
                going = doc.get("going") or []
                if not going:
                    continue
                mentions = " ".join(f"<@{uid}>" for uid in going)
                start = doc["startAt"]
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                await channel.send(
                    f"⏰ **{doc['title']}** 곧 시작해요! "
                    f"({when_parser.discord_timestamp(start, 'R')})\n{mentions}"
                )
                log.info("📅 일정 리마인더: %s (%d명)", doc["title"], len(going))
            except Exception:  # noqa: BLE001
                log.warning("📅 리마인더 전송 실패 (event=%s)", doc["_id"], exc_info=True)

    @remind_loop.before_loop
    async def before_remind(self):
        await self.bot.wait_until_ready()

    @remind_loop.error
    async def remind_error(self, exc: BaseException):
        """🚨 **이게 없으면 루프가 영구 정지해요.** 이 저장소에서 실제로 겪은 사고예요."""
        log.error("📅 일정 리마인더 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.remind_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
