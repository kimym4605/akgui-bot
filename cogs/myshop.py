"""
"내 계정의 개인 오늘의 상점"(로그인 필요, 4개 로테이션)을 보여주는 기능이에요.

⚠️⚠️ 중요 ⚠️⚠️
처음엔 봇이 직접 아이디/비밀번호를 받아 라이엇 로그인을 흉내내는 방식으로 만들었는데,
라이엇 로그인 폼이 클라우드플레어 봇 탐지 + hCaptcha로 보호되어 있어서 자동화된 로그인
시도는 자격증명이 맞아도 항상 거부당했어요(2026-08-27 확인). 이 보호를 우회하는 자동화는
하지 않기로 했어요.

그래서 지금은: 유저가 실제 브라우저에서 라이엇 공식 로그인 페이지를 직접 열어 로그인
(hCaptcha도 본인이 직접 통과)하고, 로그인 후 나오는 주소창 URL을 복사해서 붙여넣으면
그 URL 안의 토큰만 꺼내 써요. 비밀번호는 이 봇 서버에 전혀 남지 않아요.
매번 로그인하는 게 번거로운 유저를 위해, 선택적으로 세션 쿠키(ssid)를 직접 복사해서
등록해두면 당분간(쿠키 자체 만료 전까지, 대략 한 달 정도) 로그인 없이 바로 /오상을
쓸 수 있어요. 이 쿠키는 utils/riot_session_store.py에서 암호화해서 저장해요.

설정 방법 (.env):
  VALORANT_SHOP_CHANNEL_ID=발로란트-상점_채널ID   ← 없으면 채널 제한 없이 아무 채널에서나 동작해요.
"""
import datetime
import os
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import riot_auth, riot_session_store, valorant_skins

KST = ZoneInfo("Asia/Seoul")


def _get_shop_channel_id() -> int | None:
    raw = os.getenv("VALORANT_SHOP_CHANNEL_ID")
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def require_shop_channel():
    """이 데코레이터를 붙인 명령어는 VALORANT_SHOP_CHANNEL_ID로 지정한 채널에서만
    쓸 수 있어요. 설정 안 했으면 제한 없이 아무 채널에서나 동작해요."""

    async def predicate(interaction: discord.Interaction) -> bool:
        channel_id = _get_shop_channel_id()
        if channel_id is None or interaction.channel_id == channel_id:
            return True

        await interaction.response.send_message(
            f"이 명령어는 <#{channel_id}> 채널에서만 사용할 수 있어요.", ephemeral=True
        )
        return False

    return app_commands.check(predicate)
# 발로란트 상점은 매일 자정 전후로 갱신돼요. 그 전에 미리 한 번 등록된 유저 전원의
# 쿠키를 재인증해서 저장해두면(SkinPeek류 봇과 동일한 방식) 쿠키 자체 만료(대략 1~3주) 전에
# 계속 갱신되니까, 한 번 등록만 해두면 사실상 다시 로그인할 일이 없어져요.
SESSION_REFRESH_TIME = datetime.time(hour=4, minute=0, tzinfo=KST)

LOGIN_URL = (
    "https://auth.riotgames.com/authorize"
    "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
    "&client_id=play-valorant-web-prod"
    "&response_type=token%20id_token"
    "&scope=openid%20account"
    "&nonce=1"
)

VP_CURRENCY_ID = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"


def _format_remaining(seconds: int) -> str:
    seconds = max(0, seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}시간 {minutes}분 후 갱신"


_DEFAULT_TIER_COLOR = 0x555555


