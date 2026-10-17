"""🤝 악귀카드 거래 - **상대를 지목해** 카드를 팔아요.

## 2026-10-18: 공개 장터 → 지목 거래 (사용자 결정)

전에는 `/장터등록`으로 올리면 **아무나 먼저 누른 사람**이 사는 공개 매물이었어요.
12일간 0건이다가 첫 거래(60코인)가 나자마자 "판매자가 상대를 고를 수 없다"는 게
드러나서 바꿨어요. `/장터` `/장터등록` `/내장터`는 **없어졌어요.**

## 🚨 이건 소비처가 아니에요

코인이 **산 사람 -> 판 사람**으로 옮겨갈 뿐 사라지지 않아요. 🎴 뽑기처럼 소각되는 게
아니에요. 🎲 내전 베팅(파리뮤추얼)을 한동안 "소비처"로 잘못 세던 것과 같은 함정이라
([[project_akgui_shop_coin_sinks]]), 경제 리포트에서 **발행·소각 양쪽에서 빼요.**

수수료를 붙이면 그만큼은 소각이 되는데, 지금은 **수수료 없음**이에요(사용자 결정).

## 명령어

| 명령어 | 하는 일 |
|---|---|
| `/카드거래 상대 카드 가격` | 그 사람에게만 거래를 제안해요 (제안하면 도감에서 빠져요) |
| `/거래함` | 나에게 온 제안을 수락/거절하고, 내가 보낸 제안을 취소해요 |

## 에스크로

제안하면 **그 자리에서 카드를 회수**하고 취소·거절되면 돌려줘요. 수락될 때만 빼면
같은 카드를 여러 사람에게 제안해두고 전부 수락돼서 **없는 카드를 넘겨야 하는** 상태가
생겨요.

## 🚨 코인을 받아낸 뒤에 카드를 줘요

순서는 **선점 → 결제 → 카드 지급**이에요(사용자 요구사항). 각 단계가 실패하면
앞 단계를 반드시 되돌려요:
- 결제 실패 → `release()`로 제안을 다시 열어요 (안 하면 카드가 에스크로에 영영 잠겨요)
- 카드 지급 실패 → **코인을 되돌려주고** 제안도 열어요 (돈만 가는 게 최악이에요)

## 🚨 수락과 취소가 겹칠 때

지목 거래라 "둘이 동시에 산다"는 없지만, 수락과 판매자의 취소가 동시에 오면 카드가
**복제**될 수 있어요(구매자에게 주고 판매자에게도 돌려줌). 그래서 수락·거절·취소가
전부 `find_one_and_update` 한 번으로 승자를 정해요. 자세한 건 `utils/card_market.py`.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import card_market, card_render, card_store, coin_wallet
from utils.card_data import BY_KEY, CARDS
from utils.card_market import MAX_OFFERS, MAX_PRICE, MIN_PRICE
from utils.card_store import GRADE_COLOR, GRADE_EMOJI, GRADE_ORDER
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

CHANNEL_GROUP = "card_market"
CHANNEL_ENV = "CARD_MARKET_CHANNEL_ID"

_KEYS_BY_GRADE = {g: [c["key"] for c in cards] for g, cards in CARDS.items()}


def _offer_line(item: dict, *, side: str) -> str:
    """제안 한 줄. `side`가 'in'이면 상대는 판매자, 'out'이면 지목한 사람이에요."""
    grade, name = BY_KEY.get(item["key"], ("일반", item["key"]))
    other = item["seller"] if side == "in" else item["buyer"]
    arrow = "←" if side == "in" else "→"
    return (f"{GRADE_EMOJI[grade]} **{name}** · `{item['price']}코인` "
            f"{arrow} <@{other}>")


# ==================================================================
# 수락 (코인을 받아낸 뒤에 카드를 줘요)
# ==================================================================
async def accept_offer(interaction: discord.Interaction, listing_id: str):
    """제안 수락. ⚠️ 부르기 전에 `defer()`가 끝나 있어야 해요."""
    buyer = interaction.user.id

    # 1) 🚨 원자적 선점. **필터에 buyer가 들어가서** 지목된 사람만 통과해요.
    #    남의 제안 id를 알아내도 여기서 막혀요(권한 검사를 선점과 한 번에).
    item = await card_market.claim(listing_id, buyer)
    if item is None:
        await interaction.followup.send(
            "이미 끝났거나 내게 온 제안이 아니에요. `/거래함`으로 다시 확인해주세요.",
            ephemeral=True)
        return

    price = int(item["price"])
    key = item["key"]
    grade, name = BY_KEY.get(key, ("일반", key))

    # 2) 💰 **코인을 먼저 받아내요.** 실패하면 선점을 되돌려요
    #    (안 그러면 카드가 에스크로에 영영 잠겨요).
    try:
        ok, reason = await coin_wallet.transfer(buyer, item["seller"], price,
                                                note=f"거래:{key}")
    except Exception:
        await card_market.release(listing_id)
        log.exception("🤝 거래 결제 실패 - 제안을 되돌렸어요 (offer=%s)", listing_id)
        await interaction.followup.send(
            "결제 중 문제가 생겼어요. 코인은 빠져나가지 않았어요.", ephemeral=True)
        return

    if not ok:
        await card_market.release(listing_id)
        balance = await coin_wallet.get_balance(buyer)
        msg = ("악귀코인이 모자라요. "
               f"**{price}코인**인데 지금 **{balance}개** 있어요."
               if reason == "balance" else "수락할 수 없는 제안이에요.")
        await interaction.followup.send(msg, ephemeral=True)
        return

    # 3) 🎴 코인을 받아냈으니 카드를 넘겨요.
    try:
        await card_store.give_card(buyer, key)
    except Exception:
        # 돈은 갔는데 카드가 안 간 최악의 경우. 돈을 되돌리고 제안도 풀어줘요.
        log.exception("🤝 거래 카드 지급 실패 - 결제를 되돌려요 (offer=%s)", listing_id)
        await coin_wallet.transfer(item["seller"], buyer, price, note=f"거래:환불:{key}")
        await card_market.release(listing_id)
        await interaction.followup.send(
            "카드를 넘기는 데 실패해서 **코인을 돌려드렸어요.** 다시 시도해주세요.",
            ephemeral=True)
        return

    log.info("🤝 카드 거래: %s -> %s %s %d코인", item["seller"], buyer, key, price)

    embed = discord.Embed(
        title=f"{GRADE_EMOJI[grade]} 거래 완료!",
        description=f"**{name}** 을(를) **{price}코인**에 받았어요.",
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

    await _dm(interaction.client, item["seller"],
              f"🤝 **{name}** 거래가 성사됐어요! **{price}코인**을 받았어요. "
              f"(상대: {interaction.user.display_name})")


async def _dm(client, user_id, text: str) -> bool:
    """DM을 보내요. 막혀 있으면 조용히 False — **거래 성패와 무관**해야 해요.

    🚨 DM 실패로 예외가 올라가면 이미 끝난 거래가 "실패"로 보여요(코인·카드는 이미
    옮겨간 뒤예요). 그래서 여기서 삼켜요."""
    try:
        user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
        await user.send(text)
        return True
    except Exception:  # noqa: BLE001
        log.info("거래 알림 DM 실패 (user=%s)", user_id)
        return False


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

    @app_commands.command(name="카드거래",
                          description="상대를 정해서 내 악귀카드를 팔아요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    @app_commands.describe(상대="이 사람에게만 팔아요",
                           카드="넘길 카드 (내가 가진 것만 나와요)",
                           가격=f"받을 악귀코인 ({MIN_PRICE}~{MAX_PRICE})")
    @app_commands.autocomplete(카드=_owned_autocomplete)
    async def card_trade(
        self, interaction: discord.Interaction, 상대: discord.Member, 카드: str,
        가격: app_commands.Range[int, MIN_PRICE, MAX_PRICE],
    ):
        await interaction.response.defer(ephemeral=True)
        key = 카드
        me = interaction.user.id
        if key not in BY_KEY:
            await interaction.followup.send(
                "그런 카드가 없어요. 목록에서 골라주세요.", ephemeral=True)
            return

        # 🚨 상대 검사를 **카드 회수보다 먼저** 해요. 뒤에 두면 거절당한 제안마다
        #    카드를 뺐다 돌려주는 왕복이 생겨서, 중간에 터지면 카드가 떠버려요.
        if 상대.id == me:
            await interaction.followup.send(
                "나한테는 팔 수 없어요. 상대를 골라주세요.", ephemeral=True)
            return
        if 상대.bot:
            await interaction.followup.send("봇과는 거래할 수 없어요.", ephemeral=True)
            return

        if await card_market.open_count(me) >= MAX_OFFERS:
            await interaction.followup.send(
                f"보낼 수 있는 제안은 한 번에 **{MAX_OFFERS}개**까지예요. "
                "`/거래함`에서 일부를 취소해주세요.", ephemeral=True)
            return

        # 🚨 카드를 **먼저 회수**해요(에스크로). 제안만 해두고 카드를 들고 있으면
        #    같은 카드를 여러 사람에게 제안해서 전부 수락되는 사고가 나요.
        if not await card_store.take_card(me, key):
            await interaction.followup.send(
                f"**{BY_KEY[key][1]}** 을(를) 갖고 있지 않아요. `/도감`에서 확인해주세요.",
                ephemeral=True)
            return

        try:
            await card_market.offer(me, 상대.id, key, int(가격))
        except Exception:
            # 제안이 실패하면 회수한 카드를 반드시 돌려줘요.
            await card_store.give_card(me, key)
            log.exception("🤝 거래 제안 실패 - 카드를 돌려줬어요 (user=%s key=%s)", me, key)
            await interaction.followup.send(
                "제안에 실패했어요. 카드는 그대로 있어요.", ephemeral=True)
            return

        grade, name = BY_KEY[key]
        embed = discord.Embed(
            title="🤝 거래를 제안했어요",
            description=(f"{GRADE_EMOJI[grade]} **{name}** · **{가격}코인**\n"
                         f"상대: {상대.mention}"),
            color=GRADE_COLOR[grade],
        )
        embed.set_footer(
            text="상대가 수락하면 코인을 받고 카드가 넘어가요 · /거래함 에서 취소할 수 있어요")
        await interaction.followup.send(embed=embed, ephemeral=True)

        sent = await _dm(
            interaction.client, 상대.id,
            f"🤝 **{interaction.user.display_name}** 님이 "
            f"**{name}** 을(를) **{가격}코인**에 팔겠다고 제안했어요.\n"
            f"`/거래함` 에서 수락하거나 거절할 수 있어요.")
        if not sent:
            # DM이 막혀 있으면 상대가 제안을 **모를 수 있어요.** 제안은 그대로 두고
            # 판매자에게만 알려줘요(직접 말하면 되니까요).
            await interaction.followup.send(
                "-# ⚠️ 상대에게 DM이 안 갔어요(DM을 막아둔 것 같아요). "
                "제안은 살아있으니 `/거래함`을 확인하라고 말해주세요.", ephemeral=True)

    # ---------------- 거래함 ----------------
    @app_commands.command(name="거래함",
                          description="주고받은 거래 제안을 수락·거절·취소해요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def trade_inbox(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        me = interaction.user.id
        inbox = await card_market.incoming(me)
        outbox = await card_market.outgoing(me)

        if not inbox and not outbox:
            await interaction.followup.send(
                "주고받은 제안이 없어요. `/카드거래 상대:@이름 카드:... 가격:...` "
                "으로 제안할 수 있어요.", ephemeral=True)
            return

        balance = await coin_wallet.get_balance(me)
        embed = discord.Embed(title="🤝 거래함", color=0xFFC850)
        if inbox:
            embed.add_field(
                name=f"📥 나에게 온 제안 {len(inbox)}개",
                value="\n".join(_offer_line(i, side="in") for i in inbox[:10]),
                inline=False)
        if outbox:
            embed.add_field(
                name=f"📤 내가 보낸 제안 {len(outbox)}개",
                value="\n".join(_offer_line(i, side="out") for i in outbox[:10]),
                inline=False)
        embed.set_footer(text=f"내 코인 {balance}개 · 수락하면 코인이 빠지고 카드가 들어와요")
        await interaction.followup.send(
            embed=embed, view=InboxView(me, inbox, outbox), ephemeral=True)


class OfferSelect(discord.ui.Select):
    """제안 하나를 골라 처리해요.

    ⚠️ 받은 제안과 보낸 제안을 **한 Select에 섞지 않아요** — 수락/거절과 취소는
    권한이 반대라, 섞으면 "내가 보낸 걸 수락"하는 입력이 만들어져요."""

    def __init__(self, items: list[dict], *, action: str, row: int):
        self.action = action
        verb = {"accept": "수락할", "decline": "거절할", "cancel": "취소할"}[action]
        super().__init__(
            placeholder=f"{verb} 제안을 골라주세요",
            row=row,
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
        view: "InboxView" = self.view  # type: ignore[assignment]
        await view.handle(interaction, self.action, self.values[0])


class InboxView(discord.ui.View):
    def __init__(self, user_id: int, inbox: list[dict], outbox: list[dict]):
        super().__init__(timeout=300)
        self.user_id = user_id
        row = 0
        if inbox:
            self.add_item(OfferSelect(inbox, action="accept", row=row)); row += 1
            self.add_item(OfferSelect(inbox, action="decline", row=row)); row += 1
        if outbox:
            self.add_item(OfferSelect(outbox, action="cancel", row=row))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def handle(self, interaction: discord.Interaction, action: str, offer_id: str):
        # 🚨 defer가 **DB보다 먼저**예요. Atlas가 느려지면 3초를 넘겨 토큰이 죽어요
        #    (reference_discord_interaction_3s_token).
        await interaction.response.defer(ephemeral=True)
        if action == "accept":
            await accept_offer(interaction, offer_id)
            return
        if action == "decline":
            item = await card_market.decline(offer_id, interaction.user.id)
            if item is None:
                await interaction.followup.send("이미 끝난 제안이에요.", ephemeral=True)
                return
            # 거절하면 카드는 **판매자에게** 돌아가요 (내가 아니라).
            await card_store.give_card(item["seller"], item["key"])
            name = BY_KEY[item["key"]][1]
            await interaction.followup.send(
                f"❌ **{name}** 제안을 거절했어요. 카드는 상대에게 돌아갔어요.",
                ephemeral=True)
            await _dm(interaction.client, item["seller"],
                      f"❌ **{name}** 거래 제안이 거절됐어요. 카드는 돌려받았어요. "
                      f"(상대: {interaction.user.display_name})")
            return

        # cancel — 내가 보낸 제안 거두기
        item = await card_market.cancel(offer_id, interaction.user.id)
        if item is None:
            await interaction.followup.send(
                "이미 수락됐거나 없는 제안이에요.", ephemeral=True)
            return
        await card_store.give_card(interaction.user.id, item["key"])
        await interaction.followup.send(
            f"🎴 **{BY_KEY[item['key']][1]}** 을(를) 거둬들였어요. 도감에 다시 들어갔어요.",
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CardMarket(bot))
