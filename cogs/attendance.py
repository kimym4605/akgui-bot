import io
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from cogs import mission
from utils import profile_card, profile_service, stat_art
from utils.channel_check import channel_key, restrict_to_channel
from utils import attend_service
from utils.settings_store import set_setting

log = logging.getLogger(__name__)

COIN_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "coin.png"



def _fallback_embed(user: discord.abc.User, data: dict) -> discord.Embed:
    """Pillow가 없거나 카드를 그리다 실패했을 때 대신 띄우는 임베드예요.

    카드가 이 기능의 핵심이라 없으면 아쉽긴 한데, **명령어가 통째로 죽는 것보다는**
    글자로라도 보여주는 게 나아요(배포 직후 폰트/Pillow 문제로 전부 실패하는 상황 대비)."""
    record = data["record"]
    embed = discord.Embed(title=f"{data['name']}님의 악귀 프로필", color=0x5865F2)
    if data.get("title"):
        embed.description = f"「{data['title']}」"
    embed.add_field(name="VALORANT", value=data.get("tier") or "티어 미확인", inline=True)
    embed.add_field(name="악귀코인", value=f"{data['coin']:,}개", inline=True)
    embed.add_field(
        name="내전 전적",
        value=(f"{record['wins']}승 {record['losses']}패 (승률 {record['win_rate']:.0f}%)"
               if record["wins"] + record["losses"] else "아직 기록 없음"),
        inline=True,
    )
    embed.add_field(name="최고 연승", value=f"{record['best_streak']}", inline=True)
    embed.add_field(
        name="이번 주 악귀력",
        value=f"{data['agwi']:,.0f}" if data.get("agwi") else "`/전적`을 돌려주세요",
        inline=True,
    )
    voice = data.get("voice") or {}
    embed.add_field(
        name="🎙️ 음성 레벨",
        value=f"Lv.{voice.get('level', 0)}" if voice.get("minutes") else "-", inline=True,
    )
    fishing = data.get("fishing") or {}
    best = fishing.get("best") or {}
    embed.add_field(
        name="🎣 낚시",
        value=(f"{fishing.get('caught', 0):,}마리"
               + (f" (최대 {best['name']})" if best.get("name") else ""))
        if fishing.get("caught") else "-",
        inline=True,
    )
    embed.add_field(name="📋 누적 미션", value=f"{data.get('mission_total', 0):,}개", inline=True)
    embed.add_field(
        name="📅 출석",
        value=f"연속 {data.get('attendance_streak', 0)}일 · 누적 {data.get('attendance', 0)}회",
        inline=True,
    )
    embed.add_field(
        name="업적", value=f"{data['achievements']} / {data['achievements_total']}", inline=True
    )
    return embed