def _build_shop_embeds(user: discord.abc.User, storefront: dict, riot_id: str = "") -> list[discord.Embed]:
    """제트봇 스타일: 헤더 임베드 1개 + 스킨마다 등급색 테두리 임베드(작은 썸네일)로 구성해요."""
    panel = storefront.get("SkinsPanelLayout", {})
    offer_ids = panel.get("SingleItemOffers", [])
    remaining = panel.get("SingleItemOffersRemainingDurationInSeconds", 0)

    offers_by_id = {}
    for offer in panel.get("SingleItemStoreOffers", []):
        for reward in offer.get("Rewards", []):
            offers_by_id[reward.get("ItemID")] = offer

    header = discord.Embed(
        description=f"**{riot_id or user.display_name}** | ⏳ {_format_remaining(remaining)}",
        color=0xFF4655,
    )
    header.set_author(name="🔫 오상 · 오늘의 상점", icon_url=user.display_avatar.url)
    embeds = [header]

    for item_id in offer_ids:
        info = valorant_skins.get(item_id)
        offer = offers_by_id.get(item_id)
        cost = 0
        if offer:
            cost_map = offer.get("Cost", {})
            cost = cost_map.get(VP_CURRENCY_ID) or (next(iter(cost_map.values())) if cost_map else 0)

        name = info["name"] if info else "알 수 없는 스킨"
        color = (info.get("tier_color") if info else None) or _DEFAULT_TIER_COLOR

        item_embed = discord.Embed(title=name, description=f"💠 {cost:,} VP", color=color)
        if info and info.get("icon"):
            item_embed.set_thumbnail(url=info["icon"])
        embeds.append(item_embed)

    if not offer_ids:
        header.description += "\n오늘 로테이션된 아이템 정보를 못 받아왔어요."

    return embeds


async def _send_shop(interaction: discord.Interaction, session, access_token: str, id_token: str) -> bool:
    """access_token/id_token으로 상점까지 조회해서 채널에 공개로 올려요. 성공하면 True."""
    region = await riot_auth.get_region(session, access_token, id_token)
    if not region:
        await interaction.followup.send("라이엇 서버 지역 확인에 실패했어요. 다시 시도해주세요.", ephemeral=True)
        return False

    puuid = riot_auth.puuid_from_access_token(access_token)
    if not puuid:
        await interaction.followup.send("로그인 정보를 읽지 못했어요. 다시 시도해주세요.", ephemeral=True)
        return False

    entitlement = await riot_auth.get_entitlement(session, access_token)
    if not entitlement:
        await interaction.followup.send("라이엇 서버에서 권한 토큰을 못 받았어요. 잠시 후 다시 시도해주세요.", ephemeral=True)
        return False

    storefront = await riot_auth.get_storefront(
        session, access_token=access_token, entitlement=entitlement, region=region, puuid=puuid
    )
    if storefront is None:
        await interaction.followup.send("상점 정보를 못 받아왔어요. 잠시 후 다시 시도해주세요.", ephemeral=True)
        return False

    if not valorant_skins.is_loaded():
        # valorant-api.com은 로그인이 필요 없는 공개 API라 별도의 임시 세션을 써요.
        async with aiohttp.ClientSession() as skin_session:
            await valorant_skins.load(skin_session)

    riot_id = riot_auth.riot_id_from_id_token(id_token) or ""
    # 결과는 제트봇처럼 채널에 공개로 올려요(로그인 과정 자체만 본인만 보이게 처리).
    await interaction.followup.send(embeds=_build_shop_embeds(interaction.user, storefront, riot_id), ephemeral=False)
    return True


