"""
발로란트 티어 이름 <-> 디스코드 역할 이름 변환, 그리고 역할 생성/부여/교체를 담당하는 공용 모듈이에요.
cogs/tier.py(확인 명령어)와 cogs/rank.py(/전적 실행 시 자동 동기화)가 같이 사용해요.
"""
import logging
from typing import Optional

import discord

log = logging.getLogger(__name__)

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

# 🕰️ **옛 이름**에 쓰던 이모지예요. 커스텀 이미지 아이콘을 못 붙이던 시절(부스트 레벨 1)의
# 대체재였어요. 2026-11-03에 `ROLE_ICONS`가 해금돼서 진짜 배지가 붙었고, 이모지까지 같이 두니
# 아이콘이 둘로 보여서 **이름에서는 뺐어요**(`💠 다이아몬드 2` -> `다이아몬드 2`).
#
# 🚨 지우지 말 것. 디스코드에 아직 옛 이름으로 남아 있는 역할을 **알아보는 데** 써요.
#    이게 없으면 봇이 같은 티어 역할을 이름만 다르게 하나 더 만들어요.
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
    """실제 디스코드에 보일 역할 이름이에요. 지금은 티어 이름 그대로예요 ('골드 2').

    역할에 진짜 배지 이미지가 붙은 뒤로 이모지 접두사를 뺐어요. 이 함수를 거치는 이유는
    `cogs/team.py` 같은 호출부가 "표시용 이름"을 여기서만 받아가게 하려는 거예요."""
    return tier_name


def text_label_for(tier_name: str) -> str:
    """글자만 나오는 곳(임베드·명단)에서 쓸 이름이에요. '골드 2' -> '🥇 골드 2'.

    🚨 **역할 아이콘은 글자 출력엔 안 따라와요.** `/팀짜기` 명단처럼 역할이 아니라 텍스트로
    찍히는 자리에선 이모지가 유일한 색 단서라, 거기서는 이모지를 그대로 써요."""
    if not tier_name:
        return tier_name
    base = tier_name.split()[0]
    emoji = TIER_EMOJI.get(base, "")
    return f"{emoji} {tier_name}".strip()


def legacy_display_name_for(tier_name: str) -> str:
    """🕰️ 2026-11-03 이전의 **역할** 이름이에요. 지금의 텍스트 라벨과 형식이 같아요.

    쓰임이 달라서 이름을 따로 뒀어요 — 이쪽은 "디스코드에 아직 안 바뀐 채 남아 있는 역할을
    찾는" 용도예요. 나중에 텍스트 라벨 형식을 바꾸더라도 이 함수는 옛 역할 이름 그대로여야 해요."""
    return text_label_for(tier_name)


def _build_tier_role_names() -> list[str]:
    """'실버 1', '실버 2', '실버 3', ..., '레디언트' 형태의 전체(순수) 역할명 목록을 만들어요."""
    names = []
    for base in TIER_BASES:
        names.extend(f"{base} {division}" for division in (1, 2, 3))
    names.append(TOP_TIER)
    return names


# 8개 티어 * 3단계 + 레디언트 = 25개 (디스코드 선택지 한도인 25개와도 딱 맞아요)
TIER_OPTIONS = _build_tier_role_names()
# 실제 디스코드에 만들어질 이름 목록이에요.
TIER_ROLE_DISPLAY_NAMES = [display_name_for(t) for t in TIER_OPTIONS]
# 🚨 역할 판별용 집합엔 **옛 이름(이모지 붙은 것)도 같이** 넣어요. 개명이 아직 안 된 역할을
#    "티어 역할이 아니다"라고 보면, 중복 정리도 못 하고 역할만 하나 더 만들게 돼요.
TIER_ROLE_LEGACY_NAMES = [legacy_display_name_for(t) for t in TIER_OPTIONS]
TIER_ROLE_NAME_SET = set(TIER_ROLE_DISPLAY_NAMES) | set(TIER_ROLE_LEGACY_NAMES)


