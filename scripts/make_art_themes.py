# -*- coding: utf-8 -*-
"""🎨 그림 테마 8종을 **코드로 합성**해요 (2026-11-15).

## 왜 만들었나

색 테마(15코인)는 전체 기간 1건, 그림 테마(오로라·케이오)는 3건 팔렸어요. 사람들은
"어두운 색"보다 **그림**에 돈을 써요. 그래서 그림 테마를 늘려요. 오로라 샘플
(`make_sample_card_theme.py`)과 같은 방식 — 외부 그림을 받아오지 않고 도형·그라데이션·
블러만으로 오리지널 풍경을 만들어요.

## 🚨 볼거리는 **오른쪽**에

카드 글씨는 왼쪽 62% 안에 있고 그 위를 스크림이 90%로 덮어요(`profile_card.SCRIM_*`).
그림의 주인공(달·행성·나무·건물)은 **x 640 이후**에 둬야 보여요.

    python scripts/make_art_themes.py          # 8장 생성 + themes.json에 없는 줄만 추가

🚨 결정적이에요(난수 시드 고정) — 다시 돌려도 같은 그림이 나와요.
그다음 `python scripts/check_card_themes.py`로 파일↔목록 대조.
"""
import json
import math
import os
import random
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from PIL import Image, ImageDraw, ImageFilter       # noqa: E402

from utils.card_theme_assets import CARD_SIZE, MANIFEST, THEME_DIR  # noqa: E402

W, H = CARD_SIZE


# ------------------------------------------------------------------ 공용 붓
def vgrad(stops) -> Image.Image:
    """세로 그라데이션. stops = [(0.0, rgb), (0.6, rgb), (1.0, rgb)]"""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        r = y / (H - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= r <= p1:
                t = (r - p0) / max(1e-6, p1 - p0)
                d.line([(0, y), (W, y)], fill=tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3)))
                break
    return img


def layer():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def comp(base, top, blur=0):
    if blur:
        top = top.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(base.convert("RGBA"), top).convert("RGB")


def glow_disc(base, cx, cy, r, color, halo=2.4, halo_alpha=80):
    h, hd = layer()
    R = r * halo
    hd.ellipse((cx - R, cy - R, cx + R, cy + R), fill=(*color, halo_alpha))
    base = comp(base, h, blur=r * 0.8)
    c, cd = layer()
    cd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, 255))
    return comp(base, c, blur=1.5)


def stars(base, rng, n, ymax, color=(255, 255, 255)):
    s, sd = layer()
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(0, ymax)
        size = rng.choice((1, 1, 1, 2, 2, 3))
        sd.ellipse((x, y, x + size, y + size), fill=(*color, rng.randint(90, 230)))
    return comp(base, s)


def ridge(rng, y0, amp, rough, seed_shift=0.0):
    """산 능선 점들 (왼→오)."""
    pts, y = [], y0
    for x in range(0, W + 20, 20):
        y = y0 + math.sin(x / 140 + seed_shift) * amp + rng.uniform(-rough, rough)
        pts.append((x, y))
    return pts + [(W, H), (0, H)]


# ------------------------------------------------------------------ 테마들
def sakura(rng):
    base = vgrad([(0, (28, 16, 40)), (0.6, (70, 34, 70)), (1, (40, 20, 44))])
    base = stars(base, rng, 120, H * 0.5)
    base = glow_disc(base, 820, 140, 60, (255, 232, 238), halo=2.8, halo_alpha=70)
    # 나무 줄기 (오른쪽)
    t, td = layer()
    td.polygon([(880, H), (905, 420), (870, 330), (900, 330), (935, 410), (960, H)], fill=(30, 14, 26, 255))
    td.line([(905, 400), (780, 300)], fill=(30, 14, 26, 255), width=16)
    td.line([(915, 380), (1000, 280)], fill=(30, 14, 26, 255), width=14)
    base = comp(base, t)
    # 꽃 구름
    f, fd = layer()
    for _ in range(260):
        cx = rng.gauss(870, 110)
        cy = rng.gauss(300, 70)
        r = rng.uniform(10, 26)
        col = rng.choice([(255, 183, 206), (255, 160, 190), (250, 205, 222)])
        fd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*col, rng.randint(90, 170)))
    base = comp(base, f, blur=3)
    # 흩날리는 꽃잎
    p, pd = layer()
    for _ in range(140):
        x, y = rng.uniform(450, W), rng.uniform(0, H)
        a = rng.uniform(0, math.pi)
        dx, dy = math.cos(a) * 5, math.sin(a) * 3
        pd.ellipse((x - 4 + dx, y - 2 + dy, x + 4 + dx, y + 2 + dy), fill=(255, 196, 214, rng.randint(120, 220)))
    return comp(base, p, blur=0.6)


