"""🎴 악귀카드 - 악귀코인으로 서버 전용 수집 카드를 뽑아요.

## 왜 만들었나

코인이 쌓이기만 했어요. 2026-10-15 실측에서 소각률이 20%였는데 그게 **전부 🎰 도박 몫**이고,
`/악귀상점` 3종(리롤권·보호권·테마)은 열흘째 **0건**이었어요. 구매력은 충분했고(12코인 이상
21명), 문제는 **상점에 진열만 해둔 것**이었어요 -> [[project_akgui_shop_coin_sinks]]

그래서 이 기능은 상점에 기대지 않아요:
  - **`/출석` 응답에 🎴 버튼**을 달아요. 코인이 손에 들어오는 그 순간이 쓸 자리예요.
  - 뽑기 결과에도 "한 번 더" 버튼을 달아요(이어서 돌릴 수 있게).

## 결과를 누구에게 보여주나

| 어디서 | 결과 |
|---|---|
| `/카드뽑기` (뽑기방 전용) | **공개** |
| 🎴 버튼을 **뽑기방**에서 | **공개** |
| 🎴 버튼을 다른 채널(`#출석체크` 등)에서 | 본인에게만 |

판단은 `_is_card_channel`이 해요. 실패·환불 안내는 **장소와 무관하게 늘 본인에게만** 보내요
(남의 잔액 부족을 채널에 띄울 이유가 없어요).

단 🟡 **레전드(0.5%)는 어디서 뽑았든 뽑기방에 홍보**해요 - 서버에서 가장 귀한 순간이라
한 줄 띄워줘요. 그리고 **나쁜말악귀가 나오면 🥈 부방장을 멘션**해요(2026-10-27 사용자 지시).
`announce_legend` 주석을 보세요 - "공개 뽑기면 건너뛴다"를 넣었다가 **그 경로가 지금의
전부여서** 되돌린 기록이 있어요.

## 수치 (2026-10-17 사용자 확정)

| 항목 | 값 |
|---|---|
| 가격 | 10코인에 **3장** (연속뽑기 최대 10회 = 100코인·30장, 할인 없음) |
| 확률 | 일반 76.5 / 레어 20 / 에픽 3 / 레전드 0.5 (2026-10-17 3차) |
| 천장 | 레전드 없이 **240장**(=80뽑기)이면 그 장은 레전드 확정 (최악 800코인) |
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

`🎴 악귀카드` 카테고리 아래 세 채널로 갈라뒀어요(2026-10-17).

| 채널 | 명령어 | 그룹 / env |
|---|---|---|
| `#🎴｜뽑기방` | `/카드뽑기` `/카드확률` | `card` / `CARD_CHANNEL_ID` |
| `#🎪｜거래장터` | `/카드거래` `/거래함` | `card_market` / `CARD_MARKET_CHANNEL_ID` |
| `#📖｜도감` | `/도감` | `card_dex` / `CARD_DEX_CHANNEL_ID` | 그런데 `/채널설정`이 저장하는 `data/settings.json`은
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
    FUSE_N,
    GRADE_COLOR,
    GRADE_EMOJI,
    GRADE_ORDER,
    GRADE_WEIGHTS,
    PITY_DRAWS,
    PULL_PRICE,
)
from utils.channel_check import get_allowed_channel_id, restrict_to_channel
from utils.staff_check import normalize_role_name

log = logging.getLogger(__name__)

COIN_LOG_NOTE = "카드뽑기"

# ============================================================
# 🟡 레전드 홍보 (2026-10-27 사용자 지시)
#
# 레전드는 한 장당 0.5%예요. 그게 나오면 **뽑기방에 홍보**해요.
#
# 🚨 **"공개로 뽑았으면 결과가 이미 보이니 건너뛴다"고 만들었다가 되돌렸어요.**
#    그 판단은 `/출석`에 🎴 버튼이 달려 있던 시절의 지형을 전제로 했는데, 그 버튼은
#    **2026-10-17에 제거됐어요**(`cogs/attendance.py` 주석). `/카드뽑기`는 뽑기방
#    전용이고 결과에 달린 "한 번 더"도 거기서 눌리니, 지금 뽑기는 **거의 전부 뽑기방
#    공개 뽑기**예요. 그래서 건너뛰기를 넣으면 이 기능이 **한 번도 안 터져요.**
#    → 기능을 "언제 안 하는지"로 조건을 달 때는 그 조건이 지금도 일어나는 일인지
#      **경로를 직접 확인할 것.** 옛 주석의 전제를 그대로 믿으면 죽은 코드가 돼요.
#
# ⚠️ 결과가 이미 그 채널에 공개로 올라갔을 때는 **카드 그림만 생략**해요(같은 그림이
#    위아래로 두 번 뜨니까요). 홍보 자체는 올라가요.
# ⚠️ 홍보가 실패해도 **뽑기는 이미 끝났어요.** 절대 예외를 올리지 않아요(코인은 나갔고
#    카드는 들어간 상태라, 여기서 터지면 유저에겐 "실패한 뽑기"로 보여요).
# ============================================================
# 나쁜말악귀(l02)가 나오면 🥈 부방장을 멘션해요.
NAUGHTY_CARD_KEY = "l02"

# 역할은 **이모지 뗀 이름으로 정확히 일치** 비교해요 — ID로 박으면 역할을 지웠다 다시
# 만들 때 조용히 멘션이 사라져요(`utils/staff_check.py` 맨 위 설명과 같은 이유예요).
# 🚨 부분 일치로 하면 안 돼요: `방장` ⊂ `부방장`이라 👑 방장까지 걸려요.
VICE_LEADER_ROLE_NAME = "부방장"


def _is_card_channel(interaction: discord.Interaction) -> bool:
    """지금 이 상호작용이 **뽑기방**에서 일어났는지.

    ## 왜 필요한가 (2026-10-17)

    🎴 버튼은 **컴포넌트라 `restrict_to_channel`이 안 걸려요.** `/출석` 응답에 붙어 있어서
    `#출석체크`에서도 눌러지는데, 그건 일부러 그런 거예요(코인이 손에 들어온 그 자리에서
    쓰게 하는 게 이 기능의 전제니까요).

    문제는 **결과를 어디에 보여주느냐**였어요. 처음엔 무조건 본인에게만(ephemeral) 보여줬는데,
    그러면 뽑기방에서 `/카드뽑기`로 공개 뽑기를 한 뒤 **같은 메시지의 "한 번 더" 버튼을
    누르면 그때부터 비공개로 바뀌는** 모순이 생겼어요. 같은 자리, 같은 행동인데 첫 판만
    보이는 거죠. 뽑기는 자랑하는 재미가 큰데 그게 통째로 죽어요.

    그래서 **장소로 판단**해요 - 뽑기방이면 공개, 아니면 본인에게만.
    `#출석체크`가 뽑기 결과로 덮이지 않으면서 뽑기방에서는 서로의 결과가 보여요.

    ⚠️ 채널 지정이 아예 없으면(`/채널설정`도 `CARD_CHANNEL_ID`도 없을 때) `restrict_to_channel`이
    "아무 데서나 허용"으로 동작해요. 그 상태에선 여기도 **전부 공개**로 봐요 - 제한이 없는데
    결과만 숨기면 오히려 이상하니까요.
    """
    allowed = get_allowed_channel_id("card", "CARD_CHANNEL_ID")
    if not allowed:
        return True
    # 스레드 안에서 눌렀으면 부모 채널로 판단해요(restrict_to_channel과 같은 규칙).
    parent_id = getattr(interaction.channel, "parent_id", None)
    return interaction.channel_id == allowed or parent_id == allowed


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
    pulls = max(1, len(drawn) // CARDS_PER_PULL)

    def line(d):
        mark = " 🆕" if d["is_new"] else ""
        pity = " ⭐천장" if d["pity"] else ""
        return f"{GRADE_EMOJI[d['grade']]} **{d['grade']}** · {d['name']}{mark}{pity}"

    # ⚠️ 장수가 많으면 **전부 나열하지 않아요.** 10연이면 30줄이 돼서 임베드가 화면을
    #    가득 채우고, 정작 중요한 에픽·레전드가 일반 카드 사이에 묻혀요.
    #    그림에는 어차피 전부 보이니, 글로는 **상위 등급만** 짚어줘요.
    if len(drawn) <= CARDS_PER_PULL * 3:
        description = "\n".join(line(d) for d in drawn)
    else:
        tally = " · ".join(
            f"{GRADE_EMOJI[g]} {g} **{sum(1 for d in drawn if d['grade'] == g)}**"
            for g in GRADE_ORDER if any(d["grade"] == g for d in drawn)
        )
        highlight = [line(d) for d in drawn if d["grade"] not in card_store.DUPE_OK]
        description = tally
        if highlight:
            description += "\n\n" + "\n".join(highlight[:10])
            if len(highlight) > 10:
                description += f"\n-# 외 {len(highlight) - 10}장"

    title = (f"{GRADE_EMOJI[best]} 카드 {len(drawn)}장을 뽑았어요!" if pulls == 1
             else f"{GRADE_EMOJI[best]} {pulls}연속! 카드 {len(drawn)}장을 뽑았어요")
    embed = discord.Embed(title=title, description=description, color=GRADE_COLOR[best])
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


def _vice_leader_role(guild: discord.Guild) -> discord.Role | None:
    """🥈 부방장 역할. 못 찾으면 None(멘션 없이 홍보만 올라가요)."""
    for role in guild.roles:
        if normalize_role_name(role.name) == VICE_LEADER_ROLE_NAME:
            return role
    log.warning("🥈 부방장 역할을 못 찾았어요 - 나쁜말악귀 멘션을 건너뛰어요")
    return None


def _legend_embed(member: discord.abc.User, legends: list[dict],
                  summary: dict | None) -> discord.Embed:
    """뽑기방에 올릴 홍보 임베드. 뽑은 사람은 멘션으로 적지만 핑은 안 쏴요
    (`allowed_mentions`에서 users를 꺼둬요 - 본인은 이미 결과를 봤어요)."""
    names = " · ".join(f"**{d['name']}**{' 🆕' if d['is_new'] else ''}" for d in legends)
    title = (f"🟡 레전드 출현! {legends[0]['name']}" if len(legends) == 1
             else f"🟡 레전드 {len(legends)}장 출현!")
    embed = discord.Embed(
        title=title,
        description=f"{member.mention} 님이 {names} 를 뽑았어요!",
        color=GRADE_COLOR["레전드"],
    )
    if summary:
        legend = summary["per_grade"]["레전드"]
        embed.add_field(
            name="레전드 도감",
            value=f"**{legend['owned']}/{legend['total']}종**",
            inline=True,
        )
    if any(d["pity"] for d in legends):
        embed.add_field(name="천장", value=f"⭐ {PITY_DRAWS}장 확정", inline=True)
    embed.set_footer(
        text=f"레전드는 한 장당 {GRADE_WEIGHTS['레전드']}% · /카드뽑기 로 도전해봐요"
    )
    return embed


async def announce_legend(interaction: discord.Interaction, drawn: list[dict], *,
                          shown_publicly: bool, summary: dict | None = None) -> None:
    """레전드를 뽑았으면 뽑기방에 홍보해요. 나쁜말악귀면 🥈 부방장을 멘션해요.

    ⚠️ 부르는 쪽에서 반드시 `try/except`로 감싸주세요(위 설명 참고)."""
    legends = [d for d in drawn if d["grade"] == "레전드"]
    if not legends:
        return

    guild = interaction.guild
    if guild is None:
        return  # DM이면 홍보할 곳이 없어요

    channel_id = get_allowed_channel_id("card", "CARD_CHANNEL_ID")
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        # 채널 지정이 아예 없으면 결과가 어차피 전부 공개라 홍보할 자리가 따로 없어요.
        log.info("🟡 레전드가 나왔는데 뽑기방을 못 찾아서 홍보를 건너뛰어요 (channel_id=%s)",
                 channel_id)
        return

    role = (_vice_leader_role(guild)
            if any(d["key"] == NAUGHTY_CARD_KEY for d in legends) else None)
    content = (f"{role.mention} 🗯️ **나쁜말악귀**가 깨어났어요!" if role else None)
    mentions = discord.AllowedMentions(
        everyone=False, users=False, roles=[role] if role else False)

    # 결과가 이미 이 채널에 공개로 올라갔으면 그림만 생략해요(위 설명 참고).
    already_shown = shown_publicly and _is_card_channel(interaction)

    embed = _legend_embed(interaction.user, legends, summary)
    file = None
    if not already_shown:
        png = await card_render.render_pull(legends)
        if png is not None:
            name = f"legend_{interaction.user.id}.png"
            file = discord.File(io.BytesIO(png), filename=name)
            embed.set_image(url=f"attachment://{name}")
    await channel.send(content=content, embed=embed, file=file,
                       allowed_mentions=mentions)
    log.info("🟡 레전드 홍보: user=%s cards=%s", interaction.user.id,
             [d["key"] for d in legends])


async def do_pull(interaction: discord.Interaction, *, pulls: int = 1,
                  ephemeral: bool = False):
    """뽑기 `pulls`회(= `pulls * CARDS_PER_PULL`장). `/카드뽑기`와 🎴 버튼이 같이 써요.

    ⚠️ 부르기 전에 `defer()`가 끝나 있어야 해요.
    ⚠️ 코인은 **한 번에 전액** 차감해요. 1회씩 나눠 차감하면 중간에 실패했을 때 몇 회분을
       돌려줘야 하는지가 복잡해지고, 부분 성공이라는 애매한 상태가 생겨요."""
    user_id = interaction.user.id
    pulls = max(1, min(int(pulls), card_store.MAX_PULLS))
    cost = PULL_PRICE * pulls
    note = COIN_LOG_NOTE if pulls == 1 else f"{COIN_LOG_NOTE}x{pulls}"

    # 1) 코인 먼저 차감. 조건부 update라 잔액이 모자라면 아무것도 안 바뀌어요.
    if not await coin_wallet.spend(user_id, cost, reason=note):
        balance = await coin_wallet.get_balance(user_id)
        can = balance // PULL_PRICE
        hint = (f"\n-# 지금 잔액으로는 **{can}연속**까지 돌릴 수 있어요."
                if can else "\n-# `/출석` · `/미션` · `/업적`으로 모을 수 있어요.")
        await interaction.followup.send(
            f"악귀코인이 모자라요. **{pulls}연속**은 **{cost}코인**인데 "
            f"지금 **{balance}개** 있어요.{hint}",
            ephemeral=True,
        )
        return

    # 2) 뽑기. 실패하면 반드시 환불해요.
    try:
        drawn = await card_store.pull(user_id, CARDS_PER_PULL * pulls)
    except Exception:
        await coin_wallet.add(user_id, cost, reason=f"{COIN_LOG_NOTE}:환불")
        log.exception("카드 뽑기 실패 - 코인을 되돌렸어요 (user=%s)", user_id)
        await interaction.followup.send(
            "뽑기 도중 문제가 생겨서 **코인을 돌려드렸어요.** 잠시 후 다시 시도해주세요.",
            ephemeral=True,
        )
        return

    if drawn is None:
        await coin_wallet.add(user_id, cost, reason=f"{COIN_LOG_NOTE}:환불")
        await interaction.followup.send(
            "방금 다른 뽑기가 먼저 처리됐어요. **코인은 돌려드렸으니** 다시 눌러주세요.",
            ephemeral=True,
        )
        return

    if not drawn:
        # 일반·레어가 중복을 허용하는 한 실제로는 안 나오는 경로예요(방어용).
        await coin_wallet.add(user_id, cost, reason=f"{COIN_LOG_NOTE}:환불")
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
    else:
        file = discord.File(io.BytesIO(png), filename=f"gacha_{user_id}.png")
        embed.set_image(url=f"attachment://gacha_{user_id}.png")
        await interaction.followup.send(embed=embed, file=file, view=view,
                                        ephemeral=ephemeral)

    # 4) 🟡 레전드면 뽑기방에 홍보해요. 결과는 이미 보냈으니 여기서 터져도 조용히 넘겨요.
    try:
        await announce_legend(interaction, drawn, shown_publicly=not ephemeral,
                              summary=summary)
    except Exception:
        log.exception("🟡 레전드 홍보 실패 - 뽑기 자체는 정상이에요 (user=%s)", user_id)


# ============================================================
# ⚒️ 합성 — 중복 3장을 뽑기와 똑같은 확률로 1장 다시 굴려요 (2026-10-31)
#
# 규칙·시뮬레이션 결과는 `utils/card_store.py`의 합성 구역 주석에 있어요.
# 여기는 **보여주기**만 해요.
#
# 🚨 그림은 **레어 이상 + 신규만** 그려요. "전부" 합성은 결과가 50장까지 나오는데
#    (실측 최다 보유자 = 53회) 그 대부분은 **또 중복인 일반**이에요. 전부 그리면
#    6열 격자가 9행까지 늘어나 세로 2000px이 되고, 정작 성과(레어·신규)가 묻혀요.
# ============================================================
FUSE_ART_MAX = 30     # 그림에 올리는 최대 장수 (10연 = 30장과 같은 상한)


def _fuse_embed(results: list[dict], used: dict[str, int], *,
                summary: dict, dup_left: int) -> discord.Embed:
    """합성 결과. 받은 카드가 많을 수 있어서 **등급별 집계**를 먼저 보여줘요."""
    by_grade = {g: [d for d in results if d["grade"] == g] for g in GRADE_ORDER}
    runs = len(results)
    rarest = _rarest(results)

    lines = []
    for grade in GRADE_ORDER:
        got = by_grade[grade]
        if not got:
            continue
        new_n = sum(1 for d in got if d["is_new"])
        tail = f" (🆕 신규 {new_n}종)" if new_n else ""
        lines.append(f"{GRADE_EMOJI[grade]} **{grade} {len(got)}장**{tail}")

    embed = discord.Embed(
        title=f"⚒️ 합성 {runs}회",
        description="\n".join(lines),
        color=GRADE_COLOR.get(rarest, 0x9CA3AF),
    )
    # 🚨 재료 장수를 손으로 적지 않아요 — `used`를 더해서 세요(FUSE_N을 고쳐도 따라와요).
    embed.add_field(
        name="먹은 재료",
        value=f"중복 **{sum(used.values())}장** → 새 카드 **{runs}장**",
        inline=True,
    )
    embed.add_field(
        name="남은 중복",
        value=(f"**{dup_left}장**" if dup_left >= FUSE_N
               else f"**{dup_left}장** (합성엔 {FUSE_N}장 필요)"),
        inline=True,
    )
    embed.add_field(
        name="도감",
        value=f"**{summary['owned']} / {summary['total']}종**",
        inline=True,
    )

    news = [d for d in results if d["is_new"]]
    if news:
        embed.add_field(
            name=f"🆕 처음 얻은 카드 {len(news)}종",
            value=" · ".join(f"{GRADE_EMOJI[d['grade']]}{d['name']}" for d in news[:20]),
            inline=False,
        )
    return embed


async def do_fuse(interaction: discord.Interaction, *, times: int = 1,
                  ephemeral: bool = True):
    """합성 `times`회. `times=0`이면 중복이 바닥날 때까지.
    `/카드합성`과 ⚒️ 패널 버튼이 같이 써요.

    ⚠️ 부르기 전에 `defer()`가 끝나 있어야 해요.
    ⚠️ **코인을 안 써요** — 재료가 중복 카드예요. 그래서 환불 경로가 없어요
       (`do_pull`과 다른 점이에요). 실패하면 아무것도 안 바뀌어요."""
    user_id = interaction.user.id

    try:
        outcome = await card_store.fuse(user_id, times)
    except Exception:
        log.exception("카드 합성 실패 (user=%s)", user_id)
        await interaction.followup.send(
            "합성 도중 문제가 생겼어요. **카드는 그대로 있어요** — 잠시 후 다시 해주세요.",
            ephemeral=True,
        )
        return

    if outcome is None:
        await interaction.followup.send(
            "방금 다른 합성이 먼저 처리됐어요. **카드는 그대로예요** — 다시 눌러주세요.",
            ephemeral=True,
        )
        return

    results, used = outcome
    if not results:
        # 재료 부족. 지금 몇 장인지 같이 알려줘야 "얼마나 더 모아야 하나"를 알아요.
        state = await card_store.get_collection(user_id)
        have = card_store.dup_count(state["counts"])
        await interaction.followup.send(
            f"합성할 **중복 카드가 모자라요.** 지금 쓸 수 있는 중복이 **{have}장**인데 "
            f"1회에 **{FUSE_N}장**이 필요해요.\n"
            f"-# ⚪일반·🔵레어만 재료가 돼요(🟣에픽·🟡레전드는 안 먹어요). "
            f"각 카드의 **마지막 1장은 남겨둬요** — 도감이 비지 않아요.",
            ephemeral=True,
        )
        return

    state = await card_store.get_collection(user_id)
    summary = card_store.summarize(state["counts"])
    dup_left = card_store.dup_count(state["counts"])
    embed = _fuse_embed(results, used, summary=summary, dup_left=dup_left)

    # 그림엔 성과만 — 레어 이상과 신규. (위 FUSE_ART_MAX 주석 참고)
    art = [d for d in results if d["grade"] != "일반" or d["is_new"]][:FUSE_ART_MAX]
    png = await card_render.render_pull(art) if art else None
    if png is None:
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        file = discord.File(io.BytesIO(png), filename=f"fuse_{user_id}.png")
        embed.set_image(url=f"attachment://fuse_{user_id}.png")
        await interaction.followup.send(embed=embed, file=file, ephemeral=ephemeral)

    # 🟡 레전드면 뽑기방에 홍보해요. 뽑기와 **같은 함수**를 써요 — 합성으로 나온 레전드도
    # 서버에서 가장 귀한 순간이고, 따로 짜면 문구가 갈려요.
    # ⚠️ 합성 결과는 늘 본인에게만 보이니 `shown_publicly=False`예요(그림도 같이 올라가요).
    try:
        await announce_legend(interaction, results, shown_publicly=False, summary=summary)
    except Exception:
        log.exception("🟡 레전드 홍보 실패 - 합성 자체는 정상이에요 (user=%s)", user_id)


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
    # 🚨 뒤쪽 `:횟수`는 **반드시 선택(optional)이어야** 해요.
    #
    # 연속뽑기를 넣으면서 custom_id에 횟수를 붙였는데, 패턴을 `gacha:pull:<횟수>:<유저>`로
    # 바꿨다면 **이미 디스코드에 떠 있는 옛 버튼**(`gacha:pull:<유저>`)이 패턴에 안 맞아
    # 눌러도 아무 반응이 없게 돼요 - 로그조차 안 남아요(2026-09-29에 프로필 카드 버튼이
    # 정확히 이렇게 죽었어요). 옛 형식도 계속 맞게 두고, 없으면 1회로 봐요.
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"gacha:pull:(?P<user_id>\d+)(?::(?P<pulls>\d+))?",
):
    def __init__(self, user_id: int, pulls: int = 1):
        pulls = max(1, min(int(pulls), card_store.MAX_PULLS))
        cost = PULL_PRICE * pulls
        label = f"카드 뽑기 ({cost}코인)" if pulls == 1 else f"{pulls}연속 ({cost}코인)"
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji="🎴",
                style=discord.ButtonStyle.primary if pulls == 1
                else discord.ButtonStyle.success,
                # 1회는 **옛 형식 그대로** 둬요. 새 형식으로 바꾸면 기존에 떠 있는
                # 버튼과 모양이 갈려서 섞이고, 굳이 바꿀 이유도 없어요.
                custom_id=(f"gacha:pull:{user_id}" if pulls == 1
                           else f"gacha:pull:{user_id}:{pulls}"),
            )
        )
        self.user_id = user_id
        self.pulls = pulls

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        # 옛 버튼은 `pulls` 그룹이 아예 없어요(None) -> 1회로 봐요.
        return cls(int(match["user_id"]), int(match["pulls"] or 1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """남의 출석/뽑기 메시지로 내 코인을 쓰게 되면 헷갈려요. 주인만 눌러요."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "이 버튼은 주인만 누를 수 있어요. `/카드뽑기`로 직접 뽑아주세요.", ephemeral=True
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        log.info("🎴 카드 뽑기 버튼: user=%s pulls=%s", interaction.user.id, self.pulls)
        # 뽑기방에서 눌렀으면 **공개**, 다른 채널이면 나한테만 (_is_card_channel 주석 참고).
        public = _is_card_channel(interaction)
        await interaction.response.defer(ephemeral=not public)
        await do_pull(interaction, pulls=self.pulls, ephemeral=not public)


