"""
`/팀짜기` — 음성채널 인원(또는 `인원`에 직접 적은 사람들)을 두 팀으로 나눠요.

누구를 나눌지는 두 갈래예요:
  - `인원`을 비우면 **명령어를 쓴 사람이 들어가 있는 음성채널** 인원을 긁어와요(원래 방식).
  - `인원`에 `@`로 나열하면 **그 사람들로만** 짜요. 음성채널에 없어도 되고, 방에 관전자가
    섞여 있을 때 일부만 골라낼 수도 있어요. 서버 멤버만 받아요(parse_members).

예전엔 그냥 `random.shuffle`이었는데, 내전에서 실력이 한쪽으로 쏠리면 재미가 없어져서
**티어와 악귀 스코어를 근거로 균형을 맞추는 방식**을 기본으로 바꿨어요. 완전 랜덤도
버튼/옵션으로 그대로 쓸 수 있어요.

점수의 출처(둘 다 이미 봇에 쌓여 있는 데이터예요. 새로 API를 부르지 않아요):
  - **티어 역할**: `/전적`을 본인 계정으로 돌리면 자동으로 붙어요(utils/tier_roles.py).
  - **악귀 스코어**: `/전적`이 계산해서 `data/rank_stats.json`에 남겨둔 값(utils/rank_stats_store.py).
    같은 티어 안에서 세부 보정으로만 써요(250점 = 1단계, 최대 ±3단계).
자세한 계산은 utils/team_balance.py에 있어요.
"""
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils import (
    achievement_store,
    rank_stats_store,
    riot_account_store,
    scrim_record_store,
    team_balance,
    tier_roles,
)

log = logging.getLogger(__name__)

# 버튼을 눌러 다시 섞을 수 있는 시간이에요. 내전 팀을 정하는 동안은 살아있어야 해요.
VIEW_TIMEOUT = 600
# 미리 뽑아둘 후보 편성 수. '다시 섞기'를 누르면 이 안에서 다음 것을 보여줘요.
CANDIDATE_COUNT = 10
# 이 차이 미만이면 "균형이 잘 맞는다"고 표시해요. (티어 단계 기준)
GOOD_BALANCE = 0.5
# `인원`에 적은 멘션을 떼어낼 때 써요. `<@123>`과 `<@!123>` 둘 다 들어와요.
_MENTION_RE = re.compile(r"<@!?(\d+)>")


class MemberParseError(Exception):
    """`인원`에 적은 걸 서버 멤버로 못 바꿨을 때 띄울 안내문을 담아요."""


def parse_members(guild: discord.Guild, raw: str) -> list[discord.Member]:
    """`@가 @나 다람쥐` 같은 입력을 서버 멤버 목록으로 바꿔요.

    디스코드가 `@`를 자동완성해주면 `<@123>` 형태로 들어와서 id로 바로 찾을 수 있어요.
    자동완성을 안 쓰고 이름만 적는 사람도 있어서, 멘션이 아닌 토막은 표시이름/계정이름으로
    찾아봐요(대소문자 무시). **서버에 없는 사람은 받지 않아요** - 티어도 악귀 스코어도 없고
    내전 전적에도 남길 수 없어서, 조용히 평균으로 끼워넣는 대신 무엇을 못 찾았는지 알려줘요.

    순서는 적은 순서를 지키고, 같은 사람을 두 번 적으면 한 번만 넣어요.
    """
    found: list[discord.Member] = []
    seen: set[int] = set()
    unknown: list[str] = []

    # 멘션(`<@123>`, `<@!123>`)은 공백이 없지만, 이름은 공백을 품을 수 있어요(`최 강`).
    # 그래서 멘션을 먼저 떼어내고, 남은 덩어리를 쉼표로 끊어 이름으로 봐요.
    rest = _MENTION_RE.sub(lambda m: _consume(m, guild, found, seen, unknown), raw)
    for chunk in re.split(r"[,\n]+", rest):
        name = chunk.strip().lstrip("@").strip()
        if not name:
            continue
        member = _find_by_name(guild, name)
        if member is None:
            unknown.append(name)
        elif member.id not in seen:
            seen.add(member.id)
            found.append(member)

    if unknown:
        shown = ", ".join(f"`{u}`" for u in unknown[:5])
        if len(unknown) > 5:
            shown += f" 외 {len(unknown) - 5}개"
        raise MemberParseError(
            f"{shown} 은(는) 이 서버에서 못 찾았어요.\n"
            "`@`를 눌러 자동완성으로 고르면 확실해요. 이름이 여러 단어면 쉼표로 끊어주세요. "
            "(예: `@가 @나` 또는 `최 강, 생명체`)"
        )
    return [m for m in found if not m.bot]