def neon_city(rng):
    base = vgrad([(0, (10, 6, 26)), (0.65, (48, 14, 70)), (1, (16, 8, 30))])
    base = stars(base, rng, 60, H * 0.35)
    # 빌딩
    b, bd = layer()
    w_, wd = layer()
    x = 560
    while x < W:
        bw = rng.randint(40, 90)
        top = rng.randint(180, 430)
        bd.rectangle((x, top, x + bw, H), fill=(14, 10, 28, 255))
        for wy in range(top + 12, H - 20, 18):
            for wx in range(x + 8, x + bw - 8, 14):
                if rng.random() < 0.35:
                    col = rng.choice([(255, 80, 200), (80, 220, 255), (255, 210, 120)])
                    wd.rectangle((wx, wy, wx + 6, wy + 8), fill=(*col, rng.randint(140, 240)))
        x += bw + rng.randint(2, 10)
    base = comp(base, b)
    base = comp(base, w_, blur=0.8)
    # 네온 간판 줄
    n, nd = layer()
    nd.line([(640, 360), (760, 360)], fill=(255, 60, 200, 255), width=5)
    nd.line([(820, 250), (820, 340)], fill=(60, 230, 255, 255), width=5)
    nd.line([(900, 300), (980, 300)], fill=(255, 60, 200, 255), width=5)
    base = comp(base, n, blur=6)
    base = comp(base, n, blur=1)
    # 바닥 반사 안개
    g, gd = layer()
    gd.rectangle((450, H - 90, W, H), fill=(255, 60, 200, 60))
    return comp(base, g, blur=30)


def cosmos(rng):
    base = vgrad([(0, (6, 6, 18)), (1, (14, 10, 34))])
    # 성운
    for col, cx, cy, r in (((120, 40, 160), 760, 260, 260), ((40, 90, 180), 900, 380, 220),
                           ((200, 60, 120), 680, 420, 160)):
        n, nd = layer()
        for _ in range(60):
            x, y = rng.gauss(cx, r * 0.5), rng.gauss(cy, r * 0.35)
            rr = rng.uniform(30, 90)
            nd.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(*col, 26))
        base = comp(base, n, blur=30)
    base = stars(base, rng, 420, H)
    # 행성 + 고리
    p, pd = layer()
    cx, cy, r = 840, 230, 78
    for i in range(r, 0, -1):
        t = i / r
        pd.ellipse((cx - i, cy - i, cx + i, cy + i),
                   fill=(int(230 - 120 * t), int(150 - 80 * t), int(110 - 40 * t), 255))
    base = comp(base, p)
    ring, rd = layer()
    rd.ellipse((cx - 150, cy - 26, cx + 150, cy + 26), outline=(240, 210, 170, 200), width=5)
    ring = ring.rotate(-14, center=(cx, cy))
    # 고리 뒤쪽은 행성에 가려져야 해요 → 위쪽 절반을 행성 원으로 지워요
    mask = Image.new("L", (W, H), 255)
    ImageDraw.Draw(mask).pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=0)
    ring.putalpha(Image.composite(ring.getchannel("A"), Image.new("L", (W, H), 0), mask))
    return comp(base, ring, blur=0.8)


