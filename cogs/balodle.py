"""🧩 발로들 — 하루 한 번 발로란트 요원·스킬·맵을 맞히는 퍼즐 (2026-11-24).

전용 채널의 **상설 패널**에서 버튼을 누르면 나만 보이는 문제 화면이 떠요. 다 풀면 정답은 가린
결과 칸(🟩🟨⬛)만 채널에 올라가요. 규칙은 볼트 `악귀봇 설계서`, 문구·색·그림은 `악귀봇 디자인`.

## 나눠 둔 곳

- 채점·이름 인식·보상·연속 규칙  → `utils/balodle_logic.py` (DB·디스코드를 몰라요)
- 요원·스킬·설정 JSON           → `utils/balodle_data.py` (`config/balodle/`)
- DB                           → `utils/balodle_store.py` (`balodle_days`·`_plays`·`_users`)
- 그림                         → `utils/balodle_art.py`
- 여기                         → 화면과 흐름만

## 🚨 영속 뷰 규칙 (셋 중 하나만 빠져도 재시작 뒤 패널 버튼이 죽어요)
1. `timeout=None`
2. 버튼마다 **고정 `custom_id`** (`akgui:balodle:*`)
3. `cog_load`에서 `bot.add_view(BalodlePanelView())`
→ `scripts/test_balodle.py`와 `scripts/test_cog_load.py`가 검사해요.

## 🚨 패널 버튼은 패널 메시지를 고치지 않아요
누른 사람에게만 보이는 **새 ephemeral 화면**을 띄워요. 패널은 봇 전체에 하나뿐인 뷰라
`self`에 상태를 담지도 않아요(누른 사람은 `interaction.user`로만 알아내요).

## 🚨 `[정답 입력]` 버튼은 `ack` 없이 바로 `send_modal`
입력창은 **첫 응답으로만** 띄울 수 있어요. DB 확인은 입력창을 제출한 뒤에 해요.

## 🚨 `@tasks.loop`은 예외 하나에 영구 정지해요 → `@loop.error`에서 `restart()`.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import logging
import os
import random
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import (
    balodle_art,
    balodle_data,
    balodle_logic as logic,
    balodle_store,
    coin_wallet,
    settings_store,
)
from utils.interaction_ack import ack

log = logging.getLogger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))
KINDS = logic.KINDS

# 종류 → (이모지, 이름). 버튼·제목·결과 줄이 같은 표를 써요.
KIND_META = {"agent": ("🕵️", "요원"), "ability": ("✨", "스킬"), "map": ("🗺️", "맵")}

# embed 왼쪽 띠 색 (디자인 D4)
COLOR_PANEL = 0x8B5CF6
COLOR_KIND = {"agent": 0xFF4655, "ability": 0x4FC3F7, "map": 0xF2A65A}
COLOR_SOLVED = 0x57C785
COLOR_FAILED = 0x747F8D

# 알림 역할 — **코드가 만들어요.** 디스코드에서 손으로 이름을 바꾸면 중복이 생겨요.
NOTIFY_ROLE_NAME = "🧩 발로들 알림"
NOTIFY_ROLE_PLAIN = "발로들 알림"
# 연속 칭호를 얻었을 때 안내 줄 앞에 붙는 이모지 (디자인 D6, 연속 일수 → 이모지)
TITLE_EMOJI = {7: "🧩", 30: "🎓"}

# settings_store 키
KEY_PANEL = "balodle:panel"            # {channel, message}
KEY_NOTIFY_ROLE = "balodle:notify_role"
KEY_NOTIFY_MSG = "balodle:notify_msg"  # {id, day}

VIEW_TIMEOUT = 14 * 60                 # 문제 화면. 상호작용 토큰(15분)보다 짧게 둬요.
BANNER_FILE = "panel_banner.png"
ABILITY_FILE = "ability.png"
BOARD_FILE = "agent_board.png"
MAP_FILE = "map.jpg"

NEW_DAY_AT = datetime.time(hour=0, minute=0, second=5, tzinfo=KST)
_NOTIFY_H, _NOTIFY_M = logic.parse_time(balodle_data.SETTINGS.get("notify_time"))
NOTIFY_AT = datetime.time(hour=_NOTIFY_H, minute=_NOTIFY_M, tzinfo=KST)


# ------------------------------------------------------------------
# 글 다듬기
# ------------------------------------------------------------------
def _has_final(word: str) -> bool:
    """마지막 한글 글자에 받침이 있는지. 조사(은/는, 을/를, 이었어요/였어요)를 고를 때 써요."""
    for ch in reversed(word or ""):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
    return False


def _josa(word: str, with_final: str, without: str) -> str:
    return with_final if _has_final(word) else without


def _plain(name: str) -> str:
    """역할 이름에서 이모지·기호를 떼요. 역할은 **이 이름이 정확히 일치**하는 것으로 찾아요."""
    return re.sub(r"[^0-9A-Za-z가-힣 ]", "", name or "").strip()


def _answer_text(kind: str, day: dict) -> str:
    """정답을 글로. 요원 `제트` · 스킬 `제트 — 순풍 (E)` · 맵 `어센트`."""
    if kind == "agent":
        return balodle_data.agent_name(day.get("agent"))
    if kind == "ability":
        ab = balodle_data.ABILITIES.get(day.get("ability")) or {}
        return f"{balodle_data.agent_name(ab.get('agent'))} — {ab.get('ko', '?')} ({ab.get('slot', '?')})"
    return str(day.get("map") or "?")


def _guess_name(kind: str, guess: str) -> str:
    return guess if kind == "map" else balodle_data.agent_name(guess)


def _wrong_guesses(kind: str, part: dict) -> list[str]:
    guesses = list(part.get("guesses") or [])
    if part.get("status") == "solved":
        guesses = guesses[:-1]
    return [_guess_name(kind, g) for g in guesses]


# ------------------------------------------------------------------
# 화면 (embed) — 전부 순수 함수예요. DB를 읽지 않고 받은 문서로만 그려요.
# ------------------------------------------------------------------
def panel_embed(day: dict, yesterday: dict | None, *, with_banner: bool = True) -> discord.Embed:
    settings = balodle_data.SETTINGS
    limits = {logic.max_attempts(k, settings) for k in KINDS}
    chance = f"문제마다 기회는 {limits.pop()}번" if len(limits) == 1 else "문제마다 기회가 정해져 있고"
    finished = day.get("finished") or {}
    lines = [
        "요원 · 스킬 · 맵, 하루에 한 문제씩이에요.",
        f"{chance}, 빨리 맞힐수록 코인을 더 받아요.",
        "",
        "오늘 푼 사람  " + " · ".join(
            f"{KIND_META[k][0]} {int(finished.get(k) or 0)}명" for k in KINDS),
    ]
    if yesterday:
        ab = balodle_data.ABILITIES.get(yesterday.get("ability")) or {}
        lines.append(
            f"어제 정답  🕵️ ||{balodle_data.agent_name(yesterday.get('agent'))}|| · "
            f"✨ ||{ab.get('ko', '?')}|| · 🗺️ ||{yesterday.get('map', '?')}||")
    lines.append("-# 매일 0시에 새 문제가 나와요.")
    embed = discord.Embed(title=f"🧩 오늘의 발로들 #{day.get('no', 1)}",
                          description="\n".join(lines), color=COLOR_PANEL)
    if with_banner and os.path.exists(balodle_data.ui_path(BANNER_FILE)):
        embed.set_image(url=f"attachment://{BANNER_FILE}")
    return embed


def _banner_file() -> discord.File | None:
    path = balodle_data.ui_path(BANNER_FILE)
    return discord.File(path, filename=BANNER_FILE) if os.path.exists(path) else None


def _agent_rows(part: dict, day: dict) -> list[str]:
    rows = []
    for guess in part.get("guesses") or []:
        if guess not in balodle_data.AGENTS:
            continue
        cells = logic.compare_agent(guess, day["agent"], balodle_data.AGENTS, balodle_data.SETTINGS)
        rows.append(f"{''.join(mark for _, mark in cells)}  **{balodle_data.agent_name(guess)}** — "
                    + " · ".join(value for value, _ in cells))
    return rows


def problem_embed(kind: str, day: dict, part: dict, *, with_art: bool = False) -> discord.Embed:
    """푸는 중인 문제 화면.

    `with_art=True`면 비교표(요원)·힌트(스킬)를 **그림이 맡아서** 글에서는 빼요(2026-11-24).
    그림을 못 그렸으면 False로 불러 예전처럼 글로 보여줘요."""
    limit = logic.max_attempts(kind, balodle_data.SETTINGS)
    guesses = part.get("guesses") or []
    turn = min(len(guesses) + 1, limit)
    emoji, name = KIND_META[kind]

    if kind == "agent":
        lines = ["요원 이름을 넣으면 정답과 얼마나 비슷한지 알려드려요.", ""]
        rows = _agent_rows(part, day)
        if rows and with_art:
            lines.append("-# 🟩 같아요 · 🟨 비슷해요 · ⬛ 달라요 · ▲ 정답이 더 나중 · ▼ 정답이 더 먼저")
        elif rows:
            lines += ["`역할군 · 출신 · 출시 · 성별`", *rows,
                      "-# 🟩 같아요 · 🟨 비슷해요 · ⬛ 달라요 · ⬆ 정답이 더 나중 · ⬇ 정답이 더 먼저"]
        else:
            lines.append("아직 넣은 답이 없어요. 아래 **정답 입력**을 눌러 보세요.")
        title = f"{emoji} {name} 맞히기 · {turn}/{limit}"

    elif kind == "ability":
        ab = balodle_data.ABILITIES.get(day.get("ability")) or {}
        agent = balodle_data.AGENTS.get(ab.get("agent")) or {}
        lines = ["이 스킬은 어느 요원의 스킬일까요?", ""]
        hints = logic.ability_hints(len(guesses), ab, agent)
        if hints and not with_art:
            lines += ["💡 힌트", *(f"{head}: **{value}**" for head, value in hints), ""]
        wrong = _wrong_guesses(kind, part)
        if wrong:
            lines.append("넣은 답: " + " · ".join(f"~~{w}~~" for w in wrong))
        if not with_art:
            lines.append("-# 틀릴 때마다 힌트가 하나씩 늘어나요.")
        title = f"{emoji} {name} 맞히기 · {turn}/{limit}"

    else:
        lines = ["어느 맵일까요? 아래에서 골라 주세요.", "틀릴 때마다 그림이 조금씩 넓어져요."]
        wrong = _wrong_guesses(kind, part)
        if wrong:
            lines += ["", "넣은 답: " + " · ".join(f"~~{w}~~" for w in wrong)]
        title = f"{emoji} {name} 맞히기 · 확대 {turn}/{limit}"

    return discord.Embed(title=title, description="\n".join(lines), color=COLOR_KIND[kind])


def _square_lines(kind: str, day: dict, part: dict) -> list[str]:
    return logic.squares(kind, part, day, balodle_data.AGENTS, balodle_data.SETTINGS)


def done_embed(kind: str, day: dict, part: dict, outcome: dict) -> discord.Embed:
    """방금 끝낸 화면. `outcome` = {coin, coin_failed, rank, streak, bumped, new_titles}."""
    solved = part.get("status") == "solved"
    answer = _answer_text(kind, day)
    left = logic.left_text()
    if solved:
        attempts = len(part.get("guesses") or [])
        coin = int(outcome.get("coin") or 0)
        first = "**한 번에** 맞혔어요." if attempts == 1 else f"{attempts}번 만에 맞혔어요."
        if outcome.get("coin_failed"):
            first += " (코인 지급이 늦어지고 있어요. 곧 넣어드릴게요.)"
        elif coin:
            first += f" **+{coin}코인**"
        lines = [first]
        if outcome.get("rank"):
            lines.append(f"오늘 {outcome['rank']}번째로 맞혔어요.")
        lines += ["", *_square_lines(kind, day, part)]
        tail = []
        if outcome.get("bumped"):
            tail.append(f"🔥 발로들 연속 **{outcome.get('streak', 1)}일**")
        titles = balodle_data.SETTINGS.get("titles") or {}
        for title in outcome.get("new_titles") or []:
            days = logic.title_days(title, titles)
            tail.append(f"{TITLE_EMOJI.get(days, '🧩')} 연속 {days}일! 칭호 **「{title}」**"
                        f"{_josa(title, '을', '를')} 얻었어요. `/프로필`에서 볼 수 있어요.")
        if tail:
            lines += ["", *tail]
        lines.append(f"-# 다음 문제까지 {left}")
        return discord.Embed(title=f"🎉 정답! {answer}", description="\n".join(lines),
                             color=COLOR_SOLVED)

    if kind == "ability":
        ab = balodle_data.ABILITIES.get(day.get("ability")) or {}
        who = balodle_data.agent_name(ab.get("agent"))
        reveal = f"정답은 **{who}**의 **{ab.get('ko', '?')} ({ab.get('slot', '?')})**이었어요."
    else:
        reveal = f"정답은 **{answer}**{_josa(answer, '이었어요', '였어요')}."
    lines = [reveal, "", *_square_lines(kind, day, part), "",
             f"-# 내일 다시 도전해요. 다음 문제까지 {left}"]
    return discord.Embed(title="😵 아쉬워요", description="\n".join(lines), color=COLOR_FAILED)


def already_embed(kind: str, day: dict, part: dict) -> discord.Embed:
    """이미 끝낸 문제의 버튼을 다시 눌렀을 때."""
    solved = part.get("status") == "solved"
    lines = [*_square_lines(kind, day, part), "", f"-# 다음 문제까지 {logic.left_text()}"]
    return discord.Embed(title=f"✅ 오늘 {KIND_META[kind][1]} 문제는 이미 풀었어요",
                         description="\n".join(lines),
                         color=COLOR_SOLVED if solved else COLOR_FAILED)


def stats_embed(user: dict, today: str) -> discord.Embed:
    """📊 내 기록 — 연속·칭호, 종류별 푼 횟수·정답률·시도 분포."""
    settings = balodle_data.SETTINGS
    streak = logic.live_streak(int(user.get("streak", 0) or 0), user.get("last_solved_day"), today)
    lines = [f"🔥 지금 연속 **{streak}일** · 최고 **{int(user.get('best_streak', 0) or 0)}일**"]
    title = logic.top_title(user.get("titles"), settings.get("titles"))
    if title:
        lines.append(f"🏷️ 칭호 **「{title}」**")
    for kind in KINDS:
        emoji, name = KIND_META[kind]
        part = user.get(kind) or {}
        played, solved = int(part.get("played", 0) or 0), int(part.get("solved", 0) or 0)
        lines.append("")
        if not played:
            lines.append(f"{emoji} {name} — 아직 푼 적이 없어요")
            continue
        lines.append(f"{emoji} {name} — {played}번 풀어 {solved}번 맞힘 ({round(solved * 100 / played)}%)")
        lines += logic.dist_rows(part.get("dist") or {}, logic.max_attempts(kind, settings))
    return discord.Embed(title="📊 내 발로들 기록", description="\n".join(lines), color=COLOR_PANEL)


# ------------------------------------------------------------------
# 문제 화면의 입력 (사람마다 따로 만드는 일반 뷰)
# ------------------------------------------------------------------
class GuessModal(discord.ui.Modal):
    """요원·스킬 문제의 입력창. 스킬 문제도 **요원 이름**을 넣어요."""

    def __init__(self, view: "ProblemView"):
        super().__init__(title=f"{KIND_META[view.kind][1]} 맞히기", timeout=VIEW_TIMEOUT)
        self.problem = view
        self.name = discord.ui.TextInput(label="요원 이름", placeholder="예: 제트, jett",
                                         max_length=30, required=True)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        if not await ack(interaction):       # 화면을 그대로 두고 받아요 → edit_original_response
            return
        await self.problem.cog.handle_guess(interaction, self.problem, str(self.name.value))


class GuessButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="정답 입력", emoji="✏️", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        # 🚨 ack 없이 **바로** 입력창이에요. 입력창은 첫 응답으로만 띄울 수 있어요.
        await interaction.response.send_modal(GuessModal(self.view))


class MapSelect(discord.ui.Select):
    def __init__(self, guessed):
        options = [discord.SelectOption(label=name, value=name)
                   for name in balodle_data.map_choices() if name not in set(guessed or ())]
        super().__init__(placeholder="맵을 골라 주세요", options=options[:25],
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not await ack(interaction):
            return
        await self.view.cog.handle_guess(interaction, self.view, self.values[0])


class ProblemView(discord.ui.View):
    """문제 하나의 화면. 사람마다 따로 만드는 뷰라 `self`에 누구의 어떤 문제인지 담아도 돼요
    (영속 뷰인 패널과 달라요)."""

    def __init__(self, cog: "Balodle", uid: int, kind: str, day_iso: str, guessed=()):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog, self.uid, self.kind, self.day_iso = cog, uid, kind, day_iso
        # 화면 시간이 지났을 때 이 상호작용의 토큰으로 안내를 남겨요(가장 최근 것).
        self.anchor: discord.Interaction | None = None
        self.add_item(MapSelect(guessed) if kind == "map" else GuessButton())

    async def on_timeout(self):
        if self.anchor is None:
            return
        try:
            await self.anchor.edit_original_response(
                content="⏰ 화면이 오래돼서 닫혔어요. 패널에서 다시 눌러 주세요. 넣은 답은 그대로 있어요.",
                view=None)
        except discord.HTTPException:
            pass                              # 토큰이 이미 죽었어요. 넣은 답은 DB에 있어요.


# ------------------------------------------------------------------
# 상설 패널 (영속 뷰) — 🚨 `self`에 상태를 담지 않아요
# ------------------------------------------------------------------
def _cog(interaction: discord.Interaction) -> "Balodle | None":
    return interaction.client.get_cog("Balodle")


class BalodlePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="요원", emoji="🕵️", style=discord.ButtonStyle.primary,
                       custom_id="akgui:balodle:open:agent", row=0)
    async def open_agent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_problem(interaction, "agent")

    @discord.ui.button(label="스킬", emoji="✨", style=discord.ButtonStyle.primary,
                       custom_id="akgui:balodle:open:ability", row=0)
    async def open_ability(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_problem(interaction, "ability")

    @discord.ui.button(label="맵", emoji="🗺️", style=discord.ButtonStyle.primary,
                       custom_id="akgui:balodle:open:map", row=0)
    async def open_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_problem(interaction, "map")

    @discord.ui.button(label="내 기록", emoji="📊", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:balodle:stats", row=0)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_stats(interaction)

    @discord.ui.button(label="알림", emoji="🔔", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:balodle:notify", row=0)
    async def notify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_notify(interaction)


async def open_problem(interaction: discord.Interaction, kind: str) -> None:
    """패널 버튼 → 나만 보이는 새 문제 화면. 패널 메시지는 건드리지 않아요."""
    if not await ack(interaction, ephemeral=True, thinking=True):
        return
    cog = _cog(interaction)
    if cog is None:
        await interaction.followup.send("발로들을 준비하고 있어요. 잠시 뒤에 다시 눌러 주세요.",
                                        ephemeral=True)
        return
    await cog.send_problem(interaction, kind)


async def show_stats(interaction: discord.Interaction) -> None:
    if not await ack(interaction, ephemeral=True, thinking=True):
        return
    user = await balodle_store.get_user(interaction.user.id)
    await interaction.followup.send(embed=stats_embed(user, logic.today_iso()), ephemeral=True)


async def toggle_notify(interaction: discord.Interaction) -> None:
    if not await ack(interaction, ephemeral=True, thinking=True):
        return
    cog = _cog(interaction)
    guild, member = interaction.guild, interaction.user
    if cog is None or guild is None or not isinstance(member, discord.Member):
        await interaction.followup.send("서버 안에서 눌러 주세요.", ephemeral=True)
        return
    role = await cog.notify_role(guild, create=True)
    if role is None:
        await interaction.followup.send(
            "알림 역할을 만들 수 없었어요. 운영진에게 알려 주세요. (봇에 역할 관리 권한이 필요해요)",
            ephemeral=True)
        return
    turn_on = role not in member.roles
    try:
        if turn_on:
            await member.add_roles(role, reason="발로들 알림 켜기")
        else:
            await member.remove_roles(role, reason="발로들 알림 끄기")
    except discord.HTTPException:
        log.warning("🧩 알림 역할을 바꾸지 못했어요 (user=%s)", member.id, exc_info=True)
        await interaction.followup.send(
            "알림 역할을 바꾸지 못했어요. 운영진에게 알려 주세요. (봇 역할이 알림 역할보다 위에 있어야 해요)",
            ephemeral=True)
        return
    await balodle_store.set_notify(member.id, turn_on)
    when = logic.time_label(balodle_data.SETTINGS.get("notify_time"))
    text = (f"🔔 발로들 알림을 켰어요. 매일 {when}에 알려드릴게요." if turn_on
            else "🔕 발로들 알림을 껐어요.")
    await interaction.followup.send(embed=discord.Embed(description=text, color=COLOR_PANEL),
                                    ephemeral=True)


# ------------------------------------------------------------------
# cog
# ------------------------------------------------------------------
class Balodle(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._day_lock = asyncio.Lock()
        self._shot_lock = asyncio.Lock()
        self._map_shots: dict[str, list[bytes]] = {}     # 날짜 → 확대 그림 7장 (최근 이틀만)
        self._panel_sig: tuple | None = None             # 마지막으로 패널에 그린 (날짜, 푼 사람 수)
        self.new_day_loop.start()
        self.notify_loop.start()
        self.panel_loop.start()

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 패널 버튼을 눌러도 **아무 반응이 없어요**(에러도 안 나요).
        self.bot.add_view(BalodlePanelView())

    async def cog_unload(self):
        self.new_day_loop.cancel()
        self.notify_loop.cancel()
        self.panel_loop.cancel()

    # -------------------------- 오늘 문제 --------------------------
    async def ensure_day(self, day_iso: str) -> dict:
        """그날 문제를 읽고, 없으면 만들어요. 그날 처음 문제를 여는 사람이 만들게 돼요."""
        day = await balodle_store.get_day(day_iso)
        if day:
            return day
        async with self._day_lock:
            day = await balodle_store.get_day(day_iso)
            if day:
                return day
            settings = balodle_data.SETTINGS
            recent = await balodle_store.recent_answers(day_iso, settings.get("no_repeat_days") or {})
            rng = random.Random()
            map_name = logic.pick_answer(balodle_data.map_candidates(), recent["map"], rng)
            focus = [0.5, 0.5]
            if map_name:
                focus = await asyncio.to_thread(balodle_art.pick_focus, map_name)
            doc = {
                "no": logic.puzzle_no(day_iso, settings["start_date"]),
                "agent": logic.pick_answer(balodle_data.agent_candidates(), recent["agent"], rng),
                "ability": logic.pick_answer(balodle_data.ability_candidates(), recent["ability"], rng),
                "map": map_name,
                "map_focus": focus,
            }
            day = await balodle_store.get_or_create_day(day_iso, doc)
            log.info("🧩 발로들 #%s (%s) 문제를 만들었어요", day.get("no"), day_iso)
            return day

    async def map_shots(self, day: dict) -> list[bytes]:
        """그날 맵 문제의 확대 그림 7장. 처음 한 번만 굽고 메모리에 둬요(장당 수십 KB)."""
        key = day["_id"]
        if key in self._map_shots:
            return self._map_shots[key]
        async with self._shot_lock:
            if key not in self._map_shots:
                shots = await asyncio.to_thread(
                    balodle_art.map_steps, day["map"], day.get("map_focus") or [0.5, 0.5])
                self._map_shots[key] = shots
                for old in sorted(self._map_shots)[:-2]:      # 최근 이틀 치만 남겨요
                    self._map_shots.pop(old, None)
        return self._map_shots[key]

    # -------------------------- 문제 화면 --------------------------
    async def _board_png(self, kind: str, day: dict, part: dict) -> bytes | None:
        """요원 비교표·스킬 힌트판 그림. 그릴 게 없거나 실패하면 None(글 화면으로 물러나요)."""
        settings = balodle_data.SETTINGS
        guesses = list(part.get("guesses") or [])
        try:
            if kind == "agent":
                rows = [(g, logic.compare_agent(g, day["agent"], balodle_data.AGENTS, settings))
                        for g in guesses if g in balodle_data.AGENTS]
                if not rows:
                    return None
                return await asyncio.to_thread(balodle_art.agent_board, rows)

            ab = balodle_data.ABILITIES.get(day.get("ability")) or {}
            agent = balodle_data.AGENTS.get(ab.get("agent")) or {}
            status = part.get("status")
            limit = logic.max_attempts(kind, settings)
            if status == "playing":
                hints = logic.ability_hints(len(guesses), ab, agent)
                marks = ["wrong"] * len(guesses) + ["now"]
            else:                                  # 끝났으면 힌트를 다 열어 보여줘요
                hints = logic.ability_hints(len(logic.HINT_HEADS), ab, agent)
                marks = ["wrong"] * len(guesses)
                if status == "solved" and marks:
                    marks[-1] = "solved"
            marks = (marks + ["left"] * limit)[:limit]
            return await asyncio.to_thread(balodle_art.ability_board, day["ability"], hints,
                                           logic.HINT_HEADS, marks)
        except Exception:                          # noqa: BLE001 — 그림은 덤이에요
            log.warning("🧩 발로들 %s 그림을 못 그렸어요 — 글로 보여줘요", kind, exc_info=True)
            return None

    async def _screen(self, uid: int, kind: str, day: dict, part: dict, outcome: dict | None):
        """(embed, 첨부 파일들, 뷰 또는 None). 상태에 따라 푸는 화면·끝난 화면을 골라요."""
        playing = part.get("status") == "playing"
        art = None
        if kind == "agent" or (kind == "ability" and (playing or outcome is not None)):
            art = await self._board_png(kind, day, part)
        if playing:
            embed = problem_embed(kind, day, part, with_art=art is not None)
        elif outcome is not None:
            embed = done_embed(kind, day, part, outcome)
        else:
            embed = already_embed(kind, day, part)

        files = []
        if kind == "agent" and art is not None:
            files.append(discord.File(io.BytesIO(art), filename=BOARD_FILE))
            embed.set_image(url=f"attachment://{BOARD_FILE}")
        elif kind == "ability" and (playing or outcome is not None):
            png = art or await asyncio.to_thread(balodle_art.ability_card, day["ability"])
            files.append(discord.File(io.BytesIO(png), filename=ABILITY_FILE))
            embed.set_image(url=f"attachment://{ABILITY_FILE}")
        elif kind == "map" and (playing or outcome is not None):
            shots = await self.map_shots(day)
            # 푸는 중이면 틀린 횟수만큼 넓어진 그림, 끝났으면 전체 그림이에요.
            index = min(len(part.get("guesses") or []), len(shots) - 2) if playing else -1
            files.append(discord.File(io.BytesIO(shots[index]), filename=MAP_FILE))
            embed.set_image(url=f"attachment://{MAP_FILE}")

        view = None
        if playing:
            view = ProblemView(self, uid, kind, day["_id"],
                               guessed=part.get("guesses") if kind == "map" else ())
        return embed, files, view

    async def send_problem(self, interaction: discord.Interaction, kind: str) -> None:
        """패널 버튼에서 불려요(이미 `ack`된 뒤). 새 ephemeral 화면을 띄워요."""
        day = await self.ensure_day(logic.today_iso())
        if not day.get(kind):
            await interaction.followup.send("오늘 이 문제는 준비하지 못했어요. 운영진에게 알려 주세요.",
                                            ephemeral=True)
            return
        play = await balodle_store.open_play(day["_id"], interaction.user.id, kind)
        part = play.get(kind) or {}
        embed, files, view = await self._screen(interaction.user.id, kind, day, part, None)
        kwargs = {"embed": embed, "files": files, "ephemeral": True}
        if view is not None:
            kwargs["view"] = view
            view.anchor = interaction
        await interaction.followup.send(**kwargs)

    async def _redraw(self, interaction: discord.Interaction, old_view: ProblemView, day: dict,
                      part: dict, *, notice: str | None = None, outcome: dict | None = None) -> None:
        """같은 화면을 고쳐 그려요(입력창 제출·맵 선택 뒤)."""
        embed, files, view = await self._screen(old_view.uid, old_view.kind, day, part, outcome)
        if view is not None:
            view.anchor = interaction
        old_view.stop()                       # 옛 뷰의 시간 초과 안내가 새 화면을 덮지 않게
        await interaction.edit_original_response(
            content=notice, embed=embed, attachments=files, view=view)

    async def handle_guess(self, interaction: discord.Interaction, view: ProblemView, raw: str) -> None:
        """답 하나를 채점해요. 호출한 쪽(입력창·선택 메뉴)이 이미 `ack`했어요."""
        uid, kind, day_iso = interaction.user.id, view.kind, view.day_iso
        day = await balodle_store.get_day(day_iso)
        play = await balodle_store.get_play(day_iso, uid)
        part = (play or {}).get(kind) or {}
        if not day or not part:
            await interaction.edit_original_response(
                content="문제를 찾지 못했어요. 패널에서 다시 눌러 주세요.", view=None)
            return
        if part.get("status") != "playing":
            await self._redraw(interaction, view, day, part)
            return

        # --- 이름 인식 (기회를 쓰지 않는 입력: 없는 이름, 이미 넣은 답) ---
        if kind == "map":
            guess = raw if raw in balodle_data.map_choices() else None
            suggestion = None
        else:
            guess, suggestion = logic.resolve_agent(raw, balodle_data.AGENTS, balodle_data.NAME_INDEX)
        if guess is None:
            hint = (f"혹시 **{balodle_data.agent_name(suggestion)}**인가요?" if suggestion
                    else "이름을 다시 확인해 주세요.")
            await self._redraw(interaction, view, day, part,
                               notice=f"🤔 그런 요원은 없어요. {hint} (기회는 그대로예요)")
            return
        if logic.is_duplicate(part.get("guesses"), guess):
            name = _guess_name(kind, guess)
            await self._redraw(
                interaction, view, day, part,
                notice=f"🔁 **{name}**{_josa(name, '은', '는')} 이미 넣었어요. (기회는 그대로예요)")
            return

        # --- 채점. 끝나는 순간의 상태·보상을 **같은 업데이트**에서 정해요 ---
        settings = balodle_data.SETTINGS
        count = len(part.get("guesses") or [])
        attempts = count + 1
        correct = logic.is_correct(kind, guess, day, balodle_data.ABILITIES)
        finish = "solved" if correct else ("failed" if attempts >= logic.max_attempts(kind, settings) else None)
        coin = logic.reward(attempts, correct, settings) if finish else 0
        updated = await balodle_store.submit_guess(
            day_iso, uid, kind, guess, count, finish=finish, reward=coin)
        if updated is None:
            # 그사이 다른 요청이 먼저 넣었어요(입력창을 두 번 보냄). 지금 상태만 다시 그려요.
            play = await balodle_store.get_play(day_iso, uid)
            await self._redraw(interaction, view, day, (play or {}).get(kind) or part)
            return

        outcome = None
        if finish:
            # 🚨 여기까지 온 요청만 카운터를 올리고 코인을 줘요 → 두 번 지급되지 않아요.
            outcome, day, updated = await self._finish(day_iso, uid, kind, correct, attempts, coin, updated)
        await self._redraw(interaction, view, day, updated.get(kind) or {}, outcome=outcome)

    async def _finish(self, day_iso: str, uid: int, kind: str, correct: bool, attempts: int,
                      coin: int, play: dict) -> tuple[dict, dict, dict]:
        """문제 하나가 끝났을 때: 서버 카운터 → 코인 → 누적 기록 → 연속·칭호 → 채널 결과.
        (끝난 화면에 쓸 값, 올린 뒤의 그날 문서, 최신 풀이 문서)"""
        day = await balodle_store.finish_counters(day_iso, kind, correct)
        outcome = {"coin": coin, "coin_failed": False, "rank": None,
                   "streak": 0, "bumped": False, "new_titles": []}
        if correct:
            outcome["rank"] = int(((day.get("solved") or {}).get(kind)) or 0) or None
            if outcome["rank"]:
                await balodle_store.set_rank(day_iso, uid, kind, outcome["rank"])

        if coin > 0:
            try:
                await coin_wallet.add(uid, coin, reason="발로들")
            except Exception:  # noqa: BLE001 — 풀이 상태는 되돌리지 않고 표시만 남겨요
                log.exception("🧩 발로들 코인 지급 실패 (user=%s, %s, %d코인)", uid, kind, coin)
                outcome["coin_failed"] = True
                await balodle_store.mark_reward_failed(day_iso, uid, kind)

        try:
            await balodle_store.record_result(uid, kind, correct, attempts)
            if correct:
                bumped = await balodle_store.bump_streak(
                    uid, day_iso, balodle_data.SETTINGS.get("titles") or {})
                outcome.update(streak=bumped["streak"], bumped=bumped["bumped"],
                               new_titles=bumped["new_titles"])
            else:
                user = await balodle_store.get_user(uid)
                outcome["streak"] = logic.live_streak(
                    int(user.get("streak", 0) or 0), user.get("last_solved_day"), day_iso)
        except Exception:  # noqa: BLE001 — 누적 기록이 실패해도 끝난 화면은 보여줘요
            log.exception("🧩 발로들 누적 기록 실패 (user=%s, %s)", uid, kind)

        play = await balodle_store.get_play(day_iso, uid) or play
        try:
            await self._share(day, play, uid, outcome["streak"])
        except Exception:  # noqa: BLE001 — 채널에 못 올려도 풀이는 끝난 거예요
            log.warning("🧩 발로들 결과를 채널에 올리지 못했어요 (user=%s)", uid, exc_info=True)
        return outcome, day, play

    async def _share(self, day: dict, play: dict, uid: int, streak: int) -> None:
        """채널 결과 메시지 — **한 사람에 하루 한 개.** 첫 문제를 끝내면 올리고, 다음 문제를
        끝낼 때마다 그 메시지를 고쳐 줄을 더해요. 정답은 넣지 않고, 멘션 알림은 꺼요."""
        channel = self._panel_channel()
        if channel is None:
            return
        text = "\n".join(logic.share_lines(
            play, day, f"<@{uid}>", streak, balodle_data.AGENTS, balodle_data.SETTINGS))
        quiet = discord.AllowedMentions.none()
        if play.get("share_msg"):
            try:
                await channel.get_partial_message(int(play["share_msg"])).edit(
                    content=text, allowed_mentions=quiet)
                return
            except discord.NotFound:
                pass                          # 누가 지웠어요. 새로 올려요.
        message = await channel.send(text, allowed_mentions=quiet)
        await balodle_store.set_share_msg(day["_id"], uid, message.id)

    # -------------------------- 패널 --------------------------
    def _panel_channel(self) -> discord.TextChannel | None:
        panel = settings_store.get_setting(KEY_PANEL) or {}
        channel = self.bot.get_channel(int(panel["channel"])) if panel.get("channel") else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def refresh_panel(self, *, force: bool = False) -> None:
        """패널의 번호·푼 사람 수·어제 정답을 고쳐요. 바뀐 게 없으면 아무것도 안 해요."""
        panel = settings_store.get_setting(KEY_PANEL) or {}
        channel = self._panel_channel()
        if channel is None or not panel.get("message"):
            return
        today = logic.today_iso()
        day = await self.ensure_day(today)
        counts = await balodle_store.count_today(today)
        sig = (today, tuple(counts[k] for k in KINDS))
        if not force and sig == self._panel_sig:
            return
        yesterday = await balodle_store.get_day(logic.day_before(today))
        try:
            await channel.get_partial_message(int(panel["message"])).edit(
                embed=panel_embed(day, yesterday))
            self._panel_sig = sig
        except discord.NotFound:
            log.warning("🧩 발로들 패널 메시지가 없어요 — `/발로들패널`로 다시 올려 주세요")
            self._panel_sig = sig             # 없는 메시지를 10분마다 다시 찾지 않게

    # -------------------------- 알림 역할 --------------------------
    async def notify_role(self, guild: discord.Guild, *, create: bool) -> discord.Role | None:
        """알림 역할을 ID로 찾고, 없으면 **이모지 뗀 이름이 정확히 일치**하는 역할, 그래도 없으면 만들어요."""
        saved = settings_store.get_setting(KEY_NOTIFY_ROLE)
        role = guild.get_role(int(saved)) if saved else None
        if role is None:
            role = discord.utils.find(lambda r: _plain(r.name) == NOTIFY_ROLE_PLAIN, guild.roles)
        if role is None and create:
            try:
                role = await guild.create_role(
                    name=NOTIFY_ROLE_NAME, mentionable=False, reason="발로들 알림 역할 자동 생성")
            except discord.HTTPException:
                log.warning("🧩 알림 역할을 만들지 못했어요 (guild=%s)", guild.id, exc_info=True)
                return None
        if role is not None and str(role.id) != str(saved):
            settings_store.set_setting(KEY_NOTIFY_ROLE, role.id)
        return role

    def can_ping_roles(self, guild: discord.Guild) -> bool:
        """알림 역할은 `mentionable=False`라, 봇에 "모든 역할 멘션" 권한이 있어야 실제로 울려요."""
        me = guild.me
        return bool(me and me.guild_permissions.mention_everyone)

    async def send_notify(self) -> None:
        """매일 알림. 전날 알림을 지우고 새로 보내요(채널이 멘션으로 덮이지 않게)."""
        panel = settings_store.get_setting(KEY_PANEL) or {}
        channel = self._panel_channel()
        if channel is None:
            return
        today = logic.today_iso()
        last = settings_store.get_setting(KEY_NOTIFY_MSG) or {}
        if last.get("day") == today:
            return                            # 오늘 이미 보냈어요(루프가 다시 시작된 경우)
        day = await self.ensure_day(today)
        role = await self.notify_role(channel.guild, create=True)
        if role is None:
            return
        if not self.can_ping_roles(channel.guild):
            log.warning("🧩 봇에 '모든 역할 멘션' 권한이 없어요 — 발로들 알림이 울리지 않아요")
        if last.get("id"):
            try:
                await channel.get_partial_message(int(last["id"])).delete()
            except discord.HTTPException:
                pass
        lines = [role.mention,
                 f"🧩 **오늘의 발로들 #{day.get('no', 1)}**이 나왔어요! 요원 · 스킬 · 맵 세 문제예요."]
        if panel.get("message"):
            lines.append("👉 풀러 가기: https://discord.com/channels/"
                         f"{channel.guild.id}/{channel.id}/{panel['message']}")
        lines.append("-# 알림을 끄려면 패널의 🔔 버튼을 눌러 주세요.")
        message = await channel.send(
            "\n".join(lines), allowed_mentions=discord.AllowedMentions(roles=[role]))
        settings_store.set_setting(KEY_NOTIFY_MSG, {"id": message.id, "day": today})

    # -------------------------- 명령어 --------------------------
    @app_commands.command(
        name="발로들패널",
        description="[서버 소유자 전용] 이 채널에 발로들 패널을 박아둬요 (결과·알림도 이 채널에 올라와요).",
    )
    async def panel(self, interaction: discord.Interaction):
        if not await ack(interaction, ephemeral=True):
            return
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("텍스트 채널에서 써주세요.", ephemeral=True)
            return

        today = logic.today_iso()
        day = await self.ensure_day(today)
        yesterday = await balodle_store.get_day(logic.day_before(today))
        old = settings_store.get_setting(KEY_PANEL) or {}
        kwargs = {"embed": panel_embed(day, yesterday), "view": BalodlePanelView()}
        banner = _banner_file()
        if banner is not None:
            kwargs["file"] = banner
        message = await channel.send(**kwargs)
        settings_store.set_setting(KEY_PANEL, {"channel": channel.id, "message": message.id})
        self._panel_sig = None
        log.info("🧩 발로들 패널 게시: 채널 %s", channel.id)

        # 예전 패널이 남아 있으면 지워요(버튼이 두 군데 있으면 헷갈려요).
        if old.get("channel") and old.get("message"):
            old_channel = self.bot.get_channel(int(old["channel"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    await old_channel.get_partial_message(int(old["message"])).delete()
                except discord.HTTPException:
                    pass

        role = await self.notify_role(interaction.guild, create=True)
        notes = [f"🧩 {channel.mention} 에 발로들 패널을 올렸어요.",
                 "-# 메시지를 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요."]
        if role is None:
            notes.append("⚠️ 알림 역할을 만들지 못했어요. 봇에 역할 관리 권한이 있는지 확인해 주세요.")
        elif not self.can_ping_roles(interaction.guild):
            notes.append("⚠️ 봇에 **모든 역할 멘션** 권한이 없어서 매일 알림이 울리지 않아요. "
                         "권한을 주면 바로 울려요.")
        await interaction.followup.send("\n".join(notes), ephemeral=True)

    @app_commands.command(name="발로들", description="오늘의 발로들 — 요원·스킬·맵 맞히기 (하루 한 번)")
    async def play(self, interaction: discord.Interaction):
        """패널과 같은 버튼을 나만 보이게 띄워요."""
        if not await ack(interaction, ephemeral=True):
            return
        today = logic.today_iso()
        day = await self.ensure_day(today)
        yesterday = await balodle_store.get_day(logic.day_before(today))
        await interaction.followup.send(
            embed=panel_embed(day, yesterday, with_banner=False),
            view=BalodlePanelView(), ephemeral=True)

    # -------------------------- 루프 --------------------------
    @tasks.loop(time=NEW_DAY_AT)
    async def new_day_loop(self):
        """0시: 오늘 문제 만들기 + 맵 그림 굽기 + 패널의 번호·어제 정답 갱신."""
        day = await self.ensure_day(logic.today_iso())
        if day.get("map"):
            await self.map_shots(day)
        await self.refresh_panel(force=True)

    @new_day_loop.before_loop
    async def before_new_day(self):
        await self.bot.wait_until_ready()

    @new_day_loop.error
    async def new_day_error(self, exc: BaseException):
        log.error("🧩 발로들 새 문제 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.new_day_loop.restart()

    @tasks.loop(time=NOTIFY_AT)
    async def notify_loop(self):
        await self.send_notify()

    @notify_loop.before_loop
    async def before_notify(self):
        await self.bot.wait_until_ready()
        channel = self._panel_channel()
        if channel is not None and not self.can_ping_roles(channel.guild):
            log.warning("🧩 봇에 '모든 역할 멘션' 권한이 없어요 — 발로들 알림이 울리지 않아요")

    @notify_loop.error
    async def notify_error(self, exc: BaseException):
        log.error("🧩 발로들 알림 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.notify_loop.restart()

    @tasks.loop(minutes=10)
    async def panel_loop(self):
        """10분마다: 푼 사람 수가 바뀌었으면 패널을 고쳐요."""
        await self.refresh_panel()

    @panel_loop.before_loop
    async def before_panel(self):
        await self.bot.wait_until_ready()
        try:
            await balodle_store.ensure_indexes()
        except Exception:  # noqa: BLE001 — 색인은 지표 스크립트용이라 없어도 봇은 돌아요
            log.warning("🧩 발로들 색인을 만들지 못했어요", exc_info=True)

    @panel_loop.error
    async def panel_error(self, exc: BaseException):
        log.error("🧩 발로들 패널 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.panel_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(Balodle(bot))
