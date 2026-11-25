"""🤝 서버 공동 목표 — 이번 주 게이지 3칸을 다 같이 채워요 (2026-11-25).

세는 규칙·목표 숫자·보상·두 번 지급 막기는 `utils/server_goal.py` 맨 위에 적어 뒀어요.
여기는 패널·버튼·루프만이에요.

## 흐름 (5분마다)

1. 이번 주 칸마다 참여한 사람을 세요(기존 기록을 읽기만).
2. 목표에 닿은 칸: 처음 닿은 순간이면 채널에 🎉 글. 참여자 중 아직 못 받은 사람에게 코인.
   → 달성한 뒤에 참여한 사람도 다음 바퀴에 받아요.
3. 세 칸 다: 하나라도 참여한 사람에게 보너스.
4. 월요일이 되면 지난주를 한 번 더 정산(일요일 밤 마지막 5분 몫)하고 마감 → 결과 글.
5. 숫자가 바뀌었으면 패널을 고쳐요.

## 🚨 영속 뷰 규칙 (발로들과 같아요)
`timeout=None` · 고정 `custom_id`(`akgui:goal:*`) · `cog_load`에서 `bot.add_view`.
패널 뷰는 봇 전체에 하나라 `self`에 상태를 담지 않아요.

## 🚨 `@tasks.loop`은 예외 하나에 영구 정지해요 → `@loop.error`에서 `restart()`.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import coin_wallet, settings_store
from utils import server_goal as sg
from utils.interaction_ack import ack

log = logging.getLogger(__name__)

KEY_PANEL = "server_goal:panel"   # {channel, message}
COLOR = 0x22C55E
COLOR_DONE = 0xF5C518
NO_PING = discord.AllowedMentions.none()


# ------------------------------------------------------------------
# 화면
# ------------------------------------------------------------------
def panel_embed(week: str, counts: dict, last: dict | None = None) -> discord.Embed:
    reached = sg.reached_keys(counts)
    all_done = len(reached) == len(sg.GOALS)
    em = discord.Embed(
        title="🤝 이번 주 서버 공동 목표" + (" — 🎉 전부 달성!" if all_done else ""),
        color=COLOR_DONE if all_done else COLOR,
        description=(
            f"**{sg.week_label(week)}** · 다 같이 채워요!\n"
            f"칸을 채우면 그 칸에 참여한 모두 **+2코인**, 세 칸 다 채우면 참여한 모두 **+{sg.ALL_BONUS}코인** 더.\n"
            "-# 한 번만 해도 한 명으로 세요. 달성한 뒤에 참여해도 보상을 받아요."
        ),
    )
    for g in sg.GOALS:
        n = counts.get(g.key, 0)
        mark = " ✅" if n >= g.target else ""
        em.add_field(
            name=f"{g.emoji} {g.name}{mark}",
            value=f"`{sg.progress_bar(n, g.target)}` **{min(n, 999)} / {g.target}명**\n-# {g.how}",
            inline=False,
        )
    if last:
        n = len(last.get("reached") or [])
        em.add_field(name="지난주",
                     value=f"{n}/{len(sg.GOALS)} 달성 · 참여 {last.get('contributors', 0)}명",
                     inline=False)
    em.set_footer(text="5분마다 갱신 · 매주 월요일 0시에 새로 시작")
    return em


def mine_embed(week: str, uid: str, ppl: dict, state: dict) -> discord.Embed:
    paid = state.get("paid") or {}
    got = sum(g.reward for g in sg.GOALS if uid in (paid.get(g.key) or []))
    if uid in (paid.get(sg.ALL_KEY) or []):
        got += sg.ALL_BONUS
    lines = []
    for g in sg.GOALS:
        if uid in ppl.get(g.key, set()):
            lines.append(f"✅ {g.emoji} {g.name} — 참여했어요")
        else:
            lines.append(f"⬜ {g.emoji} {g.name} — {g.how}")
    em = discord.Embed(title="📊 이번 주 내 기여", color=COLOR, description="\n".join(lines))
    em.add_field(name="이번 주 받은 코인", value=f"**{got}개**", inline=False)
    em.set_footer(text=sg.week_label(week))
    return em


class GoalPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="내 기여", emoji="📊", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:goal:me")
    async def me(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_mine(interaction)


async def show_mine(interaction: discord.Interaction) -> None:
    if not await ack(interaction, ephemeral=True):
        return
    week = sg.week_key()
    ppl = await sg.people(week)
    state = await sg.get_state(week)
    await interaction.followup.send(
        embed=mine_embed(week, str(interaction.user.id), ppl, state), ephemeral=True)


# ------------------------------------------------------------------
# cog
# ------------------------------------------------------------------
class ServerGoal(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._panel_sig: tuple | None = None
        self.goal_loop.start()

    async def cog_load(self):
        # 🚨 이게 없으면 재시작 뒤 [내 기여] 버튼이 아무 반응이 없어요.
        self.bot.add_view(GoalPanelView())

    async def cog_unload(self):
        self.goal_loop.cancel()

    def _channel(self) -> discord.TextChannel | None:
        panel = settings_store.get_setting(KEY_PANEL) or {}
        channel = self.bot.get_channel(int(panel["channel"])) if panel.get("channel") else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _post(self, text: str) -> None:
        channel = self._channel()
        if channel is None:
            return
        try:
            await channel.send(text, allowed_mentions=NO_PING)
        except discord.HTTPException:
            log.warning("🤝 공동 목표 글을 못 올렸어요", exc_info=True)

    # -------------------------- 정산 --------------------------
    async def _pay(self, week: str, key: str, uids: set, amount: int, state: dict) -> int:
        """아직 못 받은 사람에게 지급. 이번에 준 사람 수를 돌려줘요."""
        already = set((state.get("paid") or {}).get(key) or [])
        paid = 0
        for uid in sorted(uids - already):
            if not await sg.claim(week, key, uid):
                continue
            try:
                await coin_wallet.add(int(uid), amount, reason=f"{sg.REASON_PREFIX}:{week}:{key}")
                paid += 1
            except Exception:  # noqa: BLE001 — 한 사람 실패로 나머지를 멈추지 않아요
                log.warning("🤝 공동 목표 지급 실패 (week=%s key=%s uid=%s)", week, key, uid,
                            exc_info=True)
        return paid

    async def settle(self, week: str, *, announce: bool) -> tuple[dict, dict]:
        """그 주를 정산해요. (칸별 인원, 칸별 참여자)"""
        ppl = await sg.people(week)
        counts = {g.key: len(ppl.get(g.key, set())) for g in sg.GOALS}
        state = await sg.get_state(week)
        reached = sg.reached_keys(counts)
        for key in reached:
            g = sg.BY_KEY[key]
            first = await sg.mark_reached(week, key)
            paid = await self._pay(week, key, ppl[key], g.reward, state)
            if first and announce:
                await self._post(
                    f"🎉 **공동 목표 달성!** {g.emoji} {g.name} **{counts[key]}명** (목표 {g.target}명)\n"
                    f"참여한 {paid}명에게 **{g.reward}코인**씩 드렸어요. 지금 참여해도 받아요!")
        if len(reached) == len(sg.GOALS):
            everyone = sg.contributors_all(ppl)
            first = await sg.mark_reached(week, sg.ALL_KEY)
            paid = await self._pay(week, sg.ALL_KEY, everyone, sg.ALL_BONUS, state)
            if first and announce:
                await self._post(
                    "🏆 **이번 주 공동 목표 세 칸 전부 달성!** 다들 고마워요.\n"
                    f"참여한 {paid}명에게 보너스 **{sg.ALL_BONUS}코인**씩 더 드렸어요.")
        return counts, ppl

    async def close_previous(self) -> None:
        """월요일: 지난주 마지막 몫을 정산하고 결과를 한 번만 올려요."""
        prev = sg.previous_week_key()
        if prev < sg.FIRST_WEEK:
            return
        state = await sg.get_state(prev)
        if state.get("closed"):
            return
        counts, ppl = await self.settle(prev, announce=False)
        if not await sg.close_week(prev):
            return
        contributors = len(sg.contributors_all(ppl))
        await sg.save_summary(prev, counts, contributors)
        n = len(sg.reached_keys(counts))
        lines = [f"📅 **지난주 공동 목표 결과** ({sg.week_label(prev)}) — **{n}/{len(sg.GOALS)} 달성**, 참여 {contributors}명"]
        for g in sg.GOALS:
            mark = "✅" if counts[g.key] >= g.target else "❌"
            lines.append(f"{mark} {g.emoji} {g.name} {counts[g.key]}/{g.target}명")
        lines.append("이번 주 목표가 새로 시작됐어요! 🤝")
        await self._post("\n".join(lines))
        self._panel_sig = None

    async def refresh_panel(self, week: str, counts: dict, *, force: bool = False) -> None:
        panel = settings_store.get_setting(KEY_PANEL) or {}
        channel = self._channel()
        if channel is None or not panel.get("message"):
            return
        sig = (week, tuple(counts.get(g.key, 0) for g in sg.GOALS))
        if not force and sig == self._panel_sig:
            return
        last = await sg.summary(sg.previous_week_key())
        try:
            await channel.get_partial_message(int(panel["message"])).edit(
                embed=panel_embed(week, counts, last), view=GoalPanelView())
            self._panel_sig = sig
        except discord.NotFound:
            log.warning("🤝 공동 목표 패널 메시지가 없어요 — `/패널 종류:공동목표`로 다시 올려 주세요")
            self._panel_sig = sig

    async def tick(self) -> None:
        await self.close_previous()
        week = sg.week_key()
        counts, _ = await self.settle(week, announce=True)
        await self.refresh_panel(week, counts)

    # -------------------------- 명령어 --------------------------
    # 🧭 슬래시 명령어가 아니에요 — `/패널 종류:공동목표`(cogs/panels.py)이 이 함수를 불러요.
    #    (전역 명령어 100개 한도 때문에 패널 명령어 7개를 하나로 합쳤어요, 2026-11-26)
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
        week = sg.week_key()
        ppl = await sg.people(week)
        counts = {g.key: len(ppl.get(g.key, set())) for g in sg.GOALS}
        last = await sg.summary(sg.previous_week_key())
        old = settings_store.get_setting(KEY_PANEL) or {}
        message = await channel.send(embed=panel_embed(week, counts, last), view=GoalPanelView())
        settings_store.set_setting(KEY_PANEL, {"channel": channel.id, "message": message.id})
        self._panel_sig = None
        log.info("🤝 공동 목표 패널 게시: 채널 %s", channel.id)
        if old.get("channel") and old.get("message") and int(old["message"]) != message.id:
            old_channel = self.bot.get_channel(int(old["channel"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    await old_channel.get_partial_message(int(old["message"])).delete()
                except discord.HTTPException:
                    pass
        await interaction.followup.send(
            f"🤝 {channel.mention} 에 공동 목표 패널을 올렸어요.\n"
            "-# 메시지를 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요.", ephemeral=True)

    @app_commands.command(name="공동목표", description="이번 주 서버 공동 목표와 내 기여를 봐요")
    async def show(self, interaction: discord.Interaction):
        if not await ack(interaction, ephemeral=True):
            return
        week = sg.week_key()
        ppl = await sg.people(week)
        counts = {g.key: len(ppl.get(g.key, set())) for g in sg.GOALS}
        state = await sg.get_state(week)
        last = await sg.summary(sg.previous_week_key())
        await interaction.followup.send(
            embeds=[panel_embed(week, counts, last),
                    mine_embed(week, str(interaction.user.id), ppl, state)],
            ephemeral=True)

    # -------------------------- 루프 --------------------------
    @tasks.loop(minutes=5)
    async def goal_loop(self):
        await self.tick()

    @goal_loop.before_loop
    async def before_goal(self):
        # 🚨 남의 컬렉션(balodle_plays·fishing_week·coin_log)에 색인을 만들지 않아요.
        #    balodle_plays.date 는 발로들이 이미 걸고, fishing_week 는 주마다 십여 건이에요.
        await self.bot.wait_until_ready()

    @goal_loop.error
    async def goal_error(self, exc: BaseException):
        log.error("🤝 공동 목표 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.goal_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerGoal(bot))
