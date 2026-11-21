"""🖼️ /커스텀테마 — 내가 올린 그림으로 프로필 카드 배경을 만들어요 (2026-11-15).

## 흐름
1. `/커스텀테마 그림:<첨부>` → 그림을 카드 크기로 손질 → **CUSTOM_THEME_PRICE(50코인) 차감** → 대기
2. 🛡️ 방장-매니저(`MANAGER_CHANNEL_ID`)에 미리보기 + ✅승인 / ❌거절 버튼
3. 승인 → '커스텀' 테마 지급·자동 선택 + DM / 거절 → **전액 환불** + 사유 DM

## 🚨 순서: **검사 → 손질 → 차감 → 대기 등록 → 관리방 게시**
돈을 먼저 빼고 그림이 깨져 있으면 환불 경로가 하나 더 생겨요. 실패할 수 있는 건
전부 차감 **앞**에 둬요. 차감 뒤 실패(대기 중복·관리방 게시 실패)는 **반드시 환불**.

## 🚨 승인 버튼은 DynamicItem이에요
심사가 며칠 걸릴 수 있는데 그 사이 배포하면 일반 View 버튼은 죽어요. custom_id에
신청자 id를 박아두고(`akgui:ctheme:approve:<uid>`) 눌린 순간 되살려요.
→ `cogs/card_gacha.py` GachaButton과 같은 방식.

## 🚨 두 매니저가 동시에 눌러도 한 번만
승인·거절 모두 `custom_theme_store`에서 "`pending`이 있을 때만" 원자적으로 바꿔요.
늦게 누른 쪽은 "이미 처리됐어요"를 받아요(환불이 두 번 나가지 않아요).
"""
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from utils import coin_wallet, cosmetic_store, custom_theme_store
from utils.interaction_ack import ack
from utils.profile_card import CUSTOM_THEME_KEY, CUSTOM_THEME_PRICE

log = logging.getLogger(__name__)

MANAGER_CHANNEL_ID = int(os.getenv("MANAGER_CHANNEL_ID") or 0) or None


def _ids(key: str) -> set[int]:
    return {int(v) for v in (os.getenv(key) or "").split(",") if v.strip().isdigit()}


# 승인할 수 있는 사람: 서버 소유자 + 매니저·부방장 역할 (성인인증 심사와 같은 사람들)
REVIEWER_ROLE_IDS = _ids("MANAGER_ROLE_IDS") | _ids("SENIOR_ROLE_IDS")

SPEND_REASON = "커스텀테마:신청"
REFUND_REASON = "커스텀테마 환불"
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def _is_reviewer(interaction: discord.Interaction) -> bool:
    guild, user = interaction.guild, interaction.user
    if guild is None:
        return False
    if user.id == guild.owner_id:
        return True
    roles = {r.id for r in getattr(user, "roles", [])}
    return bool(roles & REVIEWER_ROLE_IDS)


async def _dm(bot: commands.Bot, user_id: int, text: str) -> None:
    """DM이 막혀 있어도 심사는 끝나야 해요 → 실패는 삼켜요."""
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await user.send(text)
    except discord.HTTPException:
        log.info("🖼️ 커스텀 테마 DM 실패 (user=%s) — DM이 막혀 있어요", user_id)


async def _close_review(interaction: discord.Interaction, line: str) -> None:
    """심사 메시지에 결과 한 줄을 붙이고 버튼을 떼요."""
    msg = interaction.message
    if msg is None:
        return
    content = ((msg.content or "") + "\n" + line).strip()[:2000]
    try:
        await msg.edit(content=content, view=None)
    except discord.HTTPException:
        log.warning("🖼️ 심사 메시지 수정 실패 (msg=%s)", msg.id, exc_info=True)


# ------------------------------------------------------------------ 승인 / 거절 버튼
class ReviewButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"akgui:ctheme:(?P<action>approve|reject):(?P<user_id>\d+)",
):
    def __init__(self, action: str, user_id: int):
        approve = action == "approve"
        super().__init__(discord.ui.Button(
            label="승인" if approve else "거절",
            emoji="✅" if approve else "❌",
            style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
            custom_id=f"akgui:ctheme:{action}:{user_id}",
        ))
        self.action = action
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if _is_reviewer(interaction):
            return True
        await interaction.response.send_message(
            "❌ 방장·매니저만 심사할 수 있어요.", ephemeral=True)
        return False

    async def callback(self, interaction: discord.Interaction):
        if self.action == "reject":
            # 🚨 모달은 **첫 응답**이어야 해요(ack 금지).
            await interaction.response.send_modal(RejectModal(self.user_id))
            return
        if not await ack(interaction):
            return
        await approve(interaction, self.user_id)


