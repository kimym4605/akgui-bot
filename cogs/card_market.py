"""🎪 악귀카드 거래장터 - 카드를 코인 가격에 내놓고 사고팔아요.

## 🚨 이건 소비처가 아니에요

코인이 **산 사람 -> 판 사람**으로 옮겨갈 뿐 사라지지 않아요. 🎴 뽑기처럼 소각되는 게
아니에요. 🎲 내전 베팅(파리뮤추얼)을 한동안 "소비처"로 잘못 세던 것과 같은 함정이라
([[project_akgui_shop_coin_sinks]]), 경제 리포트에서 **발행·소각 양쪽에서 빼요.**

수수료를 붙이면 그만큼은 소각이 되는데, 지금은 **수수료 없음**이에요(사용자 결정).

## 명령어

| 명령어 | 하는 일 |
|---|---|
| `/장터등록 카드 가격` | 내 카드를 내놔요 (등록하면 도감에서 바로 빠져요) |
| `/장터` | 매물을 둘러보고 사요 (등급 필터 · 페이지) |
| `/내장터` | 내가 올린 매물을 보고 거둬들여요 |

## 에스크로

등록하면 **그 자리에서 카드를 회수**하고 취소하면 돌려줘요. 팔릴 때만 빼면 같은 카드를
여러 번 등록해두고 전부 팔려서 **없는 카드를 넘겨야 하는** 상태가 생겨요.

## 🚨 동시 구매

둘이 같은 매물을 동시에 사면 둘 다 결제하고 카드는 하나가 돼요. 그래서 결제 전에
**`card_market.claim()`으로 매물을 원자적으로 선점**하고, 이긴 사람만 결제해요.
결제가 실패하면 반드시 `release()`로 되돌려요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import card_market, card_render, card_store, coin_wallet
from utils.card_data import BY_KEY, CARDS
from utils.card_market import MAX_LISTINGS, MAX_PRICE, MIN_PRICE
from utils.card_store import GRADE_COLOR, GRADE_EMOJI, GRADE_ORDER
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

PAGE_SIZE = 8
CHANNEL_GROUP = "card_market"
CHANNEL_ENV = "CARD_MARKET_CHANNEL_ID"

_KEYS_BY_GRADE = {g: [c["key"] for c in cards] for g, cards in CARDS.items()}


def _label(key: str) -> str:
    grade, name = BY_KEY[key]
    return f"{GRADE_EMOJI[grade]} {name}"


def _listing_line(item: dict) -> str:
    grade, name = BY_KEY.get(item["key"], ("일반", item["key"]))
    return (f"{GRADE_EMOJI[grade]} **{name}** · `{item['price']}코인` "
            f"· <@{item['seller']}>")


# ==================================================================
# 둘러보기 + 구매
# ==================================================================
class BuyButton(discord.ui.Button):
    def __init__(self, item: dict, index: int, affordable: bool):
        grade, name = BY_KEY.get(item["key"], ("일반", item["key"]))
        super().__init__(
            label=f"{name} {item['price']}코인",
            emoji=GRADE_EMOJI[grade],
            style=discord.ButtonStyle.success if affordable else discord.ButtonStyle.secondary,
            disabled=not affordable,
            row=1 + index // 2,
        )
        self.item = item

    async def callback(self, interaction: discord.Interaction):
        await self.view.do_buy(interaction, self.item)  # type: ignore[attr-defined]


class MarketView(discord.ui.View):
    """매물 목록. ephemeral이라 DynamicItem이 아니어도 돼요(cogs/card_gacha.py 주석)."""

    def __init__(self, user_id: int, grade: str | None, page: int,
                 items: list[dict], total: int, balance: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.grade = grade
        self.page = page
        self.items = items
        self.total = total
        self.balance = balance
        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    def _build(self):
        self.clear_items()
        pages = max(1, -(-self.total // PAGE_SIZE))
        prev = discord.ui.Button(label="이전", emoji="◀️", disabled=self.page <= 0, row=0)
        nxt = discord.ui.Button(label="다음", emoji="▶️",
                                disabled=self.page >= pages - 1, row=0)
        prev.callback = self._go(-1)
        nxt.callback = self._go(1)
        self.add_item(prev)
        self.add_item(nxt)
        # 🚨 버튼은 한 줄에 5개, 전체 5줄까지예요. 페이지당 8개면 넘치니 2개씩 4줄로 깔아요.
        for i, item in enumerate(self.items):
            self.add_item(BuyButton(item, i, affordable=item["price"] <= self.balance))

    def _go(self, delta: int):
        async def handler(interaction: discord.Interaction):
            await interaction.response.defer()
            await send_market(interaction, self.grade, self.page + delta, edit=True)
        return handler

    async def do_buy(self, interaction: discord.Interaction, item: dict):
        await interaction.response.defer(ephemeral=True)
        await buy_listing(interaction, item["_id"])


async def send_market(interaction: discord.Interaction, grade: str | None,
                      page: int, *, edit: bool = False):
    keys = _KEYS_BY_GRADE.get(grade) if grade else None
    total = await card_market.count_open(keys)
    pages = max(1, -(-total // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    items = await card_market.browse(keys, limit=PAGE_SIZE, skip=page * PAGE_SIZE)
    balance = await coin_wallet.get_balance(interaction.user.id)

    title = "🎪 악귀카드 거래장터" + (f" — {GRADE_EMOJI[grade]} {grade}" if grade else "")
    if not items:
        embed = discord.Embed(
            title=title,
            description=("지금 나와 있는 매물이 없어요.\n"
                         "-# `/장터등록 카드:... 가격:...` 으로 내 카드를 내놓을 수 있어요."),
            color=0xFFC850,
        )
        view = None
    else:
        embed = discord.Embed(
            title=title,
            description="\n".join(_listing_line(i) for i in items),
            color=GRADE_COLOR[grade] if grade else 0xFFC850,
        )
        embed.set_footer(
            text=(f"{page + 1}/{pages} 페이지 · 매물 {total}개 · 내 코인 {balance}개"
                  " · 살 수 있는 것만 버튼이 켜져요")
        )
        view = MarketView(interaction.user.id, grade, page, items, total, balance)

    kwargs = {"embed": embed, "view": view} if view else {"embed": embed}
    if edit:
        await interaction.edit_original_response(**{**kwargs, "view": view})
    else:
        await interaction.followup.send(**kwargs, ephemeral=True)


async def buy_listing(interaction: discord.Interaction, listing_id: str):
    """매물 구매. ⚠️ 부르기 전에 `defer()`가 끝나 있어야 해요."""
    buyer = interaction.user.id

    # 1) 🚨 원자적 선점. 여기서 이긴 사람만 결제로 가요.
    item = await card_market.claim(listing_id, buyer)
    if item is None:
        await interaction.followup.send(
            "이미 팔렸거나 거둬들인 매물이에요. `/장터`로 다시 확인해주세요.", ephemeral=True)
        return

    if str(item["seller"]) == str(buyer):
        await card_market.release(listing_id)
        await interaction.followup.send(
            "내가 올린 매물은 살 수 없어요. 거둬들이려면 `/내장터`를 써주세요.", ephemeral=True)
        return

    price = int(item["price"])
    key = item["key"]
    grade, name = BY_KEY.get(key, ("일반", key))

    # 2) 결제. 실패하면 **반드시 선점을 되돌려요** (안 그러면 매물이 영영 잠겨요).
    try:
        ok, reason = await coin_wallet.transfer(buyer, item["seller"], price,
                                                note=f"장터:{key}")
    except Exception:
        await card_market.release(listing_id)
        log.exception("장터 결제 실패 - 매물을 되돌렸어요 (listing=%s)", listing_id)
        await interaction.followup.send(
            "결제 중 문제가 생겼어요. 코인은 빠져나가지 않았어요.", ephemeral=True)
        return

    if not ok:
        await card_market.release(listing_id)
        balance = await coin_wallet.get_balance(buyer)
        msg = ("악귀코인이 모자라요. "
               f"**{price}코인**인데 지금 **{balance}개** 있어요."
               if reason == "balance" else "구매할 수 없는 매물이에요.")
        await interaction.followup.send(msg, ephemeral=True)
        return

    # 3) 카드 지급. 여기까지 왔으면 결제는 끝났어요.
    try:
        await card_store.give_card(buyer, key)
    except Exception:
        # 돈은 갔는데 카드가 안 간 최악의 경우. 돈을 되돌리고 매물도 풀어줘요.
        log.exception("장터 카드 지급 실패 - 결제를 되돌려요 (listing=%s)", listing_id)
        await coin_wallet.transfer(item["seller"], buyer, price, note=f"장터:환불:{key}")
        await card_market.release(listing_id)
        await interaction.followup.send(
            "카드를 넘기는 데 실패해서 **코인을 돌려드렸어요.** 다시 시도해주세요.",
            ephemeral=True)
        return

    log.info("🎪 장터 거래: %s -> %s %s %d코인", item["seller"], buyer, key, price)

    embed = discord.Embed(
        title=f"{GRADE_EMOJI[grade]} 구매 완료!",
        description=f"**{name}** 을(를) **{price}코인**에 샀어요.",
        color=GRADE_COLOR[grade],
    )
    embed.add_field(name="판매자", value=f"<@{item['seller']}>", inline=True)
    embed.add_field(name="남은 코인",
                    value=f"**{await coin_wallet.get_balance(buyer)}개**", inline=True)
    embed.set_footer(text="/도감 에서 확인할 수 있어요")

    file = None
    path = card_render.card_file_path(key)
    if path is not None:
        file = discord.File(path, filename=f"{key}.webp")
        embed.set_image(url=f"attachment://{key}.webp")

    kwargs = {"embed": embed, "ephemeral": True}
    if file:
        kwargs["file"] = file
    await interaction.followup.send(**kwargs)

    # 판매자에게 알려줘요 (DM이 막혀 있으면 조용히 넘어가요 - 거래는 이미 끝났어요).
    try:
        seller = interaction.client.get_user(int(item["seller"])) or \
            await interaction.client.fetch_user(int(item["seller"]))
        await seller.send(
            f"🎪 장터에 올린 **{name}** 이(가) **{price}코인**에 팔렸어요! "
            f"(구매자: {interaction.user.display_name})")
    except Exception:  # noqa: BLE001
        log.info("판매 알림 DM 실패 (seller=%s)", item["seller"])


class CardMarket(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- 등록 ----------------
    async def _owned_autocomplete(self, interaction: discord.Interaction, current: str):
        """내가 가진 카드만 보여줘요. 디스코드 자동완성은 **25개까지**예요."""
        try:
            counts = await card_store.owned_keys(interaction.user.id)
        except Exception:  # noqa: BLE001
            return []
        cur = (current or "").strip().lower()
        out = []
        for grade in GRADE_ORDER:                     # 높은 등급부터 보여줘요
            for key in _KEYS_BY_GRADE[grade]:
                n = counts.get(key, 0)
                if not n:
                    continue
                name = BY_KEY[key][1]
                if cur and cur not in name.lower():
                    continue
                tail = f" ×{n}" if n > 1 else ""
                out.append(app_commands.Choice(
                    name=f"{grade} · {name}{tail}"[:100], value=key))
                if len(out) >= 25:
                    return out
        return out

    @app_commands.command(name="장터등록", description="내 악귀카드를 장터에 내놔요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    @app_commands.describe(카드="내놓을 카드 (내가 가진 것만 나와요)",
                           가격=f"악귀코인 가격 ({MIN_PRICE}~{MAX_PRICE})")
    @app_commands.autocomplete(카드=_owned_autocomplete)
    async def market_list(
        self, interaction: discord.Interaction, 카드: str,
        가격: app_commands.Range[int, MIN_PRICE, MAX_PRICE],
    ):
        await interaction.response.defer(ephemeral=True)
        key = 카드
        if key not in BY_KEY:
            await interaction.followup.send(
                "그런 카드가 없어요. 목록에서 골라주세요.", ephemeral=True)
            return

        if await card_market.open_count(interaction.user.id) >= MAX_LISTINGS:
            await interaction.followup.send(
                f"한 번에 올릴 수 있는 매물은 **{MAX_LISTINGS}개**까지예요. "
                "`/내장터`에서 일부를 거둬들여주세요.", ephemeral=True)
            return

        # 🚨 카드를 **먼저 회수**해요(에스크로). 등록만 해두고 카드를 들고 있으면
        #    같은 카드를 여러 번 올려서 전부 팔리는 사고가 나요.
        if not await card_store.take_card(interaction.user.id, key):
            await interaction.followup.send(
                f"**{BY_KEY[key][1]}** 을(를) 갖고 있지 않아요. `/도감`에서 확인해주세요.",
                ephemeral=True)
            return

        try:
            await card_market.create(interaction.user.id, key, int(가격))
        except Exception:
            # 등록이 실패하면 회수한 카드를 반드시 돌려줘요.
            await card_store.give_card(interaction.user.id, key)
            log.exception("장터 등록 실패 - 카드를 돌려줬어요 (user=%s key=%s)",
                          interaction.user.id, key)
            await interaction.followup.send(
                "등록에 실패했어요. 카드는 그대로 있어요.", ephemeral=True)
            return

        grade, name = BY_KEY[key]
        embed = discord.Embed(
            title="🎪 장터에 올렸어요",
            description=f"{GRADE_EMOJI[grade]} **{name}** · **{가격}코인**",
            color=GRADE_COLOR[grade],
        )
        embed.set_footer(text="올린 카드는 도감에서 빠져요 · /내장터 에서 거둬들일 수 있어요")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------------- 둘러보기 ----------------
    @app_commands.command(name="장터", description="장터에 나온 악귀카드를 보고 사요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    @app_commands.describe(등급="이 등급만 봐요 (안 고르면 전체)")
    @app_commands.choices(등급=[
        app_commands.Choice(name=f"{GRADE_EMOJI[g]} {g}", value=g) for g in GRADE_ORDER
    ])
    async def market_browse(
        self, interaction: discord.Interaction, 등급: app_commands.Choice[str] | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        await send_market(interaction, 등급.value if 등급 else None, 0)

    # ---------------- 내 매물 ----------------
    @app_commands.command(name="내장터", description="내가 올린 매물을 보고 거둬들여요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def market_mine(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        items = await card_market.mine(interaction.user.id)
        if not items:
            await interaction.followup.send(
                "올려둔 매물이 없어요. `/장터등록` 으로 내놓을 수 있어요.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎪 내가 올린 매물",
            description="\n".join(
                f"{_label(i['key'])} · `{i['price']}코인`" for i in items),
            color=0xFFC850,
        )
        embed.set_footer(text=f"{len(items)}/{MAX_LISTINGS}개 · 아래에서 골라 거둬들일 수 있어요")
        await interaction.followup.send(
            embed=embed, view=MineView(interaction.user.id, items), ephemeral=True)


class CancelSelect(discord.ui.Select):
    def __init__(self, items: list[dict]):
        super().__init__(
            placeholder="거둬들일 매물을 골라주세요",
            options=[
                discord.SelectOption(
                    label=f"{BY_KEY[i['key']][1]} — {i['price']}코인"[:100],
                    value=i["_id"],
                    emoji=GRADE_EMOJI[BY_KEY[i["key"]][0]],
                )
                for i in items[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        await self.view.do_cancel(interaction, self.values[0])  # type: ignore[attr-defined]


class MineView(discord.ui.View):
    def __init__(self, user_id: int, items: list[dict]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.add_item(CancelSelect(items))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def do_cancel(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer(ephemeral=True)
        # 🚨 취소도 **한 번의 update로** 소유자·상태를 확인해요. 조회 후 변경이면
        #    그 사이에 팔려버린 매물을 취소하고 카드까지 돌려주는 사고가 나요.
        item = await card_market.cancel(listing_id, interaction.user.id)
        if item is None:
            await interaction.followup.send(
                "이미 팔렸거나 없는 매물이에요.", ephemeral=True)
            return
        await card_store.give_card(interaction.user.id, item["key"])
        await interaction.followup.send(
            f"🎴 **{BY_KEY[item['key']][1]}** 을(를) 거둬들였어요. 도감에 다시 들어갔어요.",
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CardMarket(bot))
