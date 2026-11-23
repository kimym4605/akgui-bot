# -*- coding: utf-8 -*-
"""🐟 물고기 그림·📖 낚시 도감 검사 (2026-11-22). DB를 안 건드려요.

    python scripts/test_fish_art.py

막으려는 사고:
- 새 종을 `fish_data.FISH`에 넣고 **그림을 깜빡하는 것** (낚시는 돌지만 그 종만 그림이 없어요)
- 배경을 안 뺀 그림이 들어가는 것 (디스코드 어두운 화면에 밝은 네모가 떠요)
- 잡은 기록 두 경로(한 판·몰아 던지기) 중 **한쪽만** 도감을 올리는 것
"""
import io
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from PIL import Image  # noqa: E402

from utils import fish_art  # noqa: E402
from utils.fish_data import BY_KEY, FISH, GRADE_ORDER  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


print("[1] 모든 종에 그림이 있다")
missing = [f"{k} {BY_KEY[k][1]}" for k in BY_KEY if fish_art.art_path(k) is None]
check(f"{len(BY_KEY)}종 전부 assets/fish/<key>.webp", not missing, str(missing))
extra = sorted(p.stem for p in fish_art.ART_DIR.glob("*.webp") if p.stem not in BY_KEY)
check("종 목록에 없는 그림이 남아 있지 않다", not extra, str(extra))

print("[2] 그림이 512×512 · 배경 투명")
bad = []
for key in BY_KEY:
    p = fish_art.art_path(key)
    if p is None:
        continue
    im = Image.open(p)
    corners = [im.convert("RGBA").getpixel(xy)[3] for xy in ((0, 0), (511, 0), (0, 511), (511, 511))] \
        if im.size == (512, 512) else [255]
    if im.size != (512, 512) or max(corners) > 0:
        bad.append(f"{key} size={im.size} 모서리알파={corners}")
check("전부 512×512이고 네 모서리가 투명", not bad, str(bad))

print("[3] 도감 이미지")
png = fish_art.render_dex({"f01": 3, "f31": 1})
im = Image.open(io.BytesIO(png))
check("PNG로 그려진다", im.format == "PNG" and im.width > 800, f"{im.format} {im.size}")
check("8MB(디스코드 첨부 한도)보다 한참 작다", len(png) < 2_000_000, f"{len(png)} bytes")
png_all = fish_art.render_dex({k: 1 for k in BY_KEY})
check("전 종을 잡은 도감도 그려진다", len(png_all) > 10_000)
check("한 줄 최대 8칸 (넘으면 그림 폭이 디스코드에서 너무 작아져요)",
      max(len(FISH[g]) for g in GRADE_ORDER) <= 8, str({g: len(FISH[g]) for g in GRADE_ORDER}))

print("[4] 잡은 기록 두 경로 모두 도감을 올린다")
src = open(os.path.join(BOT_DIR, "utils", "fishing_store.py"), encoding="utf-8").read()
check("한 판(`_record_cast_sync`)과 몰아 던지기 둘 다 `dex.<key>`를 $inc", src.count('f"dex.{key}"') >= 2,
      str(src.count('f"dex.{key}"')))

print("[5] 결과 화면이 지난 판 그림을 지운다")
cog = open(os.path.join(BOT_DIR, "cogs", "fishing.py"), encoding="utf-8").read()
check("기다리는 화면(show)이 attachments=[]를 기본으로 넘긴다", 'kw.setdefault("attachments", [])' in cog)
check("놓친 묶음 화면도 attachments=[]", "view=next_view, attachments=[])" in cog)

# ==================================================================
print("[6] 🪣 어항 카드 — 무엇을 그리나")
# ------------------------------------------------------------------
from utils.fish_data import SIZE_BY_KEY  # noqa: E402


def mid(key, t=0.5):
    lo, hi = SIZE_BY_KEY[key]
    return int(lo + (hi - lo) * t)


check("어항 배경 그림이 있다", fish_art.TANK_BG.exists(), str(fish_art.TANK_BG))
if fish_art.TANK_BG.exists():
    check("배경이 카드 크기(1000×630)다 — 다르면 그릴 때마다 늘려서 흐려져요",
          Image.open(fish_art.TANK_BG).size == (fish_art.TANK_W, fish_art.TANK_H))
