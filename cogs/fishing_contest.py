"""🎣 주간 낚시 대회 — 이주의 최대어와 최다 수익을 매주 발표해요.

## 왜 (2026-10-18 실측)

낚시가 코인 발행의 **70%**인데 참여자는 **10명뿐**이에요. 게다가 한 사람이 1,612캐스트로
전체의 절반을 넘겨요. 캐스트 수를 겨루면 그 사람이 영원히 1등이라 아무도 도전을 안 해요.

그래서 종목을 둘로 나눠요.
- 🏆 **최대어** — 운이 섞여서 **누구나 하루아침에** 1등이 될 수 있어요.
- 💰 **최다 수익** — 꾸준함을 보상해요.

## 🚨 상으로 코인을 주지 않아요

낚시는 이미 최대 발행원이에요. 여기에 상금을 얹으면 경제가 더 기울어요.
상은 **역할(명예)**이고, 다음 주 우승자가 나오면 넘어가요.

## 🚨 `@tasks.loop`은 예외 하나에 영구 정지

`@loop.error`에서 반드시 `restart()` — 이 저장소에서 `/오상` 루프가 그렇게 죽었어요.
"""
from __future__ import annotations

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import fishing_week
from utils.channel_check import get_allowed_channel_id
from utils.fish_data import BY_KEY, GRADES

log = logging.getLogger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))

ROLE_BIG = "🎣 이주의 낚시왕"
ROLE_COLOR = discord.Colour(0x3B82F6)

# 🏆 주간결산 채널에 발표해요.
#
# 🚨 **낚시터에 발표하면 안 돼요.** 실측(2026-10-18) 하루 66개 글이 쏟아져서 월요일
#    11:30 발표가 바로 묻혀요. 게다가 낚시터는 **이미 낚시하는 사람만** 보는 채널이라,
#    "수혜자 12명을 늘린다"는 이 대회의 목적에 발표가 닿지 않아요.
# ⚠️ `fallback_group`은 설정 전 보험이에요(없으면 조용히 발표를 못 해요).
CHANNEL_GROUP = "weekly"
CHANNEL_ENV = "WEEKLY_CHANNEL_ID"
CHANNEL_FALLBACK = "fishing"

# 월요일 낮. 🏅 주간 MVP(11:00)와 겹치지 않게 조금 뒤로 미뤄요.
SEND_AT = datetime.time(hour=11, minute=30, tzinfo=KST)
SEND_WEEKDAY = 0  # 월요일

MEDALS = ("🥇", "🥈", "🥉")


def _fish_line(doc: dict) -> str:
    key = doc.get("bestKey")
    if not key:
        return "기록 없음"
    grade, name = BY_KEY.get(key, ("?", key))
    emoji = (GRADES.get(grade) or {}).get("emoji", "🐟")
    size = doc.get("bestSize") or 0
    return f"{emoji} **{name}** {size}cm ({grade})"


def build_embed(wk: str, big: list[dict], rich: list[dict],
                names: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎣 {wk} 주간 낚시 대회",
        color=ROLE_COLOR,
    )

    if big:
        lines = []
        for i, doc in enumerate(big):
            mark = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            who = names.get(str(doc.get("userId")), "알 수 없음")
            lines.append(f"{mark} **{who}** — {_fish_line(doc)}")
        embed.add_field(name="🏆 최대어", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🏆 최대어", value="이번 주엔 아무도 낚지 않았어요.",
                        inline=False)

    if rich:
        lines = []
        for i, doc in enumerate(rich):
            mark = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            who = names.get(str(doc.get("userId")), "알 수 없음")
            lines.append(f"{mark} **{who}** — {doc.get('sold', 0):,}코인")
        embed.add_field(name="💰 최다 수익", value="\n".join(lines), inline=False)

    embed.set_footer(text="최대어는 등급이 먼저, 같은 등급이면 치수로 가려요 · 상은 역할이에요")
    return embed


