"""
`/팀짜기` — 음성채널 인원(또는 `인원`에 직접 적은 사람들)을 두 팀으로 나눠요.

누구를 나눌지는 두 갈래예요:
  - `인원`을 비우면 **명령어를 쓴 사람이 들어가 있는 음성채널** 인원을 긁어와요(원래 방식).
  - `인원`에 `@`로 나열하면 **그 사람들로만** 짜요. 음성채널에 없어도 되고, 방에 관전자가
    섞여 있을 때 일부만 골라낼 수도 있어요. 서버 멤버만 받아요(parse_members).

예전엔 그냥 `random.shuffle`이었는데, 내전에서 실력이 한쪽으로 쏠리면 재미가 없어져서
**티어와 악귀 스코어를 근거로 균형을 맞추는 방식**을 기본으로 바꿨어요. 완전 랜덤도
버튼/옵션으로 그대로 쓸 수 있어요.

편성이 마음에 안 들면 **🔀 직접 조정** 버튼으로 손을 볼 수 있어요. 양쪽에서 한 명씩 고르면
맞교환하고, 한쪽만 고르면 그 사람만 반대편으로 옮겨요(ManualAdjustView). 바꾼 명단은
`_current`에 반영돼서 승리 보고도 **바꾼 뒤 명단**으로 기록돼요.

**👑 팀장** 버튼으로 양 팀의 팀장을 정할 수 있어요. 드롭다운으로 직접 고르거나 🎲 무작위로
뽑을 수 있고, 정하면 명단에서 그 사람 앞에 👑이 붙어요(CaptainPickView). 편성이 통째로
바뀌는 🔄/🎲는 팀장을 지우고, 🔀 직접 조정은 **팀장이 그 팀에 남아 있으면** 그대로 둬요.

**`/팀보기`** 는 그 서버에서 마지막으로 짠 편성을 다시 보여줘요. `/팀짜기` 메시지는 10분 뒤에
버튼이 꺼지고 채팅에 묻혀버려서, 한참 뒤에 "우리 팀 뭐였지?"를 볼 방법이 없었어요. 편성이
바뀔 때마다 utils/team_store.py에 마지막 하나만 덮어써 두고, 거기서 읽어 그려요.
명령어를 쓴 사람만이 아니라 **누구나** 볼 수 있어요.

점수의 출처(둘 다 이미 봇에 쌓여 있는 데이터예요. 새로 API를 부르지 않아요):
  - **티어 역할**: `/전적`을 본인 계정으로 돌리면 자동으로 붙어요(utils/tier_roles.py).
  - **악귀 스코어**: `/전적`이 계산해서 `data/rank_stats.json`에 남겨둔 값(utils/rank_stats_store.py).
    같은 티어 안에서 세부 보정으로만 써요(250점 = 1단계, 최대 ±3단계).
자세한 계산은 utils/team_balance.py에 있어요.
"""
import asyncio
import logging
import random
import re
from datetime import datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils import (
    achievement_store,
    rank_stats_store,
    riot_account_store,
    scrim_record_store,
    scrim_stats_fetch,
    team_balance,
    team_store,
    tier_roles,
    valorant_maps,
)

log = logging.getLogger(__name__)

# 버튼을 눌러 다시 섞을 수 있는 시간이에요. 내전 팀을 정하는 동안은 살아있어야 해요.
VIEW_TIMEOUT = 600
# 미리 뽑아둘 후보 편성 수. '다시 섞기'를 누르면 이 안에서 다음 것을 보여줘요.
CANDIDATE_COUNT = 10
# '🔀 직접 조정'과 '👑 팀장' 창이 열려 있는 시간이에요. 고르고 누르는 데만 쓰니 짧아도 돼요.
MANUAL_TIMEOUT = 180
# 드롭다운 하나에 담을 수 있는 최대 항목 수(디스코드 제한).
SELECT_LIMIT = 25
# 이 차이 미만이면 "균형이 잘 맞는다"고 표시해요. (티어 단계 기준)
GOOD_BALANCE = 0.5
# 경기 기록(KDA)을 못 찾았을 때 다시 시도하기까지 기다리는 시간이에요.
# 경기가 라이엇 전적에 올라오는 데 시간이 걸려요. 상호작용 토큰이 15분이라 그보다 짧게 둬요.
STATS_RETRY_SECONDS = 150
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


