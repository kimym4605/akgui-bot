# -*- coding: utf-8 -*-
"""🎨 프로필에서 테마 바꾸기 검사 (2026-11-22). DB·디스코드를 안 건드려요(전부 가짜).

    python scripts/test_theme_switch.py

막으려는 사고:
- 안 산 테마가 목록에 뜨거나, 드롭다운이 남아 있는 사이 안 가진 테마로 바뀌는 것(공짜 테마)
- 여기서 코인이 빠지는 것(사는 건 상점 몫)
- 승인된 그림이 없는데 '커스텀'이 떠서 고르면 기본 배경이 나오는 것
- 카드 제자리 교체가 실패했을 때 아무것도 안 보이는 것
"""
import asyncio
import os
import sys
import types

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")     # 접속하지 않아요

import discord  # noqa: E402

from cogs import attendance as att  # noqa: E402
from utils import coin_wallet, cosmetic_store, custom_theme_store, profile_card, profile_service  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


STATE = {"themes": ["기본", "벚꽃", "우사기", "커스텀", "옛날에뺀테마"], "theme": "벚꽃"}
HAS_ART = {"v": False}
selected, spent = [], []


async def _get(_uid):
    return {"themes": list(STATE["themes"]), "theme": STATE["theme"]}


async def _select(_uid, key):
    selected.append(key)
    STATE["theme"] = key


async def _status(_uid):
    return {"has_image": HAS_ART["v"], "pending": False, "pending_paid": 0}


async def _spend(*a, **k):
    spent.append(a)
    return True


async def _collect(_user):
    return {"theme": STATE["theme"]}


async def _avatar(_user):
    return None


RENDER = {"png": b"\x89PNG fake"}


async def _render(_data, _avatar):
    return RENDER["png"]


cosmetic_store.get, cosmetic_store.select_theme = _get, _select
custom_theme_store.status = _status
coin_wallet.spend = _spend
profile_service.collect, profile_service.avatar_for = _collect, _avatar
profile_card.render_card = _render


class _HTTP:
    status, reason = 403, "Forbidden"


class FakeMsg:
    def __init__(self, fail=False):
        self.edits, self.fail = [], fail

    async def edit(self, **kw):
        self.edits.append(kw)
        if self.fail:
            raise discord.HTTPException(_HTTP(), "일부러")


class FakeInter:
    def __init__(self):
        self.user = types.SimpleNamespace(id=7, display_name="t")
        self.sent, self.edits = [], []
        self.response = types.SimpleNamespace(defer=self._defer)
        self.followup = types.SimpleNamespace(send=self._send)

    async def _defer(self, **_k):
        pass

    async def _send(self, content=None, **kw):
        kw["content"] = content
        self.sent.append(kw)

    async def edit_original_response(self, **kw):
        self.edits.append(kw)


print("[1] 목록 = 가진 것만")
choices, sel = asyncio.run(att.owned_theme_choices(7))
keys = [k for k, *_ in choices]
check("가진 테마 중 지금 있는 것만 (뺀 테마·승인 안 된 커스텀은 빠진다)", keys == ["기본", "벚꽃", "우사기"], str(keys))
check("지금 테마를 알려준다", sel == "벚꽃")
HAS_ART["v"] = True
keys = [k for k, *_ in asyncio.run(att.owned_theme_choices(7))[0]]
check("승인된 그림이 있으면 커스텀도 뜬다", "커스텀" in keys, str(keys))
HAS_ART["v"] = False
check("자세히 보기 메뉴에 🎨 테마 바꾸기가 있다", "theme" in att.ProfileMoreSelect.OPTIONS
      and len(att.ProfileMoreSelect.OPTIONS) <= 25)

print("[2] 메뉴 띄우기")
it = FakeInter()
asyncio.run(att.send_theme_switcher(it, card_message=None))
s = it.sent[0]
check("나만 보이는 메뉴 + 가진 테마 수", s["ephemeral"] is True and isinstance(s["view"], att.ThemeSwitchView)
      and "3개" in s["content"])
opts = s["view"].children[0].options
check("지금 테마가 골라진 채로 뜬다", [o.value for o in opts if o.default] == ["벚꽃"])
saved = STATE["themes"]
STATE["themes"] = ["기본"]
it = FakeInter()
asyncio.run(att.send_theme_switcher(it, card_message=None))
check("기본만 있으면 상점 안내만 (메뉴 없음)", "view" not in it.sent[0] and "악귀상점" in it.sent[0]["content"])
STATE["themes"] = saved


def pick(key, card):
    sel_ = att.ThemeSwitchSelect(7, choices, "벚꽃", card)
    sel_._values = [key]                     # discord.py가 고른 값을 담는 자리
    sel_.__dict__["_values"] = [key]
    type(sel_).values = property(lambda self: self._values)
    it_ = FakeInter()
    asyncio.run(sel_.callback(it_))
    return it_


print("[3] 고르기")
card = FakeMsg()
it = pick("우사기", card)
check("고르면 그 테마로 바뀐다", selected[-1:] == ["우사기"] and STATE["theme"] == "우사기")
check("🚨 코인은 한 푼도 안 빠진다", spent == [])
check("카드를 그 자리에서 새 그림으로 바꾼다 (메뉴 유지)", len(card.edits) == 1
      and card.edits[0]["attachments"][0].filename == "agwi_profile_7.png" and card.edits[0]["view"] is not None)
check("나만 보이는 메시지는 완료 안내로", "우사기" in it.edits[-1]["content"] and it.edits[-1]["view"] is None)

n = len(selected)
it = pick("용암", FakeMsg())
check("🚨 안 가진 테마를 골라도(드롭다운이 낡았을 때) 안 바뀐다", len(selected) == n
      and "가지고 있지 않아요" in it.edits[-1]["content"])

card = FakeMsg(fail=True)
it = pick("벚꽃", card)
check("카드 교체가 실패하면 새 카드를 나만 보이게 보여준다", len(card.edits) == 1
      and it.edits[-1]["attachments"][0].filename == "agwi_profile_7.png")

RENDER["png"] = None
it = pick("우사기", FakeMsg())
check("카드를 못 그려도 테마는 바뀌고 안내는 나간다", STATE["theme"] == "우사기" and "/프로필" in it.edits[-1]["content"])

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
