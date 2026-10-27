"""`/악귀상점` + 🪙 **상설 패널** - 악귀코인을 쓰는 곳을 한 군데로 모았어요.

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

## 🪙 상설 패널 (2026-10-27)

🔴 **리롤권·보호권·테마는 22일째 0건이에요.** 10-06 · 10-15 · 10-27 세 번 재봤어요.
구매력 문제가 아니에요 — 그때도 살 수 있는 사람이 수십 명이었고, 같은 날 만든
🔓 한도 연장권은 팔렸어요. 차이는 **막힌 그 자리에서 파는가**였어요.
`/악귀상점`은 **"있는 줄 알고 쳐야" 열려요.** 즉 문턱이 품목이 아니라 **명령어**예요.
→ [[feedback_pickup_plaintext_not_slash_command]]가 💡건의·📅일정·❓매니저에서 같은
   진단을 세 번 찍었어요(슬래시 명령어가 문턱이었다).

그래서 **상점을 방 하나에 꺼내 놓고** 가격표가 늘 보이게 했어요(`ShopPanelView`).
명령어를 몰라도 눈에 들어오고, 누르면 그 자리에서 사져요.
📌 **며칠 뒤 `coin_log`의 `note`로 재볼 것** — `미션리롤` · `출석보호권` · `카드테마:*`
   건수가 0에서 움직이면 진단이 맞은 거예요. 안 움직이면 남은 건 **동기**라서,
   그때는 진열이 아니라 품목 자체를 손봐야 해요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import (
    adult_check, attend_service, coin_wallet, cosmetic_store, inventory_store,
    mission_store, riot_account_store,
)
from utils.interaction_ack import ack
from utils.inventory_store import PROTECT_MAX, PROTECT_PRICE
from utils.mission_store import MISSIONS, REROLL_LIMIT_PER_DAY, REROLL_PRICE
from utils.fish_data import (
    DAILY_CAST_CAP, ROD_DURABILITY, ROD_PRICE, SMALL_ROD_DURABILITY,
    SMALL_ROD_PRICE,
)
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


def _item_fields(state: dict | None = None) -> list[tuple[str, str]]:
    """품목 설명 — **진열장 한 벌**이에요.

    `/악귀상점`(본인만 보임)과 🪙 상설 패널(공개)이 둘 다 이걸 써요.
    🚨 **설명·가격을 두 벌 들고 있으면 안 돼요.** 실제로 "(하루 1개)" 라벨이
       한쪽에만 남아서, 제한이 풀린 뒤에도 10명이 88개를 산 뒤까지 거짓으로
       떠 있었어요(2026-10-17).
    🚨 그래서 **숫자를 손으로 적지 않아요** — 상수를 그대로 끼워 넣어서
       `ROD_PRICE`·`DAILY_CAST_CAP` 같은 값만 바꾸면 안내문이 따라와요.

    `state`를 주면 그 사람의 보유·남은 횟수 줄을 덧붙여요. **안 주면 빼요** —
    공개 패널은 봇 전체에 메시지가 하나뿐이라, 누구의 값을 적어도 나머지
    전원에게는 거짓이 돼요.
    """
    fields: list[tuple[str, str]] = []

    fields.append((
        f"🎣 낚시대 — {ROD_PRICE}코인 / 🪝 소형 — {SMALL_ROD_PRICE}코인",
        f"**{ROD_DURABILITY}번** 던질 수 있어요. 다 쓰면 부서져요.\n"
        f"　└ 🪝 **소형**은 {SMALL_ROD_PRICE}코인에 **{SMALL_ROD_DURABILITY}번** — "
        "횟수당 값이 **똑같아요.** 코인이 적을 때 시작용이에요\n"
        "　└ 낚시는 낚시대가 있어야 해요 · 꽝 없이 **반드시 물고기가 나와요**\n"
        + (f"　└ ⏳ 던지는 건 **하루 {DAILY_CAST_CAP}번**까지예요 "
           "(낚시대 개수는 제한 없어요 · 남은 횟수는 다음 날로 넘어가요)\n"
           if DAILY_CAST_CAP else
           "　└ **몇 개든** 살 수 있어요 (하루 제한 없어요)\n")
        + "　└ 잡은 건 `/어항`에 쌓였다가 `/물고기판매`로 한 번에 팔려요",
    ))

    reroll = (
        "오늘 **아직 못 깬 미션 1개**를 다른 서버 미션으로 바꿔요.\n"
        "　└ 발로란트를 안 하는 날 발로 미션이 뽑혔을 때 쓰면 좋아요\n"
        f"　└ 하루 **{REROLL_LIMIT_PER_DAY}번**까지 쓸 수 있어요"
    )
    if state:
        reroll += (f"\n　└ 오늘 남은 횟수: "
                   f"**{state['rerolls_left']}/{REROLL_LIMIT_PER_DAY}회**")
    fields.append((f"🎲 미션 리롤권 — {REROLL_PRICE}코인", reroll))

    fields.append((
        f"🏷️ 칭호 — {TITLE_PLANS[10]}코인(10일) / {TITLE_PLANS[TITLE_DAYS]}코인({TITLE_DAYS}일)",
        "이름과 색을 직접 정하는 나만의 역할이에요.\n"
        "　└ `/칭호구매` 에서 기간을 골라 사요 (기간이 남았을 때 또 사면 이어붙어요)",
    ))

    protect = (
        "하루 빠져도 **연속 출석이 안 끊겨요.** 다음 출석 때 자동으로 쓰여요.\n"
        "　└ 살릴 수 있는 건 **하루치**예요 (이틀 이상 빠지면 못 살려요)\n"
        f"　└ 최대 **{PROTECT_MAX}장**까지 가질 수 있어요"
    )
    if state:
        protect += f"\n　└ 지금 가진 보호권: **{state['protects']}/{PROTECT_MAX}장**"
    fields.append((f"🧊 출석 보호권 — {PROTECT_PRICE}코인", protect))

    theme = f"`/프로필` 카드 배경을 바꿔요. 전체 {len(THEMES)}종.\n"
    if state:
        owned_extra = [t for t in state["themes"] if t != cosmetic_store.DEFAULT_THEME]
        selected = state["theme"]
        theme += (
            f"　└ 지금 쓰는 테마: "
            f"**{THEMES.get(selected, THEMES['기본'])['emoji']} {selected}**\n"
            f"　└ 가진 테마: "
            f"{('**' + '** · **'.join(owned_extra) + '**') if owned_extra else '기본만'}"
        )
    else:
        theme += "　└ 한 번 사면 **영구히** 남아서 언제든 다시 골라 쓸 수 있어요"
    fields.append((f"🎨 프로필 카드 테마 — {THEME_PRICE}코인 (영구)", theme))

    return fields


def _shop_embed(balance: int, rerolls_left: int, owned: list[str], selected: str,
                protects: int) -> discord.Embed:
    """`/악귀상점` · 🪙 버튼 — **본인에게만** 보이는 화면이에요(잔액·보유 포함)."""
    embed = discord.Embed(
        title="🪙 악귀상점",
        description=f"내 악귀코인: **{balance}개**\n`/출석` · `/미션` · `/업적`으로 모아요.",
        color=0xFFC850,
    )
    state = {
        "rerolls_left": rerolls_left,
        "protects": protects,
        "themes": owned,
        "theme": selected,
    }
    for name, value in _item_fields(state):
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="아래 버튼으로 바로 쓸 수 있어요. 나에게만 보여요.")
    return embed


def _panel_embed() -> discord.Embed:
    """🪙 상설 패널 — 상점 채널에 **공개로 박아두는** 가격표예요.

    🚨 사람별 값(잔액·보유·남은 횟수)을 **넣지 않아요.** 메시지가 하나뿐이라
       누구의 값을 적어도 나머지 전원에게 거짓이 돼요. 그건 🪙 버튼이
       본인에게만 보이게 띄워줘요.
    """
    embed = discord.Embed(
        title="🪙 악귀상점",
        description=(
            "악귀코인으로 살 수 있는 것들이에요.\n"
            "**아래 버튼을 누르면 그 자리에서 바로 사져요** — 누른 사람에게만 보여요."
        ),
        color=0xFFC850,
    )
    for name, value in _item_fields():
        embed.add_field(name=name, value=value, inline=False)
    embed.add_field(
        name="🪙 악귀코인은 어디서 모아요?",
        value=(
            "`/출석` 매일 · `/미션` 하루 3개 · `/업적` 달성 · 🎣 낚시로 잡아서 팔기\n"
            "　└ 내 코인과 보유 목록은 맨 아래 **🪙 내 코인·보유** 버튼으로 봐요"
        ),
        inline=False,
    )
    embed.set_footer(text="이 패널은 항상 여기 있어요 · 명령어로도 열려요: /악귀상점")
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
        # 🚨 **코인보다 `ack`가 먼저예요.** 전에는 코인을 뺀 뒤 DB를 네 번 다녀와서야
        #    첫 응답을 했어요. 3초를 넘기면 `10062`로 터지는데, 그 순서에선
        #    **코인은 빠지고 미션은 바뀐 채 유저는 아무 화면도 못 봐요.**
        #    받지 못했으면 코인을 건드리기 전에 빠져나와요. -> utils/interaction_ack.py
        if not await ack(interaction):
            return

        # ⚠️ 코인부터 빼요. 미션을 먼저 바꾸면 코인이 모자랄 때 공짜 리롤이 돼요.
        if not await coin_wallet.spend(interaction.user.id, REROLL_PRICE, reason="미션리롤"):
            balance = await coin_wallet.get_balance(interaction.user.id)
            await interaction.edit_original_response(
                content=f"악귀코인이 부족해요. 리롤권은 **{REROLL_PRICE}개**가 필요한데 "
                        f"지금 **{balance}개** 갖고 있어요.",
                embed=None, view=None,
            )
            return

        # ⚠️ `adult`를 넘겨야 해요. 안 넘기면 성인 인증자도 🔞 미션으로는 안 바뀌고,
        #    거꾸로 True로 고정하면 인증 없는 사람이 **못 깨는 미션**을 2코인에 사게 돼요.
        new_key, reason = await mission_store.reroll(
            interaction.user.id, key, adult_check.is_adult(interaction.user)
        )
        if new_key is None:
            # 바꾸지 못했으면 반드시 돌려줘요(실패 사유와 무관하게).
            await coin_wallet.add(interaction.user.id, REROLL_PRICE, reason="미션리롤 실패 환불")
            await interaction.edit_original_response(
                content=f"⚠️ {REROLL_ERRORS.get(reason, '바꾸지 못했어요.')} (코인은 돌려드렸어요)",
                embed=None, view=None,
            )
            return

        balance = await coin_wallet.get_balance(interaction.user.id)
        left = await mission_store.rerolls_left(interaction.user.id)
        await interaction.edit_original_response(
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
        # 🚨 **코인보다 `ack`가 먼저예요.** 여기는 상점에서 제일 비싸요(10코인).
        #    전에는 DB를 다섯 번 다녀와서야 첫 응답을 했어요 - 3초를 넘기면 10코인이
        #    빠진 채 화면이 안 떠요. -> utils/interaction_ack.py
        if not await ack(interaction):
            return

        owned = await cosmetic_store.owned_themes(interaction.user.id)

        if key not in owned:
            if not await coin_wallet.spend(interaction.user.id, THEME_PRICE, reason=f"카드테마:{key}"):
                balance = await coin_wallet.get_balance(interaction.user.id)
                await interaction.edit_original_response(
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
        await interaction.edit_original_response(
            content=(
                f"{info['emoji']} 카드 테마를 **{key}**(으)로 바꿨어요. ({info['desc']})\n"
                f"`/프로필` 을 다시 쳐보면 적용돼 있어요 · 남은 코인 {balance}개"
            ),
            embed=None, view=None,
        )


# ─── 품목별 동작 ─────────────────────────────────────────────────────────
# 🚨 **View 메서드가 아니라 모듈 함수예요.** `/악귀상점`(본인만 보이는 `ShopView`)과
#    🪙 상설 패널(`ShopPanelView`)이 **같은 코드**를 써야 해요. 한쪽에 복사해두면
#    가격·환불 순서를 한쪽만 고치는 사고가 나요 — 낚시대 구매 로직을
#    `cogs/fishing.purchase_rod` 하나로 모아둔 것과 똑같은 이유예요.
# 🚨 전부 `interaction.user.id`만 보고 **ephemeral로만** 답해요. 공개 패널에서
#    여러 사람이 같은 버튼을 동시에 눌러도 지갑이 섞이지 않는 근거가 이거예요.
# 🚨 `ack`는 **자원을 건드리기 전에** 불러요. 받지 못했으면(토큰 3초 초과) 코인을
#    손대지 않고 빠져나와요. -> utils/interaction_ack.py


async def act_buy_rod(interaction: discord.Interaction, *, small: bool = False) -> None:
    """🎣 낚시대 - 이 상점의 **첫 소모품**이에요.

    리롤권·보호권·테마는 22일째 0건인데, 그건 전부 '있으면 좋은' 물건이라서예요.
    낚시대는 **없으면 낚시를 아예 못 해요** - 매일 사야 하는 필수품이라 이 상점이
    실제로 쓰이는 첫 계기가 됐어요(실측 497건 / 14명).

    🪝 `small=True`는 입문용이에요 (2026-10-18). 낚시가 **발행의 80%**인데 48명 중
    **33명(69%)이 10코인이 없어서** 최대 발행원에 못 들어갔어요. 횟수당 값이 큰 것과
    같아서 **발행 구조는 안 바뀌고** 진입만 31% → 71%로 넓어져요.
    → 근거는 `utils/fish_data.SMALL_ROD_PRICE` 주석.

    ⚠️ 구매 로직은 `cogs/fishing.py`의 `purchase_rod` 하나뿐이에요. 여기서 복사해
    두면 한쪽만 고치는 사고가 나요(지급→차감→실패 시 환불 순서가 핵심이에요)."""
    if not await ack(interaction, ephemeral=True, thinking=True):
        return
    from cogs.fishing import purchase_rod

    _, msg = await purchase_rod(interaction.user.id, small=small)
    await interaction.followup.send(msg, ephemeral=True)


async def act_reroll(interaction: discord.Interaction) -> None:
    # 🚨 DB를 세 번 다녀오니 먼저 받아둬요(`thinking=True` = 새 비공개 메시지).
    #    -> utils/interaction_ack.py
    if not await ack(interaction, ephemeral=True, thinking=True):
        return

    left = await mission_store.rerolls_left(interaction.user.id)
    if left <= 0:
        await interaction.followup.send(REROLL_ERRORS["limit"], ephemeral=True)
        return

    # ⚠️ `linked`를 반드시 실제로 확인해요. False로 넘기면, 오늘 미션 문서가 아직
    #    없는 연동자에게 **서버 미션만** 배정돼서 발로 미션을 통째로 잃어요.
    linked = riot_account_store.get_account(interaction.user.id) is not None
    doc = await mission_store.ensure_today(
        interaction.user.id, linked=linked, adult=adult_check.is_adult(interaction.user)
    )
    done = set(doc.get("done") or [])
    pending = [k for k in (doc.get("picks") or []) if k not in done]
    if not pending:
        await interaction.followup.send(
            "오늘 미션을 전부 깼어요! 바꿀 게 없네요 👏", ephemeral=True
        )
        return

    await interaction.followup.send(
        f"바꿀 미션을 골라주세요. **{REROLL_PRICE}코인**이 들어요.\n"
        "-# 바뀐 미션은 **서버 미션**(통화·명령어) 중에서 무작위로 나와요.",
        view=RerollView(interaction.user.id, pending),
        ephemeral=True,
    )


async def act_protect(interaction: discord.Interaction) -> None:
    # 🚨 **코인보다 `ack`가 먼저예요.** 전에는 DB를 네 번 다녀와서야 첫 응답을
    #    했어요 - 3초를 넘기면 코인은 빠지고 보호권은 들어간 채 화면이 안 떠요.
    #    -> utils/interaction_ack.py
    if not await ack(interaction, ephemeral=True, thinking=True):
        return

    have = await inventory_store.protect_count(interaction.user.id)
    if have >= PROTECT_MAX:
        await interaction.followup.send(
            f"보호권은 최대 **{PROTECT_MAX}장**까지만 가질 수 있어요. 지금 {have}장 갖고 있어요.\n"
            "-# 쌓아둘 수 있으면 사실상 연속 출석이 무의미해져서 상한을 뒀어요.",
            ephemeral=True,
        )
        return

    # ⚠️ 코인부터 빼요. 지급을 먼저 하면 코인이 모자랄 때 공짜로 받아가요.
    if not await coin_wallet.spend(interaction.user.id, PROTECT_PRICE, reason="출석보호권"):
        balance = await coin_wallet.get_balance(interaction.user.id)
        await interaction.followup.send(
            f"악귀코인이 부족해요. 보호권은 **{PROTECT_PRICE}개**가 필요한데 "
            f"지금 **{balance}개** 갖고 있어요.",
            ephemeral=True,
        )
        return

    if not await inventory_store.grant_protect(interaction.user.id):
        # 그 찰나에 상한이 찼어요(동시에 두 번 눌렀을 때). 코인은 돌려줘요.
        await coin_wallet.add(interaction.user.id, PROTECT_PRICE, reason="출석보호권 환불")
        await interaction.followup.send(
            f"보호권이 이미 {PROTECT_MAX}장이에요. 코인은 돌려드렸어요.", ephemeral=True
        )
        return

    have = await inventory_store.protect_count(interaction.user.id)
    balance = await coin_wallet.get_balance(interaction.user.id)
    await interaction.followup.send(
        f"🧊 출석 보호권을 샀어요. 지금 **{have}장** · 남은 코인 {balance}개\n"
        "-# 하루 빠진 뒤 `/출석`을 하면 **자동으로** 쓰여서 연속이 이어져요.",
        ephemeral=True,
    )
    log.info("🧊 출석 보호권 구매: %s (보유 %d장)", interaction.user.id, have)


async def act_theme(interaction: discord.Interaction) -> None:
    if not await ack(interaction, ephemeral=True, thinking=True):
        return

    state = await cosmetic_store.get(interaction.user.id)
    await interaction.followup.send(
        f"테마를 고르면 바로 적용돼요. 안 가진 테마는 고르는 순간 **{THEME_PRICE}코인**이 빠져요.\n"
        "-# 한 번 산 테마는 영구히 남아서 언제든 다시 고를 수 있어요.",
        view=ThemeView(interaction.user.id, state["themes"], state["theme"]),
        ephemeral=True,
    )


async def act_title(interaction: discord.Interaction) -> None:
    """🏷️ 칭호는 이름·색을 받는 모달이 필요해서 `/칭호구매`로 보내요.
    ⚠️ 같은 모달을 두 벌 들고 있으면 한쪽만 고치는 사고가 나요."""
    await interaction.response.send_message(
        f"칭호는 `/칭호구매` 에서 사요 (이름·색을 직접 적어야 해서요).\n"
        f"　└ **{TITLE_PLANS[10]}코인 = 10일** · **{TITLE_PLANS[TITLE_DAYS]}코인 = {TITLE_DAYS}일**\n"
        f"-# `기간` 선택지에서 고를 수 있어요. 하루 단가는 {TITLE_DAYS}일권이 더 싸요.",
        ephemeral=True,
    )


async def act_open_shop(interaction: discord.Interaction) -> None:
    """🪙 내 코인·보유 — 본인만 보이는 상점 화면을 띄워요.

    `/악귀상점`과 상설 패널의 🪙 버튼이 **같이** 써요.
    ⚠️ `thinking=True`는 둘 다에 안전해요 — 슬래시 명령은 어차피 "생각 중"이 되고,
       버튼은 새 비공개 메시지가 떠요. 어느 쪽이든 그 뒤는 `followup.send`예요."""
    if not await ack(interaction, ephemeral=True, thinking=True):
        return
    balance = await coin_wallet.get_balance(interaction.user.id)
    left = await mission_store.rerolls_left(interaction.user.id)
    state = await cosmetic_store.get(interaction.user.id)
    protects = await inventory_store.protect_count(interaction.user.id)

    view = ShopView(None, interaction.user.id)
    view.message = await interaction.followup.send(
        embed=_shop_embed(balance, left, state["themes"], state["theme"], protects),
        view=view, ephemeral=True, wait=True,
    )


class ShopView(discord.ui.View):
    """`/악귀상점` 응답에 붙는 뷰 — **한 사람 전용**이에요(5분 뒤 꺼져요).

    공개 패널은 `ShopPanelView`예요. 동작은 둘 다 위의 `act_*`를 써요."""

    def __init__(self, cog: "AkguiShop | None", user_id: int):
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
        await act_buy_rod(interaction)

    @discord.ui.button(label="소형 낚시대", emoji="🪝", style=discord.ButtonStyle.secondary)
    async def buy_small_rod(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        await act_buy_rod(interaction, small=True)

    @discord.ui.button(label="미션 리롤", emoji="🎲", style=discord.ButtonStyle.primary)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_reroll(interaction)

    @discord.ui.button(label="출석 보호권", emoji="🧊", style=discord.ButtonStyle.primary)
    async def protect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_protect(interaction)

    @discord.ui.button(label="카드 테마", emoji="🎨", style=discord.ButtonStyle.secondary)
    async def theme(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_theme(interaction)

    @discord.ui.button(label="칭호 사러 가기", emoji="🏷️", style=discord.ButtonStyle.secondary)
    async def title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_title(interaction)


class ShopPanelView(discord.ui.View):
    """🪙 상점 채널에 **항상 떠 있는** 공개 패널이에요 (2026-10-27).

    ## 왜 이게 필요한가
    `/악귀상점`은 **"있는 줄 알고 쳐야" 열려요.** 리롤권·보호권·테마가 22일째 0건인 건
    구매력이 아니라 거기서 왔어요 — 같은 진단을 💡건의·📅일정·❓매니저에서 이미 세 번
    찍었어요(슬래시 명령어가 문턱). → [[feedback_pickup_plaintext_not_slash_command]]
    그래서 가격표를 방에 꺼내 놓고, **누르면 그 자리에서 사지게** 했어요.

    ## 🚨 영속 뷰 규칙 (셋 중 하나만 빠져도 재시작 뒤 버튼이 죽어요)
    1. `timeout=None`
    2. 버튼마다 **고정 `custom_id`** (`akgui:shop:*`)
    3. `cog_load`에서 `bot.add_view(ShopPanelView())`
    → `scripts/test_akgui_shop.py`가 관문에서 셋 다 검사해요.

    ## 🚨 상태를 `self`에 담지 마세요
    이 객체는 **봇 전체에 하나뿐**이라 모든 사람이 공유해요. 누른 사람은
    `interaction.user`로만 알아내고, 답은 전부 ephemeral이에요.
    → `cogs/suggestion.py`·`cogs/team.py`에 같은 경고가 있어요.
    """

    def __init__(self):
        super().__init__(timeout=None)
        # 🚨 **가격을 라벨에 손으로 적지 않아요.** 데코레이터엔 f-string을 못 쓰니
        #    여기서 상수로 덮어써요 — 상수만 바꾸면 버튼까지 따라와요.
        #    (`discord.ui.View.__init__`이 각 버튼을 같은 이름의 속성으로 꽂아줘요.)
        self.rod.label = f"낚시대 {ROD_PRICE}코인"
        self.small_rod.label = f"소형 낚시대 {SMALL_ROD_PRICE}코인"
        self.reroll.label = f"미션 리롤 {REROLL_PRICE}코인"
        self.protect.label = f"출석 보호권 {PROTECT_PRICE}코인"
        self.theme.label = f"카드 테마 {THEME_PRICE}코인"
        self.title.label = f"칭호 {TITLE_PLANS[10]}코인부터"

    @discord.ui.button(label="낚시대", emoji="🎣", style=discord.ButtonStyle.success,
                       custom_id="akgui:shop:rod", row=0)
    async def rod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_buy_rod(interaction)

    @discord.ui.button(label="소형 낚시대", emoji="🪝", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:shop:rod_small", row=0)
    async def small_rod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_buy_rod(interaction, small=True)

    @discord.ui.button(label="미션 리롤", emoji="🎲", style=discord.ButtonStyle.primary,
                       custom_id="akgui:shop:reroll", row=1)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_reroll(interaction)

    @discord.ui.button(label="출석 보호권", emoji="🧊", style=discord.ButtonStyle.primary,
                       custom_id="akgui:shop:protect", row=1)
    async def protect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_protect(interaction)

    @discord.ui.button(label="카드 테마", emoji="🎨", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:shop:theme", row=2)
    async def theme(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_theme(interaction)

    @discord.ui.button(label="칭호", emoji="🏷️", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:shop:title", row=2)
    async def title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_title(interaction)

    @discord.ui.button(label="내 코인·보유", emoji="🪙", style=discord.ButtonStyle.primary,
                       custom_id="akgui:shop:mine", row=3)
    async def mine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await act_open_shop(interaction)


class AkguiShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 패널 버튼을 눌러도 봇이 custom_id를 알아보지
        #    못해서 **아무 반응이 없어요**(에러도 안 나요).
        self.bot.add_view(ShopPanelView())

    @app_commands.command(name="악귀상점", description="악귀코인으로 미션 리롤권·출석 보호권·칭호·카드 테마를 사요.")
    async def shop(self, interaction: discord.Interaction):
        # 채널 제한을 안 걸었어요. 소비처가 없어서 코인이 쌓이는 게 문제였는데, 여기에
        # "그건 저쪽 채널에서" 를 또 붙이면 안 쓰는 이유를 하나 더 만드는 거예요.
        await act_open_shop(interaction)

    @app_commands.command(
        name="상점패널",
        description="[서버 소유자 전용] 이 채널에 악귀상점 패널을 박아둬요 (항상 떠 있어요).",
    )
    async def panel(self, interaction: discord.Interaction):
        """🪙 상설 패널을 **지금 이 채널에** 올려요.

        ⚠️ `/채널설정`을 쓰지 않아요 — 이건 "명령어를 어디서 쓸 수 있나"가 아니라
           **메시지를 한 번 박는** 일이에요. 채널을 옮기고 싶으면 옛 메시지를 지우고
           새 채널에서 다시 치면 돼요.
        📌 올린 뒤 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요."""
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "텍스트 채널에서 써주세요.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🪙 {channel.mention} 에 상점 패널을 올렸어요.\n"
            "-# 메시지를 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요. "
            "옮기려면 그 메시지를 지우고 다른 채널에서 다시 치면 돼요.",
            ephemeral=True,
        )
        await channel.send(embed=_panel_embed(), view=ShopPanelView())
        log.info("🪙 악귀상점 패널 게시: 채널 %s", channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(AkguiShop(bot))
