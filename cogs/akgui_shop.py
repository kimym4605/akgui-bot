"""`/악귀상점` - 악귀코인을 쓰는 곳을 한 군데로 모았어요.

## 왜 만들었나 (2026-10-05 실측)

코인은 쌓이기만 했어요. `coin_log` 668건 중 **지급 662건 / 소비 6건**, 지갑 57개에 869코인.
소비처가 `/칭호구매`(30코인) 하나뿐인데 **지갑 중앙값이 3코인**이라, 절반 이상은 코인을
쓸 방법이 아예 없었어요. 그래서 지갑 구간별로 품목을 뒀어요.

| 품목 | 가격 | 노리는 구간 |
|---|---|---|
| 🎲 미션 리롤권 | 2코인 (하루 1회) | 중앙값 3코인 — 거의 전원 |
| 🏷️ 칭호 10일권 | 10코인 | 10코인 이상 22명 |
| 🎨 프로필 카드 테마 | 15코인 (영구) | 30코인 이상 10명 |

리롤권은 **싱크로는 약해요**(2코인 내고 1코인짜리 미션을 깨니 순 소모 1코인). 그쪽 역할은
미션 완료율이고, 코인을 실제로 태우는 건 칭호·테마예요.

⚠️ 칭호는 이름·색을 받아야 해서 모달이 필요해요. 그건 `/칭호구매`가 이미 하고 있으니
여기서는 **그 명령어로 안내만** 해요(같은 모달을 두 벌 들고 있으면 한쪽만 고치는 사고가 나요).
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import attend_service, coin_wallet, cosmetic_store, inventory_store, mission_store, riot_account_store
from utils.inventory_store import PROTECT_MAX, PROTECT_PRICE
from utils.mission_store import MISSIONS, REROLL_LIMIT_PER_DAY, REROLL_PRICE
from utils.fish_data import ROD_DURABILITY, ROD_PRICE
from utils.profile_card import THEME_PRICE, THEMES
from utils.title_store import TITLE_DAYS, TITLE_PLANS

log = logging.getLogger(__name__)

# 리롤 실패 사유별 안내. 사유 문자열은 mission_store._reroll_sync가 정해요.
REROLL_ERRORS = {
    "no_doc": "오늘 미션을 아직 안 받았어요. `/미션`을 한 번 쳐주세요.",
    "not_assigned": "그 미션은 오늘 배정된 게 아니에요. `/미션`으로 다시 확인해주세요.",
    "already_done": "이미 깬 미션은 바꿀 수 없어요.",
    "limit": f"리롤은 하루 **{REROLL_LIMIT_PER_DAY}번**까지예요. 내일 다시 올 수 있어요.",
    "exhausted": "바꿀 수 있는 서버 미션이 더 없어요.",
    "race": "방금 다른 처리가 먼저 들어갔어요. 다시 눌러주세요.",
}


def _shop_embed(balance: int, rerolls_left: int, owned: list[str], selected: str,
                protects: int) -> discord.Embed:
    embed = discord.Embed(
        title="🪙 악귀상점",
        description=f"내 악귀코인: **{balance}개**\n`/출석` · `/미션` · `/업적`으로 모아요.",
        color=0xFFC850,
    )
    embed.add_field(
        name=f"🎣 낚시대 — {ROD_PRICE}코인 (하루 1개)",
        value=(
            f"**{ROD_DURABILITY}번** 던질 수 있어요. 다 쓰면 부서져요.\n"
            "　└ 낚시는 낚시대가 있어야 해요 · 꽝 없이 **반드시 물고기가 나와요**\n"
            "　└ 잡은 건 `/어항`에 쌓였다가 `/물고기판매`로 한 번에 팔려요"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"🎲 미션 리롤권 — {REROLL_PRICE}코인",
        value=(
            "오늘 **아직 못 깬 미션 1개**를 다른 서버 미션으로 바꿔요.\n"
            "　└ 발로란트를 안 하는 날 발로 미션이 뽑혔을 때 쓰면 좋아요\n"
            f"　└ 오늘 남은 횟수: **{rerolls_left}/{REROLL_LIMIT_PER_DAY}회**"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"🏷️ 칭호 — {TITLE_PLANS[10]}코인(10일) / {TITLE_PLANS[TITLE_DAYS]}코인({TITLE_DAYS}일)",
        value=(
            "이름과 색을 직접 정하는 나만의 역할이에요.\n"
            "　└ `/칭호구매` 에서 기간을 골라 사요 (기간이 남았을 때 또 사면 이어붙어요)"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"🧊 출석 보호권 — {PROTECT_PRICE}코인",
        value=(
            "하루 빠져도 **연속 출석이 안 끊겨요.** 다음 출석 때 자동으로 쓰여요.\n"
            "　└ 살릴 수 있는 건 **하루치**예요 (이틀 이상 빠지면 못 살려요)\n"
            f"　└ 지금 가진 보호권: **{protects}/{PROTECT_MAX}장**"
        ),
        inline=False,
    )
    owned_extra = [t for t in owned if t != cosmetic_store.DEFAULT_THEME]
    embed.add_field(
        name=f"🎨 프로필 카드 테마 — {THEME_PRICE}코인 (영구)",
        value=(
            f"`/프로필` 카드 배경을 바꿔요. 전체 {len(THEMES)}종.\n"
            f"　└ 지금 쓰는 테마: **{THEMES.get(selected, THEMES['기본'])['emoji']} {selected}**\n"
            f"　└ 가진 테마: {('**' + '** · **'.join(owned_extra) + '**') if owned_extra else '기본만'}"
        ),
        inline=False,
    )
    embed.set_footer(text="아래 버튼으로 바로 쓸 수 있어요. 나에게만 보여요.")
    return embed


class RerollSelect(discord.ui.Select):
    """오늘 못 깬 미션만 골라서 보여줘요."""

    def __init__(self, pending: list[str]):
        options = [
            discord.SelectOption(
                label=MISSIONS[key]["title"],
                value=key,
                description=MISSIONS[key]["desc"][:100],
                emoji="🔫" if MISSIONS[key]["kind"] == "valorant" else "💬",
            )
            for key in pending[:25]
        ]
        super().__init__(placeholder="바꿀 미션을 골라주세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.do_reroll(interaction, self.values[0])  # type: ignore[attr-defined]


class RerollView(discord.ui.View):
    def __init__(self, user_id: int, pending: list[str]):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(RerollSelect(pending))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def do_reroll(self, interaction: discord.Interaction, key: str):
        # ⚠️ 코인부터 빼요. 미션을 먼저 바꾸면 코인이 모자랄 때 공짜 리롤이 돼요.
        if not await coin_wallet.spend(interaction.user.id, REROLL_PRICE, reason="미션리롤"):
            balance = await coin_wallet.get_balance(interaction.user.id)
            await interaction.response.edit_message(
                content=f"악귀코인이 부족해요. 리롤권은 **{REROLL_PRICE}개**가 필요한데 "
                        f"지금 **{balance}개** 갖고 있어요.",
                embed=None, view=None,
            )
            return

        new_key, reason = await mission_store.reroll(interaction.user.id, key)
        if new_key is None:
            # 바꾸지 못했으면 반드시 돌려줘요(실패 사유와 무관하게).
            await coin_wallet.add(interaction.user.id, REROLL_PRICE, reason="미션리롤 실패 환불")
            await interaction.response.edit_message(
                content=f"⚠️ {REROLL_ERRORS.get(reason, '바꾸지 못했어요.')} (코인은 돌려드렸어요)",
                embed=None, view=None,
            )
            return

        balance = await coin_wallet.get_balance(interaction.user.id)
        left = await mission_store.rerolls_left(interaction.user.id)
        await interaction.response.edit_message(
            content=(
                f"🎲 **{MISSIONS[key]['title']}** → **{MISSIONS[new_key]['title']}** 으로 바꿨어요!\n"
                f"　└ {MISSIONS[new_key]['desc']}\n"
                f"사용한 코인 **{REROLL_PRICE}개** (남은 코인 {balance}개) · 오늘 남은 리롤 {left}회"
            ),
            embed=None, view=None,
        )
        log.info("🎲 미션 리롤: %s / %s → %s", interaction.user.id, key, new_key)


class ThemeSelect(discord.ui.Select):
    def __init__(self, owned: list[str], selected: str):
        options = []
        for key, info in THEMES.items():
            has = key in owned
            options.append(discord.SelectOption(
                label=key,
                value=key,
                emoji=info["emoji"],
                default=(key == selected),
                description=(
                    f"{info['desc']} · " + ("보유 중" if has else f"{THEME_PRICE}코인")
                )[:100],
            ))
        super().__init__(placeholder="테마를 골라주세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.pick_theme(interaction, self.values[0])  # type: ignore[attr-defined]


class ThemeView(discord.ui.View):
    def __init__(self, user_id: int, owned: list[str], selected: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(ThemeSelect(owned, selected))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def pick_theme(self, interaction: discord.Interaction, key: str):
        owned = await cosmetic_store.owned_themes(interaction.user.id)

        if key not in owned:
            if not await coin_wallet.spend(interaction.user.id, THEME_PRICE, reason=f"카드테마:{key}"):
                balance = await coin_wallet.get_balance(interaction.user.id)
                await interaction.response.edit_message(
                    content=f"악귀코인이 부족해요. 테마는 **{THEME_PRICE}개**가 필요한데 "
                            f"지금 **{balance}개** 갖고 있어요.",
                    embed=None, view=None,
                )
                return
            # ⚠️ `grant_theme`이 False면 그 찰나에 이미 받은 거예요(중복 결제) → 돌려줘요.
            if not await cosmetic_store.grant_theme(interaction.user.id, key):
                await coin_wallet.add(interaction.user.id, THEME_PRICE, reason="카드테마 중복 환불")
            else:
                log.info("🎨 카드 테마 구매: %s → %s", interaction.user.id, key)

        await cosmetic_store.select_theme(interaction.user.id, key)
        info = THEMES[key]
        balance = await coin_wallet.get_balance(interaction.user.id)
        await interaction.response.edit_message(
            content=(
                f"{info['emoji']} 카드 테마를 **{key}**(으)로 바꿨어요. ({info['desc']})\n"
                f"`/프로필` 을 다시 쳐보면 적용돼 있어요 · 남은 코인 {balance}개"
            ),
            embed=None, view=None,
        )


class ShopView(discord.ui.View):
    def __init__(self, cog: "AkguiShop", user_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "본인 상점만 쓸 수 있어요. `/악귀상점`을 직접 써주세요.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except Exception:  # noqa: BLE001
            pass

    @discord.ui.button(label="낚시대 사기", emoji="🎣", style=discord.ButtonStyle.success)
    async def buy_rod(self, interaction: discord.Interaction, button: discord.ui.Button):
        """🎣 낚시대 - 이 상점의 **첫 소모품**이에요.

        리롤권·보호권·테마는 12일째 0건인데, 그건 전부 '있으면 좋은' 물건이라서예요.
        낚시대는 **없으면 낚시를 아예 못 해요** - 매일 사야 하는 필수품이라 이 상점이
        실제로 쓰이는 첫 계기가 될 거예요.

        ⚠️ 구매 로직은 `cogs/fishing.py`의 `purchase_rod` 하나뿐이에요. 여기서 복사해
        두면 한쪽만 고치는 사고가 나요(지급→차감→실패 시 환불 순서가 핵심이에요)."""
        await interaction.response.defer(ephemeral=True)
        from cogs.fishing import purchase_rod

        _, msg = await purchase_rod(interaction.user.id)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="미션 리롤", emoji="🎲", style=discord.ButtonStyle.primary)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        left = await mission_store.rerolls_left(interaction.user.id)
        if left <= 0:
            await interaction.response.send_message(REROLL_ERRORS["limit"], ephemeral=True)
            return

        # ⚠️ `linked`를 반드시 실제로 확인해요. False로 넘기면, 오늘 미션 문서가 아직
        #    없는 연동자에게 **서버 미션만** 배정돼서 발로 미션을 통째로 잃어요.
        linked = riot_account_store.get_account(interaction.user.id) is not None
        doc = await mission_store.ensure_today(interaction.user.id, linked=linked)
        done = set(doc.get("done") or [])
        pending = [k for k in (doc.get("picks") or []) if k not in done]
        if not pending:
            await interaction.response.send_message(
                "오늘 미션을 전부 깼어요! 바꿀 게 없네요 👏", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"바꿀 미션을 골라주세요. **{REROLL_PRICE}코인**이 들어요.\n"
            "-# 바뀐 미션은 **서버 미션**(통화·명령어) 중에서 무작위로 나와요.",
            view=RerollView(interaction.user.id, pending),
            ephemeral=True,
        )

    @discord.ui.button(label="출석 보호권", emoji="🧊", style=discord.ButtonStyle.primary)
    async def protect(self, interaction: discord.Interaction, button: discord.ui.Button):
        have = await inventory_store.protect_count(interaction.user.id)
        if have >= PROTECT_MAX:
            await interaction.response.send_message(
                f"보호권은 최대 **{PROTECT_MAX}장**까지만 가질 수 있어요. 지금 {have}장 갖고 있어요.\n"
                "-# 쌓아둘 수 있으면 사실상 연속 출석이 무의미해져서 상한을 뒀어요.",
                ephemeral=True,
            )
            return

        # ⚠️ 코인부터 빼요. 지급을 먼저 하면 코인이 모자랄 때 공짜로 받아가요.
        if not await coin_wallet.spend(interaction.user.id, PROTECT_PRICE, reason="출석보호권"):
            balance = await coin_wallet.get_balance(interaction.user.id)
            await interaction.response.send_message(
                f"악귀코인이 부족해요. 보호권은 **{PROTECT_PRICE}개**가 필요한데 "
                f"지금 **{balance}개** 갖고 있어요.",
                ephemeral=True,
            )
            return

        if not await inventory_store.grant_protect(interaction.user.id):
            # 그 찰나에 상한이 찼어요(동시에 두 번 눌렀을 때). 코인은 돌려줘요.
            await coin_wallet.add(interaction.user.id, PROTECT_PRICE, reason="출석보호권 환불")
            await interaction.response.send_message(
                f"보호권이 이미 {PROTECT_MAX}장이에요. 코인은 돌려드렸어요.", ephemeral=True
            )
            return

        have = await inventory_store.protect_count(interaction.user.id)
        balance = await coin_wallet.get_balance(interaction.user.id)
        await interaction.response.send_message(
            f"🧊 출석 보호권을 샀어요. 지금 **{have}장** · 남은 코인 {balance}개\n"
            "-# 하루 빠진 뒤 `/출석`을 하면 **자동으로** 쓰여서 연속이 이어져요.",
            ephemeral=True,
        )
        log.info("🧊 출석 보호권 구매: %s (보유 %d장)", interaction.user.id, have)

    @discord.ui.button(label="카드 테마", emoji="🎨", style=discord.ButtonStyle.secondary)
    async def theme(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await cosmetic_store.get(interaction.user.id)
        await interaction.response.send_message(
            f"테마를 고르면 바로 적용돼요. 안 가진 테마는 고르는 순간 **{THEME_PRICE}코인**이 빠져요.\n"
            "-# 한 번 산 테마는 영구히 남아서 언제든 다시 고를 수 있어요.",
            view=ThemeView(interaction.user.id, state["themes"], state["theme"]),
            ephemeral=True,
        )

    @discord.ui.button(label="칭호 사러 가기", emoji="🏷️", style=discord.ButtonStyle.secondary)
    async def title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"칭호는 `/칭호구매` 에서 사요 (이름·색을 직접 적어야 해서요).\n"
            f"　└ **{TITLE_PLANS[10]}코인 = 10일** · **{TITLE_PLANS[TITLE_DAYS]}코인 = {TITLE_DAYS}일**\n"
            f"-# `기간` 선택지에서 고를 수 있어요. 하루 단가는 {TITLE_DAYS}일권이 더 싸요.",
            ephemeral=True,
        )


class AkguiShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="악귀상점", description="악귀코인으로 미션 리롤권·출석 보호권·칭호·카드 테마를 사요.")
    async def shop(self, interaction: discord.Interaction):
        # 채널 제한을 안 걸었어요. 소비처가 없어서 코인이 쌓이는 게 문제였는데, 여기에
        # "그건 저쪽 채널에서" 를 또 붙이면 안 쓰는 이유를 하나 더 만드는 거예요.
        await interaction.response.defer(ephemeral=True)
        balance = await coin_wallet.get_balance(interaction.user.id)
        left = await mission_store.rerolls_left(interaction.user.id)
        state = await cosmetic_store.get(interaction.user.id)
        protects = await inventory_store.protect_count(interaction.user.id)

        view = ShopView(self, interaction.user.id)
        view.message = await interaction.followup.send(
            embed=_shop_embed(balance, left, state["themes"], state["theme"], protects),
            view=view, ephemeral=True, wait=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AkguiShop(bot))
