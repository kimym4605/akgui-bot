# -*- coding: utf-8 -*-
"""🔊 방 패널 **실동작** 검증 (2026-10-31).

지금까지는 구조만 봤다. 여기서는 **콜백을 실제로 await**해서 engine이 올바른 메서드를
올바른 인자로 받는지 실증하고, 게시된 메시지의 custom_id가 봇이 아는 것과 일치하는지
대조한다.

🚨 프로덕션에 아무것도 만들지 않는다 — engine을 **스파이**로 바꿔 호출만 기록한다.
"""
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                 # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

import discord                                  # noqa: E402
from cogs.room import ROOM_KINDS                # noqa: E402
from utils import room_panel                    # noqa: E402

fails = []


def check(cond, label, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


# ============================================================ 스파이
class SpyEngine:
    """engine 대신 호출만 기록한다. 🚨 실제 engine처럼 **자기가 defer한다**(그 규약을
    여기서도 지켜야 패널이 미리 defer하는 실수를 잡아낼 수 있다)."""

    def __init__(self):
        self.calls = []

    async def _rec(self, name, interaction, *args):
        await interaction.response.defer(ephemeral=True)
        self.calls.append((name, args))

    async def create_room(self, interaction, kind, 인원수, 입장시뮤트=False):
        await self._rec("create_room", interaction, kind, 인원수, 입장시뮤트)

    async def invite(self, interaction, 대상):
        await self._rec("invite", interaction, getattr(대상, "id", 대상))

    async def request_join(self, interaction, 방장):
        await self._rec("request_join", interaction, getattr(방장, "id", 방장))

    async def transfer_owner(self, interaction, 대상):
        await self._rec("transfer_owner", interaction, getattr(대상, "id", 대상))

    async def close_room(self, interaction):
        await self._rec("close_room", interaction)


class FakeResponse:
    def __init__(self, owner):
        self.owner = owner

    async def defer(self, ephemeral=False):
        if self.owner.responded:
            raise RuntimeError("InteractionResponded: 이미 응답했는데 또 defer했다")
        self.owner.responded = True
        self.owner.log.append(("defer", ephemeral))

    async def send_message(self, content=None, *, view=None, ephemeral=False, **kw):
        if self.owner.responded:
            raise RuntimeError("InteractionResponded: 이미 응답했는데 또 send_message했다")
        self.owner.responded = True
        self.owner.log.append(("send_message", ephemeral))
        self.owner.sent_view = view
        self.owner.sent_content = content

    async def edit_message(self, **kw):
        self.owner.log.append(("edit_message", None))

    async def send_modal(self, modal):
        self.owner.log.append(("send_modal", None))


class FakeUser:
    def __init__(self, uid=1):
        self.id = uid
        self.display_name = "테스터"


class FakeInteraction:
    """우리가 쓰는 만큼만 흉내낸다."""

    def __init__(self):
        self.responded = False
        self.log = []
        self.sent_view = None
        self.sent_content = None
        self.response = FakeResponse(self)
        self.user = FakeUser()
        self.guild = None
        self.channel_id = 123

    async def followup_send(self, *a, **k):      # pragma: no cover
        pass


async def main():
    print("=== [A] 버튼을 누르면 engine이 제대로 불리나 (콜백을 실제로 실행) ===")
    for key, cfg in ROOM_KINDS.items():
        spy = SpyEngine()
        view = room_panel.RoomPanelView(spy, ROOM_KINDS, [key])
        btn = next(i for i in view.children
                   if str(getattr(i, "custom_id", "")) == f"akgui:room:new:{key}")
        itx = FakeInteraction()
        # `item.view`는 read-only다 — `add_item`이 이미 연결해 준다(RoomPanelView.__init__).
        check(btn.view is view, f"  └ 버튼이 뷰에 연결돼 있다 (engine에 닿는 경로)")
        await btn.callback(itx)
        want = ("create_room", (key, None, False))
        check(spy.calls == [want],
              f"{cfg['emoji']} {cfg['label']} 버튼 → create_room({key}, None, False)",
              f"{spy.calls}")
        # 🚨 패널이 먼저 defer했으면 위 SpyEngine.defer가 터졌을 것이다
        check(itx.log == [("defer", True)],
              f"  └ defer가 **engine 쪽에서 한 번만** 일어났다", str(itx.log))

    print("\n=== [B] 🚪 닫기 버튼 ===")
    spy = SpyEngine()
    view = room_panel.RoomPanelView(spy, ROOM_KINDS, ["rank"])
    close = next(i for i in view.children
                 if str(getattr(i, "custom_id", "")) == "akgui:room:close")
    itx = FakeInteraction()
    await close.callback(itx)
    check(spy.calls == [("close_room", ())], "close_room이 불린다", str(spy.calls))

    print("\n=== [C] 👥 초대 → 사람 고르기 → engine ===")
    for cid, action, engine_name in (
        ("akgui:room:invite", "invite", "invite"),
        ("akgui:room:request", "request", "request_join"),
        ("akgui:room:transfer", "transfer", "transfer_owner"),
    ):
        spy = SpyEngine()
        view = room_panel.RoomPanelView(spy, ROOM_KINDS, ["rank"])
        btn = next(i for i in view.children if str(getattr(i, "custom_id", "")) == cid)
        itx = FakeInteraction()
        await btn.callback(itx)
        check(itx.log == [("send_message", True)],
              f"{cid}: 누르면 **본인에게만** 고르는 화면이 뜬다", str(itx.log))
        picker = itx.sent_view
        check(isinstance(picker, room_panel._PickMemberView),
              "  └ 그게 사람 고르는 뷰다", str(type(picker)))
        # 사람을 골랐다고 가정하고 그 흐름을 끝까지 돌린다
        sel = next(i for i in picker.children if isinstance(i, discord.ui.UserSelect))
        picked = FakeUser(777)
        sel._selected_values = [picked]           # discord.py 내부 저장소
        try:
            vals = sel.values
        except Exception:
            vals = None
        if not vals:
            # 내부 구조가 다르면 직접 꽂는다 (버전 차이 방어)
            class _S:
                values = [picked]
            picker._select = _S()
        itx2 = FakeInteraction()
        await picker._picked(itx2)
        check(spy.calls == [(engine_name, (777,))],
              f"  └ 고르면 engine.{engine_name}(그 사람)이 불린다", str(spy.calls))
        check(itx2.log == [("defer", True)],
              "  └ 거기서도 defer는 engine 쪽 한 번만", str(itx2.log))

    print("\n=== [D] ⚙️ 상세 설정 흐름 ===")
    spy = SpyEngine()
    view = room_panel.RoomPanelView(spy, ROOM_KINDS, ["practice"])
    opt_btn = next(i for i in view.children
                   if str(getattr(i, "custom_id", "")) == "akgui:room:options")
    itx = FakeInteraction()
    await opt_btn.callback(itx)
    ov = itx.sent_view
    check(isinstance(ov, room_panel._OptionsView), "옵션 뷰가 뜬다", str(type(ov)))
    check(ov.kind == "practice", "그 채널 종류가 미리 들어가 있다", str(ov.kind))
    # 정원을 고르고 뮤트를 켜고 만든다
    class _Cap:
        values = ["8"]
    ov._cap_select = _Cap()
    itx_cap = FakeInteraction()
    await ov._pick_cap(itx_cap)
    check(ov.capacity == 8, "정원 8명이 잡힌다", str(ov.capacity))
    mute_btn = next(i for i in ov.children if getattr(i, "emoji", None)
                    and str(i.emoji) == "🔇")
    itx_m = FakeInteraction()
    await mute_btn.callback(itx_m)
    check(ov.mute is True, "🔇 토글이 켜진다", str(ov.mute))
    create_btn = next(i for i in ov.children if getattr(i, "label", "") == "이 설정으로 만들기")
    itx_c = FakeInteraction()
    await create_btn.callback(itx_c)
    check(spy.calls == [("create_room", ("practice", 8, True))],
          "✅ 를 누르면 create_room(practice, 8, True)", str(spy.calls))

    print("\n=== [E] 🚨 종류를 안 고르고 ✅ 를 누르면 engine을 안 부른다 ===")
    spy2 = SpyEngine()
    ov2 = room_panel._OptionsView(spy2, ROOM_KINDS)        # preset 없음
    cb = next(i for i in ov2.children if getattr(i, "label", "") == "이 설정으로 만들기")
    itx_e = FakeInteraction()
    await cb.callback(itx_e)
    check(spy2.calls == [], "engine이 안 불린다 (KeyError 방지)", str(spy2.calls))
    check(itx_e.log == [("send_message", True)], "대신 안내가 뜬다", str(itx_e.log))


asyncio.run(main())

# ============================================================ 게시물 대조
print("\n=== [F] 게시된 버튼이 **봇이 아는 custom_id**와 일치하나 ===")
TOKEN_FILE = os.path.join(os.path.dirname(BOT_DIR), "운영봇_토큰_백업.env")
if not os.path.exists(TOKEN_FILE):
    print("  (운영 토큰 파일이 없어서 게시물 대조는 건너뜁니다 "
          "— [A]~[E]만으로도 배선은 검증됩니다)")
    print("=" * 52)
    if fails:
        print(f"❌ 실패 {len(fails)}건:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("✅ 실동작 검증(로컬) 통과")
    sys.exit(0)

conf = {}
with open(TOKEN_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
HDR = {"Authorization": f"Bot {conf['DISCORD_TOKEN']}",
       "User-Agent": "DiscordBot (https://example.com, 1.0)"}


def get(path):
    req = urllib.request.Request("https://discord.com/api/v10" + path, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"__error__": e.code}


# 🚨 봇이 `cog_load`에서 등록하는 건 **전체 종류 인스턴스**다. 게시된 버튼이 이 집합에
#    하나라도 안 들어가면 그 버튼은 눌러도 **아무 반응이 없다**(에러도 안 난다).
known = {str(i.custom_id) for i in room_panel.RoomPanelView(None, ROOM_KINDS).children}
print(f"  봇이 아는 custom_id {len(known)}개: {sorted(known)}")

chans = get(f"/guilds/{conf['GUILD_ID']}/channels")
PLAN = [("랭크-파티구인", "rank"), ("폐관수련-모집", "practice"),
        ("내전모집", "scrim"), ("프리미어-모집", "premier")]
for cname, kind in PLAN:
    ch = next((c for c in chans if cname in c["name"] and c["type"] == 0), None)
    if ch is None:
        check(False, f"#{cname} 채널")
        continue
    # 🚨🚨 **최근 메시지로 찾으면 안 돼요.** `#📣내전모집`의 패널이 하루 만에
    #    **47번째**로 밀려서 `limit=30`에 안 걸렸고, **거짓 실패**가 났어요
    #    (2026-11-01). 활발한 채널에선 패널이 대화에 묻혀요.
    #    → **핀 목록**에서 먼저 찾아요. 그게 패널이 있어야 할 자리이기도 해요
    #      (그래서 패널은 전부 핀해뒀어요).
    # 🚨 제목("만들기")이 아니라 **`akgui:room:` 버튼**으로 식별해요 —
    #    제목으로 찾으면 `/팀짜기` 결과 메시지가 걸려요.
    ids = []
    pool = (get(f"/channels/{ch['id']}/pins") or [])
    if not isinstance(pool, list):
        pool = []
    pool = pool + (get(f"/channels/{ch['id']}/messages?limit=100") or [])
    for m in pool:
        if not isinstance(m, dict) or not m.get("author", {}).get("bot"):
            continue
        cand = [b.get("custom_id") for row in m.get("components", [])
                for b in row.get("components", [])]
        if any(str(c).startswith("akgui:room:") for c in cand):
            ids = cand
            break
    unknown = [i for i in ids if i not in known]
    check(bool(ids) and not unknown,
          f"#{ch['name']}: 게시된 {len(ids)}개가 전부 봇이 아는 것",
          f"모르는 것: {unknown}")
    check(f"akgui:room:new:{kind}" in ids,
          f"  └ 그 채널 종류 버튼({kind})이 박혀 있다", str(ids))

print("\n" + "=" * 52)
if fails:
    print(f"❌ 실패 {len(fails)}건:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("✅ 실동작 검증 전부 통과")
