"""칭호 상점 - 악귀코인으로 나만의 역할(이름+색)을 한 달간 달아요.

서버에 이미 💗 여왕님 / 교수님 / 잼민이 같은 재미 역할 문화가 있어서, 그걸 코인으로 살 수
있게 만든 거예요. 30코인 = 한 달 개근이라 "개근했다"는 표시가 눈에 보이는 형태로 남아요.

## 역할 위치 (색이 보이려면 중요해요)

디스코드는 **그 사람이 가진 역할 중 가장 위에 있는 '색 있는 역할'**의 색만 보여줘요.
새로 만든 역할은 맨 아래에 생기니까 그냥 두면 티어 역할 색에 가려서 안 보여요.
그래서 만들자마자 ANCHOR_ROLE_NAME 바로 위로 옮겨요.

⚠️ 💗 여왕님/교수님처럼 앵커보다 위에 있는 역할을 이미 가진 사람은 여전히 그 색이 우선이에요.
칭호를 더 위로 올리고 싶으면 ANCHOR_ROLE_NAME을 더 높은 역할 이름으로 바꾸면 돼요.
"""
import io
import logging
import re
import unicodedata
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import coin_wallet, title_store
from utils.channel_check import restrict_to_channel
from utils.interaction_ack import ack
from utils.title_store import (
    TITLE_DAYS, TITLE_ICON_EMOJI_PRICE, TITLE_ICON_IMAGE_PRICE, TITLE_PLANS, TITLE_PRICE,
)

log = logging.getLogger(__name__)

# 이 역할 바로 위에 칭호를 놓아요. 없으면 위치 조정을 건너뛰어요(역할은 정상 생성돼요).
#
# 2026-10-05: "😈 악귀"에서 "⚔️ 타격대"로 바꿨어요. 역할 순서를 정리하면서 "😈 악귀"(전원이 가진
# 멤버 역할)를 티어 역할들 **아래**로 내렸는데, 그러면 앵커 바로 위 = 티어 묶음 아래가 되어서
# 칭호 색이 티어 색에 가려져요. "⚔️ 타격대"는 티어·포지션 묶음의 맨 위라 그 위가 안전해요.
ANCHOR_ROLE_NAME = "⚔️ 타격대"

MAX_NAME_LENGTH = 20
HEX_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")

# 이런 글자가 들어간 이름은 막아요. 멘션을 흉내 내거나 사칭에 쓰일 수 있어요.
BANNED_SUBSTRINGS = ("@everyone", "@here", "```")
BANNED_KEYWORDS = ("관리자", "매니저", "방장", "운영", "admin", "mod", "봇")


# ==================================================================
# 🎖️ 칭호 아이콘 (2026-11-15) — 근거·가격은 `utils/title_store.py` 칭호 아이콘 절
#
# 🚨 디스코드는 **아이콘이 있는 역할 중 가장 위의 것 하나만** 이름 옆에 보여줘요.
#    칭호는 `ANCHOR_ROLE_NAME`(⚔️ 타격대 = 요원·티어 아이콘 묶음의 맨 위) 바로 위에 놓이니
#    요원 아이콘보다 **칭호 아이콘이 이겨요.** 앵커를 내리면 칭호 아이콘이 가려져요.
# 🚨 순서는 /커스텀테마와 같아요: **검사 → 손질 → 차감 → 대기 등록 → 관리방 게시**.
#    차감 뒤 실패는 **반드시 환불**.
# ==================================================================
ICON_SPEND_EMOJI = "칭호아이콘:이모지"
ICON_SPEND_IMAGE = "칭호아이콘:그림"
ICON_REFUND = "칭호아이콘 환불"
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
# 이모지를 이루는 '글자 아닌' 조각들 (ZWJ·변형 선택자·키캡·피부색·태그)
_EMOJI_JOINERS = {"‍", "️", "︎", "⃣"}