def rainy_night(rng):
    base = vgrad([(0, (14, 18, 30)), (1, (24, 30, 46))])
    # 보케(번진 불빛)
    b, bd = layer()
    for _ in range(70):
        x, y = rng.uniform(520, W), rng.uniform(80, H - 40)
        r = rng.uniform(12, 40)
        col = rng.choice([(255, 180, 90), (255, 120, 90), (120, 180, 255), (255, 230, 160)])
        bd.ellipse((x - r, y - r, x + r, y + r), fill=(*col, rng.randint(50, 120)))
    base = comp(base, b, blur=8)
    # 빗줄기
    r_, rd = layer()
    for _ in range(600):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        ln = rng.uniform(14, 34)
        rd.line([(x, y), (x - ln * 0.18, y + ln)], fill=(190, 210, 240, rng.randint(40, 110)), width=1)
    base = comp(base, r_)
    # 유리창 물방울
    d, dd = layer()
    for _ in range(90):
        x, y = rng.uniform(560, W), rng.uniform(0, H)
        r = rng.uniform(2, 6)
        dd.ellipse((x - r, y - r, x + r, y + r), fill=(220, 235, 255, 150))
    return comp(base, d, blur=0.7)


def snowfield(rng):
    base = vgrad([(0, (16, 26, 48)), (0.55, (40, 64, 100)), (1, (70, 90, 120))])
    base = stars(base, rng, 120, H * 0.4)
    base = glow_disc(base, 780, 120, 40, (240, 246, 255), halo=3.0, halo_alpha=60)
    d = ImageDraw.Draw(base)
    d.polygon(ridge(rng, 340, 40, 18, 1.0), fill=(52, 70, 104))
    d.polygon(ridge(rng, 420, 30, 10, 2.6), fill=(150, 170, 200))
    d.polygon(ridge(rng, 500, 18, 6, 4.1), fill=(200, 214, 232))
    # 침엽수
    for _ in range(14):
        x = rng.uniform(620, W)
        y = rng.uniform(470, 560)
        h = rng.uniform(50, 100)
        d.polygon([(x, y - h), (x - h * 0.28, y), (x + h * 0.28, y)], fill=(24, 40, 54))
    s, sd = layer()
    for _ in range(320):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.uniform(1, 3.2)
        sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randint(120, 230)))
    return comp(base, s, blur=0.5)


def lava(rng):
    base = vgrad([(0, (18, 8, 8)), (0.6, (40, 12, 8)), (1, (90, 24, 6))])
    d = ImageDraw.Draw(base)
    # 화산 실루엣
    d.polygon([(560, H), (760, 250), (820, 240), (900, 260), (1000, 380), (1000, H)], fill=(20, 10, 10))
    # 분출 빛
    base = glow_disc(base, 790, 240, 26, (255, 150, 40), halo=4.5, halo_alpha=90)
    # 용암 줄기
    l, ld = layer()
    x, y = 790, 250
    for _ in range(3):
        x, y = 790 + rng.uniform(-20, 20), 250
        pts = [(x, y)]
        while y < H:
            x += rng.uniform(-18, 18)
            y += rng.uniform(16, 30)
            pts.append((x, y))
        ld.line(pts, fill=(255, 120, 30, 255), width=6)
    base = comp(base, l, blur=5)
    base = comp(base, l, blur=0.8)
    # 불씨
    e, ed = layer()
    for _ in range(160):
        x, y = rng.gauss(790, 120), rng.uniform(40, 330)
        r = rng.uniform(1, 3)
        ed.ellipse((x - r, y - r, x + r, y + r), fill=(255, rng.randint(120, 200), 60, rng.randint(140, 255)))
    return comp(base, e, blur=0.6)