def _when_text(saved_at: str | None) -> str:
    """저장해둔 시각을 '오늘 21:40' / '어제 23:05' / '10월 1일 21:00'으로 바꿔요.

    `/팀보기`에서 제일 중요한 정보예요 - 어제 짠 편성을 오늘 것으로 착각하면 안 되니까요.
    파일을 손으로 고쳐서 시각이 깨져 있어도 명령어가 죽지는 않게 해요."""
    if not saved_at:
        return "언제인지 모르는 시점"
    try:
        moment = datetime.fromisoformat(saved_at)
    except (TypeError, ValueError):
        return "언제인지 모르는 시점"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=team_store.KST)
    moment = moment.astimezone(team_store.KST)
    days = (datetime.now(team_store.KST).date() - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return f"오늘 {clock}"
    if days == 1:
        return f"어제 {clock}"
    return f"{moment.month}월 {moment.day}일 {clock}"


def _player_line(player: team_balance.Rated, *, captain: bool = False) -> str:
    """'🥇 골드 3 · 악귀 (1120점)' 같은 한 줄이에요. 팀장이면 앞에 👑을 붙여요."""
    if player.tier_index is None:
        tier_text = "❔ 티어 미확인"
    else:
        tier_text = tier_roles.display_name_for(
            tier_roles.tier_name_from_index(player.tier_index)
        )
    score_text = f" ({player.agwi_score:.0f}점)" if player.agwi_score is not None else ""
    mark = "👑 " if captain else ""
    return f"{mark}{tier_text} · **{player.label}**{score_text}"


def _team_lines(team: list[team_balance.Rated], captain_id: int | None) -> str:
    """팀장을 맨 위로 올려서 명단 한 덩어리를 만들어요(누가 팀장인지 바로 보이게)."""
    captain = next((p for p in team if p.key == captain_id), None)
    ordered = ([captain] if captain else []) + [p for p in team if p is not captain]
    lines = [_player_line(p, captain=p is captain) for p in ordered]
    return "\n".join(lines) or "-"


def _team_field_name(title: str, team: list[team_balance.Rated], balanced: bool) -> str:
    if not balanced or not team:
        return f"{title} ({len(team)}명)"
    average = sum(p.rating for p in team) / len(team)
    average_tier = tier_roles.display_name_for(tier_roles.tier_name_from_index(average))
    return f"{title} ({len(team)}명) · 평균 {average_tier}"


def _build_embed(
    team_a: list[team_balance.Rated],
    team_b: list[team_balance.Rated],
    diff: float | None,
    *,
    mode: str,
    source_label: str,
    captains: tuple[int | None, int | None] = (None, None),
    map_name: str | None = None,
) -> discord.Embed:
    # mode는 이 편성을 어떻게 만들었는지예요(team_store의 MODE_* 값).
    # MANUAL은 '🔀 직접 조정'으로 손을 본 편성이에요. 이때도 점수와 실력 차이는 보여줘요 -
    # 바꾼 뒤에 균형이 얼마나 틀어졌는지 봐야 하니까요.
    manual = mode == team_store.MODE_MANUAL
    if manual:
        title, color = "✏️ 팀 나누기 (직접 조정)", 0xF2A900
    elif mode == team_store.MODE_RANDOM:
        title, color = "🎲 팀 나누기 (완전 랜덤)", 0x9B7BF0
    else:
        title, color = "🎯 팀 나누기 (실력 균형)", 0x00B0F4
    if map_name:
        # 맵을 정해뒀으면 제목에 붙여요. 승리 보고 때 이 맵으로 기록돼요.
        title += f" · 🗺️ {map_name}"
    embed = discord.Embed(title=title, color=color)
    balanced = mode != team_store.MODE_RANDOM
    embed.add_field(
        name=_team_field_name("🅰️ 팀 A", team_a, balanced),
        value=_team_lines(team_a, captains[0]),
        inline=True,
    )
    embed.add_field(
        name=_team_field_name("🅱️ 팀 B", team_b, balanced),
        value=_team_lines(team_b, captains[1]),
        inline=True,
    )

    if balanced and diff is not None:
        if diff < GOOD_BALANCE:
            verdict = "균형이 잘 맞아요"
        elif manual:
            verdict = "직접 맞춘 편성이에요"
        else:
            verdict = "이 인원에선 이게 가장 균형 잡힌 편성이에요"
        value = f"약 **{diff:.2f}단계** — {verdict}"
        if manual:
            # 손으로 바꿔놓고 다시 섞기를 누르면 날아가서, 미리 알려줘요.
            value += "\n-# 🔄 다시 섞기를 누르면 직접 조정한 편성은 사라져요."
        embed.add_field(name="⚖️ 실력 차이", value=value, inline=False)

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
    # (`/팀보기`가 읽는 옛 기록엔 source_label이 비어 있을 수 있어서 빈 칸은 걸러요)
    parts = [source_label] if source_label else []
    if balanced:
        parts.append("점수 근거: 티어 역할 + 악귀 스코어(250점 = 1단계, 최대 ±3단계)")
    embed.set_footer(text=" · ".join(parts))
    return embed


def _stat_line(player: dict, rounds_played: int) -> str:
    """'🔫 **OwO** 24/17/7 · ADR 162 · HS 18%' 같은 한 줄이에요."""
    kda = f"{player['kills']}/{player['deaths']}/{player['assists']}"
    bits = [f"**{player.get('name') or '?'}** `{kda}`"]
    adr = scrim_stats_fetch.per_round(player.get("damage") or 0, rounds_played)
    if adr:
        bits.append(f"ADR {adr:.0f}")
    hs = scrim_stats_fetch.headshot_rate(player.get("headshots") or 0, player.get("shots") or 0)
    if hs is not None:
        bits.append(f"HS {hs:.0f}%")
    if player.get("agent"):
        bits.append(player["agent"])
    return " · ".join(bits)


def build_stats_embed(stats: dict, winner_index: int) -> discord.Embed:
    """경기에서 가져온 실제 기록(KDA)을 보여주는 화면이에요.

    팀 이름은 게임 쪽 Red/Blue 그대로 써요. 우리 🅰️/🅱️와 짝지으려면 명단을 맞춰봐야 하는데,
    인원이 바뀌거나(관전자 합류) 다른 경기를 물어왔을 때 **엉뚱하게 짝지으면 더 헷갈려요.**
    그래서 게임이 준 대로 보여주고, 라운드 스코어로 누가 이겼는지 알 수 있게 해둬요."""
    rounds = stats.get("rounds") or {}
    rounds_played = stats.get("roundsPlayed") or 0
    embed = discord.Embed(
        title="🗡️ 경기 기록을 가져왔어요",
        description=(
            f"🗺️ **{stats.get('map') or '맵 미확인'}** · "
            f"{rounds.get('red') if rounds.get('red') is not None else '?'}"
            f" : {rounds.get('blue') if rounds.get('blue') is not None else '?'}"
            f" ({rounds_played}라운드)"
        ),
        color=0x4E5D94,
    )

    players = stats.get("players") or []
    for team, label in (("red", "🔴 Red"), ("blue", "🔵 Blue")):
        members = [p for p in players if p.get("team") == team]
        if not members:
            continue
        # 킬 많은 순으로 보여줘요(점수 순이 더 정확하지만 킬이 눈에 먼저 들어와요).
        members.sort(key=lambda p: (p.get("kills") or 0, p.get("score") or 0), reverse=True)
        won = " · 승" if stats.get("wonTeam") == team else ""
        embed.add_field(
            name=f"{label}{won}",
            value="\n".join(_stat_line(p, rounds_played) for p in members)[:1024],
            inline=False,
        )

    unlinked = [p.get("name") for p in players if not p.get("userId")]
    notes = []
    if unlinked:
        shown = ", ".join(n for n in unlinked[:4] if n)
        if len(unlinked) > 4:
            shown += f" 외 {len(unlinked) - 4}명"
        notes.append(
            f"계정 미등록: {shown} — `/티어 계정등록`을 하면 이 기록이 전적에 쌓여요."
        )
    notes.append("경기 기록은 라이엇 전적 서버에서 가져왔어요(사용자 설정 경기).")
    embed.set_footer(text=" · ".join(notes)[:2048])
    return embed


class _TeamMemberSelect(discord.ui.Select):
    """한 팀에서 한 명을 고르는 드롭다운이에요. 안 고르는 것도 허용해요(min_values=0)."""

    def __init__(self, placeholder: str, team: list[team_balance.Rated]):
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=1,
            # 드롭다운은 25개까지만 담을 수 있어요. 한 팀이 25명을 넘는 경우는
            # manual_adjust에서 미리 막아요.
            options=[
                discord.SelectOption(label=p.label[:100], value=str(p.key))
                for p in team[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        # 고른 값은 self.values에 남아 있어요. 실제 교환은 '✅ 적용'에서 한꺼번에 해요.
        # 여기서 응답을 안 하면 디스코드가 '상호작용 실패'를 띄워서 defer만 해둬요.
        await interaction.response.defer()


class ManualAdjustView(discord.ui.View):
    """🅰️/🅱️에서 한 명씩 골라 맞교환하는 화면이에요. 명령어를 쓴 사람에게만 보여요.

    한쪽만 고르면 그 사람만 반대편으로 옮겨요(인원이 한 명씩 어긋나는 건 일부러 허용해요 -
    관전자가 생겨서 4대6으로 돌리고 싶을 때가 있어요)."""

    def __init__(self, parent: "TeamSplitView"):
        super().__init__(timeout=MANUAL_TIMEOUT)
        self._parent = parent
        team_a, team_b = parent.current
        self._a_select = _TeamMemberSelect("🅰️ A팀에서 뺄 사람 (안 골라도 돼요)", team_a)
        self._b_select = _TeamMemberSelect("🅱️ B팀에서 뺄 사람 (안 골라도 돼요)", team_b)
        self.add_item(self._a_select)
        self.add_item(self._b_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._parent.owner_id:
            return True
        await interaction.response.send_message(
            "`/팀짜기`를 실행한 사람만 조정할 수 있어요.", ephemeral=True
        )
        return False

    @discord.ui.button(label="적용", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._parent.reported:
            await interaction.response.edit_message(
                content="이 경기는 이미 결과가 기록돼서 편성을 바꿀 수 없어요.", view=None
            )
            return

        team_a, team_b = self._parent.current
        a_out = _pick(team_a, self._a_select.values)
        b_out = _pick(team_b, self._b_select.values)

        if a_out is None and b_out is None:
            await interaction.response.send_message(
                "바꿀 사람을 한 명 이상 골라주세요.", ephemeral=True
            )
            return

        new_a, new_b = swap_players(team_a, team_b, a_out, b_out)
        if not new_a or not new_b:
            await interaction.response.send_message(
                "한쪽 팀이 비어버려요. 맞교환으로 바꾸거나, `/팀짜기`를 새로 써주세요.",
                ephemeral=True,
            )
            return

        diff = await self._parent.apply_manual(new_a, new_b)

        if a_out and b_out:
            summary = f"🔀 **{a_out.label}** ↔ **{b_out.label}** 맞교환했어요."
        elif a_out:
            summary = f"🔀 **{a_out.label}** 를 🅱️ B팀으로 옮겼어요."
        else:
            summary = f"🔀 **{b_out.label}** 를 🅰️ A팀으로 옮겼어요."
        await interaction.response.edit_message(
            content=f"{summary} (실력 차이 약 {diff:.2f}단계)\n"
                    "-# 더 바꾸려면 위 메시지에서 🔀 직접 조정을 다시 눌러주세요.",
            view=None,
        )


def _pick(
    team: list[team_balance.Rated], values: list[str]
) -> team_balance.Rated | None:
    """드롭다운이 돌려준 유저 id로 그 팀 안의 참가자를 찾아요."""
    if not values:
        return None
    return next((p for p in team if str(p.key) == values[0]), None)


def swap_players(
    team_a: list[team_balance.Rated],
    team_b: list[team_balance.Rated],
    a_out: team_balance.Rated | None,
    b_out: team_balance.Rated | None,
) -> tuple[list[team_balance.Rated], list[team_balance.Rated]]:
    """A에서 뺀 사람과 B에서 뺀 사람을 서로 보내요. 한쪽이 None이면 한 명만 이동해요.

    원본 리스트는 건드리지 않고 새 리스트를 돌려줘요 - 원본을 제자리에서 고치면
    `_candidates`에 들어있는 후보 편성까지 같이 망가져요(같은 리스트를 공유해요)."""
    new_a = [p for p in team_a if p is not a_out]
    new_b = [p for p in team_b if p is not b_out]
    if b_out is not None:
        new_a.append(b_out)
    if a_out is not None:
        new_b.append(a_out)
    return new_a, new_b


def keep_valid_captains(
    team_a: list[team_balance.Rated],
    team_b: list[team_balance.Rated],
    captains: tuple[int | None, int | None],
) -> tuple[int | None, int | None]:
    """편성이 바뀐 뒤에도 그 팀에 남아 있는 팀장만 지켜요.

    🔀 직접 조정으로 팀장이 반대편으로 넘어가면 그 자리는 비워요. '옮겨간 팀의 팀장'으로
    자동 승격시키면 반대편 팀장과 겹치거나, 아무도 원하지 않은 팀장이 생겨버려요."""
    a_ids = {p.key for p in team_a}
    b_ids = {p.key for p in team_b}
    return (
        captains[0] if captains[0] in a_ids else None,
        captains[1] if captains[1] in b_ids else None,
    )


def random_captains(
    team_a: list[team_balance.Rated], team_b: list[team_balance.Rated]
) -> tuple[int | None, int | None]:
    """양 팀에서 한 명씩 무작위로 뽑아요. 빈 팀은 None."""
    return (
        random.choice(team_a).key if team_a else None,
        random.choice(team_b).key if team_b else None,
    )


class CaptainPickView(discord.ui.View):
    """양 팀의 팀장을 정하는 화면이에요. 명령어를 쓴 사람에게만 보여요.

    드롭다운으로 직접 고르거나 🎲 무작위로 뽑을 수 있어요. 한쪽만 골라도 되고(안 고른 쪽은
    지금 팀장을 그대로 둬요), 아무도 안 고르고 **👑 팀장 해제**로 둘 다 비울 수도 있어요."""

    def __init__(self, parent: "TeamSplitView"):
        super().__init__(timeout=MANUAL_TIMEOUT)
        self._parent = parent
        team_a, team_b = parent.current
        self._a_select = _TeamMemberSelect("🅰️ A팀 팀장 (안 골라도 돼요)", team_a)
        self._b_select = _TeamMemberSelect("🅱️ B팀 팀장 (안 골라도 돼요)", team_b)
        self.add_item(self._a_select)
        self.add_item(self._b_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._parent.owner_id:
            return True
        await interaction.response.send_message(
            "`/팀짜기`를 실행한 사람만 팀장을 정할 수 있어요.", ephemeral=True
        )
        return False

    @discord.ui.button(label="적용", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        team_a, team_b = self._parent.current
        a_pick = _pick(team_a, self._a_select.values)
        b_pick = _pick(team_b, self._b_select.values)
        if a_pick is None and b_pick is None:
            await interaction.response.send_message(
                "팀장으로 세울 사람을 한 명 이상 골라주세요. "
                "(다 비우려면 **👑 팀장 해제**를 눌러주세요)",
                ephemeral=True,
            )
            return

        # 안 고른 쪽은 지금 팀장을 그대로 둬요(한 팀만 바꾸고 싶을 때가 있어요).
        current = self._parent.captains
        captains = (
            a_pick.key if a_pick else current[0],
            b_pick.key if b_pick else current[1],
        )
        await self._parent.apply_captains(captains)

        named = []
        if a_pick:
            named.append(f"🅰️ A팀 **{a_pick.label}**")
        if b_pick:
            named.append(f"🅱️ B팀 **{b_pick.label}**")
        await interaction.response.edit_message(
            content="👑 팀장을 정했어요 — " + " · ".join(named), view=None
        )

    @discord.ui.button(label="무작위로 뽑기", emoji="🎲", style=discord.ButtonStyle.primary, row=2)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        team_a, team_b = self._parent.current
        captains = random_captains(team_a, team_b)
        await self._parent.apply_captains(captains)

        def name_of(team, captain_id):
            found = next((p for p in team if p.key == captain_id), None)
            return f"**{found.label}**" if found else "(없음)"

        await interaction.response.edit_message(
            content=(
                f"🎲 팀장을 뽑았어요 — 🅰️ A팀 {name_of(team_a, captains[0])} · "
                f"🅱️ B팀 {name_of(team_b, captains[1])}"
            ),
            view=None,
        )

    @discord.ui.button(label="팀장 해제", emoji="👑", style=discord.ButtonStyle.secondary, row=3)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._parent.apply_captains((None, None))
        await interaction.response.edit_message(content="👑 팀장을 없앴어요.", view=None)


class _MapSelect(discord.ui.Select):
    """맵 하나를 고르는 드롭다운이에요. 지금 맵이 있으면 그걸 기본 선택으로 보여줘요."""

    def __init__(self, current: str | None = None):
        options = [
            discord.SelectOption(label=name, value=name, default=(name == current))
            for name in valorant_maps.MAPS[: valorant_maps.MAX_SELECT_OPTIONS]
        ]
        super().__init__(placeholder="어느 맵이었나요?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # 실제 처리는 이 드롭다운을 담은 View가 해요(맵을 어디에 쓸지가 서로 달라서요).
        await self.view.on_map_chosen(interaction, self.values[0])  # type: ignore[attr-defined]


class MapPickView(discord.ui.View):
    """경기 **전에** 맵을 정해두는 화면이에요. 명령어를 쓴 사람에게만 보여요.

    여기서 정해두면 🅰️/🅱️ 승리 버튼을 누를 때 그 맵으로 같이 기록돼요."""

    def __init__(self, parent: "TeamSplitView"):
        super().__init__(timeout=MANUAL_TIMEOUT)
        self._parent = parent
        self.add_item(_MapSelect(parent.map_name))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._parent.owner_id:
            return True
        await interaction.response.send_message(
            "`/팀짜기`를 실행한 사람만 맵을 정할 수 있어요.", ephemeral=True
        )
        return False

    async def on_map_chosen(self, interaction: discord.Interaction, name: str):
        await self._parent.apply_map(name)
        await interaction.response.edit_message(
            content=f"🗺️ 맵을 **{name}**으로 정했어요. 승리 버튼을 누르면 이 맵으로 기록돼요.",
            view=None,
        )

    @discord.ui.button(label="맵 지우기", emoji="🗺️", style=discord.ButtonStyle.secondary, row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._parent.apply_map(None)
        await interaction.response.edit_message(content="🗺️ 맵을 비웠어요.", view=None)


class MatchMapView(discord.ui.View):
    """승리 보고를 **한 뒤에** 맵을 채워 넣는 화면이에요.

    왜 보고 전에 막지 않았나: 맵을 꼭 골라야 기록되게 만들면, 승자만 누르고 맵을 안 고른
    경기는 **아무것도 기록되지 않아요**. 전적이 비는 게 맵이 비는 것보다 나빠서, 경기는
    먼저 기록하고 맵은 이 화면에서 나중에 채우게 했어요.

    결과 메시지에 공개로 붙여요(ephemeral이 아니라서 바로 안 눌러도 10분간 남아 있어요).
    누를 수 있는 사람은 결과를 보고한 사람뿐이에요."""

    def __init__(self, match_id: str, reporter_id: int, summary: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self._match_id = match_id
        self._reporter_id = reporter_id
        self._summary = summary
        self.message: discord.Message | None = None
        self.add_item(_MapSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._reporter_id:
            return True
        await interaction.response.send_message(
            "결과를 보고한 사람만 맵을 기록할 수 있어요.", ephemeral=True
        )
        return False

    async def on_map_chosen(self, interaction: discord.Interaction, name: str):
        saved = await scrim_record_store.set_match_map(self._match_id, name)
        if not saved:
            await interaction.response.send_message(
                "그 경기를 못 찾아서 맵을 기록하지 못했어요.", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content=f"{self._summary}\n\n🗺️ 맵: **{name}** 으로 기록했어요.", view=None
        )

    async def on_timeout(self):
        # 시간이 지나면 드롭다운을 떼서, 눌러도 반응 없는 채로 남지 않게 해요.
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class TeamSplitView(discord.ui.View):
    """'다시 섞기'와 '완전 랜덤'을 누를 수 있는 화면이에요. 명령어를 쓴 사람만 조작할 수 있어요."""

    def __init__(
        self,
        players: list[team_balance.Rated],
        candidates: list[tuple[list, list, float]],
        *,
        owner_id: int,
        guild_id: int | None,
        source_label: str,
        initial: tuple[list, list],
        mode: str,
        diff: float | None,
        bot: commands.Bot | None = None,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self._players = players
        self._candidates = candidates
        self._index = 0
        self._owner_id = owner_id
        self._guild_id = guild_id
        # 승리 보고 뒤에 HenrikDev를 부를 때 `/전적`의 aiohttp 세션을 빌리려고 들고 있어요.
        self._bot = bot
        self._fallback_session: aiohttp.ClientSession | None = None
        # 경기 기록 재시도 작업. 참조를 들고 있지 않으면 중간에 치워질 수 있어요.
        self._stats_retry: asyncio.Task | None = None
        self._source_label = source_label
        self.message: discord.Message | None = None
        # 지금 화면에 떠 있는 편성이에요. 승리 보고는 **이 편성 기준**으로 기록돼요.
        # (다시 섞기를 누를 때마다 같이 갱신돼요 - 안 그러면 처음 편성으로 기록돼버려요.
        #  '완전 랜덤'으로 시작하면 candidates[0]과 화면이 다르니 initial을 따로 받아요.)
        self._current: tuple[list, list] = initial
        # 지금 편성을 어떻게 만들었는지와 그때 잰 실력 차이예요. 팀장을 정할 때 화면을 다시
        # 그려야 해서, 제목/색을 고를 근거를 들고 있어야 해요.
        self._mode = mode
        self._diff = diff
        # 양 팀 팀장의 유저 id. 안 정했으면 None이에요.
        self._captains: tuple[int | None, int | None] = (None, None)
        # 이번 경기 맵. 승리 보고 때 같이 기록돼요(안 정해도 기록은 돼요).
        self._map: str | None = None
        # 결과를 한 번 기록했으면 더 못 바꾸게 잠가요.
        self._reported = False

    # ManualAdjustView / CaptainPickView가 들여다봐야 하는 값들이에요(상태는 이 View가 쥐고 있어요).
    @property
    def current(self) -> tuple[list[team_balance.Rated], list[team_balance.Rated]]:
        return self._current

    @property
    def owner_id(self) -> int:
        return self._owner_id

    @property
    def reported(self) -> bool:
        return self._reported

    @property
    def captains(self) -> tuple[int | None, int | None]:
        return self._captains

    @property
    def map_name(self) -> str | None:
        return self._map

    def build_embed(self) -> discord.Embed:
        team_a, team_b = self._current
        return _build_embed(
            team_a, team_b, self._diff,
            mode=self._mode, source_label=self._source_label, captains=self._captains,
            map_name=self._map,
        )

    def save_state(self, *, winner: int | None = None) -> None:
        """지금 편성을 그 서버의 '마지막 편성'으로 저장해요(`/팀보기`가 이걸 읽어요).

        DM에서 쓰면 guild_id가 없어서 저장할 곳이 없어요 - 그때는 그냥 넘어가요.
        저장이 실패해도 팀 나누기 자체는 굴러가야 하니 조용히 로그만 남겨요."""
        if self._guild_id is None:
            return
        team_a, team_b = self._current
        try:
            team_store.save_split(
                self._guild_id,
                team_a=team_a, team_b=team_b,
                mode=self._mode, diff=self._diff,
                source_label=self._source_label,
                captains=self._captains,
                map_name=self._map,
                message_url=self.message.jump_url if self.message else None,
                winner=winner,
            )
        except Exception:
            log.warning("마지막 팀 편성 저장 실패 (guild=%s)", self._guild_id, exc_info=True)

    async def apply_manual(
        self, new_a: list[team_balance.Rated], new_b: list[team_balance.Rated]
    ) -> float:
        """손으로 바꾼 편성을 화면에 반영해요. 돌려주는 값은 다시 잰 실력 차이예요.

        `_current`도 같이 갱신해서, 승리 보고가 **바꾼 뒤 명단**으로 기록되게 해요."""
        diff = team_balance.imbalance(new_a, new_b)
        self._current = (new_a, new_b)
        self._mode = team_store.MODE_MANUAL
        self._diff = diff
        # 팀장이 반대편으로 넘어갔으면 그 자리는 비워요.
        self._captains = keep_valid_captains(new_a, new_b, self._captains)
        if self.message is not None:
            await self.message.edit(embed=self.build_embed(), view=self)
        self.save_state()
        return diff

    async def apply_captains(self, captains: tuple[int | None, int | None]) -> None:
        """팀장을 화면에 반영해요. 편성은 그대로 두고 명단 표시만 바뀌어요."""
        team_a, team_b = self._current
        self._captains = keep_valid_captains(team_a, team_b, captains)
        if self.message is not None:
            await self.message.edit(embed=self.build_embed(), view=self)
        self.save_state()

    async def apply_map(self, map_name: str | None) -> None:
        """이번 경기 맵을 정해요. 제목에 뜨고, 승리 보고 때 같이 기록돼요."""
        self._map = map_name
        if self.message is not None:
            await self.message.edit(embed=self.build_embed(), view=self)
        self.save_state()

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
        self._mode = team_store.MODE_BALANCED
        self._diff = diff
        # 편성이 통째로 바뀌니 팀장은 지워요(엉뚱한 팀의 팀장으로 남으면 안 돼요).
        self._captains = (None, None)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        self.save_state()

    @discord.ui.button(label="완전 랜덤", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def pure_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        team_a, team_b, diff = team_balance.random_split(self._players)
        self._current = (team_a, team_b)
        self._mode = team_store.MODE_RANDOM
        self._diff = diff
        self._captains = (None, None)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        self.save_state()

    @discord.ui.button(label="직접 조정", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def manual_adjust(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._reported:
            await interaction.response.send_message(
                "이 경기는 이미 결과가 기록돼서 편성을 바꿀 수 없어요. "
                "다음 경기는 `/팀짜기`를 새로 써주세요.",
                ephemeral=True,
            )
            return
        team_a, team_b = self._current
        if max(len(team_a), len(team_b)) > SELECT_LIMIT:
            await interaction.response.send_message(
                f"한 팀이 {SELECT_LIMIT}명을 넘어서 드롭다운에 담을 수 없어요. "
                "`/팀짜기 인원:`으로 명단을 직접 지정해 주세요.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "바꿀 사람을 고르고 **✅ 적용**을 눌러주세요.\n"
            "-# 양쪽에서 한 명씩 고르면 맞교환하고, 한쪽만 고르면 그 사람만 반대편으로 옮겨요.",
            view=ManualAdjustView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="팀장", emoji="👑", style=discord.ButtonStyle.secondary)
    async def pick_captains(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 결과를 보고하면 이 화면의 버튼이 전부 꺼져서 팀장도 더 못 바꿔요(_report 참고).
        team_a, team_b = self._current
        if max(len(team_a), len(team_b)) > SELECT_LIMIT:
            await interaction.response.send_message(
                f"한 팀이 {SELECT_LIMIT}명을 넘어서 드롭다운에 담을 수 없어요. "
                "🎲 무작위로 뽑는 건 인원과 상관없이 돼요.",
                ephemeral=True,
                view=CaptainPickView(self),
            )
            return
        await interaction.response.send_message(
            "팀장을 고르고 **✅ 적용**을 눌러주세요. 🎲를 누르면 무작위로 뽑아요.\n"
            "-# 한쪽만 골라도 돼요(안 고른 팀은 지금 팀장을 그대로 둬요).",
            view=CaptainPickView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="맵", emoji="🗺️", style=discord.ButtonStyle.secondary)
    async def pick_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 맵은 편성과 무관해서 🔄/🎲로 팀을 다시 짜도 그대로 남아요.
        await interaction.response.send_message(
            "이번 경기 맵을 골라주세요. 승리 버튼을 누르면 이 맵으로 기록돼요.\n"
            "-# 지금 안 골라도 돼요 — 결과를 보고한 뒤에도 맵을 고를 수 있어요.",
            view=MapPickView(self),
            ephemeral=True,
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
            map_name=self._map,
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

        # `/팀보기`가 "이 경기는 A팀이 이겼다"까지 보여줄 수 있게 승자도 같이 남겨요.
        self.save_state(winner=winner_index)

        won_name = "🅰️ A팀" if winner_index == 0 else "🅱️ B팀"
        map_text = f" · 🗺️ **{self._map}**" if self._map else ""
        lines = [
            f"🏆 **{won_name} 승리**로 기록했어요!{map_text} "
            f"(기록: {interaction.user.display_name})",
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
        lines.append("-# `/내전전적`으로 내 승패·연승·맵별 성적·KDA를 볼 수 있어요.")
        summary = "\n".join(lines)

        # 맵을 안 정해뒀으면 여기서 고를 수 있게 드롭다운을 붙여요. 기록은 이미 들어갔으니
        # 안 고르고 넘어가도 전적은 남아요(맵별 집계에서만 빠져요).
        if self._map or not match_id:
            await interaction.followup.send(summary)
        else:
            map_view = MatchMapView(match_id, interaction.user.id, summary)
            map_view.message = await interaction.followup.send(
                summary + "\n\n🗺️ **어느 맵이었나요?** 골라두면 맵별 승률이 쌓여요 "
                "(안 골라도 전적은 기록됐어요)",
                view=map_view,
                wait=True,
            )

        # 실제 경기 기록(KDA)을 찾아 붙여요. **여기서 실패해도 위 보고는 이미 끝났어요.**
        if match_id:
            await self._attach_real_stats(interaction, match_id, winners + losers, winner_index)

    async def _attach_real_stats(
        self,
        interaction: discord.Interaction,
        match_id: str,
        roster: list[int],
        winner_index: int,
    ) -> None:
        """HenrikDev에서 그 내전의 실제 경기 기록을 찾아 저장하고 화면에 띄워요.

        조회가 실패하거나 경기를 못 찾는 건 **흔한 일**이에요(계정 미등록, 아직 전적 서버에
        안 올라옴, API 한도). 그래서 조용히 넘어가고, 승패 기록은 그대로 둬요.

        ⚠️ 경기가 끝난 **직후**엔 라이엇 전적에 아직 안 올라와 있을 수 있어요. 그래서 못 찾으면
        한 번만 더(STATS_RETRY_SECONDS 뒤에) 시도해요. 이건 기다리지 않고 뒤로 떼어내요 -
        안 그러면 승리 보고 응답이 몇 분 멈춰요."""
        if await self._try_attach_stats(interaction, match_id, roster, winner_index):
            return
        # 참조를 들고 있어야 가비지 컬렉터가 중간에 치우지 않아요.
        self._stats_retry = asyncio.create_task(
            self._retry_attach_stats(interaction, match_id, roster, winner_index)
        )

    async def _try_attach_stats(
        self, interaction: discord.Interaction, match_id: str,
        roster: list[int], winner_index: int,
    ) -> bool:
        try:
            stats = await scrim_stats_fetch.fetch_for_match(
                self._bot_session(),
                set(roster),
                reported_at=discord.utils.utcnow().timestamp(),
                prefer=interaction.user.id,
            )
        except Exception:
            log.warning("내전 KDA 조회에서 예외 (match=%s)", match_id, exc_info=True)
            return False
        if stats is None:
            return False

        await scrim_record_store.attach_stats(match_id, stats)
        try:
            await interaction.followup.send(embed=build_stats_embed(stats, winner_index))
        except discord.HTTPException:
            log.warning("내전 KDA 화면을 못 보냈어요 (match=%s)", match_id, exc_info=True)
        return True

    async def _retry_attach_stats(
        self, interaction: discord.Interaction, match_id: str,
        roster: list[int], winner_index: int,
    ) -> None:
        """잠시 뒤 한 번만 더 찾아봐요. 그래도 없으면 조용히 포기해요.

        ⚠️ followup은 상호작용 토큰이 살아있는 15분 안에만 보낼 수 있어요. 재시도 간격을
        그보다 훨씬 짧게 둔 이유예요."""
        await asyncio.sleep(STATS_RETRY_SECONDS)
        try:
            if not await self._try_attach_stats(interaction, match_id, roster, winner_index):
                log.info("내전 KDA를 재시도에서도 못 찾았어요 (match=%s)", match_id)
        except Exception:
            # 떼어낸 작업이라 여기서 터지면 'Task exception was never retrieved'만 남아요.
            log.warning("내전 KDA 재시도에서 예외 (match=%s)", match_id, exc_info=True)

    def _bot_session(self) -> "aiohttp.ClientSession":
        """HenrikDev를 부를 aiohttp 세션이에요.

        `/전적`(cogs/rank.py)이 쓰는 세션을 재사용해요 - 매번 세션을 새로 만들면 커넥션이
        쌓이고 'Unclosed client session' 경고가 나요. 없으면 그때 하나 만들어 들고 있어요."""
        rank_cog = self._bot.get_cog("Rank") if self._bot else None
        session = getattr(rank_cog, "session", None)
        if session is not None and not session.closed:
            return session
        if self._fallback_session is None or self._fallback_session.closed:
            self._fallback_session = aiohttp.ClientSession()
        return self._fallback_session


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
            mode = team_store.MODE_RANDOM
            candidates = team_balance.balanced_splits(players, limit=CANDIDATE_COUNT)
        else:
            candidates = team_balance.balanced_splits(players, limit=CANDIDATE_COUNT)
            team_a, team_b, diff = candidates[0]
            mode = team_store.MODE_BALANCED

        view = TeamSplitView(
            players, candidates,
            owner_id=interaction.user.id,
            guild_id=interaction.guild_id,
            source_label=source_label,
            initial=(team_a, team_b),
            mode=mode,
            diff=diff,
            bot=self.bot,
        )
        message = await interaction.followup.send(
            embed=view.build_embed(), view=view, wait=True
        )
        view.message = message
        # 메시지를 받은 뒤에 저장해요 - `/팀보기`에 "원래 메시지로 가기" 링크를 넣으려면
        # jump_url이 필요하고, 그건 메시지가 올라간 뒤에만 알 수 있어요.
        view.save_state()

    @app_commands.command(
        name="팀보기",
        description="이 서버에서 마지막으로 짠 팀 편성을 다시 봐요.",
    )
    async def team_last(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "`/팀보기`는 서버 안에서만 쓸 수 있어요.", ephemeral=True
            )
            return

        record = team_store.get_split(interaction.guild_id)
        if record is None:
            await interaction.response.send_message(
                "아직 짠 팀이 없어요. `/팀짜기`로 먼저 팀을 나눠주세요.", ephemeral=True
            )
            return

        team_a, team_b = team_store.load_teams(record)
        if not team_a and not team_b:
            await interaction.response.send_message(
                "저장된 편성이 비어 있어요. `/팀짜기`로 다시 나눠주세요.", ephemeral=True
            )
            return

        embed = _build_embed(
            team_a, team_b, record.get("diff"),
            mode=record.get("mode") or team_store.MODE_BALANCED,
            source_label=record.get("source_label") or "",
            captains=team_store.load_captains(record),
            map_name=record.get("map"),
        )

        # 언제 짠 편성인지가 제일 중요해요 - 어제 것을 오늘 것으로 착각하면 안 되니까요.
        notes = [f"🕒 {_when_text(record.get('saved_at'))}에 짠 편성이에요."]
        winner = record.get("winner")
        if winner in (0, 1):
            notes.append(
                f"🏆 결과는 **{'🅰️ A팀' if winner == 0 else '🅱️ B팀'} 승리**로 기록됐어요."
            )
        if record.get("message_url"):
            notes.append(f"-# [원래 메시지로 가기]({record['message_url']})")
        embed.description = "\n".join(notes)

        # 팀 확인은 여러 사람이 같이 봐야 하니 공개로 보내요. 버튼은 안 붙여요 -
        # 편성을 바꾸는 건 `/팀짜기` 쪽 화면의 몫이에요.
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Team(bot))