# ============================================================
# 카드 아래 버튼 (🏆 업적 · 🎯 발로란트 전적)
#
# 예전엔 "🐾 포켓몬 상세" 버튼도 있었는데, 2026-09-30에 포켓몬 기능을 접으면서 뺐어요.
# custom_id 정규식에서도 pokemon을 지웠으니, 그 전에 띄워둔 옛 카드의 포켓몬 버튼은
# 눌러도 아무 반응이 없어요(패턴이 안 맞아 되살아나지 않아요). 새로 `/프로필`을 부르면 돼요.
#
# ⚠️ 평범한 View가 아니라 DynamicItem인 이유 — 2026-09-29에 실제로 당했어요.
#
# 처음엔 `discord.ui.View(timeout=300)` 에 버튼을 달았는데, 보통의 View는 **봇이 재시작되면
# 메모리에서 사라져요.** 배포할 때마다 그 전에 띄워둔 카드의 버튼이 전부 죽어서, 눌러도
# 아무 반응이 없고 로그조차 안 남아요(핸들러에 진입을 못 하니까요). 5분 타임아웃도 짧아서
# 조금만 지나면 같은 증상이 났어요.
#
# DynamicItem은 버튼의 custom_id 문자열에 필요한 정보(누구 카드인지)를 다 박아두고, 눌린
# 순간 그걸 정규식으로 다시 꺼내 살아나요. 그래서 봇이 재시작돼도, 며칠 전 카드라도 그대로
# 동작해요. utils/dynamic_room.py의 SpeakGrantButton과 같은 방식이에요.
# ============================================================
class ProfileButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"profile:(?P<kind>achv|rank):(?P<user_id>\d+)",
):
    # kind -> (라벨, 이모지)
    KINDS = {
        "achv": ("업적 보기", "🏆"),
        "rank": ("발로란트 전적", "🎯"),
    }

    def __init__(self, kind: str, user_id: int):
        label, emoji = self.KINDS[kind]
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"profile:{kind}:{user_id}",
            )
        )
        self.kind = kind
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["kind"], int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """카드 주인만 누를 수 있어요.

        버튼이 전부 **카드 주인의** 정보를 여는 거라, 남이 눌렀을 때 누른 사람 것을
        보여주면 "내 카드인데 남의 전적이 뜨는" 식으로 엇갈려요."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "이 카드의 주인만 누를 수 있어요. `/프로필`로 본인 카드를 열어주세요.", ephemeral=True
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        # 버튼이 눌렸다는 흔적을 남겨둬요. 안 되던 시절엔 로그가 없어서 "눌렸는지조차"
        # 알 수 없었고, 그게 원인 찾기를 제일 어렵게 했어요.
        log.info("🎴 프로필 카드 버튼: kind=%s user=%s", self.kind, interaction.user.id)
        await interaction.response.defer(ephemeral=True)

        if self.kind == "achv":
            await self._send_achievements(interaction)
        else:
            await self._send_rank(interaction)

    async def _send_achievements(self, interaction: discord.Interaction):
        # 업적 화면은 achievement cog가 갖고 있어요(거기가 주인이라 서식도 거기 하나뿐이에요).
        from cogs.achievement import build_achievement_embed

        embed = await build_achievement_embed(interaction.user)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _send_rank(self, interaction: discord.Interaction):
        """`/전적`과 **똑같은 리포트**를 카드에서 바로 열어요.

        카드에 티어와 악귀력은 있지만 그건 저장해둔 값이라, KDA·ADR·HS%·선호 요원처럼
        경기를 실제로 뒤져야 나오는 건 없어요. rank cog의 조회를 그대로 불러요
        (서식이 두 벌이 되지 않게 `/전적` 본문을 함수로 갈라서 같이 써요).

        ⚠️ HenrikDev를 실제로 호출해요. 카드를 열 때마다가 아니라 **버튼을 눌렀을 때만**
        나가니까, `/전적`을 한 번 치는 것과 비용이 같아요."""
        rank_cog = interaction.client.get_cog("Rank")
        if rank_cog is None:
            await interaction.followup.send(
                "지금은 전적 기능을 쓸 수 없어요. 잠시 후 `/전적`으로 시도해주세요.", ephemeral=True
            )
            return
        # 본인에게만 보이게 해요. `/전적`은 #전적검색에 묶여 있는데 카드는 아무 채널에서나
        # 열리거든요 — ephemeral이면 그 채널이 전적 리포트로 덮이지 않아요.
        await rank_cog.send_rank_report(interaction, ephemeral=True)


# ============================================================
# 📋 자세히 보기 메뉴 (2026-11-15)
#
# 카드엔 내전·악귀력·음성·낚시·출석·미션·코인이 다 한 줄씩 있는데, 펼쳐볼 수 있는 건
# 업적·발로란트 전적 버튼 2개뿐이었어요. 버튼을 7개로 늘리면 카드 밑이 버튼으로 덮여서
# **드롭다운 하나**로 모았어요(항목이 늘어도 한 줄이에요).
#
# ⚠️ 위 ProfileButton은 **지우지 마세요.** 이 메뉴 이전에 띄운 카드들의 버튼이 아직
#    채널에 남아 있고, 등록이 빠지면 그 버튼들이 조용히 죽어요.
#
# ⚠️ 각 화면은 원래 명령어(/내전전적·/음성레벨·/어항 …)의 **빌더 함수를 그대로** 불러요.
#    여기서 서식을 새로 짜면 같은 정보가 두 모양으로 나와요.
# ============================================================
class ProfileMoreSelect(
    discord.ui.DynamicItem[discord.ui.Select],
    template=r"profile:more:(?P<user_id>\d+)",
):
    # value -> (라벨, 이모지, 설명)
    OPTIONS = {
        "achv":   ("업적", "🏆", "달성한 업적 · 거의 다 온 업적"),
        "rank":   ("발로란트 전적", "🎯", "KDA · ADR · HS% · 선호 요원 (/전적과 같아요)"),
        "scrim":  ("내전 전적", "⚔️", "통산·시즌 승패 · 최근 5경기 · 맵별 성적"),
        "voice":  ("음성 레벨", "🎙️", "누적·이번 주 시간 · 서버 순위 · 다음 레벨"),
        "fish":   ("낚시", "🎣", "어항 · 최고 기록 · 챔질 성공률 · 낚시대"),
        "attend": ("출석", "📅", "연속·누적 출석 · 보호권 · 다음 보너스"),
        "coin":   ("코인", "🪙", "보유 코인 · 최근 입출금 10건"),
        "theme":  ("테마 바꾸기", "🎨", "내가 가진 테마로 카드 배경을 바꿔요 (무료)"),
    }

    def __init__(self, user_id: int):
        super().__init__(
            discord.ui.Select(
                placeholder="📋 자세히 보기",
                custom_id=f"profile:more:{user_id}",
                options=[
                    discord.SelectOption(label=label, value=key, emoji=emoji, description=desc)
                    for key, (label, emoji, desc) in self.OPTIONS.items()
                ],
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Select, match):
        return cls(int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """카드 주인만 열 수 있어요(사용자 결정 2026-11-15). 🪙 코인 내역이 섞여 있어서요."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "이 카드의 주인만 열 수 있어요. `/프로필`로 본인 카드를 열어주세요.", ephemeral=True
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        kind = (self.item.values or [""])[0]
        log.info("🎴 프로필 자세히 보기: kind=%s user=%s", kind, interaction.user.id)

        # 3초 안에 ack부터. 컴포넌트에서 thinking 없는 defer는 '카드는 그대로 둔다'는 뜻이에요.
        await interaction.response.defer()

        try:
            await self._send(interaction, kind)
        except Exception:
            log.exception("🎴 프로필 자세히 보기 실패: kind=%s user=%s", kind, interaction.user.id)
            await interaction.followup.send(
                "화면을 불러오지 못했어요. 잠시 후 다시 시도해주세요.", ephemeral=True
            )

        # ⭐ 메뉴를 빈 상태로 되돌려요. 드롭다운은 고른 값이 남아 있으면 **같은 항목을 다시
        #    골라도 이벤트가 안 와요.** 방금 본 걸 또 열 수 있게 매번 새로 그려요.
        try:
            await interaction.edit_original_response(view=build_profile_view(self.user_id))
        except discord.HTTPException:
            pass  # 카드가 지워졌으면 되돌릴 메뉴도 없어요.

    async def _send(self, interaction: discord.Interaction, kind: str):
        user = interaction.user
        send = interaction.followup.send

        if kind == "achv":
            from cogs.achievement import build_achievement_embed
            await send(embed=await build_achievement_embed(user), ephemeral=True)

        elif kind == "rank":
            rank_cog = interaction.client.get_cog("Rank")
            if rank_cog is None:
                await send("지금은 전적 기능을 쓸 수 없어요. 잠시 후 `/전적`으로 시도해주세요.",
                           ephemeral=True)
                return
            await rank_cog.send_rank_report(interaction, ephemeral=True)

        elif kind == "scrim":
            from cogs.achievement import attach_scrim_card, build_scrim_embed, scrim_empty_text
            embed = await build_scrim_embed(user)
            if embed is None:
                await send(scrim_empty_text(user), ephemeral=True)
            else:
                card = await attach_scrim_card(user, embed)       # ⚔️ 그림 카드 (못 그리면 글 그대로)
                await send(embed=embed, files=[card] if card else [], ephemeral=True)

        elif kind == "voice":
            from cogs.voice_rank import build_voice_embed
            await send(embed=await build_voice_embed(user), ephemeral=True)

        elif kind == "fish":
            # 🪣 글 + 어항 그림(2026-11-22). 그림이 실패하면 files가 비어서 글만 나가요.
            from cogs.fishing import build_tank_reply
            embed, files = await build_tank_reply(user)
            await send(embed=embed, files=files, ephemeral=True)

        elif kind == "attend":
            await send(embed=await build_attend_embed(user), ephemeral=True)

        elif kind == "coin":
            from cogs.coin import build_coin_embed
            await send(embed=await build_coin_embed(user), ephemeral=True)

        elif kind == "theme":
            await send_theme_switcher(interaction, card_message=interaction.message)

        else:
            await send("알 수 없는 항목이에요. `/프로필`을 다시 열어주세요.", ephemeral=True)


