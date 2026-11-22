# -*- coding: utf-8 -*-
"""🎬 카드 뽑기 연출 검사 (2026-11-23). DB·디스코드 없이 돌아가요.

    python scripts/test_card_anim.py

막으려는 사고:
- 연출 중 임베드에 결과(등급·이름·등급 색)가 먼저 보이는 것 → 뒤집기 전에 스포일러
- 연출이 끝나도 GIF가 남아 화면에 들어올 때마다 다시 뒤집히는 것
- 레전드 홍보가 카드가 뒤집히기 **전에** 올라가는 것
- 연출을 못 보내거나 결과로 못 바꿨을 때 **결과가 아예 안 보이는 것** (코인은 이미 나갔어요)
- GIF 마지막 장이 결과 그림과 어긋나는 것, 무한 반복, 10ms 단위가 아닌 프레임 시간
- 10연 GIF가 너무 커서 업로드가 실패하는 것
"""
import asyncio
import io
import os
import random
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")     # 접속하지 않아요

import discord  # noqa: E402
from PIL import Image, ImageChops, ImageStat  # noqa: E402

import cogs.card_gacha as gacha  # noqa: E402
from utils import card_anim, card_render, card_store  # noqa: E402
from utils.card_data import CARDS  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


def card(g, i=0, new=False):
    d = CARDS[g][i]
    return {"key": d["key"], "name": d["name"], "grade": g, "is_new": new, "pity": False}


def gif_info(data):
    im = Image.open(io.BytesIO(data))
    durs = []
    for k in range(im.n_frames):
        im.seek(k)
        durs.append(im.info.get("duration", 0))
    return im, durs


# ==================================================================
print("[1] GIF 자체")
one = [card("일반", 0), card("레전드", 0, True), card("레어", 1)]
png = card_render._render(one)
gif, sec = card_anim.render_pull_anim(one, png)
im, durs = gif_info(gif)
check("한 번만 재생 (loop 없음)", "loop" not in Image.open(io.BytesIO(gif)).info)
check("프레임 시간이 10ms 단위", all(d % 10 == 0 for d in durs), str(set(durs)))
check("마지막 장을 오래 붙든다", durs[-1] == card_anim.HOLD_MS)
check("연출 초 = 마지막 장 빼고 합", abs(sec - sum(durs[:-1]) / 1000) < 0.02, f"{sec} vs {sum(durs[:-1])}")
check("폭이 임베드용으로 줄었다", im.width <= card_anim.GIF_W)
im.seek(im.n_frames - 1)
last = im.convert("RGB")
still = Image.open(io.BytesIO(png)).convert("RGB").resize(last.size, Image.LANCZOS)
diff = sum(ImageStat.Stat(ImageChops.difference(last, still)).mean) / 3
check("마지막 장 = 결과 그림 (팔레트 오차만)", diff < 6, f"평균 차이 {diff:.1f}")
im.seek(0)
first = im.convert("RGB")
check("첫 장에는 카드 앞면이 없다 (엎어져서 올라오는 중)",
      sum(ImageStat.Stat(ImageChops.difference(first, still)).mean) / 3 > 20)

print("[2] 뒤집는 순서 — 제일 좋은 카드가 마지막")
cells, cols, use_thumb = card_anim._cells(3)
rise, rise_end, charge_end, flip_at, flip_len, total = card_anim._timeline(one, cols, not use_thumb)
check("1뽑기: 일반 → 레어 → 레전드 순", flip_at[0] < flip_at[2] < flip_at[1], str(flip_at))
check("전부 연출이 끝나기 전에 뒤집힌다", max(a + b for a, b in zip(flip_at, flip_len)) <= total)
many = [card("일반", i % 20) for i in range(30)]
many[4], many[20], many[9] = card("레전드", 1, True), card("에픽", 2), card("에픽", 3)
cells, cols, use_thumb = card_anim._cells(30)
_, _, _, fa, fl, total = card_anim._timeline(many, cols, not use_thumb)
low_done = max(fa[i] + fl[i] for i in range(30) if many[i]["grade"] == "일반")
check("10연: 일반이 다 넘어간 뒤 에픽", low_done <= min(fa[9], fa[20]))
check("10연: 에픽 둘은 한꺼번에", fa[9] == fa[20])
check("10연: 레전드가 제일 마지막", fa[4] > fa[9])

print("[3] 크기 — 최악의 10연도 올릴 수 있어야")
rnd = random.Random(5)
worst = [card(rnd.choice(["에픽", "레전드"]), rnd.randrange(10), True) for _ in range(30)]
worst_png = card_render._render(worst)
gif_w, sec_w = card_anim.render_pull_anim(worst, worst_png)
too_big = len(gif_w) > card_anim.MAX_BYTES
got = asyncio.run(card_anim.pull_anim(worst, worst_png))
check("너무 큰 연출은 건너뛴다 (업로드 실패 대신 결과 그림)", (got is None) == too_big,
      f"{len(gif_w) / 1e6:.1f}MB")
