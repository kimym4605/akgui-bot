"""`/팀짜기` 운영진 제한 검증. 디스코드에 접속하지 않고 확인해요.

2026-10-05에 붙였어요. 여기서 확인하는 것:
  1) 운영진 역할(이모지 붙은 실제 이름)은 통과한다
  2) 일반 유저·관전자는 막힌다
  3) 이모지가 바뀌거나 빠져도 통과한다 (이름의 뼈대로 보니까)
  4) `방장`이 `부방장`의 부분 문자열인 함정 — 비슷한 이름이 멋대로 통과하지 않는다
  5) administrator 권한은 이름과 무관하게 통과한다 (역할 이름이 바뀌어도 잠기지 않는 비상구)
  6) DM(서버 밖)에서는 막힌다
  7) 거절 안내는 ephemeral이고, 서버에 실제로 있는 역할 이름을 그대로 보여준다
  8) 🎲 베팅 버튼은 여전히 누구나 누를 수 있다 (코인 소비처라 좁히면 안 돼요)
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_staff_test"

import discord  # noqa: E402

from utils import staff_check  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
# 가짜 디스코드 객체
# ------------------------------------------------------------------
class FakeRole:
    def __init__(self, name):
        self.name = name


class FakePerms:
    def __init__(self, administrator=False):
        self.administrator = administrator


class FakeGuild:
    def __init__(self, role_names):
        # discord.Guild.roles는 낮은 순서부터예요(@everyone이 앞).
        self.roles = [FakeRole(n) for n in role_names]


class FakeMember(discord.Member):
    """`isinstance(x, discord.Member)` 검사를 통과해야 해서 상속만 받고 __init__은 건너뛰어요.

    ⚠️ `roles`·`guild_permissions`는 discord.Member에서 **읽기 전용 property**라 그냥은
    대입이 안 돼요(`has no setter`). 클래스 본문에서 평범한 속성으로 덮어써야 해요."""

    roles = ()
    guild_permissions = None

    def __init__(self, role_names, administrator=False, name="테스터"):
        self.roles = [FakeRole(n) for n in role_names]
        self.guild_permissions = FakePerms(administrator)
        self._name = name

    def __str__(self):
        return self._name


class FakeUser:
    """서버 밖(DM)에서 온 사용자예요. discord.Member가 아니에요."""

    def __init__(self):
        self.roles = []

    def __str__(self):
        return "DM유저"


class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class FakeInteraction:
    def __init__(self, user, guild):
        self.user = user
        self.guild = guild
        self.response = FakeResponse()


# 2026-10-05 실제 서버 역할 구성(상위 일부 + 일반 역할)
GUILD = FakeGuild([
    "@everyone", "잼민이", "대학원생", "⚔️ 타격대", "✨ 레디언트",
    "🎉 이벤트 담당", "⚖️ 신고 담당", "📩 문의 담당", "🛠️ 서버 담당", "🥈 부방장", "👑 방장",
])

print("1) 운영진 역할은 통과한다")
for role in ["👑 방장", "🥈 부방장", "🛠️ 서버 담당", "📩 문의 담당", "⚖️ 신고 담당", "🎉 이벤트 담당"]:
    check(f"{role} 통과", staff_check.is_staff(FakeMember([role, "⚔️ 타격대"])) is True)

print("2) 일반 유저는 막힌다")
for roles in (["잼민이"], ["⚔️ 타격대", "✨ 레디언트"], [], ["대학원생", "Server Booster"]):
    check(f"{roles or '역할 없음'} 거절", staff_check.is_staff(FakeMember(roles)) is False)

print("3) 이모지가 바뀌거나 빠져도 통과한다")
for variant in ["방장", "👑방장", "🔥 방장", "방 장", "서버담당", "🛠️서버 담당"]:
    check(f"'{variant}' 통과", staff_check.is_staff(FakeMember([variant])) is True, )

print("4) 비슷한 이름이 멋대로 통과하지 않는다 (방장 ⊂ 부방장 함정)")
for impostor in ["폐관수련방장", "방장님", "부방장 후보", "담당", "서버", "전 방장", "방장(임시)"]:
    check(f"'{impostor}' 거절", staff_check.is_staff(FakeMember([impostor])) is False)
# 그리고 부방장은 '방장'을 품고 있어도 **제 이름으로** 통과해야 해요.
check("'부방장'은 제 이름으로 통과", staff_check.is_staff(FakeMember(["부방장"])) is True)

print("5) administrator 권한은 비상구다")
check(
    "역할 이름이 전부 바뀌어도 ADMIN은 통과",
    staff_check.is_staff(FakeMember(["이름이바뀐역할"], administrator=True)) is True,
)

print("6) DM(서버 밖)에서는 막힌다")
check("discord.Member가 아니면 거절", staff_check.is_staff(FakeUser()) is False)
check("None도 거절", staff_check.is_staff(None) is False)

print("7) 데코레이터의 거절 안내")
predicate = staff_check.restrict_to_staff("`/팀짜기`", hint="편성은 `/팀보기` 로 볼 수 있어요.")
# app_commands.check는 함수에 __discord_app_commands_checks__를 붙여요. 거기서 꺼내 직접 돌려요.
dummy = type("Dummy", (), {})()
decorated = predicate(dummy)
pred = decorated.__discord_app_commands_checks__[0]

it = FakeInteraction(FakeMember(["잼민이"]), GUILD)
allowed = asyncio.run(pred(it))
check("일반 유저는 False", allowed is False)
check("안내를 1건 보냈다", len(it.response.sent) == 1)
if it.response.sent:
    content, kwargs = it.response.sent[0]
    check("본인에게만 보인다(ephemeral)", kwargs.get("ephemeral") is True)
    check("명령어 이름이 들어있다", "/팀짜기" in content, content)
    check("힌트가 들어있다", "/팀보기" in content, content)
    check("서버의 실제 역할 이름을 그대로 보여준다", "👑 방장" in content and "🥈 부방장" in content, content)
    check("일반 역할은 안 섞인다", "잼민이" not in content and "타격대" not in content, content)
    print(f"    └ 실제 문구: {content}")

it2 = FakeInteraction(FakeMember(["👑 방장"]), GUILD)
check("운영진은 True이고 안내를 안 보낸다",
      asyncio.run(pred(it2)) is True and it2.response.sent == [])

print("8) /팀짜기에 체크가 실제로 붙었고, 🎲 베팅 버튼은 안 좁혀졌다")
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_staff_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_staff_test"
from discord.ext import commands as dcommands  # noqa: E402


async def load_and_inspect():
    bot = dcommands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension("cogs.team")
    cmd = bot.tree.get_command("팀짜기")
    check("/팀짜기 등록됨", cmd is not None)
    check("체크가 1개 이상 붙었다", bool(cmd.checks), str(cmd.checks))
    check("설명에 [운영진] 표시", "운영진" in cmd.description, cmd.description)
    # 운영진이 아니면 실제로 거절되는지 체크 체인으로 확인해요.
    it3 = FakeInteraction(FakeMember(["잼민이"]), GUILD)
    results = [await c(it3) for c in cmd.checks]
    check("체크 체인이 일반 유저를 거절", all(r is False for r in results), str(results))
    # /팀보기는 그대로 열려 있어야 해요(편성을 못 보면 막힌 사람이 할 게 없어요).
    view_cmd = bot.tree.get_command("팀보기")
    check("/팀보기는 제한 없음", view_cmd is not None and not view_cmd.checks)
    return bot


bot = asyncio.run(load_and_inspect())


src = open(os.path.join(BOT_DIR, "cogs", "team.py"), encoding="utf-8").read()
bet_block = src[src.index("async def bet(self"): src.index("async def bet(self") + 900]
check(
    "🎲 베팅 버튼에 소유자/운영진 검사가 없다",
    "is_staff" not in bet_block and "_is_owner" not in bet_block,
    "베팅 버튼이 좁혀졌어요 - 코인 소비처라 누구나 눌러야 해요",
)

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