# 티어 하나를 숫자 한 개로 바꿔주는 자리예요. `/팀짜기` 밸런싱이 "실력 점수"의 축으로 써요.
# 순서는 TIER_OPTIONS 그대로라, 아이언1=1 … 실버3=9 … 레디언트=25가 돼요.
# 실버3=9인 건 우연이 아니라 cogs/rank.py의 티어 배수 기준점(실버3·0RR=1.00배)과 같은 축이에요.
TIER_INDEX_BY_NAME = {name: index for index, name in enumerate(TIER_OPTIONS, start=1)}
# 옛 이름(이모지 붙은 것)도 같이 풀어줘요 — 개명 전 역할을 달고 있어도 밸런싱이 멀쩡하도록.
TIER_INDEX_BY_LEGACY_NAME = {
    legacy_display_name_for(name): index for name, index in TIER_INDEX_BY_NAME.items()
}
# 기준점(실버 3). 티어를 알 수 없는 사람을 어디에 놓을지 정할 때 씁니다.
BASELINE_TIER_INDEX = TIER_INDEX_BY_NAME["실버 3"]
MAX_TIER_INDEX = TIER_INDEX_BY_NAME[TOP_TIER]


def tier_index_of(tier_name: str) -> Optional[int]:
    """'실버 3' -> 9, '✨ 레디언트'(역할 이름) -> 25. 못 알아보면 None."""
    if not tier_name:
        return None
    return TIER_INDEX_BY_NAME.get(tier_name) or TIER_INDEX_BY_LEGACY_NAME.get(tier_name)


def tier_name_from_index(index: int) -> str:
    """9 -> '실버 3'. 범위를 벗어나면 가장 가까운 티어로 잘라줘요."""
    clamped = max(1, min(MAX_TIER_INDEX, int(round(index))))
    return TIER_OPTIONS[clamped - 1]


def member_tier_index(member: discord.Member) -> Optional[int]:
    """멤버가 지금 달고 있는 티어 역할에서 숫자를 뽑아요. 역할이 없으면 None.

    역할은 `/전적`을 본인 계정으로 돌릴 때 자동 동기화돼요(sync_tier_role).
    여러 개가 달려 있으면(비정상) 가장 높은 걸 써요."""
    indexes = [
        index
        for index in (tier_index_of(role.name) for role in member.roles)
        if index is not None
    ]
    return max(indexes) if indexes else None


async def get_or_create_tier_role(
    guild: discord.Guild, tier_name: str, icon_bytes: Optional[bytes] = None
) -> discord.Role:
    display_name = display_name_for(tier_name)
    role = discord.utils.get(guild.roles, name=display_name)

    if role is None:
        # 🕰️ 아직 옛 이름(`💠 다이아몬드 2`)으로 남아 있는 역할이면 **새로 만들지 말고 개명**해요.
        # 그냥 만들어버리면 같은 티어 역할이 둘이 되고, 멤버는 옛 쪽에 달려 있어서 조용히 어긋나요.
        legacy = discord.utils.get(guild.roles, name=legacy_display_name_for(tier_name))
        if legacy is not None:
            try:
                await legacy.edit(name=display_name, reason="티어 역할 이름에서 이모지 제거")
                log.info(f"✏️ '{legacy.name}' 역할을 '{display_name}'로 바꿨어요.")
            except discord.HTTPException as error:
                log.warning(f"⚠️ '{legacy.name}' 개명에 실패했어요 ({error}). 옛 이름 그대로 써요.")
            role = legacy

    if role is not None:
        # 🚨 예전엔 여기서 그냥 돌아갔어요. 그래서 **아이콘은 역할을 만드는 순간에만** 붙었어요.
        # 25개 티어 역할은 부스트 레벨 1이던 시절에 이미 다 만들어져 있어서, 2026-11-03에
        # `ROLE_ICONS`가 해금된 뒤에도 `/전적`을 아무리 돌려도 아이콘이 안 붙었어요.
        # 비어 있을 때만 채우니까 역할 하나당 사실상 딱 한 번만 PATCH가 나가요.
        if icon_bytes and role.icon is None:
            try:
                await role.edit(display_icon=icon_bytes, reason="티어 역할 아이콘 보충")
                log.info(f"🏷️ '{display_name}' 역할에 티어 배지 아이콘을 뒤늦게 붙였어요.")
            except discord.HTTPException as error:
                # 서버가 ROLE_ICONS를 못 쓰는 상태면(부스트 하락 등) 조용히 넘어가요.
                log.warning(f"⚠️ '{display_name}' 역할에 아이콘을 못 붙였어요 ({error}).")
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
            log.warning(f"⚠️ '{display_name}' 역할에 이미지 아이콘을 못 붙였어요 ({error}). 아이콘 없이 만들게요.")
            kwargs.pop("display_icon")
            role = await guild.create_role(**kwargs)
        else:
            raise

    log.info(f"🆕 '{display_name}' 역할을 새로 만들었어요. (서버: {guild.name})")
    return role