async def build_attend_embed(user: discord.abc.User) -> discord.Embed:
    """📅 출석 상세. 출석 데이터는 이 cog가 주인이라 화면도 여기 있어요."""
    st = await attend_service.status(user.id)
    streak = st["streak"]

    embed = discord.Embed(title=f"📅 {user.display_name}님의 출석", color=0xFFC850)
    embed.add_field(name="🔥 연속", value=f"**{streak}일**", inline=True)
    embed.add_field(name="📅 누적", value=f"**{st['total']}회**", inline=True)
    embed.add_field(name="🧊 보호권", value=f"**{st['protect']}개**", inline=True)

    if st["done_today"]:
        today = "✅ 오늘 출석했어요"
    elif st["at_risk"]:
        today = f"⏳ **아직이에요** — 오늘 안 하면 연속 {streak}일이 끊겨요"
    elif st["protectable"]:
        today = ("🧊 어제 빠졌어요. " + ("오늘 출석하면 **보호권이 자동으로 쓰여서** 이어져요"
                 if st["protect"] else "`/악귀상점`에서 보호권을 사고 출석하면 이어져요"))
    else:
        today = "⏳ 아직이에요 — `/출석`으로 시작해요"
    embed.add_field(name="오늘", value=today, inline=False)

    # 다음에 받을 보너스. 오늘 했으면 내일 기준, 아직이면 오늘 출석 기준이에요.
    nxt = streak + 1
    lines = []
    bonus = attend_service.streak_bonus(nxt)
    if bonus:
        lines.append(f"연속 보너스 **+{bonus}코인** (매일)")
    else:
        lines.append(f"연속 7일부터 매일 +1코인 — **{7 - nxt}일** 더")
    to_week = attend_service.WEEKLY_BONUS_EVERY - (nxt % attend_service.WEEKLY_BONUS_EVERY)
    if nxt % attend_service.WEEKLY_BONUS_EVERY == 0:
        lines.append(f"🎁 다음 출석이 **{nxt}일째** — 주간 보너스 +{attend_service.WEEKLY_BONUS_COIN}코인")
    else:
        lines.append(f"🎁 주간 보너스 +{attend_service.WEEKLY_BONUS_COIN}코인까지 **{to_week}일**")
    if 7 <= nxt < 30:
        lines.append(f"연속 30일부터 매일 +2코인 — **{30 - nxt}일** 더")
    embed.add_field(name="다음 출석 때", value="\n".join(lines), inline=False)
    if st["last_date"]:
        embed.set_footer(text=f"마지막 출석 {st['last_date']}")
    return embed


