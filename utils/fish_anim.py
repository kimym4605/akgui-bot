# -*- coding: utf-8 -*-
"""🎣 낚시 움직이는 그림 (2026-11-22) — 찌 기다리기 · 입질 · 대물 튀어오르기.

밤 호수 위에 찌가 떠 있는 장면을 **코드로 그려요**(그림 재료 없이).

- `wait.gif`·`bite.gif`는 판마다 같아서 **미리 만들어** `assets/fish/anim/`에 넣어 둬요
  (`python scripts/build_fish_anim.py`). 봇은 파일을 붙이기만 해요 - 던질 때마다 그리면
  운영 머신 CPU를 매번 써요.
- 튀어오르기(`catch_gif`)는 잡힌 물고기 그림이 들어가서 **그때그때** 그려요. 대물·전설만이에요
  (드물어서 부담이 작고, 그래서 더 특별해요).

## 규칙
🚨 **그림은 덤이에요.** 파일이 없거나 그리다 실패하면 None → 부른 쪽은 예전처럼 글만 보내요.
⚠️ Pillow는 스레드에서, 동시에 그리는 수는 프로필 카드와 같은 `_RENDER_LOCK`으로 묶어요.
⚠️ 기다리기·입질 GIF는 **끝없이 돌아요**(`loop=0`). 끝이 이어지게 모든 움직임을 한 바퀴(프레임 수)에 맞춰요.
⚠️ 튀어오르기는 **한 번만** 돌아요(`loop` 없음) - 마지막 장(물고기가 떠 있는 장)에 멈춰요.
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from utils.profile_card import _RENDER_LOCK, _font

log = logging.getLogger(__name__)

ANIM_DIR = Path(__file__).resolve().parent.parent / "assets" / "fish" / "anim"
WAIT_FILE = ANIM_DIR / "wait.gif"
BITE_FILE = ANIM_DIR / "bite.gif"
FISH_DIR = Path(__file__).resolve().parent.parent / "assets" / "fish"

W, H = 480, 270
HORIZON = 98
BOB_X, WATERLINE = 252, 176          # 찌가 떠 있는 자리(물에 닿는 선)
MOON = (384, 46, 19)
COLORS = 200

WAIT_FRAMES, WAIT_MS = 24, 80        # 한 바퀴 ≈ 2초 (GIF 시간은 10ms 단위라 10의 배수로)
BITE_FRAMES, BITE_MS = 12, 60
CATCH_MS = 50
CATCH_HOLD_MS = 600_000              # 마지막 장(물고기가 떠 있는 장)을 붙들어 둬요

CATCH_PX = {"대물": 150, "전설": 178}
GLOW = {"대물": (255, 170, 70), "전설": (255, 214, 92)}


# ── 바탕 ──────────────────────────────────────────────────────────────
def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _background() -> Image.Image:
    """안 움직이는 바탕(하늘·달·먼 산·물 색). RGB."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(HORIZON):
        d.line([(0, y), (W, y)], fill=_lerp((10, 8, 30), (62, 36, 92), (y / HORIZON) ** 1.4))
    for y in range(HORIZON, H):
        t = (y - HORIZON) / (H - HORIZON)
        d.line([(0, y), (W, y)], fill=_lerp((40, 40, 86), (8, 12, 30), t ** 0.7))
    rng = random.Random(7)
    for _ in range(46):                                  # 별
        x, y = rng.randrange(W), rng.randrange(HORIZON - 26)
        b = rng.randrange(120, 235)
        d.point((x, y), fill=(b, b, min(255, b + 20)))
    # 달 + 번짐
    mx, my, mr = MOON
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((mx - mr * 3, my - mr * 3, mx + mr * 3, my + mr * 3), fill=(190, 170, 255, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img.paste(glow, (0, 0), glow)
    d.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(244, 238, 216))
    d.ellipse((mx - mr + 7, my - mr + 5, mx - mr + 13, my - mr + 11), fill=(226, 218, 196))
    d.ellipse((mx + 3, my + 4, mx + 10, my + 11), fill=(228, 220, 198))
    # 먼 산 실루엣
    pts = [(0, HORIZON)]
    for x in range(0, W + 8, 8):
        h = 12 + 9 * math.sin(x / 47) + 6 * math.sin(x / 19 + 1.3) + 4 * math.sin(x / 7.3)
        pts.append((x, HORIZON - max(3, h)))
    pts.append((W, HORIZON))
    d.polygon(pts, fill=(22, 14, 40))
    d.line([(0, HORIZON), (W, HORIZON)], fill=(70, 60, 120), width=1)
    return img


def _water_life(d: ImageDraw.ImageDraw, phase: float) -> None:
    """물결 반짝임 + 달 그림자. `phase`는 0~1(한 바퀴)."""
    rng = random.Random(11)
    a = phase * 2 * math.pi
    for _ in range(64):
        y = HORIZON + 4 + int((H - HORIZON - 6) * rng.random() ** 1.6)
        depth = (y - HORIZON) / (H - HORIZON)
        x = rng.randrange(W)
        seed = rng.random() * 2 * math.pi
        k = 0.5 + 0.5 * math.sin(a + seed)
        ln = (6 + 26 * depth) * (0.4 + 0.6 * k)
        alpha = int(40 + 70 * k * (0.5 + depth / 2))
        d.line([(x - ln / 2, y), (x + ln / 2, y)], fill=(120, 140, 210, alpha), width=1 if depth < 0.5 else 2)
    mx = MOON[0]
    for i, y in enumerate(range(HORIZON + 3, H, 4)):     # 달빛 기둥 (줄마다 길이·자리를 흩어요)
        depth = (y - HORIZON) / (H - HORIZON)
        seed = rng.random() * 2 * math.pi
        wob = math.sin(a * 2 + seed)
        half = (5 + 22 * depth) * (0.35 + 0.65 * rng.random()) * (0.6 + 0.4 * wob)
        cx = mx + rng.uniform(-6, 6) * (1 + depth) + 3 * math.sin(a + seed)
        alpha = int((120 - 80 * depth) * (0.55 + 0.45 * (0.5 + 0.5 * wob)))
        d.line([(cx - half, y), (cx + half, y)], fill=(236, 228, 200, alpha), width=1 if i % 2 else 2)


def _ripples(d: ImageDraw.ImageDraw, phase: float, *, rings: int = 2, grow: float = 46, base: float = 10,
             strength: int = 120, cx: float = BOB_X) -> None:
    for k in range(rings):
        t = (phase + k / rings) % 1.0
        rx = base + grow * t
        ry = rx * 0.26
        alpha = int(strength * (1 - t) ** 1.3)
        d.ellipse((cx - rx, WATERLINE - ry, cx + rx, WATERLINE + ry), outline=(190, 210, 255, alpha), width=2)


def _line(d: ImageDraw.ImageDraw, top: tuple[float, float]) -> None:
    """낚싯줄: 왼쪽 위(화면 밖 낚싯대)에서 찌 꼭대기까지 살짝 처진 곡선."""
    x0, y0 = -10.0, -14.0
    x1, y1 = top
    pts = []
    for i in range(25):
        t = i / 24
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t + 26 * math.sin(math.pi * t)
        pts.append((x, y))
    d.line(pts, fill=(205, 205, 230, 120), width=1)


def _bobber(img: Image.Image, d: ImageDraw.ImageDraw, *, dx: float = 0, sink: float = 0) -> tuple[float, float]:
    """찌를 그려요. `sink`만큼 물에 잠겨요(px). 물 아래는 안 그려요. 줄을 맬 꼭대기 좌표를 돌려줘요."""
    s = 4
    bw, bh = 32, 46                                      # 몸통(물 밖으로 보일 수 있는 최대)
    spr = Image.new("RGBA", (bw * s, (bh + 22) * s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spr)
    # 안테나
    sd.rounded_rectangle((bw * s / 2 - 1.5 * s, 0, bw * s / 2 + 1.5 * s, 24 * s), s, fill=(250, 240, 120, 255))
    # 빨간 윗머리 · 흰 띠 · 아래(잠기는 쪽)
    sd.ellipse((0, 16 * s, bw * s, 16 * s + bw * s), fill=(226, 52, 66, 255))
    sd.rectangle((0, (16 + bw / 2) * s, bw * s, (16 + bw) * s + 30 * s), fill=(0, 0, 0, 0))
    sd.rectangle((1 * s, (16 + bw / 2) * s, (bw - 1) * s, (16 + bw / 2 + 6) * s), fill=(250, 248, 244, 255))
    sd.ellipse((3 * s, 20 * s, 10 * s, 28 * s), fill=(255, 150, 160, 200))          # 반짝
    spr = spr.resize((bw, bh + 22), Image.LANCZOS)
    vis_bottom = 16 + bw / 2 + 6                          # 흰 띠 아래 = 평소 물에 닿는 선
    top_y = WATERLINE - vis_bottom + sink
    keep = int(max(0, min(spr.height, WATERLINE - top_y)))
    x = BOB_X + dx - bw / 2
    if keep > 0:
        part = spr.crop((0, 0, spr.width, keep))
        img.paste(part, (int(round(x)), int(round(top_y))), part)
    # 물에 닿는 자리의 어두운 띠 + 밝은 테
    d.ellipse((BOB_X + dx - 15, WATERLINE - 3, BOB_X + dx + 15, WATERLINE + 4), fill=(6, 10, 26, 150))
    d.arc((BOB_X + dx - 17, WATERLINE - 4, BOB_X + dx + 17, WATERLINE + 5), 0, 180, fill=(190, 210, 255, 140), width=1)
    return BOB_X + dx, top_y


def _quantize(frames: list[Image.Image]) -> list[Image.Image]:
    """프레임 몇 장에서 팔레트 한 벌을 뽑아 다 같이 써요(디더링 끔 - casino_art 슬롯 주석)."""
    picks = [frames[0], frames[len(frames) // 2], frames[-1]]
    # 🚨 찌·`!`·물방울은 화면에서 아주 작아서, 그냥 뽑으면 팔레트에서 밀려 **빨간 찌가 보라색**이 돼요.
    #    그 색들을 넉넉한 칸으로 깔아 팔레트에 자리를 잡아 줘요(이 띠는 그림에 안 들어가요).
    swatch = Image.new("RGB", (W, 60))
    sd = ImageDraw.Draw(swatch)
    keys = [(226, 52, 66), (180, 36, 50), (250, 248, 244), (250, 240, 120), (255, 214, 92),
            (255, 150, 160), (215, 230, 255), (40, 16, 30)]
    bw = W // len(keys)
    for i, c in enumerate(keys):
        sd.rectangle((i * bw, 0, (i + 1) * bw, 60), fill=c)
    picks.append(swatch)
    sheet = Image.new("RGB", (W, sum(im.height for im in picks)))
    y = 0
    for im in picks:
        sheet.paste(im, (0, y))
        y += im.height
    palette = sheet.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    return [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]


def _save(frames: list[Image.Image], durations, *, loop: bool) -> bytes:
    frames = _quantize(frames)
    buf = io.BytesIO()
    kw = {"loop": 0} if loop else {}
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                   disposal=1, optimize=True, **kw)
    return buf.getvalue()


# ── 기다리기 · 입질 (미리 만들어 두는 것) ─────────────────────────────
def render_wait() -> bytes:
    bg = _background()
    frames = []
    for f in range(WAIT_FRAMES):
        p = f / WAIT_FRAMES
        img = bg.copy()
        d = ImageDraw.Draw(img, "RGBA")
        _water_life(d, p)
        _ripples(d, p)
        top = _bobber(img, d, dx=1.2 * math.sin(2 * math.pi * p + 1), sink=2.2 * math.sin(2 * math.pi * p))
        _line(d, top)
        frames.append(img)
    return _save(frames, WAIT_MS, loop=True)


def _splash(d: ImageDraw.ImageDraw, t: float, *, cx: float = BOB_X, n: int = 14, power: float = 1.0,
            seed: int = 3) -> None:
    """물방울이 튀었다 떨어져요. t: 0~1."""
    rng = random.Random(seed)
    for _ in range(n):
        vx = rng.uniform(-70, 70) * power
        vy = rng.uniform(70, 150) * power
        r = rng.uniform(1.6, 3.4)
        x = cx + vx * t
        y = WATERLINE - (vy * t - 210 * t * t)
        if y > WATERLINE + 2:
            continue
        alpha = int(230 * (1 - t))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(215, 230, 255, alpha))


def render_bite() -> bytes:
    """찌가 쑥 들어갔다 흔들리고, 큰 물결과 물방울, 머리 위에 `!`."""
    bg = _background()
    frames = []
    sinks = [4, 9, 6, 11, 7, 12, 5, 10, 6, 11, 7, 12]      # 찌 머리가 보일 만큼만 잠겨요
    font = _font("bold", 44)
    for f in range(BITE_FRAMES):
        p = f / BITE_FRAMES
        img = bg.copy()
        d = ImageDraw.Draw(img, "RGBA")
        _water_life(d, p)
        _ripples(d, p, rings=3, grow=80, base=14, strength=200)
        _splash(d, (p * 2) % 1.0, n=10, power=0.7, seed=f // 6)
        dx = 3 * (1 if f % 2 else -1)
        top = _bobber(img, d, dx=dx, sink=sinks[f % len(sinks)])
        _line(d, (top[0], min(top[1], WATERLINE - 4)))
        # 머리 위 `!` - 커졌다 작아졌다
        size = 44 if f % 4 < 2 else 38
        fnt = font if size == 44 else _font("bold", size)
        tw = d.textlength("!", font=fnt)
        d.text((BOB_X - tw / 2, WATERLINE - 112 + (44 - size)), "!", font=fnt, fill=(255, 214, 92),
               stroke_width=4, stroke_fill=(40, 16, 30))
        frames.append(img)
    return _save(frames, BITE_MS, loop=True)


# ── 🐟 튀어오르기 (잡을 때마다 그리는 것) ──────────────────────────────
def render_catch(key: str, grade: str) -> bytes | None:
    """물고기가 물을 뚫고 튀어올라 가운데 떠요. 그림이 없는 종이면 None."""
    path = FISH_DIR / f"{key}.webp"
    if not path.exists():
        return None
    with Image.open(path) as src:
        fish = src.convert("RGBA")
    px = CATCH_PX.get(grade, 150)
    fish = fish.resize((px, px), Image.LANCZOS)
    glow_color = GLOW.get(grade, (255, 200, 90))
    halo = Image.new("RGBA", (px * 2, px * 2), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((px * 0.35, px * 0.35, px * 1.65, px * 1.65), fill=glow_color + (150,))
    halo = halo.filter(ImageFilter.GaussianBlur(px * 0.22))

    bg = _background()
    peak_y = 92                                          # 물고기 가운데가 멈추는 높이
    start_y = WATERLINE + px * 0.55
    frames, durations = [], []
    rise, settle_n, glow_n = 9, 5, 6

    def frame(cy: float, angle: float, *, t_splash: float, halo_a: float, p: float) -> Image.Image:
        img = bg.copy()
        d = ImageDraw.Draw(img, "RGBA")
        _water_life(d, p)
        _ripples(d, p, rings=3, grow=120, base=20, strength=170)
        if 0 <= t_splash <= 1:
            _splash(d, t_splash, n=26, power=1.5, seed=5)
            # 물기둥
            col_h = 70 * math.sin(math.pi * min(1.0, t_splash * 1.4))
            d.ellipse((BOB_X - 24, WATERLINE - col_h, BOB_X + 24, WATERLINE + 6), fill=(200, 220, 255, int(120 * (1 - t_splash))))
        if halo_a > 0:
            h = halo.copy()
            h.putalpha(h.getchannel("A").point(lambda v: int(v * halo_a)))
            img.paste(h, (int(BOB_X - px), int(cy - px)), h)
        spr = fish.rotate(angle, resample=Image.BICUBIC, expand=True) if angle else fish
        x, y = BOB_X - spr.width / 2, cy - spr.height / 2
        keep = int(max(0, min(spr.height, WATERLINE - y)))   # 물 아래는 안 그려요
        if keep > 0:
            part = spr.crop((0, 0, spr.width, keep))
            img.paste(part, (int(x), int(y)), part)
        return img

    k = 0
    for f in range(1, rise + 1):                         # 솟구쳐요
        t = f / rise
        e = 1 - (1 - t) ** 2
        cy = start_y + (peak_y - 18 - start_y) * e
        frames.append(frame(cy, -28 * (1 - t), t_splash=t * 0.7, halo_a=0, p=k / WAIT_FRAMES))
        durations.append(CATCH_MS)
        k += 1
    for f in range(1, settle_n + 1):                     # 살짝 내려앉아요
        t = f / settle_n
        cy = peak_y - 18 + 18 * math.sin(t * math.pi / 2)
        frames.append(frame(cy, 6 * math.sin(t * math.pi), t_splash=0.7 + 0.3 * t, halo_a=t * 0.6, p=k / WAIT_FRAMES))
        durations.append(CATCH_MS + 10)
        k += 1
    for f in range(glow_n):                              # 반짝여요
        a = 0.6 + 0.4 * (1 if f % 2 == 0 else 0)
        frames.append(frame(peak_y, 0, t_splash=2, halo_a=a, p=k / WAIT_FRAMES))
        durations.append(90)
        k += 1
    frames.append(frame(peak_y, 0, t_splash=2, halo_a=0.8, p=k / WAIT_FRAMES))
    durations.append(CATCH_HOLD_MS)
    return _save(frames, durations, loop=False)


def catch_seconds() -> float:
    """튀어오르기가 끝나는 데 걸리는 시간(마지막 장 붙들기 빼고)."""
    return (9 * CATCH_MS + 5 * (CATCH_MS + 10) + 6 * 90) / 1000


async def catch_gif(key: str, grade: str) -> bytes | None:
    """🚨 예외를 안 올려요. 실패하면 None(부른 쪽은 원래 그림으로)."""
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(render_catch, key, grade)
        except Exception:                                # noqa: BLE001
            log.exception("🐟 튀어오르기 GIF를 못 그렸어요 (%s) - 원래 그림으로", key)
            return None


def wait_path() -> Path | None:
    return WAIT_FILE if WAIT_FILE.exists() else None


def bite_path() -> Path | None:
    return BITE_FILE if BITE_FILE.exists() else None
