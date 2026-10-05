"""`sync_tier_role`이 티어 역할 중복을 치우는지 확인해요. 디스코드 없이 돌아가요.

2026-10-05 실측으로 찾은 버그예요. 두 사람이 `🔷 플래티넘 1` + `🥇 골드 1`을 **동시에**
달고 있었는데, 실제 티어(플래티넘 1)가 보유 역할 중 하나와 맞으면 `sync_tier_role`이
그 자리에서 조기 반환해서 **나머지 티어 역할을 영구히 안 치웠어요**. `/전적`을 몇 번
돌려도 그대로였고, `member_tier_index()`가 max()를 써서 밸런싱은 안 깨졌지만 디스코드에서
역할 색이 엉뚱하게 보였어요.

여기서 확인하는 것:
  1) 역할이 없던 사람 → 부여 (status="new")
  2) 다른 티어 하나만 달린 사람 → 교체 (status="updated")
  3) ⭐ 맞는 역할 + 옛 티어 역할 → 옛 것만 치움 (status="cleaned")
  4) 맞는 역할 하나만 → 아무것도 안 함 (status="unchanged", 쓸데없는 API 호출 없음)
  5) 치울 때 티어가 아닌 역할(칭호·포지션 등)은 절대 건드리지 않는다
  6) member_tier_index는 여러 개가 달려 있으면 가장 높은 걸 쓴다
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)

import discord  # noqa: E402

from utils import tier_roles  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


class FakeRole:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<{self.name}>"

    def __eq__(self, other):
        return isinstance(other, FakeRole) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


class FakeGuild:
    def __init__(self):
        self.created = []


class FakeMember(discord.Member):
    """`roles`·`guild_permissions`는 읽기 전용 property라 클래스 본문에서 덮어써요."""

    roles = ()
    guild_permissions = None

    def __init__(self, role_names):
        self.roles = [FakeRole(n) for n in role_names]
        self.guild = FakeGuild()
        self.removed = []
        self.added = []

    async def remove_roles(self, *roles, reason=None):
        self.removed.extend(r.name for r in roles)
        self.roles = [r for r in self.roles if r not in roles]

    async def add_roles(self, *roles, reason=None):
        self.added.extend(r.name for r in roles)
        self.roles = list(self.roles) + list(roles)


async def fake_get_or_create(guild, tier_name, icon_bytes=None):
    guild.created.append(tier_name)
    return FakeRole(tier_roles.display_name_for(tier_name))


tier_roles.get_or_create_tier_role = fake_get_or_create

PLAT1 = "🔷 플래티넘 1"
GOLD1 = "🥇 골드 1"
print(f"기준 이름: 플래티넘 1 -> {tier_roles.display_name_for('플래티넘 1')!r}")
assert tier_roles.display_name_for("플래티넘 1") == PLAT1

print("1) 역할이 없으면 새로 부여한다")
m = FakeMember(["잼민이"])
res = asyncio.run(tier_roles.sync_tier_role(m, "플래티넘 1"))
check("status=new", res["status"] == "new", res["status"])
check("플래티넘 1을 달아줬다", m.added == [PLAT1], str(m.added))
check("아무것도 안 뗐다", m.removed == [], str(m.removed))

print("2) 다른 티어 하나만 달렸으면 교체한다")
m = FakeMember([GOLD1, "잼민이"])
res = asyncio.run(tier_roles.sync_tier_role(m, "플래티넘 1"))
check("status=updated", res["status"] == "updated", res["status"])
check("골드 1을 뗐다", m.removed == [GOLD1], str(m.removed))
check("플래티넘 1을 달았다", m.added == [PLAT1], str(m.added))

print("3) ⭐ 맞는 역할 + 옛 티어 역할 → 옛 것만 치운다 (이번에 고친 부분)")
m = FakeMember([PLAT1, GOLD1, "⚔️ 타격대"])
res = asyncio.run(tier_roles.sync_tier_role(m, "플래티넘 1"))
check("status=cleaned", res["status"] == "cleaned", res["status"])
check("골드 1만 뗐다", m.removed == [GOLD1], str(m.removed))
check("플래티넘 1은 그대로 (다시 안 달았다)", m.added == [], str(m.added))
check("removed 목록을 돌려준다", res.get("removed") == [GOLD1], str(res.get("removed")))
check("role은 유지된 역할", res["role"].name == PLAT1, res["role"].name)
check("남은 역할이 플래티넘 1 + 타격대", sorted(r.name for r in m.roles) == sorted([PLAT1, "⚔️ 타격대"]),
      str(m.roles))
check("역할을 새로 만들지 않았다", m.guild.created == [], str(m.guild.created))

print("4) 맞는 역할 하나만 달렸으면 아무것도 안 한다")
m = FakeMember([PLAT1, "잼민이"])
res = asyncio.run(tier_roles.sync_tier_role(m, "플래티넘 1"))
check("status=unchanged", res["status"] == "unchanged", res["status"])
check("뗀 것도 단 것도 없다", m.removed == [] and m.added == [])

print("5) 티어가 아닌 역할은 안 건드린다")
m = FakeMember([PLAT1, GOLD1, "마샬의 악마", "🏹 척후대", "Server Booster", "@everyone"])
asyncio.run(tier_roles.sync_tier_role(m, "플래티넘 1"))
check("뗀 건 골드 1 하나뿐", m.removed == [GOLD1], str(m.removed))
check("칭호·포지션·부스터는 남아있다",
      {"마샬의 악마", "🏹 척후대", "Server Booster", "@everyone"} <= {r.name for r in m.roles},
      str(m.roles))

print("6) 티어가 여러 개면 가장 높은 걸 쓴다 (밸런싱이 안 깨지는 이유)")
m = FakeMember([PLAT1, GOLD1])
idx = tier_roles.member_tier_index(m)
check("플래티넘 1의 번호를 쓴다", idx == tier_roles.TIER_INDEX_BY_DISPLAY_NAME[PLAT1],
      f"{idx} vs 플래{tier_roles.TIER_INDEX_BY_DISPLAY_NAME[PLAT1]}/골드{tier_roles.TIER_INDEX_BY_DISPLAY_NAME[GOLD1]}")

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
