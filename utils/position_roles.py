"""
발로란트 요원 포지션(타격대/척후대/전략가/감시자) 역할 생성/부여/교체를 담당하는 공용 모듈이에요.
tier_roles.py와 구조를 똑같이 맞췄어요. cogs/rank.py의 /전적 실행 시 자동 동기화에 사용돼요.
"""
from typing import Optional

import discord

POSITION_BASES = ["타격대", "척후대", "전략가", "감시자"]

POSITION_COLOR_MAP = {
    "타격대": discord.Color.red(),
    "척후대": discord.Color.gold(),
    "전략가": discord.Color.teal(),
    "감시자": discord.Color.green(),
}

# 서버 부스트 레벨 2 미만이면 역할에 커스텀 이미지 아이콘을 못 붙여서(디스코드 자체 제한),
# 대신 역할 이름 앞에 이모지를 붙여서 시각적으로 구분해요.
POSITION_EMOJI = {
    "타격대": "⚔️",
    "척후대": "🏹",
    "전략가": "🌀",
    "감시자": "🛡️",
}


def display_name_for(position_name: str) -> str:
    """'타격대' -> '⚔️ 타격대' 처럼, 실제 디스코드에 보일 이모지 포함 역할 이름을 만들어요."""
    if not position_name:
        return position_name
    emoji = POSITION_EMOJI.get(position_name, "")
    return f"{emoji} {position_name}".strip()


POSITION_OPTIONS = [display_name_for(p) for p in POSITION_BASES]
POSITION_OPTION_SET = set(POSITION_OPTIONS)


async def get_or_create_position_role(guild: discord.Guild, position_name: str) -> discord.Role:
    display_name = display_name_for(position_name)
    role = discord.utils.get(guild.roles, name=display_name)
    if role is None:
        color = POSITION_COLOR_MAP.get(position_name, discord.Color.default())
        role = await guild.create_role(name=display_name, color=color, reason="포지션 역할 자동 생성")
        print(f"🆕 '{display_name}' 역할을 새로 만들었어요. (서버: {guild.name})")
    return role


def get_member_current_position_roles(member: discord.Member) -> list[discord.Role]:
    """이 멤버가 지금 갖고 있는 포지션 역할들을 반환해요. (정상이라면 0개 또는 1개)"""
    return [role for role in member.roles if role.name in POSITION_OPTION_SET]


async def sync_position_role(member: discord.Member, position_name: str) -> dict:
    """
    멤버의 포지션 역할을 최근 전적 기준 주 포지션(position_name, 이모지 없는 순수 이름)에 맞게 동기화해요.
    반환값: {"role": Role, "status": "new" | "updated" | "unchanged", "previous": str | None}
    discord.Forbidden은 호출하는 쪽에서 처리해요.
    """
    display_name = display_name_for(position_name)
    current_roles = get_member_current_position_roles(member)
    previous_names = [r.name for r in current_roles]

    if display_name in previous_names:
        matching = next(r for r in current_roles if r.name == display_name)
        return {"role": matching, "status": "unchanged", "previous": display_name}

    new_role = await get_or_create_position_role(member.guild, position_name)

    if current_roles:
        await member.remove_roles(*current_roles, reason="주 포지션 변경으로 인한 이전 역할 제거")
    if new_role not in member.roles:
        await member.add_roles(new_role, reason=f"주 포지션 자동 동기화: {display_name}")

    status = "updated" if previous_names else "new"
    return {"role": new_role, "status": status, "previous": previous_names[0] if previous_names else None}