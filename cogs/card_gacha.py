"""🎴 악귀카드 - 악귀코인으로 서버 전용 수집 카드를 뽑아요.

## 왜 만들었나

코인이 쌓이기만 했어요. 2026-10-15 실측에서 소각률이 20%였는데 그게 **전부 🎰 도박 몫**이고,
`/악귀상점` 3종(리롤권·보호권·테마)은 열흘째 **0건**이었어요. 구매력은 충분했고(12코인 이상
21명), 문제는 **상점에 진열만 해둔 것**이었어요 -> [[project_akgui_shop_coin_sinks]]

그래서 이 기능은 상점에 기대지 않아요:
  - **`/출석` 응답에 🎴 버튼**을 달아요. 코인이 손에 들어오는 그 순간이 쓸 자리예요.
  - 뽑기 결과에도 "한 번 더" 버튼을 달아요(이어서 돌릴 수 있게).

## 수치 (2026-10-17 사용자 확정)

| 항목 | 값 |
|---|---|
| 가격 | 10코인에 **3장** |
| 확률 | 일반 60 / 레어 30 / 에픽 8.5 / 레전드 1.5 |
| 천장 | 레전드 없이 30장이면 **그 장은 레전드 확정** (= 최악 10뽑기·100코인) |
| 중복 | 일반·레어는 쌓이고, 에픽·레전드는 **가진 걸 풀에서 제외** |

확률과 천장은 `utils/card_store.py`에 있고, **`/카드확률`로 전부 공개**해요. 뽑기는 돈을
받는 기능이라 숨기면 안 돼요(공개해두면 "조작 아니냐"는 분쟁도 같이 막아줘요).

## 🚨 코인 환불

`card_store.pull()`이 `None`(동시 실행에 밀림)이나 `[]`(도감 완성)를 돌려주면 **반드시
코인을 되돌려야** 해요. [[project_akgui_casino]]에서 "게임이 시작 못 하면 코인+한도 둘 다
환불"을 놓쳐 사고를 낸 적이 있어요.

⚠️ `coin_log`의 note를 **`카드뽑기`**로 시작해요. `도박`으로 시작하면 경제 리포트가
베팅액으로 오인해요(`scripts/report_economy.py`).
"""
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import card_render, card_store, coin_wallet
from utils.card_data import CARDS
from utils.card_store import (
    CARDS_PER_PULL,
    GRADE_COLOR,
    GRADE_EMOJI,
    GRADE_ORDER,
    GRADE_WEIGHTS,
    PITY_DRAWS,
    PULL_PRICE,
)
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

COIN_LOG_NOTE = "카드뽑기"


def _rarest(drawn: list[dict]) -> str:
    """이번 뽑기에서 가장 높은 등급. 임베드 색을 정하는 데 써요."""
    for grade in GRADE_ORDER:
        if any(d["grade"] == grade for d in drawn):
            return grade
    return "일반"


def _result_embed(
    drawn: list[dict], balance: int, summary: dict, since_legend: int, counts: dict
) -> discord.Embed:
    best = _rarest(drawn)
    new_count = sum(1 for d in drawn if d["is_new"])

    lines = []
    for d in drawn:
        mark = " 🆕" if d["is_new"] else ""
        pity = " ⭐천장" if d["pity"] else ""
        lines.append(f"{GRADE_EMOJI[d['grade']]} **{d['grade']}** · {d['name']}{mark}{pity}")

    embed = discord.Embed(
        title=f"{GRADE_EMOJI[best]} 카드 {len(drawn)}장을 뽑았어요!",
        description="\n".join(lines),
        color=GRADE_COLOR[best],
    )
    embed.add_field(
        name="도감",
        value=f"**{summary['owned']}/{summary['total']}종** (총 {summary['cards']}장)",
        inline=True,
    )
    embed.add_field(name="새 카드", value=f"**{new_count}장**", inline=True)
    embed.add_field(name="남은 코인", value=f"**{balance}개**", inline=True)

    # 천장까지 몇 장 남았는지 보여줘요. 이게 없으면 천장이 있다는 걸 체감할 수 없어요.
    #
    # ⚠️ 레전드 13종을 다 모은 사람에게는 천장이 발동하지 않아요(줄 카드가 없어요).
    #    그 사람에게 "확정까지 N장"을 띄우면 **지키지 못할 약속**이 돼요.
    if card_store._exhausted("레전드", counts):
        embed.set_footer(text="🟡 레전드를 전부 모으셨어요! · /도감 으로 모은 카드를 봐요")
    else:
        left = max(0, PITY_DRAWS - since_legend)
        embed.set_footer(
            text=(f"🟡 레전드 확정까지 {left}장 남았어요" if left else "🟡 다음 장은 레전드 확정!")
            + " · /도감 으로 모은 카드를 봐요"
        )
    return embed


