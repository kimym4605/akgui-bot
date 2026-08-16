"""
오늘의 피처드 번들(상점 메인에 뜨는 큰 번들) 조회 기능이에요.

⚠️ 이건 "내 계정의 개인 일일 상점(4개 로테이션)"이 아니에요. HenrikDev API는 개인 로그인이
필요한 그 정보는 제공하지 않아요 (라이엇 계정 로그인을 봇에 넣는 건 계정 도용 위험이 있어서
지원하지 않아요). 대신 모두에게 동일하게 보이는 "피처드 번들"만 로그인 없이 가져와요.

HenrikDev의 store-featured 엔드포인트는 라이엇 원본 포맷(아이템 UUID)을 그대로 주기 때문에,
valorant-api.com의 스킨 목록으로 UUID -> 실제 이름/이미지를 매칭해요.
"""
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

HENRIK_BASE = "https://api.henrikdev.xyz"
SKINS_ENDPOINT = "https://valorant-api.com/v1/weapons/skins?language=ko-KR"

# 라이엇 상점 API의 아이템 타입 UUID 상수예요. (커뮤니티에 널리 알려진 고정값)
SKIN_LEVEL_TYPE_ID = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"   # 무기 스킨
SKIN_VARIANT_TYPE_ID = "3ad1b2b2-acdb-4524-852f-954a76ddae0a"  # 스킨 베리언트(크로마)
SPRAY_TYPE_ID = "d5f120f8-ff8c-4aac-92ea-f2b5acbe9475"         # 스프레이
BUDDY_TYPE_ID = "dd3bf334-87f3-40bd-b043-682a57a8dc3a"         # 건 버디
PLAYER_CARD_TYPE_ID = "3f296c07-64c3-494c-923b-fe692a4fa1bd"   # 플레이어 카드
TITLE_TYPE_ID = "de7caa6b-adf7-4588-bbd1-143831e786c6"         # 칭호

ITEM_TYPE_LABELS = {
    SKIN_LEVEL_TYPE_ID: "무기 스킨",
    SKIN_VARIANT_TYPE_ID: "스킨 베리언트",
    SPRAY_TYPE_ID: "스프레이",
    BUDDY_TYPE_ID: "건 버디",
    PLAYER_CARD_TYPE_ID: "플레이어 카드",
    TITLE_TYPE_ID: "칭호",
}


class Store(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.skin_level_lookup: dict[str, dict] = {}  # 스킨 레벨 UUID -> {"name", "icon"}

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        await self._load_skin_lookup()

    async def cog_unload(self):
        if self.session is not None:
            await self.session.close()

    async def _load_skin_lookup(self):
        """스킨 레벨 UUID로 실제 이름/이미지를 찾을 수 있게 미리 캐싱해둬요."""
        try:
            async with self.session.get(SKINS_ENDPOINT) as resp:
                if resp.status != 200:
                    return
                payload = await resp.json()
        except Exception as error:  # noqa: BLE001
            print(f"⚠️ 스킨 목록을 불러오지 못했어요(오늘의번들용): {error}")
            return

        lookup: dict[str, dict] = {}
        for skin in payload.get("data", []):
            name = skin.get("displayName")
            fallback_icon = skin.get("displayIcon")
            for level in skin.get("levels") or []:
                level_uuid = level.get("uuid")
                if level_uuid:
                    lookup[level_uuid] = {
                        "name": name,
                        "icon": level.get("displayIcon") or fallback_icon,
                    }
        self.skin_level_lookup = lookup
        print(f"🛒 오늘의번들용 스킨 매칭 데이터 {len(lookup)}개를 불러왔어요.")

    def _build_bundle_embed(self, bundle: dict) -> discord.Embed:
        items = bundle.get("Items", [])
        remaining_seconds = bundle.get("DurationRemainingInSeconds", 0) or 0
        days = remaining_seconds // 86400
        hours = (remaining_seconds % 86400) // 3600

        embed = discord.Embed(
            title="🛒 오늘의 피처드 번들",
            description=f"⏳ 남은 시간: 약 {days}일 {hours}시간",
            color=0xFF4655,
        )

        total_base = 0
        total_discounted = 0
        lines = []
        thumbnail_set = False

        for entry in items:
            item = entry.get("Item", {})
            item_type_id = item.get("ItemTypeID")
            item_id = item.get("ItemID")
            base_price = entry.get("BasePrice", 0) or 0
            discounted_price = entry.get("DiscountedPrice", base_price)
            total_base += base_price
            total_discounted += discounted_price

            name = "알 수 없는 아이템"
            if item_type_id == SKIN_LEVEL_TYPE_ID:
                info = self.skin_level_lookup.get(item_id)
                if info:
                    name = info["name"]
                    if not thumbnail_set and info.get("icon"):
                        embed.set_thumbnail(url=info["icon"])
                        thumbnail_set = True
                else:
                    name = "무기 스킨 (이름 매칭 실패)"
            else:
                name = ITEM_TYPE_LABELS.get(item_type_id, "기타 아이템")

            price_text = f"{discounted_price:,}VP"
            if discounted_price != base_price:
                price_text += f" ~~{base_price:,}VP~~"
            lines.append(f"• **{name}** — {price_text}")

        embed.add_field(name=f"포함 아이템 ({len(items)}개)", value="\n".join(lines) or "정보 없음", inline=False)

        total_text = f"{total_discounted:,}VP"
        if total_discounted != total_base:
            total_text += f" (정가 {total_base:,}VP)"
        embed.add_field(name="번들 총 가격", value=total_text, inline=False)

        embed.set_footer(text="출처: HenrikDev API (비공식) · 스킨 이미지: valorant-api.com")
        return embed

    @app_commands.command(name="오늘의번들", description="오늘 상점 메인에 떠 있는 피처드 번들을 보여줍니다. (개인 상점 아님)")
    async def featured_bundle(self, interaction: discord.Interaction):
        await interaction.response.defer()

        api_key = os.getenv("HENRIKDEV_API_KEY")
        if not api_key:
            await interaction.followup.send("HENRIKDEV_API_KEY가 설정되지 않았어요. .env 파일을 확인해주세요.")
            return

        headers = {"Authorization": api_key}
        try:
            async with self.session.get(f"{HENRIK_BASE}/valorant/v2/store-featured", headers=headers) as resp:
                status = resp.status
                payload = await resp.json()
        except Exception as error:  # noqa: BLE001
            print(error)
            await interaction.followup.send("피처드 번들 조회 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.")
            return

        if status != 200 or "data" not in payload:
            await interaction.followup.send("피처드 번들 조회에 실패했어요. 잠시 후 다시 시도해주세요.")
            return

        featured = payload["data"].get("FeaturedBundle", {})
        bundles = featured.get("Bundles") or ([featured["Bundle"]] if featured.get("Bundle") else [])

        if not bundles:
            await interaction.followup.send("지금은 진행 중인 피처드 번들이 없어요.")
            return

        embeds = [self._build_bundle_embed(bundle) for bundle in bundles[:5]]
        await interaction.followup.send(embeds=embeds)


async def setup(bot: commands.Bot):
    await bot.add_cog(Store(bot))