def _consume(
    match: "re.Match[str]",
    guild: discord.Guild,
    found: list[discord.Member],
    seen: set[int],
    unknown: list[str],
) -> str:
    """멘션 하나를 멤버로 바꿔 담고, 원문에서는 지워요(남은 글자를 이름으로 보려고요)."""
    member = guild.get_member(int(match.group(1)))
    if member is None:
        unknown.append(match.group(0))
    elif member.id not in seen:
        seen.add(member.id)
        found.append(member)
    return " "


def _find_by_name(guild: discord.Guild, name: str) -> discord.Member | None:
    lowered = name.lower()
    for member in guild.members:
        if member.display_name.lower() == lowered or member.name.lower() == lowered:
            return member
    return None


def _collect_players(members: list[discord.Member]) -> list[team_balance.Rated]:
    """음성채널 멤버들을 점수가 매겨진 참가자 목록으로 바꿔요."""
    players = []
    for member in members:
        tier_index = tier_roles.member_tier_index(member)
        agwi_score = None
        account = riot_account_store.get_account(member.id)
        if account:
            stats = rank_stats_store.get_stats(f"{account[0]}#{account[1]}")
            if stats:
                agwi_score = stats.get("agwi_score")
        players.append(
            team_balance.Rated(
                key=member.id,
                label=member.display_name,
                rating=team_balance.rate_one(tier_index, agwi_score),
                tier_index=tier_index,
                agwi_score=agwi_score,
            )
        )
    return team_balance.fill_missing(players)


def _player_line(player: team_balance.Rated) -> str:
    """'🥇 골드 3 · 악귀 (1120점)' 같은 한 줄이에요."""
    if player.tier_index is None:
        tier_text = "❔ 티어 미확인"
    else:
        tier_text = tier_roles.display_name_for(
            tier_roles.tier_name_from_index(player.tier_index)
        )
    score_text = f" ({player.agwi_score:.0f}점)" if player.agwi_score is not None else ""
    return f"{tier_text} · **{player.label}**{score_text}"


def _team_field_name(title: str, team: list[team_balance.Rated], balanced: bool) -> str:
    if not balanced:
        return f"{title} ({len(team)}명)"
    average = sum(p.rating for p in team) / len(team)
    average_tier = tier_roles.display_name_for(tier_roles.tier_name_from_index(average))
    return f"{title} ({len(team)}명) · 평균 {average_tier}"


def _build_embed(
    team_a: list[team_balance.Rated],
    team_b: list[team_balance.Rated],
    diff: float,
    *,
    balanced: bool,
    source_label: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="🎯 팀 나누기 (실력 균형)" if balanced else "🎲 팀 나누기 (완전 랜덤)",
        color=0x00B0F4 if balanced else 0x9B7BF0,
    )
    embed.add_field(
        name=_team_field_name("🅰️ 팀 A", team_a, balanced),
        value="\n".join(_player_line(p) for p in team_a) or "-",
        inline=True,
    )
    embed.add_field(
        name=_team_field_name("🅱️ 팀 B", team_b, balanced),
        value="\n".join(_player_line(p) for p in team_b) or "-",
        inline=True,
    )

    if balanced:
        verdict = "균형이 잘 맞아요" if diff < GOOD_BALANCE else "이 인원에선 이게 가장 균형 잡힌 편성이에요"
        embed.add_field(
            name="⚖️ 실력 차이",
            value=f"약 **{diff:.2f}단계** — {verdict}",
            inline=False,
        )

    estimated = [p.label for p in team_a + team_b if p.estimated]
    if balanced and estimated:
        # 인원이 많으면 이름을 다 적지 않아요(임베드 칸에 1024자 제한이 있어요).
        shown = ", ".join(estimated[:5])
        if len(estimated) > 5:
            shown += f" 외 {len(estimated) - 5}명"
        embed.add_field(
            name="❔ 기록이 없어 평균으로 계산한 인원",
            value=(
                f"{shown}\n"
                "`/전적`을 본인 계정으로 한 번 돌리면 티어 역할이 붙어서 다음부터 정확해져요."
            ),
            inline=False,
        )

    # 임베드 꼬리말은 줄바꿈이 제대로 안 살아서 한 줄로만 적어요.
    # source_label에는 '🎧 랭크방' / '✍️ 직접 지정 (6명)'처럼 아이콘까지 들어있어요.
    footer = source_label
    if balanced:
        footer += " · 점수 근거: 티어 역할 + 악귀 스코어(250점 = 1단계, 최대 ±3단계)"
    embed.set_footer(text=footer)
    return embed


