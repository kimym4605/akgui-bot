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

## ⭐ 평문 줍기 (2026-10-23) — 명령어를 쓰게 만드는 대신 하던 대로 두기

출시 닷새 뒤 `suggestions`가 **0건**이었어요. 그런데 `💡｜기능-추천방` 채널 로그를
읽어보니 **건의는 원래 쌓여 있었어요** — 전부 `/건의` 없이 그냥 적은 평문이에요:

    기술머신 상점에 추가해주세요 (08-04) · 미션 내용 추천점 (08-08)
    랭크방 입장권이 입장하고 나가도 안 사라져요 (08-08, 버그 신고)
    롤체 덱 평가 봇 같은 것도 만들어줘 (08-24)
    노래 듣다보면 갑자기 버벅거리고 혼자 나가요 (08-31)

그리고 10-17에 봇이 `/건의` 사용법을 붙인 **뒤로 사람 메시지가 0개**예요. 명령어가
원래 하던 행동(그냥 적기)보다 번거로워진 거예요. 그래서 **사람은 하던 대로 적고,
추적만 봇이 해요.** 두 갈래로 주워요:

1. 봇이 추천방의 평문에 **💡 를 달아둬요.** 누르면 그대로 건의가 돼요.
   → 답글을 달지 않아요. 이 서버 사람들은 한 마디를 여러 줄로 나눠 적어서
     (`버그` / `발견` / `했어요`) 답글로 물으면 채널이 봇 답글로 덮여요.
2. **메시지 우클릭 → `건의로 등록`** — 채널·시점 상관없이 주울 수 있어요.
   위 옛 글들처럼 짧게 끊긴 말이나 다른 채널의 버그 신고는 이쪽으로 주워요.

🚨 **MESSAGE CONTENT INTENT가 필요해요**(글 내용을 읽어야 하니까요). 꺼져 있으면
💡 를 안 달고 `/건의`만 돌아가요 — 판단은 `bot.intents.message_content` **하나로** 해요
(`bot.py`가 `ASSISTANT_READ_MESSAGES`를 보고 켜요. **환경변수를 또 읽지 마세요** —
두 군데가 어긋나면 켜져 있는데도 조용히 아무것도 안 해요).

