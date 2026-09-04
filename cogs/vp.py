"""
`/vp계산` — 갖고 싶은 스킨 값(목표 VP)을 채우려면 어떤 충전 팩을 어떻게 사는 게 가장 싼지
알려줘요.

발로란트는 VP를 딱 떨어지게 살 수 없어서(475 / 1,000 / 2,050 ... 같은 정해진 팩만 있음),
1,775 VP짜리 스킨 하나 사려고 해도 어떤 조합이 제일 싼지 계산이 필요해요. 팩을 여러 번
살 수 있고 목표를 조금 넘겨 사는 게 더 쌀 때도 있어서, utils/vp_prices.py에서 무한 배낭
방식으로 최소 금액 조합을 찾아요.

⚠️ 가격표는 코드가 아니라 `config/vp_prices.json`에 있어요. 가격이 바뀌면 그 파일만 고치면 돼요.
(`data/`는 Fly 볼륨이 덮어써서 배포한 파일이 서버에 안 보이니 거기 두면 안 돼요.)
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils import riot_auth, riot_session_store, vp_prices

_VP_COLOR = 0xFF4655

# /오상에서 쓰는 것과 같은 VP 통화 UUID예요.
VP_CURRENCY_ID = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"


async def _fetch_my_vp(discord_id: int) -> tuple[int | None, str]:
    """`/오상`에 쿠키를 등록해둔 유저면 현재 보유 VP를 대신 읽어와요.
    (VP, 안내문). 등록을 안 했거나 실패하면 VP는 None이에요."""
    cookie_header = riot_session_store.get_session(discord_id)
    if not cookie_header:
        return None, ""

    wallet, error = await riot_auth.get_wallet_with_cookies(cookie_header)
    if wallet is None:
        return None, f"⚠️ 보유 VP를 못 불러왔어요 ({error}) — 0 VP 기준으로 계산했어요."

    balances = wallet.get("Balances") or {}
    vp = balances.get(VP_CURRENCY_ID)
    if vp is None:
        return None, "⚠️ 보유 VP를 못 불러왔어요 — 0 VP 기준으로 계산했어요."
    return int(vp), ""

# 스킨 등급별 대표 가격이에요. 목표 VP 자리에 숫자 대신 골라 쓸 수 있게 자동완성으로 띄워줘요.
COMMON_PRICES = [
    (875, "디럭스 하위 / 배틀패스류"),
    (1275, "셀렉트 에디션"),
    (1775, "디럭스 에디션"),
    (2175, "프리미엄 에디션"),
    (2475, "프리미엄 상위"),
    (2675, "울트라 에디션"),
    (4950, "엑스클루시브 / 나이프류"),
    (7100, "번들 1개 (대략)"),
]


async def _reply(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed | None = None,
    content: str | None = None,
    ephemeral: bool = False,
):
    """보유 VP를 불러오느라 defer를 했을 수도 있고 안 했을 수도 있어서, 어느 쪽이든
    맞게 응답해줘요. (defer 후엔 response.send_message를 쓸 수 없어요.)"""
    kwargs = {"ephemeral": ephemeral}
    if embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


def _not_configured_embed() -> discord.Embed:
    return discord.Embed(
        title="🧮 VP 계산기",
        description=(
            "아직 **VP 충전 가격표가 등록되지 않았어요.**\n"
            "가격이 지역·시기마다 달라서, 잘못된 금액으로 안내하지 않으려고 값이 없으면 계산을 안 해요.\n\n"
            "-# 관리자: `config/vp_prices.json` 의 `packs` 에 `{\"vp\": 수량, \"price\": 원화}` 를 채워주세요."
        ),
        color=_VP_COLOR,
    )


class VPCalculator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="vp계산",
        description="목표 VP를 채우려면 어떤 충전 팩을 사는 게 가장 싼지 계산해요.",
    )
    @app_commands.describe(
        목표vp="필요한 VP (예: 1775). 자주 쓰는 값은 자동완성으로 떠요.",
        보유vp="지금 갖고 있는 VP. 비워두면 /오상에 쿠키를 등록해둔 분은 자동으로 불러와요.",
    )
    async def vp_calc(self, interaction: discord.Interaction, 목표vp: int, 보유vp: int | None = None):
        table = vp_prices.load()
        packs = table["packs"]
        if not packs:
            await _reply(interaction, embed=_not_configured_embed(), ephemeral=True)
            return

        if 목표vp <= 0:
            await _reply(interaction, content="목표 VP는 1 이상으로 입력해주세요.", ephemeral=True)
            return
        if 보유vp is not None and 보유vp < 0:
            await _reply(interaction, content="보유 VP는 0 이상으로 입력해주세요.", ephemeral=True)
            return

        # 직접 넣은 값이 우선이고, 안 넣었으면 라이엇에서 실제 잔액을 읽어와요(네트워크라 defer 필요).
        note = ""
        auto_loaded = False
        if 보유vp is None:
            await interaction.response.defer()
            보유vp, note = await _fetch_my_vp(interaction.user.id)
            auto_loaded = 보유vp is not None
            if 보유vp is None:
                보유vp = 0

        need = 목표vp - 보유vp
        currency = table["currency"]

        if need <= 0:
            description = (
                f"이미 **{보유vp:,} VP** 를 갖고 계셔서 추가 충전이 필요 없어요!\n"
                f"목표 {목표vp:,} VP · 남는 VP **{보유vp - 목표vp:,} VP**"
            )
            if auto_loaded:
                description += "\n-# 보유 VP는 등록해둔 라이엇 계정에서 불러왔어요."
            embed = discord.Embed(title="🧮 VP 계산기", description=description, color=_VP_COLOR)
            await _reply(interaction, embed=embed)
            return

        # 가격표에서 가장 큰 팩을 아무리 여러 번 사도 못 채우는 경우는 없지만(무한 구매 가능),
        # 목표가 터무니없이 크면 계산 시간이 길어져서 상한을 둬요.
        if need > 100_000:
            await _reply(
                interaction, content="목표 VP가 너무 커요. 100,000 VP 이하로 입력해주세요.", ephemeral=True
            )
            return

        result = vp_prices.cheapest_combo(need, packs)
        if result is None:
            await _reply(
                interaction, content="계산에 실패했어요. 가격표 설정을 확인해주세요.", ephemeral=True
            )
            return

        lines = []
        for pack_vp in sorted(result["counts"], reverse=True):
            count = result["counts"][pack_vp]
            price = next(p["price"] for p in packs if p["vp"] == pack_vp)
            lines.append(f"• **{pack_vp:,} VP** 팩 × {count}개 — {price * count:,}{currency}")

        header = f"목표 **{목표vp:,} VP**"
        if 보유vp:
            header += f" · 보유 {보유vp:,} VP → **{need:,} VP** 더 필요"
        if auto_loaded:
            header += "\n-# 보유 VP는 등록해둔 라이엇 계정에서 불러왔어요."
        if note:
            header += f"\n{note}"

        embed = discord.Embed(title="🧮 VP 계산기", description=header, color=_VP_COLOR)
        embed.add_field(name="가장 싼 조합", value="\n".join(lines), inline=False)
        embed.add_field(name="총 결제 금액", value=f"**{result['cost']:,}{currency}**", inline=True)
        embed.add_field(name="받는 VP", value=f"{result['vp']:,} VP", inline=True)
        embed.add_field(name="남는 VP", value=f"{result['leftover']:,} VP", inline=True)

        unit = result["cost"] / result["vp"]
        footer = f"1 VP당 약 {unit:,.1f}{currency}"
        if table["updated"]:
            footer += f" · 가격표 기준 {table['updated']}"
        embed.set_footer(text=footer)

        await _reply(interaction, embed=embed)

    @vp_calc.autocomplete("목표vp")
    async def target_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        # 유저가 숫자를 직접 치는 중이면 그 값을 그대로 첫 후보로 올려줘요.
        choices = []
        digits = "".join(ch for ch in (current or "") if ch.isdigit())
        if digits:
            value = int(digits[:6])
            if value > 0:
                choices.append(app_commands.Choice(name=f"{value:,} VP", value=value))

        for price, label in COMMON_PRICES:
            if digits and not str(price).startswith(digits):
                continue
            choices.append(app_commands.Choice(name=f"{price:,} VP — {label}", value=price))
        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(VPCalculator(bot))
