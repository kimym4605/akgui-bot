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
  7) ⭐ 이미 있는 역할에 아이콘이 비어 있으면 뒤늦게라도 채운다 (2026-11-03)
  8) 25개 티어가 valorant-api의 영문 티어명과 짝이 맞는다
  9) ⭐ 옛 이름(`🔷 플래티넘 1`)으로 남은 역할은 **새로 만들지 말고 개명**한다 (2026-11-03)
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


_real_get_or_create = tier_roles.get_or_create_tier_role   # 7)에서 되돌려 쓸 진짜 함수
tier_roles.get_or_create_tier_role = fake_get_or_create

PLAT1 = "플래티넘 1"
GOLD1 = "골드 1"
OLD_PLAT1 = "🔷 플래티넘 1"      # 🕰️ 2026-11-03 이전 이름
OLD_GOLD1 = "🥇 골드 1"
print(f"기준 이름: 플래티넘 1 -> {tier_roles.display_name_for('플래티넘 1')!r} "
      f"(옛 이름 {tier_roles.legacy_display_name_for('플래티넘 1')!r})")
assert tier_roles.display_name_for("플래티넘 1") == PLAT1
assert tier_roles.legacy_display_name_for("플래티넘 1") == OLD_PLAT1

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
check("플래티넘 1의 번호를 쓴다", idx == tier_roles.TIER_INDEX_BY_NAME[PLAT1],
      f"{idx} vs 플래{tier_roles.TIER_INDEX_BY_NAME[PLAT1]}/골드{tier_roles.TIER_INDEX_BY_NAME[GOLD1]}")

# 🚨 개명이 아직 안 된 역할을 달고 있어도 밸런싱이 멀쩡해야 해요. 못 알아보면 티어 없는
#    사람으로 떨어져서 기준점(실버 3)으로 잡히고, 초월자가 실버 취급을 받아요.
m = FakeMember([OLD_PLAT1, OLD_GOLD1])
check("옛 이름 역할도 알아본다", tier_roles.member_tier_index(m) == tier_roles.TIER_INDEX_BY_NAME[PLAT1],
      str(tier_roles.member_tier_index(m)))
check("옛 이름도 티어 역할로 센다",
      len(tier_roles.get_member_current_tier_roles(m)) == 2,
      str(tier_roles.get_member_current_tier_roles(m)))

print("7) ⭐ 이미 있는 역할에 아이콘이 비어 있으면 뒤늦게라도 채운다 (2026-11-03)")
# 🚨 여기서는 진짜 `get_or_create_tier_role`을 써야 해요 — 위에서 fake로 바꿔놨으니 되돌려요.
tier_roles.get_or_create_tier_role = _real_get_or_create


class FakeIconRole(FakeRole):
    """`icon`이 None이면 아이콘이 없는 역할이에요(discord.py의 Role.icon과 같은 규약)."""

    def __init__(self, name, icon=None):
        super().__init__(name)
        self.icon = icon
        self.edited = []        # 붙은 아이콘들
        self.renamed = []       # 바뀐 이름들

    async def edit(self, *, display_icon=None, name=None, reason=None):
        if display_icon is not None:
            self.edited.append(display_icon)
            self.icon = "있음"
        if name is not None:
            self.renamed.append(name)
            self.name = name


class FakeIconGuild:
    # `name`이 없으면 역할을 새로 만드는 경로에서 AttributeError로 **터져버려요**. 그러면
    # "역할을 새로 만들지 않았다" 검사가 FAIL로 안 찍히고 뒤 검사도 안 돌아요.
    name = "테스트 서버"

    def __init__(self, roles):
        self.roles = roles
        self.created = []

    async def create_role(self, **kwargs):
        self.created.append(kwargs)
        return FakeIconRole(kwargs["name"], icon="있음" if kwargs.get("display_icon") else None)


empty = FakeIconRole(PLAT1, icon=None)
guild = FakeIconGuild([empty])
got = asyncio.run(tier_roles.get_or_create_tier_role(guild, "플래티넘 1", icon_bytes=b"PNGDATA"))
check("기존 역할을 그대로 돌려준다", got is empty)
check("비어 있던 아이콘을 채웠다", empty.edited == [b"PNGDATA"], str(empty.edited))
check("역할을 새로 만들지 않았다", guild.created == [], str(guild.created))

