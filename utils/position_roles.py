"""
발로란트 요원 포지션(타격대/척후대/전략가/감시자) 역할 생성/부여/교체를 담당하는 공용 모듈이에요.
tier_roles.py와 구조를 똑같이 맞췄어요. cogs/rank.py의 /전적 실행 시 자동 동기화에 사용돼요.
"""
import logging
from typing import Optional

import discord

log = logging.getLogger(__name__)

POSITION_BASES = ["타격대", "척후대", "전략가", "감시자"]

POSITION_COLOR_MAP = {
    "타격대": discord.Color.red(),
    "척후대": discord.Color.gold(),
    "전략가": discord.Color.teal(),
    "감시자": discord.Color.green(),
}

# 🕰️ **옛 이름**에 쓰던 이모지예요. 커스텀 이미지 아이콘을 못 붙이던 시절(부스트 레벨 1)의
# 대체재였어요. 2026-11-03에 진짜 포지션 아이콘(발로란트 공식 모양)을 역할에 붙이면서
# 이름에서는 뺐어요 — 안 그러면 아이콘이 둘로 보여요. 티어 역할과 같은 처리예요.
# 🚨 지우지 말 것. 아직 옛 이름으로 남아 있는 역할을 **알아보는 데** 써요.
POSITION_EMOJI = {
    "타격대": "⚔️",
    "척후대": "🏹",
    "전략가": "🌀",
    "감시자": "🛡️",
}


def display_name_for(position_name: str) -> str:
    """실제 디스코드에 보일 역할 이름이에요. 지금은 포지션 이름 그대로예요 ('타격대')."""
    return position_name


def text_label_for(position_name: str) -> str:
    """글자만 나오는 곳에서 쓸 이름이에요. '타격대' -> '⚔️ 타격대'.

    🚨 역할 아이콘은 글자 출력에 안 따라와요. 임베드·명단처럼 텍스트로 찍히는 자리에선
    이모지가 유일한 시각 단서라 거기서는 그대로 써요."""
    if not position_name:
        return position_name
    emoji = POSITION_EMOJI.get(position_name, "")
    return f"{emoji} {position_name}".strip()


def legacy_display_name_for(position_name: str) -> str:
    """🕰️ 2026-11-03 이전의 **역할** 이름이에요. 개명 안 된 역할을 찾을 때만 써요."""
    return text_label_for(position_name)


POSITION_OPTIONS = [display_name_for(p) for p in POSITION_BASES]
POSITION_LEGACY_NAMES = [legacy_display_name_for(p) for p in POSITION_BASES]
# 🚨 판별 집합엔 **옛 이름도 같이** 넣어요. 개명 전 역할을 "포지션 역할이 아니다"라고 보면
#    정리도 못 하고 같은 역할을 하나 더 만들어요.
POSITION_OPTION_SET = set(POSITION_OPTIONS) | set(POSITION_LEGACY_NAMES)


async def get_or_create_position_role(
    guild: discord.Guild, position_name: str, icon_bytes: Optional[bytes] = None
) -> discord.Role:
    display_name = display_name_for(position_name)
    role = discord.utils.get(guild.roles, name=display_name)

    if role is None:
        # 🕰️ 옛 이름('⚔️ 타격대')으로 남아 있으면 **새로 만들지 말고 개명**해요.
        legacy = discord.utils.get(guild.roles, name=legacy_display_name_for(position_name))
        if legacy is not None:
            try:
                await legacy.edit(name=display_name, reason="포지션 역할 이름에서 이모지 제거")
                log.info(f"✏️ '{legacy.name}' 역할을 '{display_name}'로 바꿨어요.")
            except discord.HTTPException as error:
                log.warning(f"⚠️ '{legacy.name}' 개명에 실패했어요 ({error}). 옛 이름 그대로 써요.")
            role = legacy

    if role is not None:
        # 아이콘이 비어 있을 때만 채워요(역할 하나당 사실상 한 번).
        if icon_bytes and role.icon is None:
            try:
                await role.edit(display_icon=icon_bytes, reason="포지션 역할 아이콘 보충")
                log.info(f"🏷️ '{display_name}' 역할에 포지션 아이콘을 붙였어요.")
            except discord.HTTPException as error:
                log.warning(f"⚠️ '{display_name}' 역할에 아이콘을 못 붙였어요 ({error}).")
        return role

    color = POSITION_COLOR_MAP.get(position_name, discord.Color.default())
    kwargs = {"name": display_name, "color": color, "reason": "포지션 역할 자동 생성"}
    if icon_bytes:
        kwargs["display_icon"] = icon_bytes
    try:
        role = await guild.create_role(**kwargs)
    except discord.HTTPException as error:
        if "display_icon" in kwargs:
            log.warning(f"⚠️ '{display_name}' 역할에 아이콘을 못 붙였어요 ({error}). 아이콘 없이 만들게요.")
            kwargs.pop("display_icon")
            role = await guild.create_role(**kwargs)
        else:
            raise
    log.info(f"🆕 '{display_name}' 역할을 새로 만들었어요. (서버: {guild.name})")
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

    # 🚨 위 호출이 **멤버가 이미 달고 있던 역할의 이름만 바꿔서** 돌려줄 수 있어요
    #    ('⚔️ 타격대' -> '타격대'). 그걸 옛 역할로 보고 떼면 방금 맞춘 걸 뗐다 다시 달아요.
    stale = [r for r in current_roles if r != new_role]
    if stale:
        await member.remove_roles(*stale, reason="주 포지션 변경으로 인한 이전 역할 제거")
    if new_role not in member.roles:
        await member.add_roles(new_role, reason=f"주 포지션 자동 동기화: {display_name}")

    if not previous_names:
        status = "new"
    elif stale:
        status = "updated"
    else:
        status = "unchanged"      # 이름만 바뀐 경우예요
    return {"role": new_role, "status": status, "previous": previous_names[0] if previous_names else None}