def clean_emoji(text: str) -> tuple[str | None, str]:
    """(이모지, 오류). 일반 유니코드 이모지 **하나**만 받아요.

    최종 판정은 디스코드가 해요(역할에 넣어보고 400이면 환불). 여기선 돈을 빼기 전에
    **명백히 아닌 것**만 걸러요 — 글자·숫자·서버 커스텀 이모지·여러 개."""
    s = (text or "").strip()
    if not s:
        return None, "이모지를 입력해주세요."
    if s.startswith("<") or s.startswith(":"):
        return None, ("서버 커스텀 이모지는 아이콘으로 바로 못 써요. "
                      "그 그림을 `그림` 칸에 올려주세요(방장 승인 후 적용).")
    if len(s) > 12:
        return None, "이모지는 **하나만** 넣어주세요."
    keycap = "⃣" in s
    bases = 0          # '한 개'로 보이는 이모지 수. ZWJ로 이어진 건 하나로 쳐요.
    regional = 0       # 국기는 지역 표시 글자 두 개가 한 쌍이에요.
    prev = ""
    for ch in s:
        if ch in _EMOJI_JOINERS:
            prev = ch
            continue
        cat = unicodedata.category(ch)
        if keycap and ch in "0123456789#*":
            bases += 1
            prev = ch
            continue
        # So = 기호(이모지 대부분), Sk = 피부색 변경자. 한글·영문(L*)·숫자(N*)는 여기서 걸려요.
        if cat not in ("So", "Sk", "Mn", "Cf"):
            return None, "일반 이모지 **하나**만 넣어주세요. (글자·숫자는 안 돼요, 예: 🔥 🐉 👑)"
        if "\U0001F1E6" <= ch <= "\U0001F1FF":
            regional += 1
        elif cat == "So" and prev != "‍":
            bases += 1
        prev = ch
    bases += (regional + 1) // 2
    if bases != 1:
        return None, "이모지는 **하나만** 넣어주세요."
    return s, ""


async def _title_role(guild: discord.Guild, user_id: int) -> tuple[discord.Role | None, str]:
    """(칭호 역할, 오류). 아이콘을 달 수 있는 상태인지 돈 빼기 **전에** 봐요."""
    if "ROLE_ICONS" not in guild.features:
        return None, "지금은 서버 부스트 레벨이 모자라서 역할 아이콘을 달 수 없어요. (코인은 안 빠졌어요)"
    doc = await title_store.get(user_id)
    role = guild.get_role(int(doc["roleId"])) if doc else None
    if role is None:
        return None, ("아이콘은 **칭호에** 붙어요. 먼저 `/칭호구매`로 칭호를 달아주세요.\n"
                      f"-# 칭호: {TITLE_PLANS[10]}코인(10일) / {TITLE_PRICE}코인({TITLE_DAYS}일)")
    return role, ""


async def _icon_dm(bot: commands.Bot, user_id: int, text: str) -> None:
    from cogs.custom_theme import _dm
    await _dm(bot, user_id, text)


class IconReviewButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"akgui:ticon:(?P<action>approve|reject):(?P<user_id>\d+)",
):
    """🎖️ 칭호 아이콘 그림 심사 버튼. 심사가 며칠 걸려도 배포 뒤 살아나게 DynamicItem이에요."""

    def __init__(self, action: str, user_id: int):
        approve = action == "approve"
        super().__init__(discord.ui.Button(
            label="승인" if approve else "거절",
            emoji="✅" if approve else "❌",
            style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
            custom_id=f"akgui:ticon:{action}:{user_id}",
        ))
        self.action = action
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from cogs.custom_theme import _is_reviewer
        if _is_reviewer(interaction):
            return True
        await interaction.response.send_message("❌ 방장·매니저만 심사할 수 있어요.", ephemeral=True)
        return False

    async def callback(self, interaction: discord.Interaction):
        if self.action == "reject":
            # 🚨 모달은 **첫 응답**이어야 해요(ack 금지).
            await interaction.response.send_modal(IconRejectModal(self.user_id))
            return
        if not await ack(interaction):
            return
        await approve_icon(interaction, self.user_id)