filled = FakeIconRole(PLAT1, icon="있음")
guild = FakeIconGuild([filled])
asyncio.run(tier_roles.get_or_create_tier_role(guild, "플래티넘 1", icon_bytes=b"PNGDATA"))
check("이미 아이콘이 있으면 쓸데없이 PATCH 안 한다", filled.edited == [], str(filled.edited))

noicon = FakeIconRole(PLAT1, icon=None)
guild = FakeIconGuild([noicon])
asyncio.run(tier_roles.get_or_create_tier_role(guild, "플래티넘 1", icon_bytes=None))
check("줄 아이콘이 없으면 PATCH 안 한다", noicon.edited == [], str(noicon.edited))

print("8) 25개 티어 전부가 valorant-api의 영문 티어명과 짝이 맞는다")
# 🚨 `apply_tier_role_icons.py`가 이 짝짓기로 역할을 찾아요. 하나라도 어긋나면 그 티어는
#    아이콘이 안 붙는데, 스크립트는 '역할 없음'으로 조용히 건너뛰어요.
EN_NAMES = (
    [f"{en.upper()} {d}" for en in ("Iron", "Bronze", "Silver", "Gold", "Platinum",
                                    "Diamond", "Ascendant", "Immortal") for d in (1, 2, 3)]
    + ["RADIANT"]
)
mapped = []
for en in EN_NAMES:
    parts = en.title().split()
    base = tier_roles.ENGLISH_TO_KOREAN_TIER.get(parts[0])
    mapped.append(base if base == tier_roles.TOP_TIER else f"{base} {parts[1]}")
check("25개가 TIER_OPTIONS와 정확히 같다", mapped == tier_roles.TIER_OPTIONS,
      f"{len(mapped)}개 / 다른 것: {set(mapped) ^ set(tier_roles.TIER_OPTIONS)}")

print("9) ⭐ 옛 이름으로 남은 역할은 새로 만들지 말고 개명한다 (2026-11-03)")
# 🚨 여기가 깨지면 같은 티어 역할이 **둘**이 돼요. 멤버는 옛 쪽에 달려 있고 봇은 새 쪽을 보니
#    `/전적`을 돌릴 때마다 역할이 왔다 갔다 하고, 서열 위치도 어긋나요.
old = FakeIconRole(OLD_PLAT1, icon="있음")
guild = FakeIconGuild([old])
got = asyncio.run(tier_roles.get_or_create_tier_role(guild, "플래티넘 1", icon_bytes=b"PNGDATA"))
check("역할을 새로 만들지 않았다", guild.created == [], str(guild.created))
check("옛 역할을 그대로 돌려준다", got is old)
check("이름을 새 형식으로 바꿨다", old.renamed == [PLAT1], str(old.renamed))
check("이름이 실제로 바뀌어 있다", old.name == PLAT1, old.name)

# 개명 + 아이콘 보충이 한 번에 일어나는 경우
old2 = FakeIconRole(OLD_GOLD1, icon=None)
guild = FakeIconGuild([old2])
asyncio.run(tier_roles.get_or_create_tier_role(guild, "골드 1", icon_bytes=b"PNGDATA"))
check("개명과 아이콘을 같이 처리한다",
      old2.renamed == [GOLD1] and old2.edited == [b"PNGDATA"],
      f"renamed={old2.renamed} edited={old2.edited}")

# ⭐ 옛 이름 역할을 달고 있던 사람을 동기화하면, 떼었다 다시 다는 헛짓을 하면 안 돼요.
tier_roles.get_or_create_tier_role = fake_get_or_create


async def rename_in_place(guild, tier_name, icon_bytes=None):
    """실제 동작을 흉내내요 — 멤버가 **이미 달고 있는 그 역할**의 이름만 바꿔서 돌려줘요."""
    want = tier_roles.display_name_for(tier_name)
    for r in guild.member_roles:
        if r.name == tier_roles.legacy_display_name_for(tier_name):
            r.name = want
            return r
    return FakeRole(want)


tier_roles.get_or_create_tier_role = rename_in_place
m = FakeMember([OLD_PLAT1, "잼민이"])
m.guild.member_roles = m.roles
res = asyncio.run(tier_roles.sync_tier_role(m, "플래티넘 1"))
check("개명뿐이면 status=unchanged", res["status"] == "unchanged", res["status"])
check("뗀 역할이 없다", m.removed == [], str(m.removed))
check("단 역할도 없다", m.added == [], str(m.added))
check("역할은 새 이름으로 남아있다", [r.name for r in m.roles] == [PLAT1, "잼민이"], str(m.roles))

tier_roles.get_or_create_tier_role = fake_get_or_create

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