# ── 🎨 프로필에서 테마 바꾸기 (2026-11-22 사용자 요청) ─────────────────────────
# 산 테마끼리 바꾸려면 `/악귀상점`을 열어야 했고, 거기엔 안 산 테마가 가격과 같이 섞여 있어서
# "다시 사야 하나?"로 보였어요. 프로필에서는 **가진 것만** 보여주고 고르면 바로(무료) 바꿔요.
# 🚨 여기서는 **절대 코인을 안 빼요.** 사는 건 상점 몫이에요 - 그래서 고른 값이 정말 보유 중인지
#    누를 때 DB로 다시 확인해요(드롭다운은 3분 동안 남아 있어서 그 사이 상태가 바뀔 수 있어요).

async def owned_theme_choices(user_id: int) -> tuple[list[tuple[str, str, str]], str]:
    """([(키, 이모지, 설명)], 지금 테마). 지금 상점에 있는 테마 중 **가진 것만**.

    🖼️ 커스텀(내 그림)은 승인된 그림이 있을 때만 넣어요(없는데 고르면 기본 배경이 나와요)."""
    from utils import cosmetic_store, custom_theme_store
    state = await cosmetic_store.get(user_id)
    owned, selected = state["themes"], state["theme"]
    out: list[tuple[str, str, str]] = []
    for key in owned:
        if key == profile_card.CUSTOM_THEME_KEY:
            try:
                has_art = (await custom_theme_store.status(user_id))["has_image"]
            except Exception:                                # noqa: BLE001
                has_art = False
            if has_art:
                info = profile_card.CUSTOM_THEME
                out.append((key, info["emoji"], info["desc"]))
            continue
        info = profile_card.ALL_THEMES.get(key)
        if info is None:          # 방장이 뺀 테마는 못 골라요(카드가 기본으로 그려져요)
            continue
        out.append((key, info["emoji"], info["desc"]))
    return out[:25], selected      # 드롭다운 한도 25개


