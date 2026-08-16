"""
발로란트 티어 이름 <-> 디스코드 역할 이름 변환, 그리고 역할 생성/부여/교체를 담당하는 공용 모듈이에요.
cogs/tier.py(확인 명령어)와 cogs/rank.py(/전적 실행 시 자동 동기화)가 같이 사용해요.
"""
from typing import Optional

import discord

# 레디언트를 제외한 모든 랭크는 1~3단계로 나뉘어요. (레디언트만 단일 등급)
TIER_BASES = ["아이언", "브론즈", "실버", "골드", "플래티넘", "다이아몬드", "초월자", "불멸"]
TOP_TIER = "레디언트"  # 단계 구분이 없는 최상위 티어

TIER_COLOR_MAP = {
    "아이언": discord.Color.dark_gray(),
    "브론즈": discord.Color.from_rgb(205, 127, 50),
    "실버": discord.Color.light_gray(),
    "골드": discord.Color.gold(),
    "플래티넘": discord.Color.teal(),
    "다이아몬드": discord.Color.blue(),
    "초월자": discord.Color.purple(),
    "불멸": discord.Color.dark_red(),
    "레디언트": discord.Color.from_rgb(255, 255, 153),
}

# 서버 부스트 레벨 2 미만이면 역할에 커스텀 이미지 아이콘을 못 붙여서(디스코드 자체 제한),
# 대신 역할 이름 앞에 이모지를 붙여서 시각적으로 구분해요. (레벨 2 되면 실제 아이콘도 같이 붙어요)
TIER_EMOJI = {
    "아이언": "⚙️",
    "브론즈": "🥉",
    "실버": "⬜",
    "골드": "🥇",
    "플래티넘": "🔷",
    "다이아몬드": "💠",
    "초월자": "🔮",
    "불멸": "❤️‍🔥",
    "레디언트": "✨",
}

# HenrikDev가 돌려주는 영문 티어명(예: "Diamond 2")의 앞 단어를 한글로 매핑해요.
ENGLISH_TO_KOREAN_TIER = {
    "Iron": "아이언", "Bronze": "브론즈", "Silver": "실버", "Gold": "골드",
    "Platinum": "플래티넘", "Diamond": "다이아몬드", "Ascendant": "초월자",
    "Immortal": "불멸", "Radiant": "레디언트",
}


def parse_korean_tier(tier_name: str) -> Optional[str]:
    """'Diamond 2' -> '다이아몬드 2', 'Radiant' -> '레디언트' 처럼 단계까지 포함해서 뽑아내요. (이모지 없는 순수 이름)"""
    if not tier_name:
        return None

    parts = tier_name.split()
    base_kr = ENGLISH_TO_KOREAN_TIER.get(parts[0])
    if base_kr is None:
        return None

    if base_kr == TOP_TIER:
        return TOP_TIER  # 레디언트는 단계가 없어요

    if len(parts) > 1 and parts[1].isdigit():
        return f"{base_kr} {parts[1]}"

    # 방어 코드: API가 단계 없이 이름만 줄 경우엔 일단 1단계로 취급해요.
    return f"{base_kr} 1"


def display_name_for(tier_name: str) -> str:
    """'골드 2' -> '🥇 골드 2' 처럼, 실제 디스코드에 보일 이모지 포함 역할 이름을 만들어요."""
    if not tier_name:
        return tier_name
    base = tier_name.split()[0]
    emoji = TIER_EMOJI.get(base, "")
    return f"{emoji} {tier_name}".strip()


def _build_tier_role_names() -> list[str]:
    """'실버 1', '실버 2', '실버 3', ..., '레디언트' 형태의 전체(순수) 역할명 목록을 만들어요."""
    names = []
    for base in TIER_BASES:
        names.extend(f"{base} {division}" for division in (1, 2, 3))
    names.append(TOP_TIER)
    return names


# 8개 티어 * 3단계 + 레디언트 = 25개 (디스코드 선택지 한도인 25개와도 딱 맞아요)
TIER_OPTIONS = _build_tier_role_names()
# 실제 디스코드에 만들어질 이모지 포함 이름 목록/집합이에요. 역할 판별은 이걸로 해요.
TIER_ROLE_DISPLAY_NAMES = [display_name_for(t) for t in TIER_OPTIONS]
TIER_ROLE_NAME_SET = set(TIER_ROLE_DISPLAY_NAMES)


async def get_or_create_tier_role(
    guild: discord.Guild, tier_name: str, icon_bytes: Optional[bytes] = None
) -> discord.Role:
    display_name = display_name_for(tier_name)
    role = discord.utils.get(guild.roles, name=display_name)
    if role is not None:
        return role

    base_name = tier_name.split()[0]
    color = TIER_COLOR_MAP.get(base_name, discord.Color.default())

    kwargs = {"name": display_name, "color": color, "reason": "티어 역할 자동 생성"}
    if icon_bytes:
        kwargs["display_icon"] = icon_bytes

    try:
        role = await guild.create_role(**kwargs)
    except discord.HTTPException as error:
        # 서버 부스트 레벨 부족 등으로 아이콘 적용이 실패하면, 아이콘 없이라도 역할은 만들어요.
        if "display_icon" in kwargs:
            print(f"⚠️ '{display_name}' 역할에 이미지 아이콘을 못 붙였어요 ({error}). 아이콘 없이 만들게요.")
            kwargs.pop("display_icon")
            role = await guild.create_role(**kwargs)
        else:
            raise

    print(f"🆕 '{display_name}' 역할을 새로 만들었어요. (서버: {guild.name})")
    return role


def get_member_current_tier_roles(member: discord.Member) -> list[discord.Role]:
    """이 멤버가 지금 갖고 있는 티어 역할들을 반환해요. (정상이라면 0개 또는 1개)"""
    return [role for role in member.roles if role.name in TIER_ROLE_NAME_SET]


async def sync_tier_role(member: discord.Member, tier_name: str, icon_bytes: Optional[bytes] = None) -> dict:
    """
    멤버의 티어 역할을 실제 전적 기준(tier_name, 이모지 없는 순수 이름)에 맞게 동기화해요.
    - 티어 역할이 없으면: 새로 부여 (이때 icon_bytes를 주면 역할 이미지 아이콘으로 적용돼요. 서버 부스트 레벨 2 필요)
    - 있는데 다르면: 이전 역할 제거하고 새 역할 부여
    - 이미 같으면: 아무것도 안 함

    반환값: {"role": Role, "status": "new" | "updated" | "unchanged", "previous": str | None}
    discord.Forbidden은 호출하는 쪽에서 처리해요 (권한 부족 시 그대로 올라감).
    """
    display_name = display_name_for(tier_name)
    current_roles = get_member_current_tier_roles(member)
    previous_names = [r.name for r in current_roles]

    if display_name in previous_names:
        matching = next(r for r in current_roles if r.name == display_name)
        return {"role": matching, "status": "unchanged", "previous": display_name}

    new_role = await get_or_create_tier_role(member.guild, tier_name, icon_bytes=icon_bytes)

    if current_roles:
        await member.remove_roles(*current_roles, reason="티어 변경으로 인한 이전 역할 제거")
    if new_role not in member.roles:
        await member.add_roles(new_role, reason=f"티어 자동 동기화: {display_name}")

    status = "updated" if previous_names else "new"
    return {"role": new_role, "status": status, "previous": previous_names[0] if previous_names else None}