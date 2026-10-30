"""🚪 운영진이 잠긴 통화방(`/방만들기`)에 바로 들어갈 수 있는지 검증. 디스코드에 접속하지 않아요.

2026-10-30에 붙였어요. 사용자 요청: *"방장하고 부방장같은경우에는 방만들기로 만들어서 잠궈놔도
강제로 들어갈 수 있는데, 매니저들도 같은 기능을 넣어주면 좋을 것 같은데?"*

⭐ **실측해서 알아낸 전제**(`/guilds/{id}/roles`, 2026-10-30):
   👑 방장 · 🥈 부방장 · 🛠️ 서버 담당은 `administrator`가 있어서 **지금까지도** 들어갔어요.
   봇이 열어준 게 아니에요 — 관리자는 채널 권한을 통째로 무시해요.
   📩 문의 담당 · ⚖️ 신고 담당은 관리자가 없어서 **실제로 막혀 있었어요.**
   🎉 이벤트 담당은 사용자 결정으로 **일부러 제외**했어요.

여기서 확인하는 것:
  1) 두 역할 집합이 서로 어긋나지 않는다 (한쪽만 고치는 실수 · 이름 오타)
  2) 🎉 이벤트 담당은 빠져 있다 (사용자 결정이라 조용히 바뀌면 안 돼요)
  3) 이모지가 붙은 실제 역할 이름을 집고, 일반 역할은 안 집는다
  4) 역할 이름이 통째로 바뀌면 **안전한 쪽으로** 실패한다 (방이 안 잠기는 게 아니라, 기능만 꺼짐)
  5) 권한표 조립이 네 가지를 **동시에** 만족한다
     — 카테고리 상속 · @everyone 잠금 · 방장 허용 · 운영진 허용
  6) 카테고리가 운영진에게 걸어둔 제한을 이긴다 (순서 함정)
  7) 운영진이 방에 들어와도 쓸모없는 개인 권한을 쓰지 않는다 (디스코드 왕복 낭비)
  8) 끌려 들어온 일반 멤버에게는 **여전히** 개인 권한을 준다 (2026-09-05 신고 회귀 방지)
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_room_staff_test"

import discord  # noqa: E402

from utils import staff_check  # noqa: E402
from utils.dynamic_room import DynamicRoomEngine, build_room_overwrites  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
# 가짜 디스코드 객체 (test_staff_check.py와 같은 방식)
# ------------------------------------------------------------------
class FakeRole:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<역할 {self.name}>"


class FakePerms:
    def __init__(self, administrator=False):
        self.administrator = administrator


class FakeGuild:
    def __init__(self, role_names):
        # discord.Guild.roles는 낮은 순서부터예요(@everyone이 앞).
        self.roles = [FakeRole(n) for n in role_names]
        self.default_role = self.roles[0]

    def role(self, name):
        return next(r for r in self.roles if r.name == name)


class FakeMember(discord.Member):
    """`isinstance(x, discord.Member)` 검사를 통과해야 해서 상속만 받고 __init__은 건너뛰어요.

    ⚠️ `roles`·`guild_permissions`는 읽기 전용 property라 클래스 본문에서 덮어써야 해요."""

    roles = ()
    guild_permissions = None
    bot = False

    def __init__(self, role_names, administrator=False, name="테스터"):
        self.roles = [FakeRole(n) for n in role_names]
        self.guild_permissions = FakePerms(administrator)
        self._name = name

    def __str__(self):
        return self._name

    @property
    def display_name(self):
        return self._name

    # 권한표의 **키로 쓰이니까** 해시가 돼야 해요. discord.Member의 해시는 내부 `_user`를
    # 쓰는데 __init__을 건너뛰어서 그게 없어요(실제로 AttributeError가 났어요).
    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def __repr__(self):
        return f"<멤버 {self._name}>"  # discord.Member의 __repr__도 `_user`를 봐요


class FakeCategory:
    def __init__(self, overwrites=None):
        self.overwrites = dict(overwrites or {})


class FakeChannel:
    """`set_permissions` 호출을 **세기만** 해요. 실제로 안 보냈는지가 검사 대상이에요."""

    def __init__(self, guild, overwrites=None, name="🔒테스터의 랭크방"):
        self.guild = guild
        self.name = name
        self.id = 12345
        self._overwrites = dict(overwrites or {})
        self.calls = []

    def overwrites_for(self, obj):
        # 🚨 진짜 discord.py와 같은 의미여야 해요 — **그 대상 하나의** 권한만 돌려줘요.
        #    역할 권한을 합쳐서 돌려주면 7)·8)이 둘 다 거짓 통과해요.
        return self._overwrites.get(obj) or discord.PermissionOverwrite()

    async def set_permissions(self, target, **kwargs):
        kwargs.pop("reason", None)
        self.calls.append((target, kwargs))


# 2026-10-30 실제 서버 역할 구성
ROLE_NAMES = [
    "@everyone", "잼민이", "대학원생", "⚔️ 타격대", "✨ 레디언트",
    "🎉 이벤트 담당", "⚖️ 신고 담당", "📩 문의 담당", "🛠️ 서버 담당", "🥈 부방장", "👑 방장",
]
GUILD = FakeGuild(ROLE_NAMES)
EVERYONE = GUILD.default_role

ENTRY_ROLE_LABELS = ["👑 방장", "🥈 부방장", "🛠️ 서버 담당", "📩 문의 담당", "⚖️ 신고 담당"]


print("1) 두 역할 집합이 어긋나지 않는다")
check(
    "ROOM_ENTRY_ROLE_NAMES ⊂ STAFF_ROLE_NAMES",
    staff_check.ROOM_ENTRY_ROLE_NAMES <= staff_check.STAFF_ROLE_NAMES,
    f"운영진 집합에 없는 이름: {sorted(staff_check.ROOM_ENTRY_ROLE_NAMES - staff_check.STAFF_ROLE_NAMES)}",
)
check("5개다", len(staff_check.ROOM_ENTRY_ROLE_NAMES) == 5, str(sorted(staff_check.ROOM_ENTRY_ROLE_NAMES)))
for name in ["방장", "부방장", "서버담당", "문의담당", "신고담당"]:
    check(f"{name} 포함", name in staff_check.ROOM_ENTRY_ROLE_NAMES)

print("2) 🎉 이벤트 담당은 일부러 빠져 있다 (사용자 결정)")
check("이벤트담당 제외", "이벤트담당" not in staff_check.ROOM_ENTRY_ROLE_NAMES)
check(
    "그래도 운영진(/팀짜기)에는 그대로 남아있다",
    "이벤트담당" in staff_check.STAFF_ROLE_NAMES,
    "여기서 빠지면 이벤트 담당이 /팀짜기까지 못 쓰게 돼요",
)

print("3) 이모지가 붙은 실제 이름을 집고, 일반 역할은 안 집는다")
found = staff_check.room_entry_roles(GUILD)
found_names = [r.name for r in found]
check("5개 집었다", len(found) == 5, str(found_names))
for label in ENTRY_ROLE_LABELS:
    check(f"{label} 집었다", label in found_names)
for label in ["🎉 이벤트 담당", "@everyone", "잼민이", "✨ 레디언트"]:
    check(f"{label} 안 집었다", label not in found_names)
check(
    "이모지가 빠져도 집는다",
    [r.name for r in staff_check.room_entry_roles(FakeGuild(["@everyone", "신고 담당"]))] == ["신고 담당"],
)

print("4) 역할 이름이 통째로 바뀌면 안전한 쪽으로 실패한다")
renamed = FakeGuild(["@everyone", "운영팀", "스태프"])
check("아무것도 못 집으면 빈 목록", staff_check.room_entry_roles(renamed) == [])
ow_renamed = build_room_overwrites(renamed, FakeMember([], name="방주인"), None)
check(
    "그래도 방은 잠긴 채로 만들어진다",
    ow_renamed[renamed.default_role].connect is False,
    "역할을 못 찾았을 때 방이 열려버리면 최악이에요",
)

print("5) 권한표가 네 가지를 동시에 만족한다")
OWNER = FakeMember(["⚔️ 타격대"], name="방주인")
NEWCOMER = GUILD.role("잼민이")
# 랭크방 카테고리에 실제로 걸려 있는 모양: 신입은 채널을 못 봐요.
CATEGORY = FakeCategory({NEWCOMER: discord.PermissionOverwrite(view_channel=False)})
ow = build_room_overwrites(GUILD, OWNER, CATEGORY)

check("@everyone 잠금이 살아있다", ow[EVERYONE].connect is False)
check("@everyone 은 방이 보인다", ow[EVERYONE].view_channel is True)
check("방장은 입장 가능", ow[OWNER].connect is True)
check("방장은 말할 수 있다", ow[OWNER].speak is True)
check(
    "카테고리 제한(신입 채널보기 차단)이 그대로 물려받아졌다",
    NEWCOMER in ow and ow[NEWCOMER].view_channel is False,
    "2026-09-05에 고친 함정이에요 - 다시 깨지면 신입이 방 목록을 봐요",
)
for label in ENTRY_ROLE_LABELS:
    role = GUILD.role(label)
    check(f"{label} 입장 가능", role in ow and ow[role].connect is True)
    check(f"{label} 음성채널 채팅 가능", role in ow and ow[role].send_messages is True)
event_role = GUILD.role("🎉 이벤트 담당")
check(
    "🎉 이벤트 담당에게는 입장 권한이 없다",
    event_role not in ow or ow[event_role].connect is not True,
)
check("일반 역할에 입장 권한이 생기지 않았다", GUILD.role("✨ 레디언트") not in ow)
check("카테고리가 없어도(None) 터지지 않는다", build_room_overwrites(GUILD, OWNER, None)[EVERYONE].connect is False)

print("6) 카테고리가 운영진에게 걸어둔 제한을 이긴다 (순서 함정)")
report_role = GUILD.role("⚖️ 신고 담당")
blocked_cat = FakeCategory({report_role: discord.PermissionOverwrite(connect=False)})
ow2 = build_room_overwrites(GUILD, OWNER, blocked_cat)
check(
    "카테고리의 connect=False 를 덮어썼다",
    ow2[report_role].connect is True,
    "운영진 허용이 카테고리 상속보다 먼저 오면 조용히 막혀요",
)

print("7) 운영진이 들어와도 개인 권한을 쓰지 않는다")


async def entry_cases():
    # 🚨 엔진을 __init__ 없이 만들어요 — DB·봇 연결 없이 이 메서드만 돌려보려고요.
    engine = object.__new__(DynamicRoomEngine)
    engine.channel_to_kind = {12345: "rank"}
    engine.room_kinds = {"rank": {"label": "랭크방", "emoji": "🔒"}}

    # 방에는 이미 운영진 역할 권한이 얹혀 있어요(= build_room_overwrites 결과와 같은 상태).
    channel = FakeChannel(GUILD, build_room_overwrites(GUILD, OWNER, None))

    for label, admin in [("⚖️ 신고 담당", False), ("📩 문의 담당", False), ("👑 방장", True)]:
        channel.calls.clear()
        await engine._grant_entry_on_join(channel, FakeMember([label], administrator=admin, name=label))
        check(f"{label} 에게는 권한을 안 썼다", channel.calls == [], str(channel.calls))

    # 8) 회귀 방지: 끌려 들어온 일반 멤버에게는 여전히 줘야 해요.
    channel.calls.clear()
    dragged = FakeMember(["⚔️ 타격대"], name="끌려온사람")
    await engine._grant_entry_on_join(channel, dragged)
    print("8) 끌려 들어온 일반 멤버에게는 여전히 개인 권한을 준다")
    check("권한을 1번 썼다", len(channel.calls) == 1, str(channel.calls))
    if channel.calls:
        target, kwargs = channel.calls[0]
        check("대상이 그 사람이다", target is dragged)
        check("connect 를 줬다", kwargs.get("connect") is True)
        check("채팅이 되게 send_messages 도 줬다", kwargs.get("send_messages") is True)

    # 🎉 이벤트 담당은 운영진 입장 대상이 아니니, 끌려 들어오면 일반 멤버처럼 권한을 받아야 해요.
    channel.calls.clear()
    await engine._grant_entry_on_join(channel, FakeMember(["🎉 이벤트 담당"], name="이벤트담당"))
    check("🎉 이벤트 담당은 일반 멤버와 똑같이 처리된다", len(channel.calls) == 1, str(channel.calls))


asyncio.run(entry_cases())

print("9) can_enter_locked_room 판정")
check("⚖️ 신고 담당 통과", staff_check.can_enter_locked_room(FakeMember(["⚖️ 신고 담당"])) is True)
check("📩 문의 담당 통과", staff_check.can_enter_locked_room(FakeMember(["📩 문의 담당"])) is True)
check("🎉 이벤트 담당은 막힌다", staff_check.can_enter_locked_room(FakeMember(["🎉 이벤트 담당"])) is False)
check("일반 유저는 막힌다", staff_check.can_enter_locked_room(FakeMember(["잼민이", "⚔️ 타격대"])) is False)
check(
    "administrator 는 이름과 무관하게 통과",
    staff_check.can_enter_locked_room(FakeMember(["잼민이"], administrator=True)) is True,
    "실제로 방장·부방장이 들어가던 이유가 이거예요",
)
check("DM(서버 밖)은 막힌다", staff_check.can_enter_locked_room(None) is False)
check(
    "`방장` ⊂ `부방장` 함정 - 비슷한 이름이 멋대로 통과하지 않는다",
    staff_check.can_enter_locked_room(FakeMember(["폐관수련방장"])) is False,
)

print("10) /방만들기 안내문이 '운영진은 들어올 수 있다'를 말한다")
labels = staff_check.room_entry_role_labels(GUILD)
check("🎉 이벤트 담당은 안 적는다", "이벤트" not in labels, labels)
check(
    "5개를 자르지 않고 다 적는다",
    all(lab in labels for lab in ENTRY_ROLE_LABELS) and "개 역할" not in labels,
    labels,
)
check("👑 방장이 맨 앞이다", labels.startswith("👑 방장"), labels)
check("한 줄에 들어갈 길이다", len(labels) <= 80, f"{len(labels)}자: {labels}")
check("역할 이름이 다 바뀌면 그냥 '운영진'", staff_check.room_entry_role_labels(renamed) == "운영진")
check("서버를 모르면(None) 그냥 '운영진'", staff_check.room_entry_role_labels(None) == "운영진")
check(
    "운영진 전체 목록(/팀짜기용)은 그대로 6개다",
    "6개 역할" in staff_check.staff_role_labels(GUILD),
    staff_check.staff_role_labels(GUILD),
)

# 🚨 안내문은 create_room 안에서 조립돼서 여기서 불러볼 수가 없어요. 그래서 **그 함수 본문이
#    이 헬퍼를 실제로 쓰는지**를 봐요. 주석·독스트링을 먼저 떼요 — 안 떼면 위에 적어둔
#    설명 문구에 걸려서 거짓 통과해요(2026-10-27에 실제로 당한 함정이에요).
import re  # noqa: E402

src = open(os.path.join(BOT_DIR, "utils", "dynamic_room.py"), encoding="utf-8").read()
body = src[src.index("    async def create_room("):]
body = body[: body.index("\n    async def ", 10)]
code_only = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
code_only = re.sub(r'""".*?"""', "", code_only, flags=re.S)
check(
    "create_room이 room_entry_role_labels를 쓴다",
    "room_entry_role_labels(" in code_only,
    "안내문이 운영진 입장을 말하지 않으면 '승인해야 들어올 수 있어요'가 거짓이 돼요",
)
check(
    "그 문구를 실제로 보내는 메시지에 끼워넣는다",
    "{staff_text}" in code_only,
    "변수만 만들고 안 쓰면 안내문은 그대로 거짓이에요",
)
check(
    "create_room이 권한표 조립 함수를 쓴다",
    "build_room_overwrites(" in code_only,
)

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