class ThemeSwitchSelect(discord.ui.Select):
    def __init__(self, user_id: int, choices: list[tuple[str, str, str]], selected: str,
                 card_message: discord.Message | None):
        super().__init__(
            placeholder="🎨 바꿀 테마를 골라요 (가진 것만)",
            options=[discord.SelectOption(label=key, value=key, emoji=emoji, description=desc[:100],
                                          default=(key == selected))
                     for key, emoji, desc in choices],
        )
        self.user_id = user_id
        self.card_message = card_message

    async def callback(self, interaction: discord.Interaction):
        from utils import cosmetic_store
        key = self.values[0]
        await interaction.response.defer()
        choices, _ = await owned_theme_choices(self.user_id)
        if key not in {k for k, *_ in choices}:
            await interaction.edit_original_response(
                content=f"⚠️ **{key}** 테마는 지금 가지고 있지 않아요. 사는 건 `/악귀상점`에서 해요.",
                view=None)
            return
        await cosmetic_store.select_theme(self.user_id, key)
        log.info("🎨 프로필에서 테마 변경: user=%s → %s", self.user_id, key)
        done = f"🎨 카드 테마를 **{key}**(으)로 바꿨어요."

        # 카드를 새 테마로 다시 그려서 **그 자리에서** 바꿔요. 못 바꾸면 새 카드를 나만 보이게 보여줘요.
        png = None
        try:
            data = await profile_service.collect(interaction.user)
            avatar = await profile_service.avatar_for(interaction.user)
            png = await profile_card.render_card(data, avatar)
        except Exception:                                    # noqa: BLE001
            log.exception("🎨 테마 바꾼 뒤 카드 다시 그리기 실패 (user=%s)", self.user_id)
        if png is None:
            await interaction.edit_original_response(
                content=done + " `/프로필`을 다시 치면 보여요.", view=None)
            return
        name = f"agwi_profile_{self.user_id}.png"
        if self.card_message is not None:
            try:
                await self.card_message.edit(attachments=[discord.File(io.BytesIO(png), filename=name)],
                                             view=build_profile_view(self.user_id))
                await interaction.edit_original_response(content=done + " 카드도 바꿔 뒀어요.", view=None)
                return
            except discord.HTTPException:
                log.info("🎨 카드 제자리 교체 실패 → 새 카드를 나만 보이게 보내요 (user=%s)", self.user_id)
        await interaction.edit_original_response(content=done + " (`/프로필`을 다시 치면 모두에게 이렇게 보여요)",
                                                 view=None,
                                                 attachments=[discord.File(io.BytesIO(png), filename=name)])


class ThemeSwitchView(discord.ui.View):
    """나만 보이는 메시지에 붙는 일회용 메뉴(영속 아님 - 3분 뒤 꺼져요)."""

    def __init__(self, user_id: int, choices, selected: str, card_message):
        super().__init__(timeout=180)
        self.add_item(ThemeSwitchSelect(user_id, choices, selected, card_message))


async def send_theme_switcher(interaction: discord.Interaction, *, card_message) -> None:
    choices, selected = await owned_theme_choices(interaction.user.id)
    if len(choices) <= 1:
        await interaction.followup.send(
            "🎨 아직 **기본 테마**만 있어요. 테마는 `/악귀상점` → 🎨 프로필 카드 테마에서 살 수 있어요.\n"
            "-# 한 번 산 테마는 여기서 언제든 무료로 바꿔 낄 수 있어요.", ephemeral=True)
        return
    await interaction.followup.send(
        f"🎨 **가지고 있는 테마 {len(choices)}개** · 지금은 **{selected}**\n"
        "-# 고르면 바로 바뀌어요(무료). 새 테마 구매는 `/악귀상점`에서 해요.",
        view=ThemeSwitchView(interaction.user.id, choices, selected, card_message), ephemeral=True)


def build_profile_view(user_id: int) -> discord.ui.View:
    """카드에 붙일 📋 자세히 보기 메뉴. `timeout=None` + DynamicItem이라 재시작돼도 살아 있어요."""
    view = discord.ui.View(timeout=None)
    view.add_item(ProfileMoreSelect(user_id))
    return view


async def send_profile_card(interaction: discord.Interaction, target: discord.abc.User):
    """악귀 프로필 카드를 그려서 보내요. `/프로필`과 `/악귀프로필`이 같이 써요.

    ⚠️ 이 함수를 부르기 전에 반드시 `defer()`가 끝나 있어야 해요."""
    data = await profile_service.collect(target)
    avatar = await profile_service.avatar_for(target)
    png = await profile_card.render_card(data, avatar)

    view = build_profile_view(target.id)
    content = None

    # 카드를 보는 것만으로 밀린 업적이 열려요. 열렸으면 같이 알려줘야 코인이 왜 늘었는지 알죠.
    newly = data.get("newly_unlocked") or []
    if newly:
        total_reward = sum(a["reward"] for a in newly)
        names = ", ".join(f"{a['emoji']} **{a['name']}**" for a in newly[:5])
        if len(newly) > 5:
            names += f" 외 {len(newly) - 5}개"
        content = f"🎉 새 업적 {len(newly)}개 달성! {names} (+{total_reward}코인)"

    # 버튼이 영속(DynamicItem)이라 메시지를 붙잡아둘 필요가 없어요. 시간이 지나도, 봇이
    # 재시작돼도 custom_id만으로 되살아나니까 `view.message`를 기억하지 않아요.
    if png is None:
        await interaction.followup.send(
            content=content, embed=_fallback_embed(target, data), view=view
        )
    else:
        file = discord.File(io.BytesIO(png), filename=f"agwi_profile_{target.id}.png")
        await interaction.followup.send(content=content, file=file, view=view)