check("바닥에 사는 종 목록이 전부 실제 종이다",
      all(k in BY_KEY for k in fish_art.TANK_BOTTOM), str(sorted(fish_art.TANK_BOTTOM)))

full = {k: [mid(k, .9), mid(k, .5), mid(k, .2), mid(k, .1), mid(k, .1)] for k in BY_KEY}
plan = fish_art._tank_plan(full)
check("전 종 어항 — 종마다 대표가 정확히 1마리 (한 종도 빠지지 않는다)",
      sorted(e["key"] for e in plan if e["lead"]) == sorted(BY_KEY))
check(f"그리는 수가 상한({fish_art.TANK_MAX_SPRITES}마리) 이하", len(plan) <= fish_art.TANK_MAX_SPRITES,
      str(len(plan)))
many = fish_art._tank_plan({"f02": [20 + i % 15 for i in range(40)]})
check(f"한 종은 {fish_art.TANK_PER_SPECIES}마리까지만 그린다 (붕어 40마리 → {len(many)}마리)",
      len(many) == fish_art.TANK_PER_SPECIES)
lead = next(e for e in many if e["lead"])
check("대표는 그 종에서 제일 큰 놈", lead["size"] == 34, str(lead["size"]))
check("이름표의 ×n은 **진짜 마리 수** (그린 수가 아니다)", lead["count"] == 40, str(lead["count"]))
one_each = {g: fish_art._tank_plan({FISH[g][0]["key"]: [mid(FISH[g][0]["key"])]})[0] for g in GRADE_ORDER}
# ⚠️ 한 마리짜리 어항은 전부 TANK_MAX_SCALE로 커져요 → 배율을 걷어내고 기본 크기로 비교해요.
check("등급이 높을수록 기본 크기가 크다",
      [fish_art.TANK_PX[g] for g in GRADE_ORDER] == sorted(fish_art.TANK_PX.values(), reverse=True))
check("한 마리뿐이면 크게 키운다 (TANK_MAX_SCALE)",
      all(abs(one_each[g]["px"] - fish_art.TANK_PX[g] * fish_art.TANK_MAX_SCALE) <= 2 for g in GRADE_ORDER),
      str({g: one_each[g]["px"] for g in GRADE_ORDER}))
small, big = (fish_art._tank_plan({"f02": [mid("f02", t)], "f31": [mid("f31")]}) for t in (0.0, 1.0))
check("같은 종이면 치수가 클수록 크게 그린다",
      next(e["px"] for e in big if e["key"] == "f02") > next(e["px"] for e in small if e["key"] == "f02"))
check("치수 없는 옛 물고기(None)·없어진 종이 섞여도 죽지 않는다",
      [e["key"] for e in fish_art._tank_plan({"f02": [None, 20], "zzz": [10], "f01": []})] == ["f02", "f02"])
check("빈 어항은 그릴 게 없다", fish_art._tank_plan({}) == [])

# ------------------------------------------------------------------
print("[7] 🪣 어항 카드 — 어디에 그리나")
day = {"f01": [14, 12, 9], "f02": [30, 24, 22, 19], "f03": [17, 14], "f04": [4, 3], "f05": [11, 10, 9],
       "f06": [18], "f07": [22, 16], "f08": [8], "f13": [24], "f17": [26], "f22": [210]}
x0, y0, x1, y1 = fish_art.TANK_WATER
for label, tank in (("하루치 어항", day), ("전 종 어항", full)):
    items = fish_art._tank_layout(tank, seed=7)
    out = [e["key"] for e in items
           if e["pos"][0] < 0 or e["pos"][1] < y0 or e["pos"][0] + e["im"].width > fish_art.TANK_W
           or e["pos"][1] + e["im"].height > fish_art.TANK_H]
    check(f"{label}: 물고기가 전부 카드 안·머리띠 아래에 있다", not out, str(out))
