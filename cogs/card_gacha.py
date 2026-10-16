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
| 확률 | 일반 64.5 / 레어 30 / 에픽 5 / 레전드 0.5 (2026-10-17 조정) |
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

## 채널 제한 — `CARD_CHANNEL_ID` 폴백을 왜 쓰나

세 명령어는 `#🎴｜뽑기방`에서만 돼요. 그런데 `/채널설정`이 저장하는 `data/settings.json`은
**Fly 볼륨 위에 있어서** 배포로 못 넣어요([[project_pokemon_bot_fly_volume_shadowing]]).
`flyctl sftp`에는 `rm`이 없어 교체도 안 되고(get/put/shell뿐), `ssh console`은 막혀 있어요.

그래서 `restrict_to_channel`이 원래 지원하는 **env 폴백**을 써요 — `/오상`(`VALORANT_SHOP_
CHANNEL_ID`)·노래방(`KARAOKE_VOICE_CHANNEL_ID`)과 같은 방식이에요. 우선순위는
`/채널설정` > env > 제한없음이라, 나중에 서버 소유자가 `/채널설정 악귀카드 #채널`로
언제든 덮어쓸 수 있어요(그때는 재배포가 필요 없어요).

⚠️ env 값은 `.env`가 아니라 **`flyctl secrets set CARD_CHANNEL_ID=...`**로 넣어요
([[project_pokemon_bot_flyio_secrets_not_env]]).
"""
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import card_render, card_store, coin_wallet
from utils.card_data import BY_KEY, CARDS
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


# ============================================================
# 📖 도감 화면
#
# 처음엔 글자 목록만 보여줬는데, **수집 기능인데 정작 모은 카드를 볼 수가 없었어요.**
# 그래서 등급을 고르면 그 등급을 통째로 펼친 그림을 띄우고, 거기서 한 장을 골라
# 크게 볼 수 있게 했어요.
#
# ⚠️ 여기 버튼은 뽑기 버튼과 달리 **DynamicItem이 아니에요.** 도감은 ephemeral(본인에게만
# 보이는) 메시지라 어차피 봇이 재시작되면 되살릴 대상 자체가 없어요. 시간이 지나 꺼지면
# `/도감`을 다시 부르면 돼요. (공개 메시지에 남는 뽑기 버튼은 반드시 DynamicItem이어야
# 해요 - cogs/attendance.py 주석 참고)
# ============================================================
_VIEW_TIMEOUT = 300

# 디스코드 드롭다운은 선택지가 **25개**까지예요. 에픽은 30종이라 전부 모으면 넘쳐요.
_SELECT_MAX = 25


def _overview_embed(summary: dict, since_legend: int, counts: dict) -> discord.Embed:
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
    if card_store._exhausted("레전드", counts):
        embed.set_footer(text="🟡 레전드를 전부 모으셨어요! · 아래 버튼으로 카드를 펼쳐봐요")
    else:
        left = max(0, PITY_DRAWS - since_legend)
        embed.set_footer(text=f"🟡 레전드 확정까지 {left}장 · 아래 버튼으로 카드를 펼쳐봐요")
    return embed


class GradeButton(discord.ui.Button):
    """등급 하나를 펼쳐 보는 버튼."""

    def __init__(self, grade: str, owned: int, total: int):
        super().__init__(
            label=f"{grade} {owned}/{total}",
            emoji=GRADE_EMOJI[grade],
            style=discord.ButtonStyle.secondary,
        )
        self.grade = grade

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_grade(interaction, self.grade)  # type: ignore[attr-defined]


class BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="전체 진행도", emoji="📖", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_overview(interaction)  # type: ignore[attr-defined]


class CardSelect(discord.ui.Select):
    """가진 카드 중 하나를 골라 크게 봐요. (안 가진 카드는 목록에 없어요)"""

    def __init__(self, grade: str, cards: list[dict], counts: dict):
        owned = [c for c in cards if counts.get(c["key"])]
        options = [
            discord.SelectOption(
                label=c["name"][:100],
                value=c["key"],
                description=(f"{counts[c['key']]}장 보유"
                             if counts.get(c["key"], 0) > 1 else None),
                emoji=GRADE_EMOJI[grade],
            )
            for c in owned[:_SELECT_MAX]
        ]
        extra = len(owned) - len(options)
        placeholder = "카드를 골라 크게 보기"
        if extra > 0:
            placeholder = f"카드를 골라 크게 보기 (앞 {_SELECT_MAX}종만)"
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.show_card(interaction, self.values[0])  # type: ignore[attr-defined]


class CollectionView(discord.ui.View):
    def __init__(self, user_id: int, counts: dict, since_legend: int):
        super().__init__(timeout=_VIEW_TIMEOUT)
        self.user_id = user_id
        self.counts = counts
        self.since_legend = since_legend
        self.summary = card_store.summarize(counts)
        self._build_overview()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ephemeral이라 남이 누를 일은 거의 없지만, 혹시 모를 경우를 막아둬요.
        return interaction.user.id == self.user_id

    # ---- 화면 구성 ----
    def _build_overview(self):
        self.clear_items()
        for grade in GRADE_ORDER:
            g = self.summary["per_grade"][grade]
            self.add_item(GradeButton(grade, g["owned"], g["total"]))

    def _build_grade(self, grade: str):
        self.clear_items()
        self.add_item(BackButton())
        if any(self.counts.get(c["key"]) for c in CARDS[grade]):
            self.add_item(CardSelect(grade, CARDS[grade], self.counts))

    # ---- 화면 전환 ----
    async def show_overview(self, interaction: discord.Interaction):
        self._build_overview()
        await interaction.response.edit_message(
            embed=_overview_embed(self.summary, self.since_legend, self.counts),
            attachments=[],          # 그림을 떼어내요 (안 하면 이전 카드가 남아요)
            view=self,
        )

    async def show_grade(self, interaction: discord.Interaction, grade: str):
        # 썸네일을 미리 구워둬서 보통 0.1초 안에 끝나지만, 세마포어 대기가 걸릴 수 있어서
        # defer는 해둬요(3초를 넘기면 디스코드가 "응답하지 않았습니다"로 끊어요).
        await interaction.response.defer()
        self._build_grade(grade)
        embed, file = await _grade_payload(grade, self.counts, self.summary)
        await interaction.edit_original_response(
            embed=embed, attachments=[file] if file else [], view=self
        )

    async def show_card(self, interaction: discord.Interaction, key: str):
        await interaction.response.defer()
        grade, name = BY_KEY[key]
        path = card_render.card_file_path(key)
        have = self.counts.get(key, 0)

        embed = discord.Embed(
            title=f"{GRADE_EMOJI[grade]} {name}",
            description=f"**{grade}**" + (f" · {have}장 보유" if have > 1 else ""),
            color=GRADE_COLOR[grade],
        )
        files = []
        if path is not None:
            files = [discord.File(path, filename=f"{key}.webp")]
            embed.set_image(url=f"attachment://{key}.webp")
        else:
            embed.description += "\n-# 이미지를 찾지 못했어요."
        embed.set_footer(text="아래에서 다른 카드를 고르거나 📖 로 돌아갈 수 있어요")
        await interaction.edit_original_response(embed=embed, attachments=files, view=self)


async def _grade_payload(grade: str, counts: dict, summary: dict):
    """등급 도감 페이지의 (임베드, 파일). 그림이 실패하면 글자 목록으로 물러나요."""
    g = summary["per_grade"][grade]
    embed = discord.Embed(
        title=f"{GRADE_EMOJI[grade]} {grade} — {g['owned']}/{g['total']}",
        color=GRADE_COLOR[grade],
    )
    png = await card_render.render_grid(grade, CARDS[grade], counts)
    if png is not None:
        embed.set_image(url=f"attachment://dex_{grade}.png")
        embed.set_footer(text="🔒 ? 는 아직 없는 카드예요 · 아래에서 골라 크게 볼 수 있어요")
        return embed, discord.File(io.BytesIO(png), filename=f"dex_{grade}.png")

    # Pillow가 없거나 렌더가 실패한 경우 - 기능이 통째로 죽는 것보단 글자가 나아요.
    rows = []
    for card in CARDS[grade]:
        n = counts.get(card["key"], 0)
        if not n:
            rows.append(f"🔒 ||{card['name']}||")
        elif grade in card_store.DUPE_OK and n > 1:
            rows.append(f"✅ **{card['name']}** ×{n}")
        else:
            rows.append(f"✅ **{card['name']}**")
    embed.description = "\n".join(rows)
    embed.set_footer(text="🔒 는 아직 없는 카드예요 (이름은 가려뒀어요)")
    return embed, None


class CardGacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="카드뽑기",
        description=f"악귀코인 {PULL_PRICE}개로 악귀카드 {CARDS_PER_PULL}장을 뽑아요.",
    )
    @restrict_to_channel("card", "CARD_CHANNEL_ID")
    async def pull_cards(self, interaction: discord.Interaction):
        # DB 왕복 + 이미지 합성이라 3초를 넘겨요.
        await interaction.response.defer()
        await do_pull(interaction)

    @app_commands.command(name="도감", description="내가 모은 악귀카드를 펼쳐 봐요.")
    @restrict_to_channel("card", "CARD_CHANNEL_ID")
    @app_commands.describe(등급="바로 이 등급을 펼쳐요 (안 고르면 전체 진행도부터)")
    @app_commands.choices(등급=[
        app_commands.Choice(name=f"{GRADE_EMOJI[g]} {g}", value=g) for g in GRADE_ORDER
    ])
    async def collection(
        self, interaction: discord.Interaction, 등급: app_commands.Choice[str] | None = None
    ):
        # 본인 도감이라 ephemeral이에요. 채널이 남의 도감으로 덮이지 않아요.
        await interaction.response.defer(ephemeral=True)
        state = await card_store.get_collection(interaction.user.id)
        counts = state["counts"]

        view = CollectionView(interaction.user.id, counts, state["since_legend"])

        if 등급 is None:
            await interaction.followup.send(
                embed=_overview_embed(view.summary, state["since_legend"], counts),
                view=view, ephemeral=True,
            )
            return

        grade = 등급.value
        view._build_grade(grade)
        embed, file = await _grade_payload(grade, counts, view.summary)
        # ⚠️ `file=None`을 그대로 넘기면 안 돼요(discord.py 기본값이 MISSING이라
        #    None을 "파일이 있다"로 봐요). 붙일 게 있을 때만 kwargs에 넣어요.
        extra = {"file": file} if file else {}
        await interaction.followup.send(embed=embed, view=view, ephemeral=True, **extra)

    @app_commands.command(name="카드확률", description="악귀카드 뽑기의 확률과 천장을 공개해요.")
    @restrict_to_channel("card", "CARD_CHANNEL_ID")
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