def review_view(user_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(ReviewButton("approve", user_id))
    view.add_item(ReviewButton("reject", user_id))
    return view


async def approve(interaction: discord.Interaction, user_id: int) -> None:
    if not await custom_theme_store.approve(user_id, interaction.user.id):
        await interaction.followup.send("이미 처리된 신청이에요.", ephemeral=True)
        await _close_review(interaction, "⚠️ 이미 처리된 신청이에요.")
        return
    await cosmetic_store.grant_theme(user_id, CUSTOM_THEME_KEY)   # 재신청이면 이미 있어요(False, 정상)
    await cosmetic_store.select_theme(user_id, CUSTOM_THEME_KEY)
    await _close_review(interaction, f"✅ {interaction.user.mention} 님이 승인했어요.")
    await _dm(interaction.client, user_id,
              "🖼️ 올린 그림이 **승인**됐어요! 프로필 카드 배경으로 바로 적용했어요.\n"
              "-# `/프로필`로 확인해보세요. 다른 테마로 바꿨다가도 `/악귀상점` → 🎨 카드 테마 → "
              "🖼️ **내 그림**으로 언제든 돌아올 수 있어요.")
    log.info("🖼️ 커스텀 테마 승인: user=%s by %s", user_id, interaction.user.id)


class RejectModal(discord.ui.Modal, title="🖼️ 커스텀 테마 거절"):
    reason = discord.ui.TextInput(
        label="거절 사유 (신청자에게 DM으로 가요)",
        placeholder="예) 다른 사람 얼굴이 나온 사진은 안 돼요",
        required=False, max_length=200, style=discord.TextStyle.paragraph,
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        if not await ack(interaction):
            return
        paid = await custom_theme_store.reject(self.user_id)
        if paid < 0:
            await interaction.followup.send("이미 처리된 신청이에요.", ephemeral=True)
            await _close_review(interaction, "⚠️ 이미 처리된 신청이에요.")
            return
        if paid:
            await coin_wallet.add(self.user_id, paid, reason=REFUND_REASON)
        why = str(self.reason).strip()
        await _close_review(
            interaction,
            f"❌ {interaction.user.mention} 님이 거절했어요 · {paid}코인 환불"
            + (f"\n　└ 사유: {why}" if why else ""))
        await _dm(interaction.client, self.user_id,
                  f"🙏 올린 그림이 **거절**됐어요. 낸 **{paid}코인**은 전부 돌려드렸어요."
                  + (f"\n　└ 사유: {why}" if why else "")
                  + "\n-# 다른 그림으로 `/커스텀테마`를 다시 신청할 수 있어요.")
        log.info("🖼️ 커스텀 테마 거절: user=%s by %s (환불 %d)",
                 self.user_id, interaction.user.id, paid)


# ------------------------------------------------------------------ 신청
async def submit(interaction: discord.Interaction, attachment: discord.Attachment) -> None:
    if not await ack(interaction, ephemeral=True, thinking=True):
        return
    uid = interaction.user.id

    async def say(text: str):
        await interaction.followup.send(text, ephemeral=True)

    # ── 1. 돈 빼기 전 검사 ───────────────────────────────────────
    name = (attachment.filename or "").lower()
    if not ((attachment.content_type or "").startswith("image/") or name.endswith(_IMAGE_EXT)):
        await say("그림 파일(PNG·JPG·WEBP)을 첨부해주세요.")
        return
    if attachment.size > custom_theme_store.MAX_UPLOAD_BYTES:
        await say(f"파일이 너무 커요 ({attachment.size / 1024 / 1024:.1f}MB) — 8MB 이하로 올려주세요.")
        return
    if (await custom_theme_store.status(uid))["pending"]:
        await say("⏳ 이미 심사 중인 그림이 있어요. 결과가 나오면 DM으로 알려드려요.")
        return
    channel = interaction.guild.get_channel(MANAGER_CHANNEL_ID) if (
        interaction.guild and MANAGER_CHANNEL_ID) else None
    if channel is None:
        await say("⚠️ 지금은 심사 채널을 찾을 수 없어요. 방장에게 알려주세요. (코인은 안 빠졌어요)")
        return

    try:
        raw = await attachment.read()
        jpeg, top, bottom = await custom_theme_store.prepare(raw)
    except custom_theme_store.BadImage as exc:
        await say(f"⚠️ {exc}")
        return
    except discord.HTTPException:
        await say("⚠️ 첨부를 받아오지 못했어요. 잠시 뒤 다시 해주세요.")
        return

    # ── 2. 차감 ─────────────────────────────────────────────────
    if not await coin_wallet.spend(uid, CUSTOM_THEME_PRICE, reason=SPEND_REASON):
        balance = await coin_wallet.get_balance(uid)
        await say(f"악귀코인이 부족해요. 커스텀 테마는 **{CUSTOM_THEME_PRICE}개**가 필요한데 "
                  f"지금 **{balance}개** 갖고 있어요.")
        return

    # ── 3. 대기 등록 (🚨 여기부터 실패하면 반드시 환불) ─────────────
    if not await custom_theme_store.submit(uid, jpeg, top, bottom, CUSTOM_THEME_PRICE):
        await coin_wallet.add(uid, CUSTOM_THEME_PRICE, reason=REFUND_REASON)
        await say("⏳ 이미 심사 중인 그림이 있어요. 코인은 돌려드렸어요.")
        return

    # ── 4. 관리방 게시 ──────────────────────────────────────────
    try:
        import io
        file = discord.File(io.BytesIO(jpeg), filename="custom_theme.jpg")
        embed = discord.Embed(
            title="🖼️ 커스텀 카드 테마 심사",
            description=(f"{interaction.user.mention} ({interaction.user}) 님이 "
                         f"**{CUSTOM_THEME_PRICE}코인**을 내고 신청했어요.\n"
                         "카드 크기(1000x630)로 잘린 모습이에요. 프로필 카드는 **공개**로 올라가요.\n"
                         "-# 거절하면 코인은 전액 자동 환불돼요."),
            color=0xFFC850,
        )
        embed.set_image(url="attachment://custom_theme.jpg")
        msg = await channel.send(embed=embed, file=file, view=review_view(uid),
                                 allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.warning("🖼️ 심사 메시지 게시 실패 (user=%s)", uid, exc_info=True)
        paid = await custom_theme_store.reject(uid)
        if paid > 0:
            await coin_wallet.add(uid, paid, reason=REFUND_REASON)
        await say("⚠️ 심사 요청을 올리지 못했어요. 코인은 돌려드렸어요. 잠시 뒤 다시 해주세요.")
        return
    await custom_theme_store.set_review_message(uid, channel.id, msg.id)

    await say(f"🖼️ 그림을 보냈어요! **{CUSTOM_THEME_PRICE}코인**이 빠졌고 방장 확인을 기다리는 중이에요.\n"
              "　└ 승인되면 프로필 카드에 **바로 적용**되고 DM으로 알려드려요\n"
              "　└ 거절되면 코인은 **전액 돌려드려요**")
    log.info("🖼️ 커스텀 테마 신청: user=%s (%dKB)", uid, len(jpeg) // 1024)


# ------------------------------------------------------------------ 상점에서 "내 그림" 고르기
async def use_custom(interaction: discord.Interaction) -> None:
    """🎨 카드 테마 화면의 🖼️ 버튼. 승인된 그림이 있으면 그걸로 바꾸고, 없으면 신청 안내."""
    if not await ack(interaction):
        return
    st = await custom_theme_store.status(interaction.user.id)
    if st["has_image"]:
        await cosmetic_store.select_theme(interaction.user.id, CUSTOM_THEME_KEY)
        text = "🖼️ 프로필 카드를 **내 그림** 테마로 바꿨어요. `/프로필`로 확인해보세요."
        if st["pending"]:
            text += "\n-# 새로 올린 그림은 아직 심사 중이에요. 승인되면 자동으로 바뀌어요."
    elif st["pending"]:
        text = "⏳ 올린 그림이 아직 심사 중이에요. 승인되면 DM으로 알려드리고 바로 적용돼요."
    else:
        text = (f"🖼️ **내 그림으로 카드 만들기 — {CUSTOM_THEME_PRICE}코인**\n"
                "`/커스텀테마` 를 치고 `그림` 칸에 이미지를 첨부하세요.\n"
                "　└ 방장이 확인한 뒤 적용돼요 (프로필 카드는 공개라서요)\n"
                "　└ 거절되면 코인은 **전액 환불**\n"
                "　└ 가로로 긴 그림이 잘 맞아요 (1000x630으로 잘려요 · 왼쪽은 글씨 때문에 어둡게 덮여요)")
    await interaction.edit_original_response(content=text, embed=None, view=None)


class CustomTheme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 심사 버튼이 **아무 반응 없이** 죽어요.
        self.bot.add_dynamic_items(ReviewButton)

    @app_commands.command(
        name="커스텀테마",
        description=f"내 그림으로 프로필 카드 배경을 만들어요 ({CUSTOM_THEME_PRICE}코인 · 방장 승인 후 적용).",
    )
    @app_commands.rename(attachment="그림")
    @app_commands.describe(attachment="카드 배경으로 쓸 그림 (PNG·JPG·WEBP, 8MB 이하, 가로로 긴 그림 추천)")
    async def custom_theme(self, interaction: discord.Interaction, attachment: discord.Attachment):
        await submit(interaction, attachment)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomTheme(bot))
