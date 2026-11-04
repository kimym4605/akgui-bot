# -*- coding: utf-8 -*-
"""포지션 역할(타격대·척후대·전략가·감시자)의 개명·아이콘 처리를 확인해요. 디스코드 없이 돌아가요.

2026-11-03에 티어 역할과 **똑같은 작업**을 포지션 역할에도 했어요. 진짜 포지션 아이콘을
붙이면서 이름에서 이모지를 뺐어요(`⚔️ 타격대` -> `타격대`).

🚨 **같은 함정이 두 번째예요.** 옛 이름을 못 알아보면 봇이 같은 포지션 역할을 **하나 더
만들어요.** 멤버는 옛 쪽에 달려 있고 봇은 새 쪽을 보니, `/전적`을 돌릴 때마다 역할이
왔다 갔다 하고 서열도 어긋나요. 그래서 여기서 지키는 건:

  1) 역할 이름은 이모지 없는 순수 이름이고, 옛 이름은 따로 구할 수 있다
  2) 판별 집합에 **옛 이름도 들어 있다** (안 그러면 중복 정리가 안 돼요)
  3) ⭐ 옛 이름 역할이 있으면 **새로 만들지 말고 개명**한다
  4) 아이콘이 비어 있을 때만 채우고, 있으면 쓸데없이 PATCH 안 한다
  5) ⭐ 개명뿐이면 역할을 뗐다 다시 달지 않는다 (status=unchanged)
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)

import discord  # noqa: E402

from utils import position_roles  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


class FakeRole:
    def __init__(self, name, icon=None):
        self.name = name
        self.icon = icon
        self.edited = []
        self.renamed = []

    async def edit(self, *, display_icon=None, name=None, reason=None):
        if display_icon is not None:
            self.edited.append(display_icon)
            self.icon = "있음"
        if name is not None:
            self.renamed.append(name)
            self.name = name

    def __repr__(self):
        return f"<{self.name}>"

    def __eq__(self, other):
        return isinstance(other, FakeRole) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


class FakeGuild:
    # 🚨 `name`이 없으면 역할 생성 경로에서 AttributeError로 터져서, FAIL이 안 찍혀요.
    name = "테스트 서버"

    def __init__(self, roles):
        self.roles = roles
        self.created = []

    async def create_role(self, **kwargs):
        self.created.append(kwargs)
        return FakeRole(kwargs["name"], icon="있음" if kwargs.get("display_icon") else None)


class FakeMember(discord.Member):
    roles = ()
    guild_permissions = None

    def __init__(self, role_objs, guild):
        self.roles = list(role_objs)
        self.guild = guild
        self.removed = []
        self.added = []

    async def remove_roles(self, *roles, reason=None):
        self.removed.extend(r.name for r in roles)
        self.roles = [r for r in self.roles if r not in roles]

    async def add_roles(self, *roles, reason=None):
        self.added.extend(r.name for r in roles)
        self.roles = list(self.roles) + list(roles)


DUEL, OLD_DUEL = "타격대", "⚔️ 타격대"
INIT, OLD_INIT = "척후대", "🏹 척후대"

print("1) 역할 이름은 순수 이름 / 옛 이름과 텍스트 라벨은 따로 있다")
check("display_name_for", position_roles.display_name_for("타격대") == DUEL,
      position_roles.display_name_for("타격대"))
check("legacy_display_name_for", position_roles.legacy_display_name_for("타격대") == OLD_DUEL,
      position_roles.legacy_display_name_for("타격대"))
check("text_label_for(글자 출력용)", position_roles.text_label_for("타격대") == OLD_DUEL,
      position_roles.text_label_for("타격대"))

print("2) 판별 집합에 옛 이름도 들어 있다")
check("새 이름 4개가 있다", {"타격대", "척후대", "전략가", "감시자"} <= position_roles.POSITION_OPTION_SET)
check("옛 이름 4개도 있다",
      {OLD_DUEL, OLD_INIT, "🌀 전략가", "🛡️ 감시자"} <= position_roles.POSITION_OPTION_SET)
check("총 8개", len(position_roles.POSITION_OPTION_SET) == 8,
      str(sorted(position_roles.POSITION_OPTION_SET)))

print("3) ⭐ 옛 이름 역할은 새로 만들지 말고 개명한다")
old = FakeRole(OLD_DUEL)
guild = FakeGuild([old])
got = asyncio.run(position_roles.get_or_create_position_role(guild, "타격대", icon_bytes=b"PNG"))
check("역할을 새로 만들지 않았다", guild.created == [], str(guild.created))
check("옛 역할을 그대로 돌려준다", got is old)
check("이름을 바꿨다", old.name == DUEL, old.name)
check("아이콘도 같이 붙였다", old.edited == [b"PNG"], str(old.edited))

print("4) 아이콘이 이미 있으면 쓸데없이 PATCH 안 한다")
filled = FakeRole(DUEL, icon="있음")
guild = FakeGuild([filled])
asyncio.run(position_roles.get_or_create_position_role(guild, "타격대", icon_bytes=b"PNG"))
check("PATCH 안 함", filled.edited == [], str(filled.edited))

noicon = FakeRole(DUEL)
guild = FakeGuild([noicon])
asyncio.run(position_roles.get_or_create_position_role(guild, "타격대", icon_bytes=None))
check("줄 아이콘이 없으면 PATCH 안 함", noicon.edited == [], str(noicon.edited))

print("5) ⭐ 개명뿐이면 뗐다 다시 달지 않는다")
mine = FakeRole(OLD_DUEL)
guild = FakeGuild([mine])
m = FakeMember([mine, FakeRole("잼민이")], guild)
res = asyncio.run(position_roles.sync_position_role(m, "타격대"))
check("status=unchanged", res["status"] == "unchanged", res["status"])
check("뗀 역할 없음", m.removed == [], str(m.removed))
check("단 역할 없음", m.added == [], str(m.added))
check("새 이름으로 남아있다", [r.name for r in m.roles] == [DUEL, "잼민이"], str(m.roles))

print("   포지션이 진짜 바뀌면 옛 것을 뗀다")
duel = FakeRole(DUEL)
guild = FakeGuild([duel])
m = FakeMember([duel], guild)
res = asyncio.run(position_roles.sync_position_role(m, "척후대"))
check("status=updated", res["status"] == "updated", res["status"])
check("타격대를 뗐다", m.removed == [DUEL], str(m.removed))
check("척후대를 달았다", m.added == [INIT], str(m.added))

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