# 🚨 **씨앗 하나로만 보면 운 좋게 통과해요.** 자리는 유저마다(씨앗마다) 달라지니 여러 개로 봐요.
#    2026-11-22: 큰 놈 넷(전설 2 · 대물 2)이 든 어항에서 자리가 있는데도 둘이 포개진 적이 있어요.
big4 = {"f31": [mid("f31", .8)], "f33": [mid("f33", .6)], "f23": [mid("f23")], "f25": [mid("f25", .9)],
        "f02": [25, 21], "f06": [17], "f16": [88]}
SEEDS = range(1, 13)
for label, tank in (("하루치 어항", day), ("큰 놈 넷이 든 어항", big4)):
    body_hit = tag_hit = 0.0
    for seed in SEEDS:
        leads = [e for e in fish_art._tank_layout(tank, seed=seed) if e["lead"]]
        bodies = [fish_art._tank_boxes(e, *e["pos"])[0] for e in leads]
        tags = [fish_art._tank_boxes(e, *e["pos"])[1] for e in leads]
        body_hit += sum(fish_art._overlap(a, b) for i, a in enumerate(bodies) for b in bodies[i + 1:])
        tag_hit += sum(fish_art._overlap(t, b) for i, t in enumerate(tags) for j, b in enumerate(bodies) if i != j)
    check(f"{label}: 대표끼리 몸통이 겹치지 않는다 (씨앗 {len(SEEDS)}개)", body_hit == 0, f"겹친 넓이 {body_hit:.0f}px²")
    # 이름표는 몸통보다 덜 엄격하게 봐요 — 꼬리 끝에 몇 px 걸치는 건 눈에 안 띄어요.
    check(f"{label}: 이름표가 남의 몸통을 가리지 않는다 (씨앗 {len(SEEDS)}개)", tag_hit < 400,
          f"겹친 넓이 {tag_hit:.0f}px²")
leads = [e for e in fish_art._tank_layout(day, seed=7) if e["lead"]]
low = [e for e in leads if e["key"] in fish_art.TANK_BOTTOM]
high = [e for e in leads if e["key"] not in fish_art.TANK_BOTTOM]
check("바닥에 사는 종(미꾸라지·모래무지)은 물 아래쪽 절반에 있다",
      low and all(e["pos"][1] + e["im"].height / 2 > (y0 + y1) / 2 for e in low))
check("나머지는 바닥 자갈에 박히지 않는다 (아래 10%는 비워요)",
      all(e["pos"][1] + e["im"].height <= y1 - (y1 - y0) * 0.10 + 1 for e in high))
off = []
for seed in SEEDS:
    for key in ("f02", "f03", "f31"):
        solo = fish_art._tank_layout({key: [mid(key)]}, seed=seed)[0]
        off.append(abs(solo["pos"][0] + solo["im"].width / 2 - (x0 + x1) / 2))
check(f"한 마리뿐이면 가운데 쪽에 둔다 — 구석에 박히지 않는다 ({len(off)}번)",
      max(off) < (x1 - x0) * 0.25, f"가운데에서 최대 {max(off):.0f}px")
a = fish_art._tank_layout(day, seed=7)
b = fish_art._tank_layout(day, seed=7)
check("같은 어항은 같은 자리 (열 때마다 물고기가 자리를 바꾸지 않는다)",
      [(e["key"], e["pos"]) for e in a] == [(e["key"], e["pos"]) for e in b])
check("종이 적으면 이름표에 치수를 적는다",
      all("cm" in e["label"][0] for e in fish_art._tank_layout({"f02": [25], "f12": [40]}, 1)))
packed = [e for e in fish_art._tank_layout(full, 1) if e["lead"]]
check("종이 아주 많으면 일반·희귀 이름표에서 치수를 뺀다 (이름표가 물고기를 덮어요)",
      not any("cm" in e["label"][0] for e in packed if e["grade"] in ("일반", "희귀")))
check("그래도 대물·전설은 치수를 적는다",
      all("cm" in e["label"][0] for e in packed if e["grade"] in ("대물", "전설")))

# ------------------------------------------------------------------
print("[8] 🪣 어항 카드 — 그림 파일")