class TeamSplitView(discord.ui.View):
    """'다시 섞기'와 '완전 랜덤'을 누를 수 있는 화면이에요. 명령어를 쓴 사람만 조작할 수 있어요."""

    def __init__(
        self,
        players: list[team_balance.Rated],
        candidates: list[tuple[list, list, float]],
        *,
        owner_id: int,
        source_label: str,
        initial: tuple[list, list],
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self._players = players
        self._candidates = candidates
        self._index = 0
        self._owner_id = owner_id
        self._source_label = source_label
        self.message: discord.Message | None = None
        # 지금 화면에 떠 있는 편성이에요. 승리 보고는 **이 편성 기준**으로 기록돼요.
        # (다시 섞기를 누를 때마다 같이 갱신돼요 - 안 그러면 처음 편성으로 기록돼버려요.
        #  '완전 랜덤'으로 시작하면 candidates[0]과 화면이 다르니 initial을 따로 받아요.)
        self._current: tuple[list, list] = initial
        # 결과를 한 번 기록했으면 더 못 바꾸게 잠가요.
        self._reported = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._owner_id:
            return True
        await interaction.response.send_message(
            "`/팀짜기`를 실행한 사람만 편성을 바꾸거나 결과를 기록할 수 있어요. "
            "직접 `/팀짜기`를 써주세요.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self):
        # 시간이 지난 화면의 버튼은 눌러도 반응이 없어서, 눌리지 않게 꺼둬요.
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="다시 섞기", emoji="🔄", style=discord.ButtonStyle.primary)
    async def reshuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._index += 1
        if self._index >= len(self._candidates):
            # 준비해둔 후보를 다 봤으면 새로 뽑아요(동률 편성은 매번 순서가 섞여요).
            self._candidates = team_balance.balanced_splits(self._players, limit=CANDIDATE_COUNT)
            self._index = 0
        team_a, team_b, diff = self._candidates[self._index]
        self._current = (team_a, team_b)
        await interaction.response.edit_message(
            embed=_build_embed(
                team_a, team_b, diff, balanced=True, source_label=self._source_label
            ),
            view=self,
        )

    @discord.ui.button(label="완전 랜덤", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def pure_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        team_a, team_b, diff = team_balance.random_split(self._players)
        self._current = (team_a, team_b)
        await interaction.response.edit_message(
            embed=_build_embed(
                team_a, team_b, diff, balanced=False, source_label=self._source_label
            ),
            view=self,
        )

    # ── 경기 결과 보고 ─────────────────────────────────────────────
    #
    # 이 두 버튼이 **내전 전적이 쌓이는 거의 유일한 경로**예요. 팀을 나눈 직후라 출전
    # 명단이 그대로 손에 있어서, 버튼 한 번이면 양 팀 전원의 승/패가 한꺼번에 들어가요.
    # (`/베팅결과`로도 들어가지만 베팅을 안 열면 아무것도 안 남아요.)
    #
    # 결과를 보고하면 팀 편성을 더 못 바꾸게 막아요. 이미 끝난 경기의 명단이 바뀌면
    # 기록과 화면이 어긋나거든요.
    @discord.ui.button(label="🅰️ A팀 승리", style=discord.ButtonStyle.success, row=1)
    async def report_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._report(interaction, winner_index=0)

    @discord.ui.button(label="🅱️ B팀 승리", style=discord.ButtonStyle.success, row=1)
    async def report_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._report(interaction, winner_index=1)

    async def _report(self, interaction: discord.Interaction, winner_index: int):
        if self._reported:
            await interaction.response.send_message(
                "이 경기는 이미 결과가 기록됐어요. 다음 경기는 `/팀짜기`를 새로 써주세요.",
                ephemeral=True,
            )
            return

        team_a, team_b = self._current
        teams = [team_a, team_b]
        winners = [p.key for p in teams[winner_index]]
        losers = [p.key for p in teams[1 - winner_index]]

        await interaction.response.defer()
        self._reported = True

        match_id = await scrim_record_store.record_match(
            interaction.guild_id, winners, losers,
            reported_by=interaction.user.id,
            note=f"/팀짜기 · {self._source_label}",
        )
        if match_id is None:
            self._reported = False
            await interaction.followup.send(
                "한쪽 팀이 비어 있어서 기록하지 못했어요.", ephemeral=True
            )
            return

        # 결과가 나온 뒤에는 편성을 못 바꾸게 잠가요.
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

        won_name = "🅰️ A팀" if winner_index == 0 else "🅱️ B팀"
        lines = [
            f"🏆 **{won_name} 승리**로 기록했어요! (기록: {interaction.user.display_name})",
            "",
            f"**승리** {', '.join(p.label for p in teams[winner_index])}",
            f"**패배** {', '.join(p.label for p in teams[1 - winner_index])}",
        ]

        # 이번 경기로 업적이 열린 사람이 있으면 같이 알려줘요(내전 업적은 여기서만 열려요).
        unlocked_lines = await _announce_achievements(interaction, winners + losers)
        if unlocked_lines:
            lines.append("")
            lines.extend(unlocked_lines)

        lines.append("")
        lines.append("-# `/내전전적`으로 내 승패와 연승을 볼 수 있어요.")

        await interaction.followup.send("\n".join(lines))


async def _announce_achievements(interaction: discord.Interaction, user_ids: list[int]) -> list[str]:
    """경기 참가자들의 업적을 판정하고, 새로 열린 게 있으면 알림 줄을 만들어요.

    사람 수만큼 DB를 왕복하지만 내전 한 판이 끝날 때 한 번뿐이라 부담이 크지 않아요.
    여기서 실패해도 경기 기록 자체는 이미 들어간 뒤라, 조용히 넘어가요."""
    lines = []
    for user_id in user_ids:
        try:
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            stats = await achievement_store.collect_stats(
                user_id,
                tier_index=tier_roles.member_tier_index(member) if member else None,
                riot_linked=riot_account_store.get_account(user_id) is not None,
            )
            newly = await achievement_store.evaluate(user_id, stats)
            for achievement in newly:
                lines.append(
                    f"{achievement['emoji']} <@{user_id}> **{achievement['name']}** 업적 달성! "
                    f"(+{achievement['reward']}코인)"
                )
        except Exception:
            log.warning("업적 판정 실패 (user=%s)", user_id, exc_info=True)
    # 한 판에 10명이 동시에 여러 개를 열 수 있어서, 메시지가 2000자를 넘지 않게 잘라요.
    if len(lines) > 8:
        extra = len(lines) - 8
        lines = lines[:8] + [f"-# 그 외 업적 {extra}개가 더 열렸어요. `/업적`에서 확인하세요."]
    return lines


class Team(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="팀짜기",
        description="음성채널 인원(또는 직접 지정한 사람들)을 티어·전적 기준으로 두 팀으로 나눠요.",
    )
    @app_commands.describe(
        인원="직접 지정할 때만 적어요. @로 멘션해서 나열하세요. 비우면 지금 있는 음성채널 인원으로 해요.",
        방식="균형(기본)은 티어·악귀 스코어를 맞춰요. 랜덤은 실력을 무시해요.",
    )
    @app_commands.choices(
        방식=[
            app_commands.Choice(name="실력 균형 (기본)", value="balanced"),
            app_commands.Choice(name="완전 랜덤", value="random"),
        ]
    )
    async def team_split(
        self, interaction: discord.Interaction, 인원: str | None = None, 방식: str = "balanced"
    ):
        # `인원`을 적었으면 그 사람들로만 짜요. 음성채널에 안 들어가 있어도 되고, 방에 있는
        # 사람 중 일부만 빼서 짤 수도 있어요(관전자가 섞여 있는 내전에서 이게 필요했어요).
        if 인원 and 인원.strip():
            if interaction.guild is None:
                await interaction.response.send_message(
                    "`인원`을 직접 적는 건 서버 안에서만 쓸 수 있어요.", ephemeral=True
                )
                return
            try:
                members = parse_members(interaction.guild, 인원)
            except MemberParseError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            if len(members) < 2:
                await interaction.response.send_message(
                    "팀을 나누려면 최소 2명은 적어야 해요. (봇은 세지 않아요)", ephemeral=True
                )
                return
            source_label = f"✍️ 직접 지정 ({len(members)}명)"
        else:
            voice_state = (
                interaction.user.voice if isinstance(interaction.user, discord.Member) else None
            )
            if voice_state is None or voice_state.channel is None:
                await interaction.response.send_message(
                    "먼저 음성 채널에 입장한 뒤 사용해주세요. "
                    "아니면 `인원`에 `@`로 멤버를 나열해서 직접 지정할 수도 있어요.",
                    ephemeral=True,
                )
                return
            members = [m for m in voice_state.channel.members if not m.bot]
            if len(members) < 2:
                await interaction.response.send_message(
                    "팀을 나누려면 음성 채널에 최소 2명은 있어야 해요.", ephemeral=True
                )
                return
            source_label = f"🎧 {voice_state.channel.name}"

        # 역할 확인 + 저장된 전적 조회가 있어서 3초를 넘길 수 있어요.
        await interaction.response.defer()

        players = _collect_players(members)

        if 방식 == "random":
            team_a, team_b, diff = team_balance.random_split(players)
            balanced = False
            candidates = team_balance.balanced_splits(players, limit=CANDIDATE_COUNT)
        else:
            candidates = team_balance.balanced_splits(players, limit=CANDIDATE_COUNT)
            team_a, team_b, diff = candidates[0]
            balanced = True

        view = TeamSplitView(
            players, candidates,
            owner_id=interaction.user.id,
            source_label=source_label,
            initial=(team_a, team_b),
        )
        message = await interaction.followup.send(
            embed=_build_embed(
                team_a, team_b, diff, balanced=balanced, source_label=source_label
            ),
            view=view,
            wait=True,
        )
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(Team(bot))