check("그래도 연출이 너무 길지 않다 (30초 미만)", sec_w < 30, f"{sec_w:.1f}s")
typical = [card("일반", i % 20) for i in range(30)]
typical[7], typical[22] = card("에픽", 1), card("레전드", 3)
gif_t, _ = card_anim.render_pull_anim(typical, card_render._render(typical))
check("흔한 10연(에픽 1·레전드 1)은 3MB 미만", len(gif_t) < 3 * 1024 * 1024, f"{len(gif_t) / 1e6:.1f}MB")
for n in (1, 2, 4, 6, 15):
    dr = [card(rnd.choice(list(card_anim.RANK)), 0) for _ in range(n)]
    try:
        card_anim.render_pull_anim(dr, card_render._render(dr))
        ok = True
    except Exception as e:    # noqa: BLE001
        ok, err = False, repr(e)
    check(f"{n}장도 그려진다", ok)
check("그림이 없으면 연출도 안 한다 (None)", asyncio.run(card_anim.pull_anim(one, None)) is None)


# ==================================================================
print("[4] 뽑기 흐름 — 보내고 바꾸는 순서")
events = []


class FakeMsg:
    def __init__(self, fail_edit=False):
        self.fail_edit = fail_edit
        self.edits = []

    async def edit(self, **kw):
        events.append("edit")
        self.edits.append(kw)
        if self.fail_edit:
            raise discord.HTTPException(type("R", (), {"status": 500, "reason": "x"})(), "일부러")


class FakeFollowup:
    def __init__(self, msg, fail_first=False):
        self.sent, self.msg, self.fail_first = [], msg, fail_first

    async def send(self, content=None, **kw):
        kw["content"] = content
        self.sent.append(kw)
        events.append("send")
        if self.fail_first and len(self.sent) == 1:
            raise discord.HTTPException(type("R", (), {"status": 413, "reason": "big"})(), "너무 큼")
        return self.msg


class FakeWallet:
    async def spend(self, *a, **k):
        return True

    async def add(self, *a, **k):
        return 0

    async def get_balance(self, *a):
        return 77


DRAWN = [card("레어", 0), card("레전드", 2, True), card("일반", 1)]


async def _pull(uid, n=3):
    return [dict(d) for d in DRAWN]


async def _get(uid):
    return {"counts": {d["key"]: 1 for d in DRAWN}, "draws": 3, "since_legend": 0}


async def _render(drawn):
    return b"\x89PNG still"


async def _anim(drawn, png):
    return (b"GIF89a fake", 0.0)


async def _announce(*a, **k):
    events.append("announce")


gacha.coin_wallet = FakeWallet()
gacha.card_store.pull, gacha.card_store.get_collection = _pull, _get
gacha.card_render.render_pull = _render
gacha.card_anim.pull_anim = _anim
gacha.announce_legend = _announce
gacha.PULL_ANIM_PAD = 0


def inter_with(msg, fail_first=False):
    it = type("I", (), {})()
    it.user = type("U", (), {"id": 4242})()
    it.followup = FakeFollowup(msg, fail_first)
    it.guild = None
    return it


events.clear()
msg = FakeMsg()
it = inter_with(msg)
asyncio.run(gacha.do_pull(it))
first = it.followup.sent[0]
roll = first["embed"]
text = (roll.title or "") + (roll.description or "")
check("연출 GIF를 먼저 보낸다", first["file"].filename == gacha.PULL_ANIM_FILE and first.get("wait") is True)
check("🚨 연출 중 임베드에 카드 이름·등급이 없다", all(d["name"] not in text for d in DRAWN)
      and "레전드" not in text and "🟡" not in text, text)
check("🚨 연출 중 임베드 색이 등급 색이 아니다", roll.color.value not in card_store.GRADE_COLOR.values())
check("연출에도 '한 번 더' 버튼이 달려 있다", first["view"] is not None)
check("끝나면 결과 임베드 + PNG로 바꾼다 (GIF를 남기지 않는다)",
      len(msg.edits) == 1 and msg.edits[0]["attachments"][0].filename.endswith(".png")
      and "레전드" in (msg.edits[0]["embed"].description or ""))
check("🚨 레전드 홍보는 바꿔 끼운 **뒤에**", events == ["send", "edit", "announce"], str(events))