async def do_pull(interaction: discord.Interaction, *, ephemeral: bool = False):
    """뽑기 1회. `/카드뽑기`와 🎴 버튼이 같이 써요.

    ⚠️ 부르기 전에 `defer()`가 끝나 있어야 해요."""
    user_id = interaction.user.id

    # 1) 코인 먼저 차감. 조건부 update라 잔액이 모자라면 아무것도 안 바뀌어요.
    if not await coin_wallet.spend(user_id, PULL_PRICE, reason=COIN_LOG_NOTE):
        balance = await coin_wallet.get_balance(user_id)
        await interaction.followup.send(
            f"악귀코인이 모자라요. 1뽑기에 **{PULL_PRICE}코인**인데 지금 **{balance}개** 있어요.\n"
            "-# `/출석` · `/미션` · `/업적`으로 모을 수 있어요.",
            ephemeral=True,
        )
        return

    # 2) 뽑기. 실패하면 반드시 환불해요.
    try:
        drawn = await card_store.pull(user_id)
    except Exception:
        await coin_wallet.add(user_id, PULL_PRICE, reason=f"{COIN_LOG_NOTE}:환불")
        log.exception("카드 뽑기 실패 - 코인을 되돌렸어요 (user=%s)", user_id)
        await interaction.followup.send(
            "뽑기 도중 문제가 생겨서 **코인을 돌려드렸어요.** 잠시 후 다시 시도해주세요.",
            ephemeral=True,
        )
        return

    if drawn is None:
        await coin_wallet.add(user_id, PULL_PRICE, reason=f"{COIN_LOG_NOTE}:환불")
        await interaction.followup.send(
            "방금 다른 뽑기가 먼저 처리됐어요. **코인은 돌려드렸으니** 다시 눌러주세요.",
            ephemeral=True,
        )
        return

    if not drawn:
        # 일반·레어가 중복을 허용하는 한 실제로는 안 나오는 경로예요(방어용).
        await coin_wallet.add(user_id, PULL_PRICE, reason=f"{COIN_LOG_NOTE}:환불")
        await interaction.followup.send(
            "🎉 도감을 전부 모으셨어요! 더 드릴 카드가 없어서 **코인은 돌려드렸어요.**",
            ephemeral=True,
        )
        return

    # 3) 결과 그리기
    state = await card_store.get_collection(user_id)
    summary = card_store.summarize(state["counts"])
    balance = await coin_wallet.get_balance(user_id)

    embed = _result_embed(drawn, balance, summary, state["since_legend"], state["counts"])
    view = GachaView(user_id)

    png = await card_render.render_pull(drawn)
    if png is None:
        # 이미지가 실패해도 뽑은 건 이미 들어갔어요. 글자로라도 보여줘요.
        await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)
        return

    file = discord.File(io.BytesIO(png), filename=f"gacha_{user_id}.png")
    embed.set_image(url=f"attachment://gacha_{user_id}.png")
    await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=ephemeral)


