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

## ⭐ 모집글 줍기 (2026-10-23) — 이 서버는 예약이 아니라 "지금 소집"이다

출시 닷새 뒤 `events`가 **1건**이고 그것도 만든 사람이 직접 취소했어요.
🚨 **채널은 처음부터 맞게 꽂혀 있었어요** — `pokemonChannel:event`가 `📣｜내전모집`
(`1555898408861048932`)이에요. 그러니까 "채널을 안 정해서"가 아니에요.

채널 로그를 읽어보니 사람들은 `/일정`을 안 쓰고 **평문으로 모아요.** 그런데 그 평문이
바로 일정이에요:

    10-17 📣내전모집 yar_860: "@everyone 지금 당장 라잇나우 롤 내전 하실분"
          ram._.g:  "내일까지 컴이 고쳐지면 할수있을것 같은데 **일단 참여 눌러놔야하나**"
                     ↑ 버튼을 찾고 있었어요. `/일정`은 이미 이 채널에 있었는데도요.
    10-23 💬일반  yar_860: "나 1시40분 정도에 집 가서 2시에 도착할건데 게임 ㄱ?"

그래서 **모집글에 시간이 적혀 있으면 봇이 📅 를 달아둬요.** 누르면 그 글이 그대로
일정이 돼서 참가 버튼과 30분 전 리마인더가 붙어요. (`cogs/suggestion.py`의 💡 평문
줍기와 같은 수법이에요 — 사람은 하던 대로 적고, 추적만 봇이 해요)

🚨 **시간이 없는 글엔 아무것도 안 달아요.** "지금 당장 하실분"은 예약이 아니라 즉시
소집이고, 그건 `/방만들기`가 할 일이에요. 📅 를 달면 거짓 일정이 쌓여요.

🚨 **`@everyone`을 걸러내지 마세요.** 건의함(`cogs/suggestion.py`)은 `@everyone`을
공지로 보고 빼는데, 여기선 **반대로 가장 강한 모집 신호**예요(위 10-17 글이 그래요).

