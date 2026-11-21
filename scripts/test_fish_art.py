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

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