def card(tank, **kw):
    kw = {"name": "테스트", "sell_coins": 12, "dex_seen": 3, "seed": 1, **kw}
    raw = fish_art.render_tank(tank, **kw)
    return raw, Image.open(io.BytesIO(raw))


raw, im = card(day)
check("JPEG 1000×630", im.format == "JPEG" and im.size == (fish_art.TANK_W, fish_art.TANK_H), f"{im.format} {im.size}")
check("1MB보다 작다 (PNG로 바꾸면 넘어요)", len(raw) < 1_000_000, f"{len(raw)} bytes")
check("같은 어항은 같은 그림", raw == card(day)[0])
check("물고기가 늘면 그림이 달라진다", raw != card({**day, "f12": [40]})[0])
check("빈 어항도 그려진다", card({})[1].size == (fish_art.TANK_W, fish_art.TANK_H))
check("전 종 어항도 그려진다", card(full)[1].size == (fish_art.TANK_W, fish_art.TANK_H))
check("이름이 아주 길어도 그려진다", card(day, name="가" * 80)[1].size == (fish_art.TANK_W, fish_art.TANK_H))
with open(os.path.join(BOT_DIR, "assets", "coin.png"), "rb") as fh:
    check("아바타를 넣으면 그림이 달라진다 (= 실제로 그렸다)", card(day, avatar=fh.read())[0] != raw)

# ⚠️ 여기부터는 **일부러 고장 낸** 경우예요. 경고 로그(traceback)가 화면을 덮지 않게 잠깐 꺼요.
import logging  # noqa: E402

logging.disable(logging.CRITICAL)
_real_bg, _real_art = fish_art.TANK_BG, fish_art.art_path
try:
    check("아바타가 깨진 바이트여도 그려진다", card(day, avatar=b"not an image")[1].size[0] == fish_art.TANK_W)
    fish_art.TANK_BG = fish_art.TANK_BG.with_name("없는파일.webp")
    check("배경 그림이 없어도 그려진다 (그라데이션으로 물러나요)", card(day)[1].size[0] == fish_art.TANK_W)
    fish_art.TANK_BG = _real_bg
    fish_art.art_path = lambda key: None if key == "f02" else _real_art(key)
    check("그림 없는 종은 빼고 그린다 (어항이 죽지 않는다)",
          "f02" not in [e["key"] for e in fish_art._tank_layout(day, 1)] and card(day)[1].size[0] == fish_art.TANK_W)
    fish_art.art_path = lambda key: fish_art.TANK_BG.with_name("깨진그림.webp") if key == "f02" else _real_art(key)
    check("그림 파일이 깨져 있어도 그 종만 빼고 그린다",
          "f02" not in [e["key"] for e in fish_art._tank_layout(day, 1)] and card(day)[1].size[0] == fish_art.TANK_W)
finally:
    fish_art.TANK_BG, fish_art.art_path = _real_bg, _real_art
    logging.disable(logging.NOTSET)

# ------------------------------------------------------------------
print("[9] 🪣 `/어항`에 붙었나 — 그림이 죽어도 글은 나간다")
import asyncio  # noqa: E402
import types  # noqa: E402

os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")     # 접속하지 않아요(아래에서 전부 가짜로 바꿔요)
os.environ.setdefault("MONGODB_DB_NAME", "agwi_fish_test")
import cogs.fishing as fishing  # noqa: E402


async def _fake_get(_uid):
    return {"tank": dict(day), "pieces": 137, "dust": 4, "casts": 30, "caught": 21, "sold": 55,
            "best": {"key": "f22", "rank": 3, "size": 210}, "dex": {"f01": 3, "f22": 1}}


async def _fake_rod(_uid):
    return 5, 0


async def _fake_quota(_uid):
    return 3, 20


async def _no_avatar(_user):
    return None


async def _no_card(*_a, **_kw):
    return None


fishing.fishing_store.get = _fake_get
fishing.fishing_store.rod_state = _fake_rod
fishing.fishing_store.cast_quota = _fake_quota
fishing.profile_service.avatar_for = _no_avatar
_user = types.SimpleNamespace(id=42, name="tester", display_name="테스터")