async def hand_over_role(guild: discord.Guild, winner: discord.Member) -> bool:
    """낚시왕 역할을 넘겨요. 🚨 **회수 먼저, 부여 나중** (중간에 실패해도 둘이 안 달리게)."""
    role = discord.utils.find(lambda r: r.name == ROLE_BIG, guild.roles)
    try:
        if role is None:
            role = await guild.create_role(
                # ⭐ `hoist=True` — 멤버 목록에 따로 띄워요. 상금 대신 주는 명예라
                #    보이지 않으면 상이 아니에요.
                name=ROLE_BIG, colour=ROLE_COLOR, hoist=True, mentionable=False,
                reason="주간 낚시왕 역할 자동 생성",
            )
        for member in list(role.members):
            if member.id != winner.id:
                await member.remove_roles(role, reason="주간 낚시왕 교체")
        if role not in winner.roles:
            await winner.add_roles(role, reason="주간 낚시왕 선정")
        return True
    except discord.Forbidden:
        log.info("🎣 역할 권한이 없어요 (guild=%s)", guild.id)
        return False


class FishingContest(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.announce_loop.start()

    async def cog_unload(self):
        self.announce_loop.cancel()

    async def announce(self, guild: discord.Guild, wk: str) -> str:
        big = await fishing_week.top(wk, by="size", limit=3)
        rich = await fishing_week.top(wk, by="sold", limit=3)
        if not big and not rich:
            return f"{wk}에는 낚시 기록이 없어서 대회를 건너뛰었어요."

        names: dict[str, str] = {}
        for doc in big + rich:
            uid = str(doc.get("userId"))
            if uid in names:
                continue
            member = guild.get_member(int(uid))
            names[uid] = member.display_name if member else "탈퇴한 사람"

        given = ""
        if big:
            champ = guild.get_member(int(big[0]["userId"]))
            if champ is not None:
                ok = await hand_over_role(guild, champ)
                given = f" · 역할은 **{champ.display_name}** 님께" if ok else \
                    "\n⚠️ 역할은 권한이 없어 못 줬어요."

        channel_id = get_allowed_channel_id(
            CHANNEL_GROUP, CHANNEL_ENV, fallback_group=CHANNEL_FALLBACK)
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return ("대회 결과는 나왔는데 발표할 채널이 없어요. "
                    "`/채널설정`으로 🏆 주간결산 채널을 정해주세요.")

        await channel.send(embed=build_embed(wk, big, rich, names))
        return f"{channel.mention}에 발표했어요{given}"

    # ------------------------------------------------------------------
    @app_commands.command(name="낚시대회", description="이번 주 낚시 대회 중간 순위를 봐요.")
    async def standings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        wk = fishing_week.week_key()
        big = await fishing_week.top(wk, by="size", limit=5)
        rich = await fishing_week.top(wk, by="sold", limit=5)

        if not big and not rich:
            await interaction.followup.send(
                "이번 주엔 아직 기록이 없어요. `/낚시`로 첫 기록을 남겨보세요!")
            return

        names: dict[str, str] = {}
        for doc in big + rich:
            uid = str(doc.get("userId"))
            if uid in names:
                continue
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            names[uid] = member.display_name if member else "탈퇴한 사람"

        embed = build_embed(wk, big, rich, names)
        embed.title = f"🎣 {wk} 낚시 대회 (진행 중)"
        embed.set_footer(text="월요일 낮에 결산해요 · 상은 역할이에요")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    @tasks.loop(time=SEND_AT)
    async def announce_loop(self):
        if datetime.datetime.now(KST).weekday() != SEND_WEEKDAY:
            return
        wk = fishing_week.previous_week_key()
        for guild in self.bot.guilds:
            try:
                log.info("🎣 주간 낚시 대회: %s", await self.announce(guild, wk))
            except Exception:  # noqa: BLE001
                log.warning("🎣 낚시 대회 발표 실패 (guild=%s)", guild.id, exc_info=True)

    @announce_loop.before_loop
    async def before_announce(self):
        await self.bot.wait_until_ready()

    @announce_loop.error
    async def announce_error(self, exc: BaseException):
        """🚨 **이게 없으면 루프가 영구 정지해요.**"""
        log.error("🎣 낚시 대회 루프가 멈췄어요 - 다시 시작해요", exc_info=exc)
        self.announce_loop.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(FishingContest(bot))
