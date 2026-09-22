"""
`/팀짜기` — 음성채널 인원을 두 팀으로 나눠요.

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

import discord
from discord import app_commands
from discord.ext import commands

from utils import rank_stats_store, riot_account_store, team_balance, tier_roles

log = logging.getLogger(__name__)

# 버튼을 눌러 다시 섞을 수 있는 시간이에요. 내전 팀을 정하는 동안은 살아있어야 해요.
VIEW_TIMEOUT = 600
# 미리 뽑아둘 후보 편성 수. '다시 섞기'를 누르면 이 안에서 다음 것을 보여줘요.
CANDIDATE_COUNT = 10
# 이 차이 미만이면 "균형이 잘 맞는다"고 표시해요. (티어 단계 기준)
GOOD_BALANCE = 0.5


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
    channel_name: str,
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
    footer = f"🎧 {channel_name}"
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
        channel_name: str,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self._players = players
        self._candidates = candidates
        self._index = 0
        self._owner_id = owner_id
        self._channel_name = channel_name
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._owner_id:
            return True
        await interaction.response.send_message(
            "명령어를 실행한 사람만 다시 섞을 수 있어요. 직접 `/팀짜기`를 써주세요.", ephemeral=True
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
        await interaction.response.edit_message(
            embed=_build_embed(
                team_a, team_b, diff, balanced=True, channel_name=self._channel_name
            ),
            view=self,
        )

    @discord.ui.button(label="완전 랜덤", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def pure_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        team_a, team_b, diff = team_balance.random_split(self._players)
        await interaction.response.edit_message(
            embed=_build_embed(
                team_a, team_b, diff, balanced=False, channel_name=self._channel_name
            ),
            view=self,
        )


class Team(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="팀짜기",
        description="지금 음성채널에 있는 인원을 티어·전적 기준으로 균형 잡힌 두 팀으로 나눠요.",
    )
    @app_commands.describe(방식="균형(기본)은 티어·악귀 스코어를 맞춰요. 랜덤은 실력을 무시해요.")
    @app_commands.choices(
        방식=[
            app_commands.Choice(name="실력 균형 (기본)", value="balanced"),
            app_commands.Choice(name="완전 랜덤", value="random"),
        ]
    )
    async def team_split(
        self, interaction: discord.Interaction, 방식: str = "balanced"
    ):
        voice_state = (
            interaction.user.voice if isinstance(interaction.user, discord.Member) else None
        )
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "먼저 음성 채널에 입장한 뒤 사용해주세요.", ephemeral=True
            )
            return

        members = [m for m in voice_state.channel.members if not m.bot]
        if len(members) < 2:
            await interaction.response.send_message(
                "팀을 나누려면 음성 채널에 최소 2명은 있어야 해요.", ephemeral=True
            )
            return

        # 역할 확인 + 저장된 전적 조회가 있어서 3초를 넘길 수 있어요.
        await interaction.response.defer()

        players = _collect_players(members)
        channel_name = voice_state.channel.name

        if 방식 == "random":
            team_a, team_b, diff = team_balance.random_split(players)
            balanced = False
            candidates = team_balance.balanced_splits(players, limit=CANDIDATE_COUNT)
        else:
            candidates = team_balance.balanced_splits(players, limit=CANDIDATE_COUNT)
            team_a, team_b, diff = candidates[0]
            balanced = True

        view = TeamSplitView(
            players, candidates, owner_id=interaction.user.id, channel_name=channel_name
        )
        message = await interaction.followup.send(
            embed=_build_embed(
                team_a, team_b, diff, balanced=balanced, channel_name=channel_name
            ),
            view=view,
            wait=True,
        )
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(Team(bot))