# 결과 아래에 달아줄 연속뽑기 버튼. 지갑 실측(2026-10-17)에서 30코인 이상이 8명,
# 50코인 이상이 4명이라 5연이 "모아서 지르는" 자리로 맞아요. 10연(100코인)은 아직
# 아무도 못 사서 버튼으로는 안 달고 `/카드뽑기 횟수:10`으로만 열어둬요.
QUICK_PULLS = 5


class CardPanelView(discord.ui.View):
    """🎴 뽑기방 채널에 **항상 떠 있는** 공개 패널이에요 (2026-10-31).

    ## 왜 이게 필요한가

    🪙 악귀상점이 22일째 0건이던 게 **방 + 버튼**으로 깨졌고, 🎣 낚시터도 방은 있는데
    버튼이 0줄이어서 같은 걸 달았어요(2026-10-31). 뽑기방도 똑같이 **버튼이 0줄**이에요 —
    `/카드뽑기`를 쳐야 하고, 이번에 새로 만드는 ⚒️ 합성은 **아무도 모르는 명령어**예요.
    같은 진단을 💡건의·📅일정·❓매니저에서 이미 세 번 찍었어요.
    → [[feedback_pickup_plaintext_not_slash_command]]

    ## 🚨 영속 뷰 규칙 (셋 중 하나만 빠져도 재시작 뒤 버튼이 죽어요)
    1. `timeout=None`
    2. 버튼마다 **고정 `custom_id`** (`akgui:card:*`)
    3. `cog_load`에서 `bot.add_view(CardPanelView())`
    → `scripts/test_card_fusion.py`가 관문에서 셋 다 검사해요.

    ## 🚨 상태를 `self`에 담지 마세요
    이 객체는 **봇 전체에 하나뿐**이라 모든 사람이 공유해요. 누른 사람은
    `interaction.user`로만 알아내요.

    ## 🚨 뽑기 결과는 공개, 합성 결과는 본인에게만
    뽑기는 자랑하는 재미가 있어서 뽑기방이면 공개예요(`_is_card_channel`). 합성은
    "쓸모없는 중복을 녹이는" 정비 작업이라 채널을 덮을 이유가 없어요 — 늘 ephemeral이에요.
    단 🟡 레전드가 나오면 **합성이어도 뽑기방에 홍보**돼요(`announce_legend`).
    """

    def __init__(self):
        super().__init__(timeout=None)
        # 🚨 **숫자를 라벨에 손으로 적지 않아요.** 데코레이터엔 f-string을 못 쓰니
        #    여기서 상수로 덮어써요 — 상수만 바꾸면 버튼까지 따라와요.
        #    (🎣 낚시 패널·🪙 상점 패널과 같은 방식이에요)
        self.pull1.label = f"1뽑기 {PULL_PRICE}코인"
        self.pull5.label = f"{QUICK_PULLS}연속 {PULL_PRICE * QUICK_PULLS}코인"
        self.fuse1.label = f"합성 (중복 {FUSE_N}장)"

    @discord.ui.button(label="1뽑기", emoji="🎴", style=discord.ButtonStyle.success,
                       custom_id="akgui:card:pull1", row=0)
    async def pull1(self, interaction: discord.Interaction, button: discord.ui.Button):
        public = _is_card_channel(interaction)
        await interaction.response.defer(ephemeral=not public)
        await do_pull(interaction, pulls=1, ephemeral=not public)

    @discord.ui.button(label="연속뽑기", emoji="🎴", style=discord.ButtonStyle.primary,
                       custom_id="akgui:card:pull5", row=0)
    async def pull5(self, interaction: discord.Interaction, button: discord.ui.Button):
        public = _is_card_channel(interaction)
        await interaction.response.defer(ephemeral=not public)
        await do_pull(interaction, pulls=QUICK_PULLS, ephemeral=not public)

    @discord.ui.button(label="합성", emoji="⚒️", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:card:fuse1", row=1)
    async def fuse1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await do_fuse(interaction, times=1)

    @discord.ui.button(label="몰아 합성 (중복 전부)", emoji="⚒️",
                       style=discord.ButtonStyle.secondary,
                       custom_id="akgui:card:fuse_all", row=1)
    async def fuse_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        # `times=0`이 "중복이 바닥날 때까지"예요. 🎣 몰아 던지기와 같은 자리예요 —
        # 실측 최다 보유자가 **53회**라, 이게 없으면 버튼을 53번 눌러야 해요.
        await interaction.response.defer(ephemeral=True)
        await do_fuse(interaction, times=0)

    @discord.ui.button(label="내 도감", emoji="📖", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:card:dex", row=2)
    async def dex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_collection(interaction)


def _card_panel_embed() -> discord.Embed:
    """패널 설명. 🚨 **확률·가격을 손으로 적지 않아요** — 상수에서 만들어요.
    (2026-10-23에 낚시 등급표가 인상 전 값으로 7일간 남아 수익을 1/3 낮게 말한 적이 있어요)"""
    total_w = sum(GRADE_WEIGHTS.values())
    rates = " · ".join(
        f"{GRADE_EMOJI[g]}{GRADE_WEIGHTS[g] / total_w * 100:g}%" for g in GRADE_ORDER
    )
    embed = discord.Embed(
        title="🎴 악귀카드",
        description=(
            f"**{PULL_PRICE}코인에 {CARDS_PER_PULL}장**을 뽑아요. 전부 **{card_store.TOTAL}종**이에요.\n"
            f"　└ {rates}  (`/카드확률`로 천장까지 공개돼 있어요)\n\n"
            f"⚒️ **합성** — 쓸모없이 쌓인 **중복 {FUSE_N}장**을 넣으면 "
            f"**뽑기와 똑같은 확률로 1장**을 다시 굴려요.\n"
            f"　└ ⚪일반·🔵레어 중복만 재료가 돼요. 각 카드의 **마지막 1장은 안 먹어요**\n"
            f"　└ 🟣에픽·🟡레전드도 나올 수 있어요. 돌아온 일반도 중복이면 **또 재료**예요"
        ),
        color=GRADE_COLOR["레전드"],
    )
    embed.set_footer(text="합성 결과는 나만 보여요 · 🟡 레전드는 여기 홍보돼요")
    return embed


class GachaView(discord.ui.View):
    """뽑기 버튼 화면. `timeout=None`이라 시간이 지나도 안 죽어요."""

    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(GachaButton(user_id))
        self.add_item(GachaButton(user_id, QUICK_PULLS))


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


async def show_collection(interaction: discord.Interaction, grade: str | None = None):
    """📖 내 도감을 보여줘요. `/도감`과 📖 패널 버튼이 같이 써요.

    ⚠️ 부르기 전에 `defer(ephemeral=True)`가 끝나 있어야 해요."""
    state = await card_store.get_collection(interaction.user.id)
    counts = state["counts"]

    view = CollectionView(interaction.user.id, counts, state["since_legend"])

    if grade is None:
        await interaction.followup.send(
            embed=_overview_embed(view.summary, state["since_legend"], counts),
            view=view, ephemeral=True,
        )
        return

    view._build_grade(grade)
    embed, file = await _grade_payload(grade, counts, view.summary)
    # ⚠️ `file=None`을 그대로 넘기면 안 돼요(discord.py 기본값이 MISSING이라
    #    None을 "파일이 있다"로 봐요). 붙일 게 있을 때만 kwargs에 넣어요.
    extra = {"file": file} if file else {}
    await interaction.followup.send(embed=embed, view=view, ephemeral=True, **extra)


class CardGacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 패널 버튼을 눌러도 봇이 custom_id를 알아보지
        #    못해서 **아무 반응이 없어요**(에러도 안 나요).
        self.bot.add_view(CardPanelView())

    @app_commands.command(
        name="카드뽑기",
        description=f"악귀코인 {PULL_PRICE}개로 악귀카드 {CARDS_PER_PULL}장을 뽑아요. (연속뽑기 가능)",
    )
    @restrict_to_channel("card", "CARD_CHANNEL_ID")
    @app_commands.describe(
        횟수=f"연속으로 몇 번 뽑을지 (1~{card_store.MAX_PULLS}, 안 적으면 1회)"
    )
    async def pull_cards(
        self,
        interaction: discord.Interaction,
        횟수: app_commands.Range[int, 1, card_store.MAX_PULLS] = 1,
    ):
        # DB 왕복 + 이미지 합성이라 3초를 넘겨요.
        await interaction.response.defer()
        await do_pull(interaction, pulls=횟수)

    @app_commands.command(
        name="카드합성",
        description=f"쌓인 중복 {FUSE_N}장을 넣어 뽑기와 같은 확률로 카드 1장을 다시 굴려요.",
    )
    @restrict_to_channel("card", "CARD_CHANNEL_ID")
    @app_commands.describe(횟수="몇 번 합성할지 (안 적으면 1회, 0이면 중복이 바닥날 때까지)")
    async def fuse_cards(
        self,
        interaction: discord.Interaction,
        횟수: app_commands.Range[int, 0, card_store.MAX_FUSES] = 1,
    ):
        # DB 왕복 + 이미지 합성이라 3초를 넘겨요.
        # 합성 결과는 늘 본인에게만 — 쓸모없는 중복을 녹이는 정비 작업이라 채널을
        # 덮을 이유가 없어요(🟡 레전드만 따로 뽑기방에 홍보돼요).
        await interaction.response.defer(ephemeral=True)
        await do_fuse(interaction, times=횟수)

    @app_commands.command(
        name="카드패널",
        description="[서버 소유자 전용] 이 채널에 카드 패널을 박아둬요 (항상 떠 있어요).",
    )
    async def panel(self, interaction: discord.Interaction):
        """🎴 상설 패널을 **지금 이 채널에** 올려요. (🎣 `/낚시패널`과 같은 방식이에요)

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
            f"🎴 {channel.mention} 에 카드 패널을 올렸어요.\n"
            "-# 메시지를 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요. "
            "옮기려면 그 메시지를 지우고 다른 채널에서 다시 치면 돼요.",
            ephemeral=True,
        )
        await channel.send(embed=_card_panel_embed(), view=CardPanelView())
        log.info("🎴 카드 패널 게시: 채널 %s", channel.id)

    @app_commands.command(name="도감", description="내가 모은 악귀카드를 펼쳐 봐요.")
    # 📖 도감은 전용 채널(`#📖｜도감`)이에요. 뽑기 결과로 채널이 덮이지 않게 갈라뒀어요.
    # ⚠️ 설정이 없으면 제한이 풀리니, `fallback_group="card"`로 최소한 뽑기방에는
    #    묶이게 해둬요(그룹을 새로 쪼갤 때 쓰는 안전장치 - channel_check 주석 참고).
    @restrict_to_channel("card_dex", "CARD_DEX_CHANNEL_ID", fallback_group="card")
    @app_commands.describe(등급="바로 이 등급을 펼쳐요 (안 고르면 전체 진행도부터)")
    @app_commands.choices(등급=[
        app_commands.Choice(name=f"{GRADE_EMOJI[g]} {g}", value=g) for g in GRADE_ORDER
    ])
    async def collection(
        self, interaction: discord.Interaction, 등급: app_commands.Choice[str] | None = None
    ):
        # 본인 도감이라 ephemeral이에요. 채널이 남의 도감으로 덮이지 않아요.
        await interaction.response.defer(ephemeral=True)
        # 🚨 본체는 `show_collection`이에요 — 📖 패널 버튼이 같은 함수를 써요.
        #    복붙하면 한쪽만 고쳐져서 화면이 갈려요(🎣 낚시 패널에서 같은 이유로
        #    `act_tank`/`act_sell`을 모듈 함수로 뺐어요).
        await show_collection(interaction, 등급.value if 등급 else None)

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
            value=(f"**{PULL_PRICE}코인**에 **{CARDS_PER_PULL}장** "
                   f"(장당 {PULL_PRICE/CARDS_PER_PULL:.1f}코인)\n"
                   f"　└ `/카드뽑기 횟수:N` 으로 **최대 {card_store.MAX_PULLS}연속**까지 "
                   f"한 번에 돌릴 수 있어요 (할인은 없어요)"),
            inline=False,
        )
        embed.add_field(
            name="🟡 천장",
            value=(
                # ⚠️ 여기에 "N연속이면 레전드 확정" 같은 문구를 다시 넣지 마세요.
                #    천장이 240장(80뽑기)이라 한 번에 지를 수 있는 최대(10연=30장)로는
                #    **절대 천장에 못 닿아요.** 지키지 못할 약속이 돼요.
                f"레전드 없이 **{PITY_DRAWS}장**(= {PITY_DRAWS // CARDS_PER_PULL}뽑기)을 "
                f"뽑으면 그 장은 **레전드 확정**이에요.\n"
                f"　└ 아무리 운이 없어도 "
                f"**{PITY_DRAWS // CARDS_PER_PULL}뽑기"
                f"({PITY_DRAWS // CARDS_PER_PULL * PULL_PRICE}코인)** 안에는 반드시 나와요\n"
                f"　└ 보통은 그보다 훨씬 빨라요 — **평균 약 46뽑기(460코인)**에 한 장"
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
