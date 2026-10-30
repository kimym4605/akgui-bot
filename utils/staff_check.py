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

# 🚪 잠긴 통화방(`/방만들기`)에 들어갈 수 있는 역할이에요. 위 목록에서 🎉 이벤트 담당만 뺐어요
# (2026-10-30, 사용자 결정 — 이벤트 담당은 남의 개인 방에 들어갈 이유가 없어요).
#
# ⚠️ **위 집합에서 빼는 식(`STAFF_ROLE_NAMES - {...}`)으로 쓰지 않았어요.** 그렇게 두면 나중에
#    운영진 역할이 하나 늘어날 때 아무도 모르게 "남의 잠긴 방 입장 권한"까지 같이 생겨요.
#    대신 `test_staff_check.py`가 ⒜ 이게 운영진 집합의 부분집합인지 ⒝ 이벤트담당이 빠져 있는지를
#    봐서, 이름 오타나 한쪽만 고치는 실수를 잡아요.
#
# 👑 방장 · 🥈 부방장 · 🛠️ 서버 담당은 `administrator` 권한이 있어서 **지금도 이미** 들어가요.
# 그래도 여기 적어두는 이유: 나중에 그 역할에서 관리자 권한을 떼도 방 입장이 조용히 깨지지 않아요.
ROOM_ENTRY_ROLE_NAMES = frozenset({
    "방장",
    "부방장",
    "서버담당",
    "문의담당",
    "신고담당",
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


def room_entry_roles(guild: discord.Guild | None) -> list[discord.Role]:
    """잠긴 통화방에 입장 권한을 얹어줄 역할들이에요. (`utils/dynamic_room.py`가 써요)

    ⚠️ 서버에 **실제로 있는** 역할만 돌려줘요. 이름이 바뀌어서 하나도 안 걸리면 빈 목록이
    나오고, 그러면 방은 예전처럼 잠긴 상태로 만들어져요(기능이 조용히 꺼지는 것이지
    방이 아무나 들어오는 상태가 되는 게 아니에요 — 안전한 쪽으로 실패해요)."""
    if guild is None:
        return []
    return [r for r in guild.roles if normalize_role_name(r.name) in ROOM_ENTRY_ROLE_NAMES]


def can_enter_locked_room(member: discord.abc.User | None) -> bool:
    """이 사람이 "잠긴 방에 그냥 들어갈 수 있는 사람"인가요?

    `administrator`는 채널 권한을 통째로 무시하니까 여기서도 통과예요 — 실제로 👑 방장 ·
    🥈 부방장 · 🛠️ 서버 담당이 지금까지 들어갈 수 있던 이유가 역할 이름이 아니라 이거였어요."""
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(normalize_role_name(r.name) in ROOM_ENTRY_ROLE_NAMES for r in member.roles)


def staff_role_labels(guild: discord.Guild | None, names: frozenset[str] | None = None) -> str:
    """안내 문구에 쓸 역할 이름 목록이에요. **서버에 실제로 있는 이름을 그대로** 보여줘요
    (여기서 이름을 다시 타이핑하면 이모지가 바뀔 때마다 안내문이 거짓이 돼요).

    `names`를 주면 그 집합만 봐요. 안 주면 운영진 전체(`STAFF_ROLE_NAMES`)예요."""
    if guild is None:
        return "운영진"
    wanted = names if names is not None else STAFF_ROLE_NAMES
    found = [r.name for r in guild.roles if normalize_role_name(r.name) in wanted]
    if not found:
        return "운영진"
    # 위에 있는 역할부터 보여주고, 6개를 다 늘어놓으면 문장이 길어지니 3개까지만 적어요.
    found = list(reversed(found))
    if len(found) > 3:
        return " · ".join(found[:3]) + f" 등 운영진 {len(found)}개 역할"
    return " · ".join(found)


def room_entry_role_labels(guild: discord.Guild | None) -> str:
    """`/방만들기` 안내문에 "누가 초대 없이 들어올 수 있는지" 적을 때 쓰는 이름 목록이에요.

    🚨 **이름을 안내문에 직접 타이핑하지 말고 이걸 쓰세요.** 2026-10-18에 안내문이 7일간
    거짓이었던 적이 있어요 — 코드가 내는 값과 안내문이 따로 놀면 그런 일이 또 나요.

    ⚠️ `staff_role_labels`처럼 3개에서 자르지 않고 **전부 적어요.** 방장에게는 "몇 개 역할"이
    아니라 **누가** 들어올 수 있는지가 필요하고, 🎉 이벤트 담당은 안 들어온다는 것도 거기서
    드러나요. (5개라 다 적어도 한 줄이에요)"""
    if guild is None:
        return "운영진"
    # 위에 있는 역할부터 적어요(👑 방장이 먼저). `guild.roles`는 낮은 순서부터예요.
    found = [r.name for r in reversed(guild.roles)
             if normalize_role_name(r.name) in ROOM_ENTRY_ROLE_NAMES]
    return " · ".join(found) if found else "운영진"


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
