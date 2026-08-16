from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

# valorant-api.com : 로그인/인증 없이 쓸 수 있는 비공식 발로란트 정적 데이터 API
# 최신 응답 필드는 https://dash.valorant-api.com 에서 확인할 수 있어요.
SKINS_ENDPOINT = "https://valorant-api.com/v1/weapons/skins?language=ko-KR"

# ============================================================
# 커뮤니티 별명 매핑표
# ------------------------------------------------------------
# 발로란트 공식 API엔 "엑소", "혼서" 같은 커뮤니티 줄임말/은어가 없어서,
# 여기 직접 매핑을 추가해두면 그 별명으로 검색해도 실제 스킨이 나와요.
# 형식: "별명": "실제 스킨/시리즈 이름에 포함된 키워드"
# (별명은 몇 글자만 쳐도 매칭돼요. 예: "엑소" 등록해두면 "엑"만 쳐도 후보에 떠요)
#
# ⚠️ 최신 은어를 다 알진 못해서 우선 확인된 것만 넣어뒀어요. 새로 추가하고 싶으면
#    아래 딕셔너리에 "별명": "실제 이름 키워드" 한 줄만 추가하면 바로 반영돼요.
# ============================================================
SKIN_ALIASES = {
    "엑소": ".EX",
    "혼서": "혼돈의 서막",
    "혼돈서막": "혼돈의 서막",
}


class Skin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.skins_cache: list[dict] = []  # 스킨 이름 자동완성/검색에 쓰는 캐시예요.

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        await self._refresh_skin_cache()

    async def cog_unload(self):
        if self.session is not None:
            await self.session.close()

    async def _refresh_skin_cache(self):
        """스킨 전체 목록을 받아서 캐싱해둬요. 매번 API를 새로 부르지 않으려고요."""
        try:
            async with self.session.get(SKINS_ENDPOINT) as resp:
                if resp.status != 200:
                    return
                payload = await resp.json()
        except Exception as error:  # noqa: BLE001
            print(f"⚠️ 스킨 목록을 불러오지 못했어요: {error}")
            return

        skins = payload.get("data", [])
        # 이름이 없는 항목(기본 스킨 등)은 검색 대상에서 빼요.
        self.skins_cache = [s for s in skins if s.get("displayName")]
        print(f"🔫 스킨 {len(self.skins_cache)}개를 불러왔어요.")

    def _find_matches(self, raw_keyword: str) -> list[dict]:
        """스킨 이름에 직접 포함되는 것 + 별명 매핑을 통해 찾은 것을 합쳐서 반환해요."""
        keyword = raw_keyword.lower().strip()
        if not keyword:
            return self.skins_cache

        matches: list[dict] = []
        seen_uuids: set[str] = set()

        # 1) 스킨 이름에 입력값이 그대로 포함되는 경우
        for s in self.skins_cache:
            if keyword in s["displayName"].lower():
                matches.append(s)
                seen_uuids.add(s["uuid"])

        # 2) 별명(SKIN_ALIASES)에 매칭되는 경우 - 별명의 일부만 쳐도 걸리게 했어요.
        for alias, mapped_keyword in SKIN_ALIASES.items():
            alias_lower = alias.lower()
            if keyword in alias_lower:
                for s in self.skins_cache:
                    if s["uuid"] in seen_uuids:
                        continue
                    if mapped_keyword.lower() in s["displayName"].lower():
                        matches.append(s)
                        seen_uuids.add(s["uuid"])

        return matches

    async def skin_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """이름을 입력하는 동안 후보 목록을 실시간으로 보여줘요. (캐시에서 바로 필터링해서 빨라요)"""
        candidates = self._find_matches(current)
        return [app_commands.Choice(name=s["displayName"], value=s["displayName"]) for s in candidates[:25]]

    @app_commands.command(name="스킨검색", description="발로란트 무기 스킨을 검색합니다. (입력하면 후보가 자동으로 떠요)")
    @app_commands.describe(이름="검색할 스킨 이름 - 입력하면 뜨는 자동완성 목록에서 골라도 돼요")
    @app_commands.autocomplete(이름=skin_autocomplete)
    async def skin_search(self, interaction: discord.Interaction, 이름: str):
        await interaction.response.defer()

        if not self.skins_cache:
            # 봇 켜질 때 캐싱이 실패했을 경우를 대비한 안전장치예요.
            await self._refresh_skin_cache()
        if not self.skins_cache:
            await interaction.followup.send("스킨 정보를 불러오는 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.")
            return

        keyword = 이름.lower()
        matches = self._find_matches(이름)

        if not matches:
            await interaction.followup.send(f'"{이름}"(으)로 검색된 스킨이 없어요.')
            return

        # 자동완성 목록에서 정확히 골랐으면 그 스킨을, 아니면 첫 번째 검색 결과를 보여줘요.
        skin = next((s for s in matches if s["displayName"].lower() == keyword), matches[0])

        image = (
            skin.get("displayIcon")
            or (skin.get("chromas") or [{}])[0].get("fullRender")
            or (skin.get("levels") or [{}])[0].get("displayIcon")
        )

        embed = discord.Embed(title=skin["displayName"], color=0xFF4655)
        embed.set_footer(text=f"검색 결과 {len(matches)}개 중 표시 · 출처: valorant-api.com")
        if image:
            embed.set_image(url=image)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Skin(bot))