events.clear()
msg = FakeMsg()
it = inter_with(msg, fail_first=True)
asyncio.run(gacha.do_pull(it))
check("연출을 못 보내면 예전처럼 결과 그림을 보낸다",
      len(it.followup.sent) == 2 and it.followup.sent[1]["file"].filename.endswith(".png")
      and not msg.edits)

events.clear()
msg = FakeMsg(fail_edit=True)
it = inter_with(msg)
asyncio.run(gacha.do_pull(it))
check("결과로 못 바꾸면 결과 글을 새로 보낸다", len(it.followup.sent) == 2
      and "레전드" in (it.followup.sent[1]["embed"].description or ""))


async def _no_anim(drawn, png):
    return None

gacha.card_anim.pull_anim = _no_anim
events.clear()
msg = FakeMsg()
it = inter_with(msg)
asyncio.run(gacha.do_pull(it))
check("연출을 못 그리면 바로 결과 그림 (예전 그대로)", len(it.followup.sent) == 1
      and it.followup.sent[0]["file"].filename.endswith(".png") and "wait" not in it.followup.sent[0])

# ==================================================================
print("[5] ⚒️ 합성 연출")
import importlib  # noqa: E402
real_anim = importlib.reload(card_anim)      # 위에서 가짜로 바꿔 끼운 pull_anim을 되돌려요(같은 모듈 객체예요)
fz = [card("에픽", 3, True)]
fz_png = card_render._render(fz)
fgif, fsec = real_anim.render_pull_anim(fz, fz_png, fuse=True)
fim, fdurs = gif_info(fgif)
fim.seek(fim.n_frames - 1)
flast = fim.convert("RGB")
fstill = Image.open(io.BytesIO(fz_png)).convert("RGB").resize(flast.size)
check("합성 GIF도 마지막 장 = 결과 그림",
      sum(ImageStat.Stat(ImageChops.difference(flast, fstill)).mean) / 3 < 6)
check("합성 GIF도 한 번만 재생", "loop" not in Image.open(io.BytesIO(fgif)).info)
pgif, _ = real_anim.render_pull_anim(fz, fz_png)
check("합성 첫 장면은 뽑기와 다르다 (재료 3장이 모여요)", pgif != fgif)
back = real_anim._card_back(100, 150)
check("🚨 카드 뒷면에 비치는 구멍이 없다 (무늬가 투명 구멍이면 뒤 빛이 줄무늬로 비쳐요)",
      back.getchannel("A").crop((10, 10, 90, 140)).getextrema() == (255, 255))

FUSE_RESULTS = {"v": []}


async def _fuse(uid, times):
    return [dict(d) for d in FUSE_RESULTS["v"]], {"n01": 3 * max(1, len(FUSE_RESULTS["v"]))}


async def _get2(uid):
    return {"counts": {"n01": 2}, "draws": 3, "since_legend": 0}


anim_calls = []


async def _anim2(drawn, png, *, fuse=False):
    anim_calls.append((len(drawn), fuse))
    return (b"GIF89a fake", 0.0)

rendered = []


async def _render2(drawn):
    rendered.append(len(drawn))
    return b"\x89PNG still"

gacha.card_store.fuse, gacha.card_store.get_collection = _fuse, _get2
gacha.card_render.render_pull = _render2
gacha.card_anim.pull_anim = _anim2

events.clear()
FUSE_RESULTS["v"] = [card("일반", 4)]            # 또 중복인 일반 1장
msg = FakeMsg()
it = inter_with(msg)
asyncio.run(gacha.do_fuse(it, times=1))
s0 = it.followup.sent[0]
check("1회 합성(중복 일반)도 그림·연출이 나온다", anim_calls[-1:] == [(1, True)]
      and s0["file"].filename == gacha.PULL_ANIM_FILE)
check("합성 연출 제목에 결과가 없다", "일반" not in (s0["embed"].title or "") and card("일반", 4)["name"]
      not in (s0["embed"].title or ""))
check("합성은 버튼 없이 보낸다 (view 인자 없음)", "view" not in s0)
check("끝나면 합성 결과 + PNG로 바꾼다", len(msg.edits) == 1
      and msg.edits[0]["attachments"][0].filename.startswith("fuse_")
      and (msg.edits[0]["embed"].title or "").startswith("⚒️ 합성"))
check("합성 결과는 기본으로 나만 보인다", s0["ephemeral"] is True)

anim_calls.clear()
rendered.clear()
FUSE_RESULTS["v"] = [card("일반", i % 5) for i in range(12)]   # '전부' 합성, 전부 또 중복
it = inter_with(FakeMsg())
asyncio.run(gacha.do_fuse(it, times=0))
check("많은 합성인데 성과가 없으면 그림·연출 없이 글만 (예전 그대로)",
      not anim_calls and not rendered and it.followup.sent[0].get("file") is None)

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