def sunset_sea(rng):
    base = vgrad([(0, (30, 18, 50)), (0.38, (160, 70, 80)), (0.52, (250, 150, 90)),
                  (0.56, (60, 40, 70)), (1, (16, 16, 34))])
    base = glow_disc(base, 820, 330, 64, (255, 200, 120), halo=2.6, halo_alpha=90)
    # 수평선 아래를 덮어서 해가 반쯤 잠기게
    d = ImageDraw.Draw(base)
    sea_y = int(H * 0.56)
    for y in range(sea_y, H):
        t = (y - sea_y) / (H - sea_y)
        d.line([(0, y), (W, y)], fill=(int(60 - 44 * t), int(40 - 24 * t), int(70 - 36 * t)))
    # 물결 반사
    w_, wd = layer()
    for i in range(70):
        y = sea_y + 6 + i * 3.8
        half = 90 - i * 1.1 + rng.uniform(-14, 14)
        if half <= 4:
            continue
        x = 820 + rng.uniform(-10, 10)
        wd.line([(x - half, y), (x + half, y)], fill=(255, 190, 120, max(30, 200 - i * 3)), width=2)
    base = comp(base, w_, blur=1)
    # 구름 띠
    c, cd = layer()
    for _ in range(26):
        x, y = rng.uniform(500, W), rng.uniform(120, 280)
        cd.ellipse((x - 90, y - 10, x + 90, y + 10), fill=(90, 40, 70, 120))
    return comp(base, c, blur=6)


def firefly_forest(rng):
    base = vgrad([(0, (8, 20, 18)), (1, (14, 36, 28))])
    base = glow_disc(base, 900, 100, 30, (230, 255, 220), halo=3.0, halo_alpha=50)
    d = ImageDraw.Draw(base)
    # 나무 줄기 겹
    for depth, col in ((0, (18, 40, 32)), (1, (12, 28, 22)), (2, (6, 16, 12))):
        for _ in range(6 + depth * 2):
            x = rng.uniform(560, W)
            w = rng.uniform(10, 18) + depth * 8
            d.rectangle((x, 0, x + w, H), fill=col)
    # 덤불
    d.polygon(ridge(rng, 560, 14, 10, 0.4), fill=(4, 12, 8))
    # 반딧불
    f, fd = layer()
    for _ in range(90):
        x, y = rng.uniform(480, W), rng.uniform(200, H - 30)
        r = rng.uniform(2, 4)
        fd.ellipse((x - r * 4, y - r * 4, x + r * 4, y + r * 4), fill=(200, 255, 120, 40))
        fd.ellipse((x - r, y - r, x + r, y + r), fill=(240, 255, 170, 230))
    base = comp(base, f, blur=4)
    return comp(base, f, blur=0.6)


THEMES = [
    # (key, emoji, desc, 함수, 시드)
    ("벚꽃", "🌸", "달밤에 흩날리는 벚꽃", sakura, 11),
    ("네온시티", "🌃", "보랏빛 네온이 켜진 밤거리", neon_city, 12),
    ("우주", "🪐", "성운과 고리 행성", cosmos, 13),
    ("빗속", "🌧️", "비 내리는 창밖 불빛", rainy_night, 14),
    ("설원", "❄️", "눈 내리는 겨울 산", snowfield, 15),
    ("용암", "🌋", "불씨가 튀는 화산", lava, 16),
    ("노을바다", "🌅", "수평선에 걸린 해", sunset_sea, 17),
    ("반딧불숲", "✨", "반딧불이 떠다니는 숲", firefly_forest, 18),
]


def main():
    THEME_DIR.mkdir(parents=True, exist_ok=True)
    for key, emoji, desc, fn, seed in THEMES:
        img = fn(random.Random(seed))
        out = THEME_DIR / f"{key}.png"
        img.save(out, format="PNG", optimize=True)
        print(f"✅ {out.name}  {out.stat().st_size / 1024:.0f}KB")

    entries = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    have = {e.get("key") for e in entries}
    added = 0
    for key, emoji, desc, _fn, _seed in THEMES:
        if key not in have:
            entries.append({"key": key, "emoji": emoji, "desc": desc, "image": f"{key}.png"})
            added += 1
    MANIFEST.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"themes.json: {added}줄 추가 (전체 {len(entries)}종)")


if __name__ == "__main__":
    main()
