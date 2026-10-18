"""🏅 주간 MVP 선정 규칙 검증. 실제 DB·디스코드 없이 돌아요.

    python scripts/test_weekly_mvp.py

## 무엇을 막으려고 만들었나

🚨 **한 판 운으로 MVP가 되는 것.** 점수만 보고 1위를 뽑으면, 한 경기만 하고 잘 나온
사람이 20경기를 꾸준히 한 사람을 제칠 수 있어요. 아무도 납득하지 않고, 그러면 다음 주에
`/전적`을 돌릴 이유가 사라져요.

🚨 **역할이 두 명에게 달리는 것.** 교체할 때 주고 나서 회수하면, 중간에 실패했을 때
두 명이 MVP가 돼요. 반드시 **회수 먼저**.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("MONGODB_DB_NAME", "agwi_mvp_test")

from cogs import weekly_mvp  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def row(uid, score, matches, grade="B"):
    return {"userId": str(uid), "score": score, "grade": grade,
            "stats": {"kd": 1.1, "winRate": 55.0, "hs": 22.0, "matches": matches}}


# ------------------------------------------------------------------
print("⒜ 🚨 표본이 적은 1위는 건너뛴다")

# 1경기로 900점 vs 20경기로 700점 → 20경기 쪽이 MVP여야 해요.
rows = [row(1, 900, 1), row(2, 700, 20), row(3, 650, 10)]
mvp = weekly_mvp.pick_mvp(rows)
check(f"{weekly_mvp.MIN_MATCHES}경기 미만 1위는 제외된다",
      mvp is not None and mvp["userId"] == "2", f"뽑힌 사람={mvp and mvp['userId']}")

print("\n⒝ 표본을 채운 사람 중에선 점수 1위")
rows = [row(1, 500, 5), row(2, 800, 4), row(3, 650, 10)]
mvp = weekly_mvp.pick_mvp(rows)
check("점수 1위가 뽑힌다", mvp["userId"] == "2", f"뽑힌 사람={mvp['userId']}")

print("\n⒞ 아무도 조건을 못 채우면 MVP 없음")
rows = [row(1, 900, 1), row(2, 800, 2)]
check("None을 돌려준다", weekly_mvp.pick_mvp(rows) is None)
check("빈 목록도 None", weekly_mvp.pick_mvp([]) is None)

print("\n⒟ 경기 수 정보가 없는 기록은 후보에서 빠진다")
# 옛 기록에는 stats가 없을 수 있어요. 그걸 0경기로 보고 건너뛰어야 해요.
rows = [{"userId": "9", "score": 999}, row(2, 100, 5)]
mvp = weekly_mvp.pick_mvp(rows)
check("stats가 없으면 건너뛴다", mvp is not None and mvp["userId"] == "2",
      f"뽑힌 사람={mvp and mvp['userId']}")


# ------------------------------------------------------------------
print("\n⒠ 🚨 역할 교체는 '회수 먼저, 부여 나중'")


class FakeRole:
    name = weekly_mvp.ROLE_NAME

    def __init__(self):
        self.members = []


class FakeMember:
    def __init__(self, uid, name):
        self.id = uid
        self.display_name = name
        self.roles = []
        self.log = []

    async def add_roles(self, role, reason=None):
        self.roles.append(role)
        ORDER.append(("add", self.display_name))

    async def remove_roles(self, role, reason=None):
        if role in self.roles:
            self.roles.remove(role)
        ORDER.append(("remove", self.display_name))


class FakeGuild:
    def __init__(self, role):
        self.id = 1
        self.roles = [role]

    def get_member(self, uid):
        return None


ORDER: list[tuple[str, str]] = []


async def main():
    role = FakeRole()
    old = FakeMember(1, "옛MVP")
    new = FakeMember(2, "새MVP")
    old.roles.append(role)
    role.members = [old]

    guild = FakeGuild(role)
    ok = await weekly_mvp.hand_over_role(guild, new)

    check("교체에 성공한다", ok is True)
    check("이전 보유자에게서 회수한다", ("remove", "옛MVP") in ORDER, f"{ORDER}")
    check("새 MVP에게 부여한다", ("add", "새MVP") in ORDER, f"{ORDER}")
    check("🚨 회수가 부여보다 먼저다 (두 명이 달리는 순간이 없게)",
          ORDER.index(("remove", "옛MVP")) < ORDER.index(("add", "새MVP")),
          f"{ORDER}")

    # 같은 사람이 연속 MVP면 회수하지 않아야 해요.
    ORDER.clear()
    role.members = [new]
    await weekly_mvp.hand_over_role(guild, new)
    check("연속 MVP면 자기 역할을 뺏지 않는다",
          ("remove", "새MVP") not in ORDER, f"{ORDER}")


asyncio.run(main())


# ------------------------------------------------------------------
print("\n⒡ 발표 카드")
embed = weekly_mvp.build_embed(row(1, 834, 12, "A+"), "2026-W41", "와따마", 9)
check("제목에 주차와 이름", "2026-W41" in embed.title and "와따마" in embed.title, embed.title)
check("점수가 들어간다", "834" in (embed.description or ""), embed.description)
check("성적 필드가 있다", any("성적" in (f.name or "") for f in embed.fields))
check("최소 경기 수를 안내한다",
      any(str(weekly_mvp.MIN_MATCHES) in (f.value or "") for f in embed.fields))


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