🚨 **등록은 `store.claim_source`로 먼저 찜해요.** 건의 문서의 `_id`는 봇이 새로 올릴
메시지 id라서, 그걸로는 "이미 등록됐나"를 막을 수 없어요 — 두 사람이 동시에 💡 를
누르면 같은 글이 두 번 올라가요.
"""
from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils import suggestion_store as store
from utils.channel_check import get_allowed_channel_id, restrict_to_channel
from utils.staff_check import is_staff

log = logging.getLogger(__name__)

CHANNEL_GROUP = "suggestion"

MAX_LEN = 500
MIN_LEN = 5

# ── 평문 줍기 ────────────────────────────────────────────────────────────
PICKUP_EMOJI = "💡"

# 💡 를 달아줄 최소 길이. 실제 채널 로그로 정했어요:
#   줍고 싶은 것 — "미션 내용 추천점"(8) · "기술머신 상점에 추가해주세요"(15)
#   줍기 싫은 것 — "확인"(2) · "ㅇㅋ"(2) · "야하"(2) · "흠 ㅇㅋ"(5)
# 🚨 이보다 짧게 끊긴 말("버그" / "발견")은 **일부러 포기**해요. 그런 건 우클릭으로
#    주워요 — 문턱을 더 내리면 잡담마다 💡 가 붙어서 채널이 💡 로 덮여요.
MIN_PICKUP_LEN = 8

# 길어도 내용이 없는 글(`ㅋㅋㅋㅋㅋㅋㅋㅋ`, `ㅠㅠㅠㅠㅠㅠㅠㅠ`)을 걸러요.
# 🚨 길이만 보면 안 돼요 — 이 서버는 `ㅋ`를 길게 늘여 적어서 10자를 쉽게 넘어요.
_FILLER_ONLY = re.compile(r"^[ㄱ-ㅎㅏ-ㅣ\s\W\d_]*$")


def _looks_like_suggestion(message: discord.Message) -> bool:
    """이 평문에 💡 를 달아줄까? (내용을 읽을 수 있을 때만 불러요)

    🚨 `@everyone`·`@here`가 붙은 글은 **빼요.** 그건 운영진 공지라서 건의가 아니에요
    (10-16의 "@here 봇에서 원하는 기능들을 알려주면 구현해줘용"이 실제로 그랬어요)."""
    if message.author.bot or message.guild is None:
        return False
    if message.mention_everyone:
        return False

    text = (message.content or "").strip()
    if len(text) < MIN_PICKUP_LEN or len(text) > MAX_LEN:
        return False
    if _FILLER_ONLY.match(text):
        return False
    return True


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
        # 메시지 우클릭 메뉴. 🚨 이름에 이모지를 넣지 않았어요 — 컨텍스트 메뉴 이름은
        #    디스코드가 따로 검사해서, 거부되면 **명령어 동기화 전체가 400으로 죽어요.**
        self._pickup_menu = app_commands.ContextMenu(
            name="건의로 등록", callback=self.pickup_context,
        )

    async def cog_load(self):
        # 🚨 재시작 뒤에도 버튼이 살아 있으려면 여기서 등록해야 해요.
        self.bot.add_view(VoteView())
        self.bot.tree.add_command(self._pickup_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self._pickup_menu.name, type=self._pickup_menu.type)

    # ── 평문 줍기 ──────────────────────────────────────────────────────
    def _channel_id(self) -> int | None:
        return get_allowed_channel_id(CHANNEL_GROUP)

    async def _register(
        self, message: discord.Message, channel: discord.abc.Messageable
    ) -> tuple[bool, str]:
        """평문 메시지를 건의로 올려요. (성공했나, 사람에게 보여줄 말)

        🚨 **찜을 먼저 해요.** 그래야 두 사람이 동시에 💡 를 눌러도 한 번만 올라가요.
        그리고 메시지를 못 올렸으면 **반드시 풀어줘요** — 안 풀면 그 글은 영영 못 올려요."""
        text = (message.content or "").strip()
        if len(text) < MIN_LEN:
            return False, "글이 너무 짧아서 건의로 올리기 어려워요. 한 줄로 다시 적어주세요."
        if len(text) > MAX_LEN:
            return False, f"{MAX_LEN}자 안쪽이어야 해요. (지금 {len(text)}자)"
        if message.author.bot:
            return False, "봇이 쓴 글은 건의로 올릴 수 없어요."

        if not await store.claim_source(message.id):
            return False, "이 글은 이미 건의로 올라가 있어요."

        try:
            posted = await channel.send("💡 건의를 올리는 중이에요...")
            await store.create(posted.id, message.author.id, text, source_id=message.id)
            doc = await store.get(posted.id)
            await posted.edit(
                content=None,
                embed=build_embed(doc, message.author.display_name),
                view=VoteView(),
            )
        except discord.HTTPException:
            await store.release_source(message.id)
            log.warning("건의 평문 줍기 실패 (source=%s)", message.id, exc_info=True)
            return False, "지금 건의를 올리지 못했어요. 잠시 뒤에 다시 눌러주세요."

        return True, f"💡 건의로 올렸어요. → {posted.jump_url}"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """추천방의 평문에 💡 를 달아둬요. (누르는 건 아래 리액션 리스너가 받아요)

        🚨 내용을 읽을 수 없으면(인텐트 꺼짐) 조용히 아무것도 안 해요."""
        if not self.bot.intents.message_content:
            return
        channel_id = self._channel_id()
        if channel_id is None or message.channel.id != channel_id:
            return  # 채널 미설정이면 어디에도 안 달아요(조용한 기본값)
        if not _looks_like_suggestion(message):
            return
        try:
            await message.add_reaction(PICKUP_EMOJI)
        except discord.HTTPException:
            pass  # 권한이 없거나 리액션이 꽉 찬 경우. 우클릭 경로는 그대로 돼요.

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """추천방에서 💡 를 누르면 그 글을 건의로 올려요.

        ⭐ **누가 눌러도 돼요.** 제안자는 원글 작성자로 남으니까요. 작성자만 허용하면,
        정작 본인이 💡 를 못 보고 지나간 글(= 지금까지 묻혀온 그 글들)을 아무도 못
        건집니다. `raw` 이벤트를 쓰는 건 **며칠 전 글에도 달 수 있어야** 해서예요
        (캐시에 없는 메시지는 `on_reaction_add`가 아예 안 불려요)."""
        if payload.guild_id is None or str(payload.emoji) != PICKUP_EMOJI:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return  # 봇이 달아둔 그 💡
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

        ok, note = await self._register(message, channel)
        if not ok:
            # 리액션엔 답할 자리가 없어요. 이미 올라간 건 바로 아래 카드로 보이니까
            # 조용히 넘기고 로그만 남겨요(채널에 거절 메시지를 뿌리면 더 시끄러워요).
            log.info("건의 줍기 넘김 (source=%s): %s", payload.message_id, note)

    async def pickup_context(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        """메시지 우클릭 → `건의로 등록`. 채널·시점 제한이 없어요.

        🚨 올라가는 자리는 **건의함 채널**이에요(원래 글이 있던 채널이 아니에요).
        그래야 `/건의목록`과 운영자의 `/건의처리`가 한곳에서 돌아가요."""
        await interaction.response.defer(ephemeral=True)

        target = self.bot.get_channel(self._channel_id() or 0) or interaction.channel
        ok, note = await self._register(message, target)
        await interaction.followup.send(note, ephemeral=True)

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