def get_member_current_tier_roles(member: discord.Member) -> list[discord.Role]:
    """이 멤버가 지금 갖고 있는 티어 역할들을 반환해요. (정상이라면 0개 또는 1개)"""
    return [role for role in member.roles if role.name in TIER_ROLE_NAME_SET]


async def sync_tier_role(member: discord.Member, tier_name: str, icon_bytes: Optional[bytes] = None) -> dict:
    """
    멤버의 티어 역할을 실제 전적 기준(tier_name, 이모지 없는 순수 이름)에 맞게 동기화해요.
    - 티어 역할이 없으면: 새로 부여 (icon_bytes를 주면 역할 이미지 아이콘으로 적용돼요)
      ⭐ 역할이 이미 있는데 아이콘만 비어 있으면 그때도 채워줘요 — 25개 역할이 부스트 레벨 1
         시절에 만들어졌기 때문이에요. 일괄로 붙이려면 `scripts/apply_tier_role_icons.py`.
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
        # 🚨 맞는 역할을 이미 갖고 있어도, **다른 티어 역할이 같이 달려 있으면 치워야** 해요.
        # 예전엔 여기서 그냥 돌아갔어요. 그래서 티어 역할 2개가 달린 사람은 `/전적`을 몇 번
        # 돌려도 영구히 그대로였어요(2026-10-05 실측: 2명이 플래티넘 1 + 골드 1을 동시 보유).
        # `member_tier_index()`가 max()를 쓰니 밸런싱은 안 깨졌지만, 역할 색이 엉뚱하게 보여요.
        stale = [r for r in current_roles if r.name != display_name]
        if stale:
            await member.remove_roles(*stale, reason="티어 역할 중복 정리")
            return {
                "role": matching,
                "status": "cleaned",
                "previous": display_name,
                "removed": [r.name for r in stale],
            }
        return {"role": matching, "status": "unchanged", "previous": display_name}

    new_role = await get_or_create_tier_role(member.guild, tier_name, icon_bytes=icon_bytes)

    # 🚨 개명 때문에 생긴 함정: 위 호출이 **멤버가 이미 달고 있던 그 역할의 이름만 바꿔서**
    # 돌려줄 수 있어요(`💠 다이아몬드 2` -> `다이아몬드 2`). 그걸 "옛 역할"로 보고 떼면
    # 방금 맞춘 역할을 뗐다 다시 다는 꼴이 돼요. 그래서 새 역할 자신은 제외해요.
    stale = [r for r in current_roles if r != new_role]
    if stale:
        await member.remove_roles(*stale, reason="티어 변경으로 인한 이전 역할 제거")
    if new_role not in member.roles:
        await member.add_roles(new_role, reason=f"티어 자동 동기화: {display_name}")

    if not previous_names:
        status = "new"
    elif stale:
        status = "updated"
    else:
        # 달고 있던 역할의 이름만 바뀐 경우예요. 티어는 그대로니 "바뀌었다"고 하면 거짓말이에요.
        status = "unchanged"
    return {"role": new_role, "status": status, "previous": previous_names[0] if previous_names else None}