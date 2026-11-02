# -*- coding: utf-8 -*-
"""🎴 샘플 캐릭터 카드 테마 그림을 **코드로 합성**해요 (2026-11-03).

## 왜 코드로 만드나

캐릭터 테마는 **방장이 그림을 넣는** 구조라, 봇 저장소에는 "그림이 들어오면 이렇게
보인다"를 확인할 **표본 한 장**만 있으면 돼요. 외부 그림을 받아오거나 남의 캐릭터를
그려 넣지 않고, 도형과 그라데이션만으로 오리지널 한 장을 만들어요.
⭐ 겜악귀들의천국 효과음을 **코드로 합성**한 것과 같은 방식이에요 — 파일을 들고
   다니지 않아도 되고, 값을 바꿔 다시 뽑을 수 있어요.

    python scripts/make_sample_card_theme.py

`assets/card_themes/오로라.png` 를 만들어요. 이미 있으면 덮어써요.
🚨 이걸 돌린 뒤 `themes.json`에 등록해야 상점에 떠요
   (`python scripts/check_card_themes.py` 가 붙여넣을 줄을 알려줘요).
"""
import math
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from PIL import Image, ImageDraw, ImageFilter       # noqa: E402

from utils.card_theme_assets import CARD_SIZE, THEME_DIR  # noqa: E402

W, H = CARD_SIZE
OUT = THEME_DIR / "오로라.png"


def main():
    THEME_DIR.mkdir(parents=True, exist_ok=True)

    # ── 바탕: 위는 짙은 남색, 아래는 보라로 번지는 밤하늘 ──────────────
    base = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(base)
    for y in range(H):
        r = y / H
        draw.line([(0, y), (W, y)],
                  fill=(int(12 + 40 * r), int(14 + 18 * r), int(34 + 58 * r)))

    # ── 오로라 띠 3겹 ────────────────────────────────────────────────
    # 🚨 반투명 레이어를 따로 만들어 합성해요. 같은 이미지에 직접 그리면
    #    겹치는 부분이 탁해져요.
    for index, (color, amp, phase, base_y, thick) in enumerate((
        ((90, 220, 190), 54, 0.0, 190, 54),
        ((130, 150, 255), 42, 1.7, 250, 40),
        ((220, 140, 230), 32, 3.1, 310, 28),
    )):
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(band)
        for x in range(0, W, 2):
            t = x / W * math.pi * 2
            y = base_y + math.sin(t + phase) * amp + math.sin(t * 2.3 + phase) * amp * 0.3
            bdraw.line([(x, y - thick / 2), (x, y + thick / 2)], fill=(*color, 150), width=3)
        band = band.filter(ImageFilter.GaussianBlur(18 + index * 6))
        base = Image.alpha_composite(base.convert("RGBA"), band).convert("RGB")

    # ── 별 ──────────────────────────────────────────────────────────
    # 🚨 `Math.random()`을 안 쓰고 **결정적**으로 뿌려요. 다시 돌려도 같은 그림이
    #    나와야 "그림이 바뀌었나?"를 의심하지 않아도 돼요.
    stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(stars)
    for i in range(220):
        x = (i * 7919) % W
        y = (i * 104729) % (H // 2)
        size = 1 + (i % 3)
        bright = 110 + (i * 37) % 130
        sdraw.ellipse((x, y, x + size, y + size), fill=(255, 255, 255, bright))
    base = Image.alpha_composite(base.convert("RGBA"), stars).convert("RGB")

    # ── 오른쪽에 달 + 산 실루엣 ──────────────────────────────────────
    # ⭐ **오른쪽**에 두는 이유: 카드 글씨가 전부 왼쪽에 있어서 스크림이 왼쪽만
    #    어둡게 덮어요(profile_card.SCRIM_LEFT/RIGHT). 볼거리는 오른쪽에 둬야 보여요.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((744, 56, 904, 216), fill=(255, 246, 214, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(2))
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((704, 16, 944, 256), fill=(255, 240, 200, 70))
    halo = halo.filter(ImageFilter.GaussianBlur(40))
    base = Image.alpha_composite(base.convert("RGBA"), halo)
    base = Image.alpha_composite(base, glow).convert("RGB")

    draw = ImageDraw.Draw(base)
    draw.polygon([(560, H), (740, 330), (860, 430), (1000, 300), (1000, H)], fill=(14, 14, 26))
    draw.polygon([(820, H), (960, 380), (1000, 420), (1000, H)], fill=(20, 18, 36))

    base.save(OUT, format="PNG", optimize=True)
    print(f"✅ {OUT}  ({OUT.stat().st_size / 1024:.0f}KB · {base.size[0]}x{base.size[1]})")
    print("   다음: python scripts/check_card_themes.py 로 등록 줄을 확인하세요.")


if __name__ == "__main__":
    main()