class Attendance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="출석순위", description="연속 출석·누적 출석 순위를 봐요.")
    @restrict_to_channel("attend")
    async def attend_ranking(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await attend_service.rankings(limit=10)

        def render(rows, suffix: str) -> str:
            if not rows:
                return "아직 아무도 없어요."
            medals = ["🥇", "🥈", "🥉"]
            out = []
            for i, row in enumerate(rows):
                uid, value = row[0], row[1]
                mark = medals[i] if i < 3 else f"`{i + 1}.`"
                # 오늘 아직 출석 안 한 사람은 표시해줘요(연속 순위에서만 세 번째 값이 있어요).
                todo = "" if len(row) < 3 or row[2] else " ⏳"
                out.append(f"{mark} <@{uid}> — **{value}{suffix}**{todo}")
            return "\n".join(out)

        embed = discord.Embed(
            title="🏆 출석 순위",
            color=0xFFC850,
            description="-# ⏳ 는 오늘 출석을 아직 안 한 사람이에요.",
        )
        # 🏆 순위표 그림(2026-11-23). 그리면 글 목록 두 칸 대신 그림, ⏳는 "오늘 출석 전"으로.
        def rows_of(rows, suffix):
            return [{"rank": i + 1, "uid": r[0], "value": f"{r[1]}{suffix}",
                     "sub": "" if len(r) < 3 or r[2] else "오늘 출석 전"} for i, r in enumerate(rows)]
        board_file = await stat_art.board_attach(
            embed, interaction.guild, "출석 순위", "매일 /출석 으로 이어가요",
            [{"title": "연속 출석", "rows": rows_of(data["streak"], "일")},
             {"title": "누적 출석", "rows": rows_of(data["total"], "회")}], 0xFFC850)
        if board_file is not None:
            embed.description = None
        else:
            embed.add_field(name="🔥 연속 출석", value=render(data["streak"], "일"), inline=False)
            embed.add_field(name="📅 누적 출석", value=render(data["total"], "회"), inline=False)
        if data["risky"]:
            names = " · ".join(f"<@{uid}> ({streak}일)" for uid, streak in data["risky"])
            embed.add_field(
                name="🧊 오늘 안 오면 끊겨요",
                value=f"{names}\n-# `/악귀상점`의 출석 보호권으로 되살릴 수 있어요.",
                inline=False,
            )
        # 멘션 글씨는 보이되 핑은 안 쏴요 (순위표가 사람들을 호출하면 시끄러워요).
        extra = {"file": board_file} if board_file is not None else {}
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(), **extra)

    @app_commands.command(name="출석", description="오늘의 출석체크를 합니다. (하루 1회, 악귀코인 획득)")
    @restrict_to_channel("attend")
    async def do_attend(self, interaction: discord.Interaction):
        # DB를 건드리기 전에 먼저 defer해요. DB 왕복이 3초를 넘기면 디스코드가
        # "애플리케이션이 응답하지 않았습니다"로 끊어버리거든요.
        await interaction.response.defer()

        # 누구나 출석할 수 있어요. 코인이 어디에 쌓이는지(트레이너 문서 / 지갑)는
        # utils/attend_service.py가 알아서 골라줘요.
        success, info = await attend_service.attend(interaction.user.id)

        if not success:
            await interaction.followup.send(
                f"오늘은 이미 출석하셨어요. 보유 악귀코인: **{info['coin']}개** "
                f"· 연속 출석 **{info['streak']}일째** · 내일 또 출석해주세요!",
                ephemeral=True,
            )
            return

        # 🎯 📅 출석 미션 (2026-10-23). **출석이 성공한 뒤에만** 불러요.
        #
        # 🚨 `COMMAND_MISSIONS`(명령어 완료 감지)에 "출석"을 넣으면 안 돼요. 출석은 하루
        #    1회라 **이미 출석한 사람이 다시 쳐도** 명령어는 정상 종료되고, 그러면 위의
        #    `if not success: return`에 걸린 사람까지 미션이 깨져요(= 공짜 3코인 — 📅 출석
        #    미션은 🔵보통이에요).
        # ⚠️ 예외는 `on_action`이 안에서 삼켜요. 미션 때문에 출석이 깨지면 안 되니까요.
        await mission.on_action(
            interaction.user.id, "attend_check", interaction, interaction.user
        )

        streak = info["streak"]
        lines = [f"획득 악귀코인: **+{info['coinGain']}개**"]
        # 보너스가 붙었으면 **왜 더 받았는지** 한 줄로 보여줘요. 숫자만 바뀌면 왜 늘었는지 몰라요.
        if info.get("streakBonus"):
            lines.append(f"　└ 🔥 연속 {streak}일 보너스 **+{info['streakBonus']}**")
        if info.get("weeklyBonus"):
            lines.append(f"　└ 📅 {attend_service.WEEKLY_BONUS_EVERY}일 개근 보너스 **+{info['weeklyBonus']}**")
        lines.append(f"보유 악귀코인: **{info['coin']}개**")
        lines.append(f"🔥 연속 출석: **{streak}일째**")
        if info.get("usedProtect"):
            lines.append("🧊 **출석 보호권을 써서 연속이 안 끊겼어요!** (어제 빠진 걸 메웠어요)")
        elif info.get("brokenPrev"):
            # 🧊 보호권 소급 (2026-11-05 서아 사례). 끊긴 걸 **보고 나서** 사도 되게 바꿨으니
            #    그 사실을 이 자리에서 알려줘요. ⚠️ 버튼은 달지 않아요(아래 🚨 사용자 지시).
            lines.append(
                f"💔 어제 빠져서 연속 **{info['brokenPrev']}일**이 끊겼어요.\n"
                "-# **오늘 안에** `/악귀상점`에서 🧊 출석 보호권을 사면 바로 되살아나요."
            )
        else:
            # 다음 보너스까지 얼마나 남았는지 알려줘요. 이게 없으면 연속이 그냥 숫자예요.
            to_weekly = attend_service.WEEKLY_BONUS_EVERY - (streak % attend_service.WEEKLY_BONUS_EVERY)
            next_tier = next(
                (t for t, _ in reversed(attend_service.STREAK_BONUS_TIERS) if streak < t), None
            )
            tail = f"-# {to_weekly}일 더 모으면 개근 보너스 **+{attend_service.WEEKLY_BONUS_COIN}**"
            if next_tier:
                tail += f" · {next_tier - streak}일 더 가면 매일 받는 코인이 올라요"
            lines.append(tail)

        embed = discord.Embed(
            title="✅ 출석 완료!",
            description="\n".join(lines),
            color=0x57F287,
        )
        embed.set_thumbnail(url="attachment://coin.png")
        coin_file = discord.File(COIN_IMAGE_PATH, filename="coin.png")

        # 🚨 **여기에 소비 버튼을 붙이지 마세요** (2026-10-17 사용자 지시).
        #
        # 한동안 🎴 카드 뽑기 버튼(10코인·5연속)이 이 응답에 달려 있었어요. "상점에
        # 진열만 하면 안 쓰인다"(리롤권·보호권·테마가 열흘간 0건)는 실측 교훈을 적용해
        # "코인이 손에 들어오는 순간"에 붙인 건데, **그 자리를 `/출석`으로 고른 건
        # 사용자에게 묻지 않은 판단이었어요.** 사용자가 "출석에 카드뽑기가 들어가면
        # 안 된다"고 해서 뗐어요(`2f12c8b`에서 들어왔고 여기서 제거).
        #
        # ⭐ 교훈 자체는 여전히 유효해요 — 소비처는 "막힌 그 자리"에 붙어야 팔려요
        #    (🔓 도박 한도 연장권이 그래서 팔렸어요). 다만 **출석은 코인을 받는
        #    자리**라 성격이 반대고, 어디에 붙일지는 **먼저 물어볼 것.**
        #    -> [[project_akgui_shop_coin_sinks]] · [[project_akgui_card_gacha]]
        await interaction.followup.send(embed=embed, file=coin_file)

    @app_commands.command(name="프로필", description="내 악귀 프로필 카드를 봐요. (내전 · 악귀력 · 음성 레벨 · 낚시 · 업적)")
    # ⚠️ 채널 그룹이 "attendance"(=#포켓몬)가 아니라 "profile"이에요.
    #
    # 예전 /프로필은 포켓몬 전용이라 #포켓몬에 묶는 게 맞았어요. 지금은 카드 내용의 대부분이
    # 티어·내전 전적·연승·악귀력·칭호(발로란트/서버 활동)고 포켓몬은 맨 아래 한 줄이에요.
    # 게다가 전적이 **쌓이는** 곳(/팀짜기 승리 버튼)은 아무 채널에서나 되는데 **보는** 곳만
    # 묶여 있으면 앞뒤가 안 맞아요.
    #
    # 2026-09-29에 실제로 재보니 #포켓몬은 50개 글이 쌓이는 데 23일이 걸리고 마지막 글이
    # 9일 전이었어요(#일반❓은 하루에 50개). 그래서 별도 그룹으로 떼어냈어요.
    # 설정값이 없으면 제한이 없으니 **기본은 아무 채널에서나** 되고, 도배가 문제되면
    # `/채널설정 프로필 #채널`로 언제든 묶을 수 있어요(재배포 필요 없어요).
    @restrict_to_channel("profile")
    async def profile(self, interaction: discord.Interaction):
        # 카드 렌더링 + DB 조회가 여럿이라 3초를 넘길 수 있어요.
        await interaction.response.defer()

        # 본인 카드만 봐요. 남의 프로필을 지정해서 꺼내보는 건 일부러 막아뒀어요.
        await send_profile_card(interaction, interaction.user)

    # 노래방만 "명령어를 친 채널"이 아니라 "들어가 있는 음성채널"을 보기 때문에 음성채널을 받아요.
    VOICE_GROUPS = {"karaoke"}

    @app_commands.command(name="채널설정", description="[서버 소유자 전용] 각 명령어를 쓸 수 있는 채널을 지정해요.")
    @app_commands.describe(기능="채널을 지정할 명령어 그룹", 채널="이 그룹의 명령어를 허용할 채널 (노래방만 음성채널)")
    @app_commands.choices(기능=[
        app_commands.Choice(name="출석 명령어 (/출석)", value="attend"),
        app_commands.Choice(name="프로필·업적 (/프로필, /업적, /주간랭킹)", value="profile"),
        app_commands.Choice(name="내전 전적 (/내전전적)", value="scrim_record"),
        app_commands.Choice(name="악귀코인 (/코인, /코인보내기)", value="coin"),
        app_commands.Choice(name="칭호 상점 (/칭호구매, /칭호, /칭호해제)", value="title"),
        app_commands.Choice(name="미션 (/미션)", value="mission"),
        app_commands.Choice(name="도박 (/도박 슬롯·하이로우·블랙잭)", value="casino"),
        app_commands.Choice(name="악귀카드 뽑기 (/카드뽑기, /카드확률)", value="card"),
        app_commands.Choice(name="악귀카드 거래 (/카드거래, /거래함)", value="card_market"),
        app_commands.Choice(name="악귀카드 도감 (/도감)", value="card_dex"),
        app_commands.Choice(name="🎣 낚시 (/낚시, /어항, /물고기판매, /낚시왕)", value="fishing"),
        app_commands.Choice(name="즉석생성형 통화방 명령어 (/방만들기 등)", value="room"),
        app_commands.Choice(name="전적 조회 명령어 (/전적)", value="tier_lookup"),
        app_commands.Choice(name="발로란트 개인 상점 (/오상)", value="valorant_shop"),
        app_commands.Choice(name="노래방 음성채널 (/재생 등) — 음성채널을 골라주세요", value="karaoke"),
        app_commands.Choice(name="❓ 봇 매니저 (질문을 적으면 답해주는 채널)", value="assistant"),
        app_commands.Choice(name="🔔 경기 결과 자동 알림 (끄려면 지정하지 마세요)", value="match_feed"),
        app_commands.Choice(name="💡 건의함 (/건의, /건의목록)", value="suggestion"),
        app_commands.Choice(name="📅 일정 (/일정, /일정목록)", value="event"),
        # ⚠️ 선택지는 디스코드 한도가 25개예요. 지금 21개.
        app_commands.Choice(name="🏆 주간결산 (🏅 주간MVP · 🎣 낚시 대회 발표)", value="weekly"),
    ])
    async def set_channel(
        self,
        interaction: discord.Interaction,
        기능: app_commands.Choice[str],
        채널: discord.TextChannel | discord.VoiceChannel,
    ):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return

        # 그룹마다 필요한 채널 종류가 달라서, 잘못 고르면 저장하기 전에 막아줘요.
        wants_voice = 기능.value in self.VOICE_GROUPS
        is_voice = isinstance(채널, discord.VoiceChannel)
        if wants_voice and not is_voice:
            await interaction.response.send_message(
                f"**{기능.name}**는 음성채널을 골라주세요. (지금 고른 {채널.mention}은 텍스트 채널이에요)",
                ephemeral=True,
            )
            return
        if not wants_voice and is_voice:
            await interaction.response.send_message(
                f"**{기능.name}**는 텍스트 채널을 골라주세요. (지금 고른 {채널.mention}은 음성채널이에요)",
                ephemeral=True,
            )
            return

        set_setting(channel_key(기능.value), 채널.id)
        where = "음성채널에 들어가 있어야" if wants_voice else "채널에서만"
        await interaction.response.send_message(
            f"✅ **{기능.name}**는 이제 {채널.mention} {where} 사용할 수 있어요.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Attendance(bot))
    # ⚠️ 이 등록이 없으면 카드 버튼을 눌러도 봇이 custom_id를 알아보지 못해서
    #    아무 반응이 없어요(room.py의 SpeakGrantButton과 같아요).
    # ProfileButton은 11/15 이전 카드용(지우지 말 것), ProfileMoreSelect가 지금 카드의 메뉴예요.
    bot.add_dynamic_items(ProfileButton, ProfileMoreSelect)