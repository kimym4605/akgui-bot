"""🧭 /패널 — 종류마다 맞는 cog의 `panel`로 이어지는지, 권한 검사가 살아 있는지 확인해요. 디스코드에는 안 붙어요.

2026-11-26: 전역 명령어 100개 한도 때문에 패널 명령어 7개를 `/패널 종류:` 하나로 합쳤어요.
🚨 합치면서 깨지기 쉬운 것 두 가지를 봐요.
  1. 종류를 골랐는데 엉뚱한 cog로 가거나, cog가 안 실려 조용히 아무 일도 안 일어나는 것
  2. `@restrict_to_staff` 같은 **명령어 전용 검사**가 함수로 바뀌며 사라져 아무나 패널을 올리는 것
"""
import asyncio
import os
import sys
from types import SimpleNamespace

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"
os.environ["PORT"] = "0"

import discord  # noqa: E402
from discord import app_commands  # noqa: E402
from discord.ext import commands  # noqa: E402

failed = []


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        failed.append(name)


class FakeResponse:
    def __init__(self, it):
        self.it = it

    async def send_message(self, content=None, **kw):
        self.it.replies.append(content)

    async def defer(self, **kw):
        self.it.deferred = True

    def is_done(self):
        return self.it.deferred


class FakeIt:
    def __init__(self, uid, owner_id=1, roles=()):
        self.user = SimpleNamespace(id=uid, roles=list(roles), name=f"u{uid}", guild_permissions=discord.Permissions.none())
        self.guild = SimpleNamespace(owner_id=owner_id, roles=[], id=777)
        self.guild_id, self.channel_id, self.channel = 777, 555, None
        self.replies, self.deferred = [], False
        self.response = FakeResponse(self)
        self.followup = SimpleNamespace(send=self._followup)

    async def _followup(self, content=None, **kw):
        self.replies.append(content)


async def main():
    from cogs import panels

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    for name in ["akgui_shop", "fishing", "card_gacha", "room", "balodle", "server_goal", "tactics", "meetup", "panels"]:
        await bot.load_extension(f"cogs.{name}")
    hub = bot.get_cog("Panels")
    names = {c.name for c in bot.tree.get_commands()}

    print("[1] 명령어")
    old = {"상점패널", "낚시패널", "카드패널", "방패널", "발로들패널", "공동목표패널", "정모패널", "작전판패널"}
    check("/패널 하나만 있고 옛 패널 명령어는 없음", "패널" in names and not (old & names), str(sorted(old & names)))
    cmd = bot.tree.get_command("패널")
    params = {p.name: p for p in cmd.parameters}
    check("종류는 꼭 골라야 하고 선택지가 패널 수만큼", params["종류"].required
          and [c.value for c in params["종류"].choices] == list(panels.PANELS), str(params["종류"].choices))
    check("방종류·방종류2는 선택지(오타 방지), 안 골라도 됨", all(params[k].choices and not params[k].required for k in ("방종류", "방종류2")))

    print("[2] 종류 → cog")
    for key, spec in panels.PANELS.items():
        cog = hub.cog_for(spec.module)
        check(f"{spec.label} → {spec.module}.panel", cog is not None and callable(getattr(cog, "panel", None)),
              "cog 없음" if cog is None else "panel 없음")

    print("[3] 실제로 불러 보기 (권한 없는 사람)")
    calls = []
    for key, spec in panels.PANELS.items():
        if key == "meetup":
            continue
        it = FakeIt(uid=20, owner_id=1)
        await hub.panel.callback(hub, it, app_commands.Choice(name=spec.label, value=key))
        text = " ".join(r or "" for r in it.replies)
        calls.append(key)
        check(f"{spec.label}: 소유자가 아니면 거절", "소유자" in text, text[:80])
    it = FakeIt(uid=20, owner_id=1)
    await hub.panel.callback(hub, it, app_commands.Choice(name="정모", value="meetup"))
    check("🎿 정모: 운영진이 아니면 거절 (데코레이터 대신 함수 안에서 막음)", "🔒" in " ".join(r or "" for r in it.replies),
          str(it.replies))

    print("[4] 방 패널은 방종류를 그대로 넘김")
    room = bot.get_cog("Room")
    got = []

    async def spy(interaction, a=None, b=None):
        got.append((a.value if a else None, b.value if b else None))
    room.panel = spy
    first = panels.ROOM_CHOICES[0]
    await hub.panel.callback(hub, FakeIt(1), app_commands.Choice(name="방", value="room"), first, None)
    await hub.panel.callback(hub, FakeIt(1), app_commands.Choice(name="방", value="room"))
    check("방종류를 넘기고, 안 고르면 None", got == [(first.value, None), (None, None)], str(got))

    print("[5] cog가 안 실려 있으면 안내")
    await bot.remove_cog("Balodle")
    it = FakeIt(1)
    await hub.panel.callback(hub, it, app_commands.Choice(name="발로들", value="balodle"))
    check("조용히 끝나지 않고 안내", "쓸 수 없어요" in (it.replies[0] or ""), str(it.replies))


asyncio.run(main())
print("\n" + "=" * 50)
if failed:
    print("❌ 실패:", ", ".join(failed))
    sys.stdout.flush()
    os._exit(1)
print("✅ /패널 테스트 전부 통과")
sys.stdout.flush()
os._exit(0)