embed, files = asyncio.run(fishing.build_tank_reply(_user))
check("그림 1장이 붙는다", len(files) == 1 and files[0].filename == fishing.TANK_CARD_NAME,
      str([f.filename for f in files]))
check("임베드가 그 첨부를 그림으로 가리킨다", embed.image.url == f"attachment://{fishing.TANK_CARD_NAME}",
      str(embed.image.url))
_text = (embed.description or "") + "".join(f"{f.name}{f.value}" for f in embed.fields)
check("글(등급별 목록 · 팔면 · 낚시대)은 그대로 있다",
      all(s in _text for s in ("철갑상어 210cm", "팔면", "낚시대", "14코인")), _text[:120])

_real_card = fishing.fish_art.tank_card
try:
    fishing.fish_art.tank_card = _no_card
    embed, files = asyncio.run(fishing.build_tank_reply(_user))
    check("🚨 그림을 못 그려도 글은 나간다 (첨부 없이)", files == [] and not embed.image.url and embed.fields)
finally:
    fishing.fish_art.tank_card = _real_card

_real_render = fish_art.render_tank


def _boom(*_a, **_kw):
    raise RuntimeError("일부러 낸 오류")


try:
    fish_art.render_tank = _boom
    logging.disable(logging.CRITICAL)                     # 일부러 낸 오류의 traceback은 숨겨요
    check("tank_card는 그리다 터지면 None을 돌려준다 (예외를 밖으로 안 던진다)",
          asyncio.run(fish_art.tank_card(day, name="x")) is None)
finally:
    fish_art.render_tank = _real_render
    logging.disable(logging.NOTSET)

_src = open(os.path.join(BOT_DIR, "cogs", "attendance.py"), encoding="utf-8").read()
check("`/프로필` → 자세히 보기 → 낚시도 같은 화면(build_tank_reply)을 쓴다",
      "build_tank_reply" in _src and "build_tank_embed" not in _src)

# ==================================================================
print("[9] 👑 도감 왕관 (2026-11-24)")
# ------------------------------------------------------------------
from utils import fish_data as _fd  # noqa: E402
from utils import fishing_store as _fs  # noqa: E402

_lo, _hi = SIZE_BY_KEY["f01"]                        # 피라미 8~20
check("최대치는 왕관", _fd.is_crown("f01", _hi))
check("90% 지점은 왕관", _fd.is_crown("f01", _lo + (_hi - _lo) * 0.9 + 0.01))
check("89%는 왕관 아님", not _fd.is_crown("f01", _lo + int((_hi - _lo) * 0.85)))
check("치수를 모르면(None, 옛 물고기) 왕관 아님", not _fd.is_crown("f01", None))
check("모든 종에서 최대치는 왕관 (범위가 좁은 송사리 2~5도)",
      all(_fd.is_crown(k, SIZE_BY_KEY[k][1]) for k in BY_KEY))
check("새 왕관만 알린다 — 이미 왕관이면 빈 목록",
      _fs._new_crowns({"f01": _hi}, {"f01": _hi}) == [])
check("새 왕관만 알린다 — 처음이면 그 종",
      _fs._new_crowns({"f01": _lo}, {"f01": _hi, "f02": SIZE_BY_KEY["f02"][0]}) == ["f01"])
_png_c = fish_art.render_dex({"f01": 1}, "t", {"f01": _hi})
_png_n = fish_art.render_dex({"f01": 1}, "t", {"f01": _lo})
check("왕관 칸이 있으면 그림이 달라진다", _png_c != _png_n)
check("한 판·몰아 던지기 둘 다 `dexmax`를 $max로 남긴다",
      src.count('update["$max"]') >= 2 and src.count("dexmax.{k") + src.count("dexmax.{key") >= 2,
      f'$max={src.count(chr(117) + "pdate[" + chr(34) + "$max")}')
check("낚시 결과의 '최대급' 표시가 왕관과 같은 기준(is_crown)을 쓴다",
      cog.count("fish_data.is_crown(") >= 2 and "pct >= 90" not in cog)

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
