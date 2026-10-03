"""업적 · 내전 전적 · 주간 랭킹 화면이에요.

`/프로필` 카드가 요약(23/60, 31승 24패, 892)을 보여준다면, 여기는 **그 숫자를 펼쳐보는 곳**
이에요. 어떤 업적이 남았는지, 내전을 누가 제일 많이 이겼는지, 이번 주 악귀력 순위가 어떤지.

## 왜 랭킹에 API를 안 부르나

`/주간랭킹`은 `/전적`이 남겨둔 주간 스냅샷만 읽어요(utils/agwi_weekly_store.py). 랭킹을
띄울 때마다 사람 수만큼 HenrikDev를 부르면 분당 30회 한도가 한 번에 녹아서, 그 시간 동안
서버 전체의 `/전적`과 자동 미션 확인이 같이 죽어요.

그래서 **"이번 주에 `/전적`을 한 번이라도 돌린 사람"만 순위에 올라와요.** 이건 버그가 아니라
의도예요. 안 그러면 순위표를 위해 전원 조회를 돌려야 하거든요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import (
    achievement_data,
    achievement_store,
    agwi_weekly_store,
    birthday_store,
    riot_account_store,
    scrim_record_store,
    tier_roles,
    valorant_maps,
)
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

# 맵별 승률에 '강점(💪)/약점(😵)' 딱지를 붙이려면 이만큼은 해봤어야 해요.
# 1~2판이면 100%/0%가 흔해서 딱지가 아무 의미가 없어요.
MAP_MARK_MIN_MATCHES = 3
# 임베드 필드 하나는 1024자까지예요.
FIELD_LIMIT = 1024

# 한 페이지에 다 넣으면 임베드 길이 제한(필드 25개·전체 6000자)에 걸려요.
CATEGORY_CHOICES = [
    app_commands.Choice(name=label, value=key)
    for key, label in achievement_data.CATEGORIES.items()
]

MEDALS = ["🥇", "🥈", "🥉"]


def _map_stats_text(rows: list[dict]) -> str:
    """맵별 승패를 승률 높은 순으로 줄여 써요. 가장 강한/약한 맵엔 딱지를 붙여요.

    딱지는 `MAP_MARK_MIN_MATCHES`판 이상 해본 맵에만 붙여요 — 한 판 이기고 '강점 맵'이라고
    하면 안 되니까요. 그리고 승률이 50%를 넘지 않는 맵엔 💪를, 50% 미만이 아닌 맵엔 😵를
    붙이지 않아요(전부 이기는 사람에게 '약점 맵'을 만들어주지 않으려고요)."""
    ranked = []
    for row in rows:
        total = row["wins"] + row["losses"]
        if total == 0:
            continue
        ranked.append({**row, "total": total, "rate": row["wins"] / total * 100})
    if not ranked:
        return "-"

    # ⚠️ 승률만으로 줄 세우면 **1판 이기고 100%인 맵이 7승 2패 맵 위에 올라가요.**
    #    "어디가 강점인지"를 보려고 만든 화면인데 그러면 거꾸로 읽히니, 표본이 충분한 맵을
    #    먼저 승률 순으로 세우고 1~2판짜리는 아래로 내려요.
    ranked.sort(key=lambda r: (
        0 if r["total"] >= MAP_MARK_MIN_MATCHES else 1,
        -r["rate"],
        -r["total"],
        valorant_maps.sort_key(r["map"]),
    ))

    enough = [r for r in ranked if r["total"] >= MAP_MARK_MIN_MATCHES]
    best = enough[0] if enough and enough[0]["rate"] > 50 else None
    worst = None
    if len(enough) >= 2 and enough[-1]["rate"] < 50 and enough[-1] is not best:
        worst = enough[-1]

    lines = []
    for row in ranked:
        mark = " 💪" if row is best else (" 😵" if row is worst else "")
        # 판수는 `3승 1패`에 이미 드러나 있어서 따로 안 적어요. (`-#`은 줄 맨 앞에서만
        # 작은 글씨로 렌더돼서, 줄 중간에 쓰면 글자 그대로 보여요)
        lines.append(
            f"`{row['map']}` **{row['wins']}승 {row['losses']}패** · "
            f"{row['rate']:.0f}%{mark}"
        )
    if len(ranked) != len(enough):
        lines.append(
            f"-# {MAP_MARK_MIN_MATCHES}판 미만인 맵은 표본이 적어서 아래로 내렸어요 "
            f"(💪/😵도 안 붙여요)."
        )

    # 맵이 늘어나도 필드 한도를 넘지 않게 뒤에서부터 잘라요(승률 높은 쪽을 남겨요).
    text = "\n".join(lines)
    while len(text) > FIELD_LIMIT and len(lines) > 1:
        lines.pop(-2 if lines[-1].startswith("-#") else -1)
        text = "\n".join(lines)
    return text


async def _stats_for(member: discord.abc.User) -> dict:
    """업적 판정용 숫자 모음. 디스코드·파일에서 오는 값은 여기서 채워 넣어요."""
    guild_member = member if isinstance(member, discord.Member) else None
    return await achievement_store.collect_stats(
        member.id,
        tier_index=tier_roles.member_tier_index(guild_member) if guild_member else None,
        riot_linked=riot_account_store.get_account(member.id) is not None,
        birthday_set=bool(await birthday_store.get_birthday(member.id)),
    )


def _progress_text(achievement: dict, stats: dict, unlocked: bool) -> str:
    """'📗 일주일 개근 — 출석 7회' 한 줄. 아직이면 진행도를 같이 보여줘요."""
    if unlocked:
        return f"{achievement['emoji']} ~~{achievement['name']}~~ · {achievement['desc']}"

    have, need = achievement_data.progress_of(achievement, stats)
    return (
        f"🔒 **{achievement['name']}** · {achievement['desc']} "
        f"`{min(have, need):,}/{need:,}`"
    )


async def build_achievement_embed(
    member: discord.abc.User, category: str | None = None
) -> discord.Embed:
    """업적 목록 임베드. `/프로필`의 '업적 보기' 버튼도 이걸 써요."""
    stats = await _stats_for(member)
    unlocked = await achievement_store.unlocked_keys(member.id)

    total_unlocked = len(unlocked)
    total = achievement_data.TOTAL
    percent = total_unlocked / total * 100 if total else 0

    embed = discord.Embed(
        title=f"🏆 {member.display_name}님의 업적",
        description=(
            f"**{total_unlocked} / {total}** 달성 ({percent:.0f}%)\n"
            f"{_bar(percent)}"
        ),
        color=0xFFD700 if total_unlocked else 0x4F545C,
    )

    categories = [category] if category else list(achievement_data.CATEGORIES)
    for key in categories:
        items = achievement_data.BY_CATEGORY.get(key, [])
        if not items:
            continue
        done = sum(1 for a in items if a["key"] in unlocked)
        lines = [_progress_text(a, stats, a["key"] in unlocked) for a in items]

        # 임베드 필드 하나는 1024자까지예요. 넘치면 남은 개수만 알려줘요.
        text = "\n".join(lines)
        if len(text) > 1000:
            kept = []
            length = 0
            for line in lines:
                if length + len(line) + 1 > 940:
                    break
                kept.append(line)
                length += len(line) + 1
            text = "\n".join(kept) + f"\n-# 외 {len(lines) - len(kept)}개 (카테고리를 지정해서 보세요)"

        embed.add_field(
            name=f"{achievement_data.CATEGORIES[key]} ({done}/{len(items)})",
            value=text,
            inline=False,
        )

    if not category:
        embed.set_footer(text="카테고리를 지정하면 그 분야만 자세히 볼 수 있어요.")
    return embed


def _bar(percent: float, length: int = 12) -> str:
    filled = int(length * percent / 100)
    return "🟨" * filled + "⬜" * (length - filled)


class Achievement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    @app_commands.command(name="업적", description="달성한 업적과 남은 업적을 확인해요.")
    @app_commands.describe(
        유저="다른 사람의 업적을 보려면 지정하세요.",
        분야="특정 분야만 자세히 보고 싶을 때 골라주세요.",
    )
    @app_commands.choices(분야=CATEGORY_CHOICES)
    @restrict_to_channel("profile")
    async def achievements(
        self,
        interaction: discord.Interaction,
        유저: discord.Member | None = None,
        분야: str | None = None,
    ):
        await interaction.response.defer()
        target = 유저 or interaction.user

        # 보는 김에 판정도 해요(본인 것만 - 남의 업적을 내가 열어주는 건 이상하니까요).
        if target.id == interaction.user.id:
            stats = await _stats_for(target)
            newly = await achievement_store.evaluate(target.id, stats)
            if newly:
                reward = sum(a["reward"] for a in newly)
                names = ", ".join(f"{a['emoji']} **{a['name']}**" for a in newly[:5])
                if len(newly) > 5:
                    names += f" 외 {len(newly) - 5}개"
                await interaction.followup.send(
                    f"🎉 새 업적 {len(newly)}개 달성! {names} (+{reward}코인)"
                )

        await interaction.followup.send(embed=await build_achievement_embed(target, 분야))

    # ------------------------------------------------------------------
    @app_commands.command(name="내전전적", description="내전 승패와 연승 기록을 봐요.")
    @app_commands.describe(유저="다른 사람의 전적을 보려면 지정하세요.")
    @restrict_to_channel("profile")
    async def scrim_record(self, interaction: discord.Interaction, 유저: discord.Member | None = None):
        await interaction.response.defer()
        target = 유저 or interaction.user

        overall = await scrim_record_store.get_record(target.id)
        season = await scrim_record_store.get_season_record(target.id)
        total = overall["wins"] + overall["losses"]

        if total == 0:
            await interaction.followup.send(
                f"**{target.display_name}**님의 내전 기록이 아직 없어요.\n"
                "-# `/팀짜기`로 팀을 나눈 뒤 결과 버튼(**A팀 승리** / **B팀 승리**)을 누르면 기록돼요.",
            )
            return

        rate = scrim_record_store.win_rate(overall) or 0
        embed = discord.Embed(
            title=f"⚔️ {target.display_name}님의 내전 전적",
            color=0x57F287 if rate >= 50 else 0xED4245,
        )
        embed.add_field(
            name="통산",
            value=(
                f"**{overall['wins']}승 {overall['losses']}패** (승률 {rate:.1f}%)\n"
                f"최고 연승 **{overall.get('bestStreak', 0)}** · "
                f"최다 연패 **{abs(overall.get('worstStreak', 0))}**"
            ),
            inline=False,
        )

        season_total = season["wins"] + season["losses"]
        embed.add_field(
            name=f"시즌 {scrim_record_store.current_season()}",
            value=(
                f"**{season['wins']}승 {season['losses']}패** "
                f"(승률 {scrim_record_store.win_rate(season) or 0:.1f}%)"
                if season_total else "이번 시즌 기록 없음"
            ),
            inline=False,
        )
        embed.add_field(name="현재", value=scrim_record_store.streak_text(overall), inline=False)

        recent = await scrim_record_store.recent_matches(target.id, limit=5)
        if recent:
            uid = str(target.id)
            marks = " · ".join(
                ("🟩" if uid in match.get("winners", []) else "🟥")
                + (f" {match['map']}" if match.get("map") else "")
                for match in recent
            )
            embed.add_field(name="최근 5경기 (왼쪽이 최신)", value=marks, inline=False)

        map_rows = await scrim_record_store.map_stats(target.id)
        if map_rows:
            embed.add_field(
                name="🗺️ 맵별 성적",
                value=_map_stats_text(map_rows),
                inline=False,
            )
        else:
            embed.add_field(
                name="🗺️ 맵별 성적",
                value=(
                    "아직 맵이 기록된 경기가 없어요.\n"
                    "-# `/팀짜기`의 **🗺️ 맵** 버튼으로 맵을 정해두거나, "
                    "승리 보고 뒤에 뜨는 맵 드롭다운에서 골라주세요."
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    @app_commands.command(name="주간랭킹", description="이번 주 악귀력 순위와 내전 승수 순위를 봐요.")
    @app_commands.describe(지난주="지난주 순위를 보려면 켜세요.")
    @restrict_to_channel("profile")
    async def weekly_ranking(self, interaction: discord.Interaction, 지난주: bool = False):
        await interaction.response.defer()

        week = agwi_weekly_store.previous_week_key() if 지난주 else agwi_weekly_store.week_key()
        rows = await agwi_weekly_store.top(week, limit=10)

        embed = discord.Embed(
            title=f"📊 {'지난주' if 지난주 else '이번 주'} 랭킹 ({week})",
            color=0x9B59B6,
        )

        if rows:
            lines = []
            for rank, row in enumerate(rows):
                medal = MEDALS[rank] if rank < len(MEDALS) else f"`{rank + 1}.`"
                grade = f" · {row['grade']}" if row.get("grade") else ""
                lines.append(f"{medal} <@{row['userId']}> **{row['score']:,.0f}**{grade}")
            embed.add_field(name="😈 악귀력", value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name="😈 악귀력",
                value="이번 주엔 아직 아무도 `/전적`을 돌리지 않았어요.",
                inline=False,
            )

        # 내전 승수는 주 단위가 아니라 시즌 누적이에요(한 주에 내전이 두세 판이라
        # 주간으로 끊으면 순위가 거의 매번 비어요).
        season = scrim_record_store.current_season()
        scrim_rows = await scrim_record_store.top(season, limit=10, min_matches=1)
        if scrim_rows:
            lines = []
            for rank, row in enumerate(scrim_rows):
                medal = MEDALS[rank] if rank < len(MEDALS) else f"`{rank + 1}.`"
                rate = scrim_record_store.win_rate(row) or 0
                lines.append(
                    f"{medal} <@{row['userId']}> **{row['wins']}승 {row['losses']}패** ({rate:.0f}%)"
                )
            embed.add_field(name=f"⚔️ 내전 (시즌 {season})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name=f"⚔️ 내전 (시즌 {season})",
                value="아직 기록된 경기가 없어요. `/팀짜기` 후 결과 버튼을 눌러주세요.",
                inline=False,
            )

        embed.set_footer(text="악귀력은 /전적 을 돌린 사람만 집계돼요 · 내전은 /팀짜기 결과 보고 기준")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    @app_commands.command(name="내전시즌", description="[서버 소유자 전용] 내전 시즌 이름을 바꿔요. (통산 기록은 그대로)")
    @app_commands.describe(이름="새 시즌 이름 (예: S2). 비우면 지금 시즌을 알려줘요.")
    async def set_season(self, interaction: discord.Interaction, 이름: str | None = None):
        if 이름 is None:
            await interaction.response.send_message(
                f"지금 시즌은 **{scrim_record_store.current_season()}** 이에요.", ephemeral=True
            )
            return

        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "시즌 변경은 서버 소유자만 할 수 있어요.", ephemeral=True
            )
            return

        previous = scrim_record_store.current_season()
        scrim_record_store.set_season(이름.strip())
        await interaction.response.send_message(
            f"🗓️ 내전 시즌을 **{previous} → {이름.strip()}** 으로 바꿨어요.\n"
            "-# 통산 전적과 업적은 그대로예요. 시즌 순위만 새로 시작해요."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Achievement(bot))