def icon_review_view(user_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(IconReviewButton("approve", user_id))
    view.add_item(IconReviewButton("reject", user_id))
    return view


async def approve_icon(interaction: discord.Interaction, user_id: int) -> None:
    from cogs.custom_theme import _close_review
    taken = await title_store.icon_take(user_id)
    if taken is None:
        await interaction.followup.send("이미 처리된 신청이에요.", ephemeral=True)
        await _close_review(interaction, "⚠️ 이미 처리된 신청이에요.")
        return
    paid = int(taken.get("pendingPaid") or 0)

    # 심사하는 사이 칭호가 만료됐을 수 있어요 → 그땐 환불.
    role, why = await _title_role(interaction.guild, user_id)
    error = None
    if role is None:
        error = "칭호가 그 사이 끝났어요"
    else:
        try:
            await role.edit(display_icon=bytes(taken["pending"]), reason="칭호 아이콘(그림) 승인")
        except discord.HTTPException as exc:
            log.warning("🎖️ 칭호 아이콘 적용 실패 (user=%s): %s", user_id, exc)
            error = "디스코드가 그림을 받지 않았어요"

    if error:
        if paid:
            await coin_wallet.add(user_id, paid, reason=ICON_REFUND)
        await _close_review(interaction, f"⚠️ 승인했지만 적용 못 함({error}) · {paid}코인 환불")
        await _icon_dm(interaction.client, user_id,
                       f"🎖️ 칭호 아이콘 그림이 승인됐는데 적용하지 못했어요({error}). "
                       f"낸 **{paid}코인**은 전부 돌려드렸어요.")
        return

    await _close_review(interaction, f"✅ {interaction.user.mention} 님이 승인했어요.")
    await _icon_dm(interaction.client, user_id,
                   "🎖️ 올린 그림이 **승인**돼서 칭호 아이콘으로 달았어요! 이름 옆을 확인해보세요.\n"
                   "-# 아이콘은 칭호에 붙어 있어서, 칭호를 연장하면 그대로 남고 끝나면 같이 사라져요.")
    log.info("🎖️ 칭호 아이콘(그림) 승인: user=%s by %s", user_id, interaction.user.id)


class IconRejectModal(discord.ui.Modal, title="🎖️ 칭호 아이콘 거절"):
    reason = discord.ui.TextInput(
        label="거절 사유 (신청자에게 DM으로 가요)",
        placeholder="예) 다른 사람 얼굴이 나온 사진은 안 돼요",
        required=False, max_length=200, style=discord.TextStyle.paragraph,
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.custom_theme import _close_review
        if not await ack(interaction):
            return
        taken = await title_store.icon_take(self.user_id)
        if taken is None:
            await interaction.followup.send("이미 처리된 신청이에요.", ephemeral=True)
            await _close_review(interaction, "⚠️ 이미 처리된 신청이에요.")
            return
        paid = int(taken.get("pendingPaid") or 0)
        if paid:
            await coin_wallet.add(self.user_id, paid, reason=ICON_REFUND)
        why = str(self.reason).strip()
        await _close_review(
            interaction,
            f"❌ {interaction.user.mention} 님이 거절했어요 · {paid}코인 환불"
            + (f"\n　└ 사유: {why}" if why else ""))
        await _icon_dm(interaction.client, self.user_id,
                       f"🙏 칭호 아이콘 그림이 **거절**됐어요. 낸 **{paid}코인**은 전부 돌려드렸어요."
                       + (f"\n　└ 사유: {why}" if why else "")
                       + "\n-# 다른 그림이나 이모지로 `/칭호아이콘`을 다시 할 수 있어요.")
        log.info("🎖️ 칭호 아이콘 거절: user=%s by %s (환불 %d)",
                 self.user_id, interaction.user.id, paid)


async def buy_icon_emoji(interaction: discord.Interaction, role: discord.Role, emoji: str) -> None:
    uid = interaction.user.id
    price = TITLE_ICON_EMOJI_PRICE
    if not await coin_wallet.spend(uid, price, reason=ICON_SPEND_EMOJI):
        balance = await coin_wallet.get_balance(uid)
        await interaction.followup.send(
            f"악귀코인이 부족해요. 이모지 아이콘은 **{price}개**가 필요한데 지금 **{balance}개** 갖고 있어요.",
            ephemeral=True)
        return
    try:
        await role.edit(display_icon=emoji, reason="칭호 아이콘(이모지)")
    except discord.HTTPException as exc:
        await coin_wallet.add(uid, price, reason=ICON_REFUND)
        log.info("🎖️ 칭호 아이콘 이모지 거부 (user=%s, %r): %s", uid, emoji, exc)
        await interaction.followup.send(
            f"디스코드가 {emoji} 를 아이콘으로 받지 않았어요. 코인은 돌려드렸어요.\n"
            "-# 다른 이모지로 해보세요 (예: 🔥 🐉 👑 💀).", ephemeral=True)
        return
    balance = await coin_wallet.get_balance(uid)
    await interaction.followup.send(
        f"🎖️ 칭호 {role.mention} 에 {emoji} 아이콘을 달았어요! (**{price}코인**, 남은 코인 {balance}개)\n"
        "-# 칭호를 연장하면 아이콘도 그대로 남고, 칭호가 끝나면 같이 사라져요.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    log.info("🎖️ 칭호 아이콘(이모지): user=%s %s", uid, emoji)


async def submit_icon_image(interaction: discord.Interaction, attachment: discord.Attachment) -> None:
    from cogs.custom_theme import MANAGER_CHANNEL_ID
    uid = interaction.user.id
    price = TITLE_ICON_IMAGE_PRICE

    async def say(text: str):
        await interaction.followup.send(text, ephemeral=True)

    # ── 1. 돈 빼기 전 검사 ──
    name = (attachment.filename or "").lower()
    if not ((attachment.content_type or "").startswith("image/") or name.endswith(_IMAGE_EXT)):
        await say("그림 파일(PNG·JPG·WEBP)을 첨부해주세요.")
        return
    if attachment.size > title_store.ICON_MAX_UPLOAD_BYTES:
        await say(f"파일이 너무 커요 ({attachment.size / 1024 / 1024:.1f}MB) — 8MB 이하로 올려주세요.")
        return
    channel = interaction.guild.get_channel(MANAGER_CHANNEL_ID) if MANAGER_CHANNEL_ID else None
    if channel is None:
        await say("⚠️ 지금은 심사 채널을 찾을 수 없어요. 방장에게 알려주세요. (코인은 안 빠졌어요)")
        return
    try:
        png = await title_store.prepare_icon_async(await attachment.read())
    except title_store.BadIcon as exc:
        await say(f"⚠️ {exc}")
        return
    except discord.HTTPException:
        await say("⚠️ 첨부를 받아오지 못했어요. 잠시 뒤 다시 해주세요.")
        return

    # ── 2. 차감 ──
    if not await coin_wallet.spend(uid, price, reason=ICON_SPEND_IMAGE):
        balance = await coin_wallet.get_balance(uid)
        await say(f"악귀코인이 부족해요. 그림 아이콘은 **{price}개**가 필요한데 지금 **{balance}개** 갖고 있어요.")
        return

    # ── 3. 대기 등록 (🚨 여기부터 실패하면 반드시 환불) ──
    if not await title_store.icon_submit(uid, png, price):
        await coin_wallet.add(uid, price, reason=ICON_REFUND)
        await say("⏳ 이미 심사 중인 그림이 있어요. 코인은 돌려드렸어요.")
        return

    # ── 4. 관리방 게시 ──
    try:
        file = discord.File(io.BytesIO(png), filename="title_icon.png")
        embed = discord.Embed(
            title="🎖️ 칭호 아이콘 심사",
            description=(f"{interaction.user.mention} ({interaction.user}) 님이 **{price}코인**을 내고 "
                         "칭호 아이콘을 신청했어요.\n아이콘은 채팅·멤버 목록에서 **모두에게** 보여요.\n"
                         "-# 거절하면 코인은 전액 자동 환불돼요."),
            color=0xFFC850,
        )
        embed.set_thumbnail(url="attachment://title_icon.png")
        msg = await channel.send(embed=embed, file=file, view=icon_review_view(uid),
                                 allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.warning("🎖️ 칭호 아이콘 심사 게시 실패 (user=%s)", uid, exc_info=True)
        taken = await title_store.icon_take(uid)
        if taken:
            await coin_wallet.add(uid, int(taken.get("pendingPaid") or 0), reason=ICON_REFUND)
        await say("⚠️ 심사 요청을 올리지 못했어요. 코인은 돌려드렸어요. 잠시 뒤 다시 해주세요.")
        return
    await title_store.icon_set_review(uid, channel.id, msg.id)

    await say(f"🎖️ 그림을 보냈어요! **{price}코인**이 빠졌고 방장 확인을 기다리는 중이에요.\n"
              "　└ 승인되면 칭호에 **바로 달리고** DM으로 알려드려요\n"
              "　└ 거절되면 코인은 **전액 돌려드려요**")
    log.info("🎖️ 칭호 아이콘(그림) 신청: user=%s (%dB)", uid, len(png))


class TitleModal(discord.ui.Modal, title="칭호 만들기"):
    name = discord.ui.TextInput(
        label="칭호 이름",
        placeholder="예: 발로장인",
        max_length=MAX_NAME_LENGTH,
        required=True,
    )
    color = discord.ui.TextInput(
        label="색상 (헥스 코드)",
        placeholder="예: #e91e63  (색상 코드는 구글에 'color picker'로 검색)",
        min_length=6,
        max_length=7,
        required=True,
    )

    def __init__(self, cog: "TitleShop", days: int = TITLE_DAYS):
        # 제목에 기간·가격을 박아서, 모달이 열린 순간 뭘 사는지 보이게 해요.
        super().__init__(title=f"칭호 만들기 ({days}일 · {TITLE_PLANS[days]}코인)")
        self.cog = cog
        # 기간은 모달 입력이 아니라 **명령어 선택지**로 받아요. 모달에 숫자를 직접 치게 하면
        # 가격표에 없는 값이 들어와서 검증 코드가 늘어나요.
        self.days = days

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.purchase(interaction, str(self.name), str(self.color), days=self.days)


class TitleShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expire_titles.start()

    def cog_unload(self):
        self.expire_titles.cancel()

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 칭호 아이콘 심사 버튼이 **아무 반응 없이** 죽어요.
        self.bot.add_dynamic_items(IconReviewButton)

    # ------------------------------------------------------------------
    # 구매
    # ------------------------------------------------------------------
    def _validate(self, guild: discord.Guild, name: str, color_raw: str) -> tuple[str | None, int]:
        """(오류메시지, 색상값). 오류메시지가 None이면 통과예요."""
        name = name.strip()
        if not name:
            return "칭호 이름을 입력해주세요.", 0
        if len(name) > MAX_NAME_LENGTH:
            return f"칭호 이름은 {MAX_NAME_LENGTH}자까지예요.", 0
        if any(bad in name for bad in BANNED_SUBSTRINGS):
            return "쓸 수 없는 문자가 들어있어요.", 0

        lowered = name.lower()
        if any(word in lowered for word in BANNED_KEYWORDS):
            return "운영진을 사칭할 수 있는 단어는 쓸 수 없어요.", 0

        # 기존 역할과 같은 이름은 막아요(사칭 + 헷갈림 방지).
        if discord.utils.find(lambda r: r.name.lower() == lowered, guild.roles):
            return "이미 서버에 있는 역할과 같은 이름이에요.", 0

        matched = HEX_PATTERN.match(color_raw.strip())
        if not matched:
            return "색상은 `#e91e63` 같은 헥스 코드로 입력해주세요.", 0

        return None, int(matched.group(1), 16)

    async def purchase(
        self, interaction: discord.Interaction, name: str, color_raw: str, days: int = TITLE_DAYS
    ):
        await interaction.response.defer(ephemeral=True)

        guild, user = interaction.guild, interaction.user
        if guild is None:
            await interaction.followup.send("서버 안에서만 쓸 수 있어요.", ephemeral=True)
            return

        error, color_value = self._validate(guild, name, color_raw)
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return

        name = name.strip()
        existing = await title_store.get(user.id)
        # 가격표에 없는 기간이 흘러들어오면 기본(30일)으로 떨어뜨려요.
        days = days if days in TITLE_PLANS else TITLE_DAYS
        price = TITLE_PLANS[days]

        # ⚠️ 코인부터 빼요. 역할을 먼저 만들면, 코인이 모자랄 때 역할만 덩그러니 남아요.
        if not await coin_wallet.spend(user.id, price, reason=f"칭호구매:{days}일"):
            balance = await coin_wallet.get_balance(user.id)
            await interaction.followup.send(
                f"악귀코인이 부족해요. **{days}일 칭호**는 **{price}개**가 필요한데 "
                f"지금 **{balance}개** 갖고 있어요.\n"
                f"-# `/출석`과 `/미션`으로 매일 모을 수 있어요.",
                ephemeral=True,
            )
            return

        try:
            role = await self._apply_role(guild, user, existing, name, color_value)
        except discord.Forbidden:
            await coin_wallet.add(user.id, price, reason="칭호구매 실패 환불")
            await interaction.followup.send(
                "역할을 만들 권한이 없어요. 코인은 돌려드렸어요. (봇 역할이 충분히 위에 있는지 확인해주세요)",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await coin_wallet.add(user.id, price, reason="칭호구매 실패 환불")
            log.exception("칭호 역할 생성 실패 (user=%s)", user.id)
            await interaction.followup.send("역할을 만들지 못했어요. 코인은 돌려드렸어요.", ephemeral=True)
            return

        doc = await title_store.save(user.id, guild.id, role.id, name, color_value, days=days)
        remaining = title_store.remaining_days(doc)

        embed = discord.Embed(
            title="🏷️ 칭호를 달았어요!",
            description=(
                f"칭호: {role.mention}\n"
                f"사용한 악귀코인: **{price}개** (남은 코인 {await coin_wallet.get_balance(user.id)}개)\n"
                f"남은 기간: **{remaining}일**"
            ),
            color=color_value,
        )
        embed.set_footer(text="기간이 끝나면 자동으로 사라져요. 그 전에 다시 사면 기간이 이어져요.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        log.info("🏷️ 칭호 구매: %s → '%s' (#%06x, %d일 %d코인)", user, name, color_value, days, price)

    async def _apply_role(
        self, guild: discord.Guild, user: discord.Member, existing: dict | None, name: str, color: int
    ) -> discord.Role:
        """이미 칭호가 있으면 그 역할의 이름/색을 바꾸고, 없으면 새로 만들어요."""
        role = None
        if existing:
            role = guild.get_role(int(existing["roleId"]))

        if role is not None:
            await role.edit(name=name, colour=discord.Colour(color), reason="칭호 갱신")
        else:
            role = await guild.create_role(
                name=name,
                colour=discord.Colour(color),
                reason=f"칭호 상점 구매 ({user})",
                # 권한은 하나도 안 줘요. 순수하게 이름표 역할이에요.
                permissions=discord.Permissions.none(),
            )
            await self._move_role(guild, role)

        if role not in user.roles:
            await user.add_roles(role, reason="칭호 구매")
        return role

    async def _move_role(self, guild: discord.Guild, role: discord.Role):
        """색이 보이도록 앵커 역할 바로 위로 옮겨요. 실패해도 구매는 유효해요."""
        anchor = discord.utils.get(guild.roles, name=ANCHOR_ROLE_NAME)
        if anchor is None:
            return
        target = anchor.position + 1
        # 봇 자신의 역할보다 위로는 못 올려요(디스코드 제약).
        if guild.me.top_role.position <= target:
            return
        try:
            await role.edit(position=target, reason="칭호 색이 보이도록 위치 조정")
        except discord.HTTPException:
            log.warning("칭호 역할 위치 조정 실패 (role=%s)", role.id, exc_info=True)

    # ------------------------------------------------------------------
    # 명령어
    # ------------------------------------------------------------------
    @app_commands.command(name="칭호구매", description=f"악귀코인 {TITLE_PLANS[10]}개(10일) 또는 {TITLE_PRICE}개({TITLE_DAYS}일)로 나만의 칭호를 달아요.")
    # ⚠️ 그룹이 "attendance"(=#포켓몬)에서 "title"로 바뀌었어요.
    #
    # 칭호는 코인을 쓰는 거의 유일한 곳인데 실사용이 0건이었어요. 2026-09-29에 재보니
    # #포켓몬은 마지막 글이 9일 전인 사실상 죽은 채널이었고(#일반❓은 하루 50개),
    # "20코인을 쓰려면 아무도 안 가는 채널로 가야 하는" 상태였어요. 그게 원인일 수 있어서
    # 떼어냈어요. 설정값이 없으면 제한이 없으니 기본은 아무 채널에서나 돼요.
    @app_commands.describe(기간="칭호를 며칠 달지 골라요. 기본은 30일이에요.")
    @app_commands.choices(기간=[
        app_commands.Choice(name=f"10일 — {TITLE_PLANS[10]}코인", value=10),
        app_commands.Choice(name=f"{TITLE_DAYS}일 — {TITLE_PLANS[TITLE_DAYS]}코인 (하루 단가가 더 싸요)",
                            value=TITLE_DAYS),
    ])
    @restrict_to_channel("title")
    async def buy(self, interaction: discord.Interaction, 기간: int = TITLE_DAYS):
        await interaction.response.send_modal(TitleModal(self, days=기간))

    @app_commands.command(name="칭호", description="지금 달고 있는 칭호와 남은 기간을 확인해요.")
    @restrict_to_channel("title")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        doc = await title_store.get(interaction.user.id)
        if doc is None:
            await interaction.followup.send(
                "아직 칭호가 없어요. `/칭호구매`로 이름과 색을 직접 정해서 달 수 있어요.\n"
                f"**{TITLE_PLANS[10]}코인 = 10일** · **{TITLE_PRICE}코인 = {TITLE_DAYS}일** "
                f"(하루 단가는 {TITLE_DAYS}일권이 더 싸요 · 기간이 남았을 때 또 사면 이어붙어요)",
                ephemeral=True,
            )
            return

        remaining = title_store.remaining_days(doc)
        embed = discord.Embed(
            title="🏷️ 내 칭호",
            description=f"**{doc['name']}**\n남은 기간: **{remaining}일**",
            color=doc.get("color", 0x99AAB5),
        )
        # 🎖️ 아이콘은 역할 자체에 있어요(DB엔 없어요 — title_store 칭호 아이콘 절 참고).
        role = interaction.guild.get_role(int(doc["roleId"])) if interaction.guild else None
        if role is not None and role.unicode_emoji:
            icon = f"{role.unicode_emoji} 이모지"
        elif role is not None and role.icon:
            icon = "🖼️ 그림"
        else:
            icon = (f"없음 — `/칭호아이콘` 이모지 {TITLE_ICON_EMOJI_PRICE}코인 · "
                    f"그림 {TITLE_ICON_IMAGE_PRICE}코인")
        if await title_store.icon_pending(interaction.user.id):
            icon += "\n-# ⏳ 올린 그림이 심사 중이에요"
        embed.add_field(name="🎖️ 아이콘", value=icon, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="칭호아이콘",
        description=(f"칭호 옆에 아이콘을 달아요. 이모지 {TITLE_ICON_EMOJI_PRICE}코인(바로) · "
                     f"그림 {TITLE_ICON_IMAGE_PRICE}코인(방장 승인 후)"),
    )
    @app_commands.rename(attachment="그림")
    @app_commands.describe(
        이모지="아이콘으로 쓸 이모지 하나 (예: 🔥) — 바로 적용돼요",
        attachment="아이콘으로 쓸 그림 (정사각형으로 잘려요) — 방장 승인 후 적용, 거절되면 환불",
    )
    @restrict_to_channel("title")
    async def icon(self, interaction: discord.Interaction, 이모지: str | None = None,
                   attachment: discord.Attachment | None = None):
        if not await ack(interaction, ephemeral=True, thinking=True):
            return
        say = lambda text: interaction.followup.send(text, ephemeral=True)  # noqa: E731

        if interaction.guild is None:
            await say("서버 안에서만 쓸 수 있어요.")
            return
        if (이모지 is None) == (attachment is None):
            await say("`이모지` 와 `그림` 중 **하나만** 골라주세요.\n"
                      f"　└ 😀 **이모지** — {TITLE_ICON_EMOJI_PRICE}코인, 바로 달려요\n"
                      f"　└ 🖼️ **그림** — {TITLE_ICON_IMAGE_PRICE}코인, 방장이 확인한 뒤 달려요 "
                      "(거절되면 전액 환불)\n"
                      "-# 아이콘은 칭호에 붙어요. 칭호를 연장하면 남고, 칭호가 끝나면 같이 사라져요.")
            return

        role, why = await _title_role(interaction.guild, interaction.user.id)
        if role is None:
            await say(why)
            return
        if await title_store.icon_pending(interaction.user.id):
            await say("⏳ 심사 중인 그림이 있어요. 결과가 나온 뒤에 바꿔주세요. (결과는 DM으로 알려드려요)")
            return

        if 이모지 is not None:
            emoji, err = clean_emoji(이모지)
            if emoji is None:
                await say(err)
                return
            await buy_icon_emoji(interaction, role, emoji)
        else:
            await submit_icon_image(interaction, attachment)

    @app_commands.command(name="칭호해제", description="달고 있는 칭호를 뗄게요. (코인은 돌려주지 않아요)")
    @restrict_to_channel("title")
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        doc = await title_store.get(interaction.user.id)
        if doc is None:
            await interaction.followup.send("달고 있는 칭호가 없어요.", ephemeral=True)
            return

        await self._destroy_role(doc)
        await title_store.delete(interaction.user.id)
        await interaction.followup.send("칭호를 뗐어요. (코인은 돌려드리지 않아요)", ephemeral=True)

    # ------------------------------------------------------------------
    # 만료 처리
    # ------------------------------------------------------------------
    async def _destroy_role(self, doc: dict):
        guild = self.bot.get_guild(int(doc["guildId"]))
        if guild is None:
            return
        role = guild.get_role(int(doc["roleId"]))
        if role is None:
            return  # 누가 이미 지웠어요
        try:
            await role.delete(reason="칭호 기간 만료")
        except discord.HTTPException:
            log.warning("칭호 역할 삭제 실패 (role=%s)", role.id, exc_info=True)

    @tasks.loop(hours=1)
    async def expire_titles(self):
        for doc in await title_store.expired():
            await self._destroy_role(doc)
            await title_store.delete(doc["_id"])
            log.info("🏷️ 칭호 만료: %s ('%s')", doc["_id"], doc.get("name"))

    @expire_titles.error
    async def _expire_titles_error(self, error: BaseException):
        """🚨 **이게 멈추면 만료된 칭호 역할이 영구히 남아요.** 돈 받고 판 기간제
        상품이라 조용히 안 지워지면 **공짜로 계속 쓰게** 돼요.

        2026-11-01에 루프 11개 중 **3개에 이 핸들러가 없던 걸** 찾아 채웠어요.
        여기선 역할 삭제(`_destroy_role`)가 디스코드 API를 타니 타임아웃·레이트리밋이
        올라올 수 있어요."""
        log.error("🚨 칭호 만료 루프가 멈췄어요 — 다시 켤게요: %r", error, exc_info=error)
        self.expire_titles.restart()

    @expire_titles.before_loop
    async def _before_expire(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(TitleShop(bot))