# ============================================================
# 🎴 뽑기 버튼
#
# ⚠️ 평범한 View가 아니라 DynamicItem이에요. 보통 View는 **봇이 재시작되면 죽어요** -
# 배포할 때마다 그 전에 띄워둔 `/출석` 메시지의 버튼이 전부 먹통이 돼요(2026-09-29에
# 프로필 카드 버튼이 같은 이유로 죽었어요 -> cogs/attendance.py 주석).
#
# custom_id에 누구 것인지 박아두고 눌린 순간 정규식으로 되살려요.
# ============================================================
class GachaButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"gacha:pull:(?P<user_id>\d+)",
):
    def __init__(self, user_id: int):
        super().__init__(
            discord.ui.Button(
                label=f"카드 뽑기 ({PULL_PRICE}코인)",
                emoji="🎴",
                style=discord.ButtonStyle.primary,
                custom_id=f"gacha:pull:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """남의 출석/뽑기 메시지로 내 코인을 쓰게 되면 헷갈려요. 주인만 눌러요."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "이 버튼은 주인만 누를 수 있어요. `/카드뽑기`로 직접 뽑아주세요.", ephemeral=True
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        log.info("🎴 카드 뽑기 버튼: user=%s", interaction.user.id)
        # 결과를 본인에게만 보여줘요. `/출석` 메시지에 달린 버튼이라 공개로 보내면
        # 출석 채널이 뽑기 결과로 덮여요.
        await interaction.response.defer(ephemeral=True)
        await do_pull(interaction, ephemeral=True)


class GachaView(discord.ui.View):
    """뽑기 버튼 하나짜리 화면. `timeout=None`이라 시간이 지나도 안 죽어요."""

    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(GachaButton(user_id))


def build_gacha_view(user_id: int) -> discord.ui.View:
    """`/출석` 응답에 붙일 버튼. attendance cog가 불러요."""
    return GachaView(user_id)


class CardGacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="카드뽑기",
        description=f"악귀코인 {PULL_PRICE}개로 악귀카드 {CARDS_PER_PULL}장을 뽑아요.",
    )
    @restrict_to_channel("card")
    async def pull_cards(self, interaction: discord.Interaction):
        # DB 왕복 + 이미지 합성이라 3초를 넘겨요.
        await interaction.response.defer()
        await do_pull(interaction)

    @app_commands.command(name="도감", description="내가 모은 악귀카드를 봐요.")
    @restrict_to_channel("card")
    @app_commands.describe(등급="이 등급의 카드 목록만 자세히 봐요 (안 고르면 전체 진행도)")
    @app_commands.choices(등급=[
        app_commands.Choice(name=f"{GRADE_EMOJI[g]} {g}", value=g) for g in GRADE_ORDER
    ])
    async def collection(
        self, interaction: discord.Interaction, 등급: app_commands.Choice[str] | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        state = await card_store.get_collection(interaction.user.id)
        counts = state["counts"]
        summary = card_store.summarize(counts)

        if 등급 is None:
            embed = discord.Embed(
                title="🎴 내 악귀카드 도감",
                description=f"**{summary['owned']}/{summary['total']}종** 보유 · 총 {summary['cards']}장",
                color=0xFFC850,
            )
            for grade in GRADE_ORDER:
                g = summary["per_grade"][grade]
                # 진행바 10칸. 숫자만 있으면 등급 간 비교가 안 와닿아요.
                filled = round(g["owned"] / g["total"] * 10) if g["total"] else 0
                bar = "█" * filled + "░" * (10 - filled)
                note = " · 중복 쌓임" if grade in card_store.DUPE_OK else " · 중복 없음"
                embed.add_field(
                    name=f"{GRADE_EMOJI[grade]} {grade} — {g['owned']}/{g['total']}",
                    value=f"`{bar}`{note}",
                    inline=False,
                )
            left = max(0, PITY_DRAWS - state["since_legend"])
            embed.set_footer(
                text=f"🟡 레전드 확정까지 {left}장 · /도감 등급: 으로 카드 목록을 볼 수 있어요"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        grade = 등급.value
        rows = []
        for card in CARDS[grade]:
            n = counts.get(card["key"], 0)
            if not n:
                rows.append(f"🔒 ||{card['name']}||")
            elif grade in card_store.DUPE_OK and n > 1:
                rows.append(f"✅ **{card['name']}** ×{n}")
            else:
                rows.append(f"✅ **{card['name']}**")

        g = summary["per_grade"][grade]
        embed = discord.Embed(
            title=f"{GRADE_EMOJI[grade]} {grade} — {g['owned']}/{g['total']}",
            # 한 줄에 다 넣으면 25필드 한도에 걸려요. 설명 하나에 몰아넣어요.
            description="\n".join(rows),
            color=GRADE_COLOR[grade],
        )
        embed.set_footer(text="🔒 는 아직 없는 카드예요 (이름은 가려뒀어요)")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="카드확률", description="악귀카드 뽑기의 확률과 천장을 공개해요.")
    @restrict_to_channel("card")
    async def rates(self, interaction: discord.Interaction):
        total_w = sum(GRADE_WEIGHTS.values())
        lines = []
        for grade in GRADE_ORDER:
            pct = GRADE_WEIGHTS[grade] / total_w * 100
            n = len(CARDS[grade])
            rule = "중복 나옴" if grade in card_store.DUPE_OK else "**가진 카드는 제외**"
            lines.append(f"{GRADE_EMOJI[grade]} **{grade}** — {pct:.1f}% · {n}종 · {rule}")

        embed = discord.Embed(
            title="🎴 악귀카드 뽑기 확률",
            description="\n".join(lines),
            color=0xFFC850,
        )
        embed.add_field(
            name="가격",
            value=f"**{PULL_PRICE}코인**에 **{CARDS_PER_PULL}장** (장당 {PULL_PRICE/CARDS_PER_PULL:.1f}코인)",
            inline=False,
        )
        embed.add_field(
            name="🟡 천장",
            value=(
                f"레전드 없이 **{PITY_DRAWS}장**을 뽑으면 그 장은 **레전드 확정**이에요.\n"
                f"　└ 최악의 경우라도 **{-(-PITY_DRAWS // CARDS_PER_PULL)}뽑기"
                f"({-(-PITY_DRAWS // CARDS_PER_PULL) * PULL_PRICE}코인)** 안에 레전드가 나와요"
            ),
            inline=False,
        )
        embed.add_field(
            name="이미 다 모은 등급이 또 나오면?",
            value="그 등급을 빼고 **다시 뽑아요.** 헛돈이 되지 않아요.",
            inline=False,
        )
        # DB를 안 건드려서 defer 없이 바로 답해도 3초를 안 넘겨요.
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CardGacha(bot))
    # ⚠️ 이 등록이 없으면 🎴 버튼을 눌러도 봇이 custom_id를 알아보지 못해서 무반응이에요.
    bot.add_dynamic_items(GachaButton)