🚨 **시간 해석은 틀릴 수 있어요.** 잡담에서 숫자를 주워오니까요("1시40분 정도에 집
가서 2시에 도착"은 1시로 읽혀요). 그래서 **자동으로 만들지 않고 📅 로 물어봐요** —
카드에 해석한 시각이 그대로 찍히니까, 틀리면 🚫 취소를 누르면 돼요.

🚨 **MESSAGE CONTENT INTENT가 필요해요**(글 내용을 읽어야 하니까요). 판단은
`bot.intents.message_content` **하나로** 해요 — 환경변수를 또 읽으면 두 군데가
어긋나서 켜져 있는데도 조용히 아무것도 안 해요.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import event_store, when_parser
from utils.channel_check import get_allowed_channel_id, restrict_to_channel

log = logging.getLogger(__name__)

CHANNEL_GROUP = "event"

MAX_TITLE = 80
REMIND_CHECK_SECONDS = 60

# ── 모집글 줍기 ──────────────────────────────────────────────────────────
PICKUP_EMOJI = "📅"

# 이보다 짧으면 모집글로 안 봐요("9시"만 적힌 한 마디는 일정이 아니에요).
MIN_PICKUP_LEN = 5

# 너무 먼 미래로 읽힌 건 오해예요. `when_parser`는 날짜 단서가 없으면 오늘/내일로
# 잡으니까 보통 짧은데, "12월 3일"처럼 적으면 멀어질 수 있어요. 한 달까지만 받아요.
MAX_PICKUP_DAYS = 31

# `<@123>`·`<@!123>`·`<@&55>`·`<#99>` 같은 멘션 토큰. 제목에서 걷어내요
# (그대로 두면 일정 제목에 멘션이 박혀서 **카드가 사람을 또 호출해요**).
_MENTION_RE = re.compile(r"<[@#][!&]?\d+>")


def pickup_title(content: str) -> str:
    """모집글 평문 → 일정 제목. 멘션을 걷어내고 한 줄로 줄여요."""
    text = _MENTION_RE.sub(" ", content or "")
    text = text.replace("@everyone", " ").replace("@here", " ")
    # 여러 줄로 적은 모집글은 첫 줄만 제목으로 써요(나머지는 원글에 그대로 있어요).
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return " ".join(first.split())[:MAX_TITLE]


def parse_pickup(content: str, *, now: datetime | None = None) -> datetime | None:
    """모집글에서 시작 시각을 읽어요. 못 읽거나 말이 안 되면 None이에요.

    🚨 **`@everyone`을 빼지 않아요.** 건의함과 반대로, 여기선 그게 모집 신호예요."""
    text = _MENTION_RE.sub(" ", content or "").strip()
    if len(text) < MIN_PICKUP_LEN:
        return None
    try:
        start = when_parser.parse(text, now=now)
    except when_parser.ParseError:
        return None  # 시간이 없는 글 = "지금 당장 하실분". 📅 를 달지 않아요.

    base = (now or datetime.now(when_parser.KST)).astimezone(when_parser.KST)
    if (start - base).days > MAX_PICKUP_DAYS:
        return None
    return start


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

    # ── 모집글 줍기 ────────────────────────────────────────────────────
    def _channel_id(self) -> int | None:
        return get_allowed_channel_id(CHANNEL_GROUP)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """모집 채널의 평문에 시간이 적혀 있으면 📅 를 달아둬요.

        🚨 시간이 없으면 아무것도 안 달아요 — "지금 당장 하실분"은 예약이 아니에요."""
        if not self.bot.intents.message_content:
            return
        if message.author.bot or message.guild is None:
            return
        channel_id = self._channel_id()
        if channel_id is None or message.channel.id != channel_id:
            return  # 채널 미설정이면 어디에도 안 달아요(조용한 기본값)
        if parse_pickup(message.content) is None:
            return
        try:
            await message.add_reaction(PICKUP_EMOJI)
        except discord.HTTPException:
            pass  # 권한이 없거나 리액션이 꽉 찬 경우. `/일정`은 그대로 돼요.

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """📅 를 누르면 그 모집글이 일정이 돼요(참가 버튼 + 30분 전 리마인더).

        ⭐ **누가 눌러도 돼요.** 주최자는 원글 작성자로 남으니까요. `raw` 이벤트를
        쓰는 건 캐시에 없는(= 조금 전에 올라온 게 아닌) 글에도 달 수 있어야 해서예요.

        🚨 `store.claim_source`로 **먼저 찜해요.** 일정 문서의 `_id`는 봇이 새로 올릴
        메시지 id라서, 그걸로는 중복을 막을 수 없어요."""
        if payload.guild_id is None or str(payload.emoji) != PICKUP_EMOJI:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return  # 봇이 달아둔 그 📅
        channel_id = self._channel_id()
        if channel_id is None or payload.channel_id != channel_id:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if message.author.bot:
            return

        start = parse_pickup(message.content)
        title = pickup_title(message.content)
        if start is None or not title:
            return

        if not await event_store.claim_source(message.id):
            return  # 이미 일정이 된 글. 카드가 바로 아래에 있으니 조용히 넘겨요.

        try:
            posted = await channel.send("📅 일정을 만드는 중이에요...")
            await event_store.create(
                posted.id, payload.guild_id, payload.channel_id,
                message.author.id, title, start, None,
            )
            doc = await event_store.get(posted.id)
            names = collect_names(message.guild, doc)
            await posted.edit(content=None, embed=build_embed(doc, names), view=RsvpView())
        except discord.HTTPException:
            # 🚨 안 풀면 그 모집글은 **영영** 일정이 못 돼요.
            await event_store.release_source(message.id)
            log.warning("일정 모집글 줍기 실패 (source=%s)", message.id, exc_info=True)

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