class PasteUrlModal(discord.ui.Modal, title="🔫 오상 · URL 붙여넣기"):
    url_input = discord.ui.TextInput(
        label="로그인 후 나온 주소창 URL 전체",
        style=discord.TextStyle.paragraph,
        placeholder="https://playvalorant.com/.../opt_in/#access_token=...",
        max_length=4000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 디스코드 특성상 ephemeral로 defer하면 이후 followup도 전부 ephemeral로 고정돼요.
        # 성공 시엔 채널에 공개로 보여줘야 해서, 공개로 defer하고 실패 메시지만 개별적으로 ephemeral 처리해요.
        await interaction.response.defer(ephemeral=False)

        parsed = riot_auth.parse_redirect_url(self.url_input.value.strip())
        if not parsed:
            await interaction.followup.send(
                "❌ URL에서 로그인 정보를 못 찾았어요. 로그인 완료 후 나온 주소창 URL 전체를 다시 복사해서 붙여넣어주세요.",
                ephemeral=True,
            )
            return
        access_token, id_token = parsed

        session = riot_auth.new_session()
        try:
            await _send_shop(interaction, session, access_token, id_token)
        finally:
            await session.close()

    async def on_error(self, interaction: discord.Interaction, error: Exception):  # noqa: D401
        print(f"⚠️ 오상 처리 중 오류: {error}")
        if interaction.response.is_done():
            await interaction.followup.send("처리 중 오류가 발생했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("처리 중 오류가 발생했어요.", ephemeral=True)


class RegisterCookieModal(discord.ui.Modal, title="🔫 오상 · 쿠키 등록(선택)"):
    cookie_input = discord.ui.TextInput(
        label="Cookie 요청 헤더 전체",
        style=discord.TextStyle.paragraph,
        placeholder="F12 > Network 탭 > auth.riotgames.com 요청 아무거나 클릭 > Request Headers의 cookie 값 전체 복사",
        max_length=4000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        cookie_header = self.cookie_input.value.strip()
        result, session = await riot_auth.reauth_with_cookies(cookie_header)
        if not result.ok:
            await session.close()
            await interaction.followup.send(
                f"❌ {result.error or '등록에 실패했어요.'} Cookie 값을 다시 확인해서 시도해주세요.", ephemeral=True
            )
            return

        try:
            ok = await _send_shop(interaction, session, result.access_token, result.id_token)
        finally:
            await session.close()

        if ok:
            riot_session_store.save_session(interaction.user.id, cookie_header)
            await interaction.followup.send(
                "✅ 쿠키가 등록됐어요. 이제부터는 로그인 없이 `/오상`만 실행하면 돼요(약 한 달간, 만료되면 다시 등록).",
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):  # noqa: D401
        print(f"⚠️ 오상 쿠키 등록 중 오류: {error}")
        if interaction.response.is_done():
            await interaction.followup.send("처리 중 오류가 발생했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("처리 중 오류가 발생했어요.", ephemeral=True)


class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(discord.ui.Button(label="① 라이엇 로그인하기", style=discord.ButtonStyle.link, url=LOGIN_URL))

    @discord.ui.button(label="② 로그인 후 URL 붙여넣기", style=discord.ButtonStyle.primary)
    async def paste_url(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PasteUrlModal())

    @discord.ui.button(label="③ 쿠키 등록(선택, ~1달 자동)", style=discord.ButtonStyle.secondary)
    async def register_cookie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterCookieModal())


class MyShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.refresh_sessions.start()

    def cog_unload(self):
        self.refresh_sessions.cancel()

    @tasks.loop(time=SESSION_REFRESH_TIME)
    async def refresh_sessions(self):
        refreshed, expired = await riot_auth.refresh_all_stored_sessions()
        if refreshed or expired:
            print(f"🔫 오상 세션 자동 재인증: 갱신 {refreshed}건, 만료(재로그인 필요) {expired}건")

    @refresh_sessions.before_loop
    async def before_refresh_sessions(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="오상",
        description="⚠️본인 라이엇 계정으로 로그인해서 개인 오늘의 상점(4개 로테이션)을 봐요.",
    )
    @require_shop_channel()
    async def my_shop(self, interaction: discord.Interaction):
        cookie_header = riot_session_store.get_session(interaction.user.id)
        if cookie_header:
            await interaction.response.defer(ephemeral=False)
            result, session = await riot_auth.reauth_with_cookies(cookie_header)
            try:
                if not result.ok:
                    riot_session_store.delete_session(interaction.user.id)
                    await interaction.followup.send(
                        "등록해둔 로그인이 만료됐어요. `/오상`으로 다시 로그인(또는 쿠키 재등록)해주세요.",
                        ephemeral=True,
                    )
                    return
                await _send_shop(interaction, session, result.access_token, result.id_token)
            finally:
                await session.close()
            return

        embed = discord.Embed(
            title="🔫 오상 · 오늘의 상점 확인하기",
            description=(
                "① 아래 **라이엇 로그인하기** 버튼으로 실제 로그인 페이지를 열어 직접 로그인해주세요.\n"
                "② 로그인 완료 후 뜨는 흰 화면(playvalorant.com...) **주소창 URL 전체**를 복사하세요.\n"
                "③ **② 로그인 후 URL 붙여넣기** 버튼을 눌러 그 URL을 붙여넣으면 바로 오늘의 상점을 보여드려요.\n\n"
                "-# 매번 로그인하기 번거로우면 **③ 쿠키 등록**으로 한 번만 등록해두세요(약 한 달간 로그인 없이 바로 조회 가능).\n"
                "-# 비밀번호는 저장하지 않고 그 자리에서만 써요."
            ),
            color=0xFF4655,
        )
        await interaction.response.send_message(embed=embed, view=StartView(), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MyShop(bot))
