"""운영진만 쓸 수 있게 막는 체크예요. `restrict_to_channel`(utils/channel_check.py)의 형제예요.

`/팀짜기`에 붙이려고 만들었어요(2026-10-05). 내전 편성을 아무나 열면 같은 방에서 편성이
여러 번 덮어쓰이고, 거기 딸린 👑 팀장 뽑기·🎲 베팅·🗡️ KDA 자동기록까지 같이 흔들려요.

## 역할을 ID가 아니라 "이름의 뼈대"로 보는 이유

- **이모지를 떼고 비교해요.** 2026-10-04 서버 정리에서 역할·채널 이름 앞에 이모지를 붙이는
  규칙이 생겼어요(`👑 방장`). 이모지가 또 바뀌어도 이 체크는 안 깨져야 해요.
- **ID로 박으면** 역할을 지웠다 다시 만들 때(실제로 티어 역할에서 일어나는 일이에요) 조용히
  아무도 통과하지 못해요. 이름은 사람이 보는 그대로라 그런 사고가 눈에 띄어요.
- **`administrator` 권한이 있으면 이름과 무관하게 통과**시켜요. 역할 이름을 통째로 바꿔서
  운영진이 자기 명령어에서 잠기는 상황을 막는 비상구예요.

⚠️ `방장`은 `부방장`의 부분 문자열이에요. 그래서 **부분 일치가 아니라 정확히 일치**로 봐요
(부분 일치로 하면 나중에 `폐관수련방장` 같은 역할이 생길 때 조용히 통과해요).
"""
import logging
import re

import discord
from discord import app_commands

log = logging.getLogger(__name__)

# 이모지·공백을 뗀 뼈대 이름이에요. 2026-10-05 기준 서버 역할: 👑 방장 / 🥈 부방장 /
# 🛠️ 서버 담당 / 📩 문의 담당 / ⚖️ 신고 담당 / 🎉 이벤트 담당
STAFF_ROLE_NAMES = frozenset({
    "방장",
    "부방장",
    "서버담당",
    "문의담당",
    "신고담당",
    "이벤트담당",
})


def normalize_role_name(name: str) -> str:
    """이모지·공백·변형선택자를 떼고 한글/영문/숫자만 남겨요."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", name or "")


def is_staff(member: discord.abc.User | None) -> bool:
    if not isinstance(member, discord.Member):
        return False  # DM이거나 서버 정보를 못 읽는 경우예요
    if member.guild_permissions.administrator:
        return True
    return any(normalize_role_name(role.name) in STAFF_ROLE_NAMES for role in member.roles)


def staff_role_labels(guild: discord.Guild | None) -> str:
    """안내 문구에 쓸 역할 이름 목록이에요. **서버에 실제로 있는 이름을 그대로** 보여줘요
    (여기서 이름을 다시 타이핑하면 이모지가 바뀔 때마다 안내문이 거짓이 돼요)."""
    if guild is None:
        return "운영진"
    found = [r.name for r in guild.roles if normalize_role_name(r.name) in STAFF_ROLE_NAMES]
    if not found:
        return "운영진"
    # 위에 있는 역할부터 보여주고, 6개를 다 늘어놓으면 문장이 길어지니 3개까지만 적어요.
    found = list(reversed(found))
    if len(found) > 3:
        return " · ".join(found[:3]) + f" 등 운영진 {len(found)}개 역할"
    return " · ".join(found)


def restrict_to_staff(label: str = "이 명령어", hint: str = ""):
    """운영진이 아니면 조용히 거절해요(거절 안내는 본인에게만 보여요).

    거절 메시지는 여기서 직접 보내요 — `bot.tree.error`가 `CheckFailure`를 "이미 안내한
    의도된 거절"로 보고 넘기기 때문이에요(채널 제한도 같은 방식이에요)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if is_staff(interaction.user):
            return True

        # 막힌 사람이 실제로 있는지는 나중에 로그로 확인해요. 제한이 과했는지 판단할 근거예요.
        log.info(
            "🔒 %s 사용을 막았어요(운영진 아님): user=%s", label, interaction.user
        )
        message = f"🔒 {label} 는 **{staff_role_labels(interaction.guild)}** 만 쓸 수 있어요."
        if hint:
            message += f"\n{hint}"
        await interaction.response.send_message(message, ephemeral=True)
        return False

    return app_commands.check(predicate)
