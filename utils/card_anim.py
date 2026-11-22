"""🎴 카드 뽑기 연출 GIF (2026-11-23). 엎어진 카드가 올라오고 → 등급 빛이 새어 나오고 → 한 장씩 뒤집혀요.

## 왜 만들었나

슬롯·블랙잭·낚시는 움직이는데 **뽑기만 결과 그림이 툭 떴어요.** 가챠의 재미는 "뭐가 나올까"
하는 몇 초라서, 그 몇 초를 그림으로 만들어요.

## 어떻게 그리나 — 마지막 장 = 지금의 결과 그림

`card_render.render_pull()`이 그린 **결과 PNG를 그대로 마지막 장**으로 써요. 카드 앞면도
그 PNG에서 칸째 잘라 와요. 그래서

- 연출이 끝난 화면과 그 뒤에 바꿔 끼우는 결과 그림이 **한 픽셀도 안 어긋나요**
- 카드 배치(1뽑기 = 큰 카드 한 줄, 연속뽑기 = 썸네일 격자)를 **두 벌로 관리하지 않아요**
  (`card_render._pull_layout`을 같이 써요)

## 순서

1. 엎어진 카드가 아래에서 올라와요 (한 줄씩 살짝 엇갈려서)
2. 🔮 **등급 빛** — 카드 뒷면 테두리에서 등급 색 빛이 새어 나와요. 🟣에픽은 떨리고,
   🟡레전드는 금빛 줄기가 뒤에서 뻗어요. "뭔가 온다"는 예고예요
3. 뒤집기 — **낮은 등급부터** 뒤집어요(자리 순서가 아니라). 제일 좋은 카드가 마지막이에요.
   연속뽑기는 일반·레어를 물결처럼 한 번에 넘기고, 에픽·레전드만 한 장씩 따로 넘겨요
4. 레전드는 뒤집는 순간 하얗게 번쩍이고 반짝이가 흩어져요

## 크기·메모리

디스코드 임베드는 그림을 ~550px 폭으로 줄여 보여줘요. 그래서 GIF는 **폭 640px로 줄여서**
만들어요(30장 격자는 원본이 1076×1547이라 그대로면 프레임마다 5MB예요). 연출이 끝나면
원래 크기 PNG로 바꿔 끼우니, 눌러서 크게 보는 사람도 손해가 없어요.
프레임은 그리자마자 팔레트로 줄여서(P 모드) 쌓아요 — 블랙잭 때 RGB로 쌓았다가 46MB가 됐어요.

🚨 GIF 시간은 10ms 단위라 프레임 시간도 10의 배수로 둬요(`casino_art` 주석).
"""
import asyncio
import io
import logging
import math
import random

from utils.card_render import (BG_BOTTOM, BG_TOP, GAP, LABEL_H, PAD, PILLOW_AVAILABLE, _pull_layout, _rgb,
                               _vertical_gradient)
from utils.card_store import GRADE_COLOR
from utils.profile_card import _RENDER_LOCK, _font

log = logging.getLogger(__name__)

if PILLOW_AVAILABLE:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

FRAME_MS = 40
HOLD_MS = 30_000          # 마지막 장(그 전에 결과 PNG로 바꿔요)
GIF_W = 640               # GIF 폭 (임베드가 어차피 이만큼으로 줄여 보여줘요)
COLORS = 250
MAX_BYTES = 7 * 1024 * 1024      # 이보다 크면 연출을 건너뛰어요 (pull_anim 주석)
RANK = {"일반": 0, "레어": 1, "에픽": 2, "레전드": 3}
GOLD = (255, 214, 92)
BACK_TOP = (58, 26, 92)
BACK_BOTTOM = (24, 10, 44)


# ── 판 짜기 ─────────────────────────────────────────────────────────
def _cells(n: int):
    """`card_render._render`와 **똑같은 계산**으로 칸 위치를 내요. (칸 x, 칸 y, 칸 폭, 카드 높이, 라벨 포함 높이)"""
    cols, slot_w, slot_h, use_thumb = _pull_layout(n)
    label_h = LABEL_H if not use_thumb else 54
    cell_h = slot_h + label_h
    out = []
    for i in range(n):
        x = PAD + (i % cols) * (slot_w + GAP)
        y = PAD + (i // cols) * (cell_h + GAP)
        out.append((x, y, slot_w, slot_h, cell_h))
    return out, cols, use_thumb


def _card_back(w: int, h: int) -> "Image.Image":
    """악귀카드 뒷면. 보라 그라데이션 + 금테 + 가운데 문양."""
    back = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    body = _vertical_gradient((w, h), BACK_TOP, BACK_BOTTOM).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    r = max(6, w // 18)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    back.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(back)
    edge = max(2, w // 60)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=GOLD, width=edge)
    inset = max(6, w // 14)
    d.rounded_rectangle((inset, inset, w - 1 - inset, h - 1 - inset), radius=max(4, r - 4),
                        outline=(180, 140, 70), width=max(1, edge // 2))
    # 비스듬한 무늬. 🚨 따로 그려서 **섞어** 얹어요 — RGBA 그림에 반투명 색으로 바로 선을 그으면
    #    섞이지 않고 그 픽셀이 반투명으로 **바뀌어서**, 뒤에 깐 빛이 선 모양으로 비쳐 보였어요.
    step = max(10, w // 10)
    lines = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    for k in range(-h, w + h, step):
        ld.line([(k, inset), (k + h // 3, h - inset)], fill=(255, 255, 255, 14), width=1)
    lines.putalpha(ImageChops.multiply(lines.getchannel("A"), mask))
    back.alpha_composite(lines)
    d = ImageDraw.Draw(back)
    # 가운데 문양: 겹친 마름모 + 글자
    cx, cy = w / 2, h / 2
    s = w * 0.26
    d.polygon([(cx, cy - s * 1.25), (cx + s, cy), (cx, cy + s * 1.25), (cx - s, cy)],
              outline=GOLD, width=max(2, edge))
    s2 = s * 0.7
    d.polygon([(cx, cy - s2 * 1.25), (cx + s2, cy), (cx, cy + s2 * 1.25), (cx - s2, cy)],
              fill=(90, 40, 130), outline=(220, 180, 90), width=1)
    font = _font("bold", max(14, int(w * 0.13)))
    text = "악귀"
    tw = d.textlength(text, font=font)
    d.text((cx - tw / 2, cy - font.size * 0.62), text, font=font, fill=GOLD,
           stroke_width=max(1, w // 150), stroke_fill=(40, 16, 60))
    return back


def _glow(w: int, h: int, color, spread: int) -> "Image.Image":
    """카드 모양 그대로 번지는 빛. (w+2s)×(h+2s) RGBA."""
    g = Image.new("RGBA", (w + spread * 2, h + spread * 2), color + (0,))
    m = Image.new("L", g.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((spread, spread, spread + w, spread + h), radius=max(6, w // 18), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(spread / 2.2))
    g.putalpha(m)
    return g


def _with_alpha(im: "Image.Image", k: float) -> "Image.Image":
    if k >= 0.999:
        return im
    out = im.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * max(0.0, k))))
    return out


def _paste(base, layer, x, y):
    x, y = int(round(x)), int(round(y))
    base.alpha_composite(layer, (max(0, x), max(0, y)),
                         (max(0, -x), max(0, -y)))


def _rays_layer(radius: int) -> "Image.Image":
    """레전드 뒤로 뻗는 빛줄기 한 벌. 한 번만 그려 두고 프레임마다 돌려 써요(매번 흐리게 하면 느려요)."""
    size = radius * 2 + 16
    layer = Image.new("RGBA", (size, size), GOLD + (0,))
    d = ImageDraw.Draw(layer)
    c = size / 2
    for k in range(12):
        a = k * math.pi / 6
        a2 = a + 0.13
        d.polygon([(c, c), (c + math.cos(a) * radius, c + math.sin(a) * radius),
                   (c + math.cos(a2) * radius, c + math.sin(a2) * radius)], fill=GOLD + (255,))
    return layer.filter(ImageFilter.GaussianBlur(5))


def _flash_layer(w: int, h: int, pad: int) -> "Image.Image":
    """레전드가 뒤집히는 순간의 하얀 번쩍임."""
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (255, 250, 230, 0))
    ImageDraw.Draw(layer).rounded_rectangle((pad // 2, pad // 2, w + pad * 3 // 2, h + pad * 3 // 2),
                                            radius=pad, fill=(255, 226, 140, 170))    # 흰색은 어두운 바탕에서 회색 안개처럼 보여서 금빛으로
    return layer.filter(ImageFilter.GaussianBlur(pad / 2.5))


def _sparkles(d, cx, cy, w, h, t, seed):
    """뒤집힌 레전드 둘레로 흩어지는 반짝이. t: 0→1."""
    rnd = random.Random(seed)
    for _ in range(18):
        ang = rnd.uniform(0, math.tau)
        dist = (0.35 + 0.65 * t) * rnd.uniform(0.45, 0.75) * max(w, h)
        x = cx + math.cos(ang) * dist
        y = cy + math.sin(ang) * dist * 0.8
        s = max(1.5, (1 - t) * rnd.uniform(3, 7) * (w / 190 + 0.3))
        c = (255, 246, 200) if rnd.random() < 0.6 else GOLD
        d.polygon([(x, y - s * 2), (x + s * 0.5, y), (x, y + s * 2), (x - s * 0.5, y)], fill=c)
        d.polygon([(x - s * 2, y), (x, y + s * 0.5), (x + s * 2, y), (x, y - s * 0.5)], fill=c)


# ── 시간표 ───────────────────────────────────────────────────────────
RISE_F = 8         # 올라오는 장 수
FLIP_LOW = 6       # 일반·레어 뒤집기
FLIP_HIGH = 8      # 에픽·레전드 뒤집기 (조금 더 뜸 들여요)
AFTER = {"일반": 3, "레어": 3, "에픽": 7, "레전드": 12}    # 뒤집힌 뒤 숨 고르기
SPARKLE_F = 12


FUSE_F = 12        # ⚒️ 합성: 재료 3장이 모여 한 장이 되는 장 수 (RISE_F 대신)


def _timeline(drawn, cols, big, intro=RISE_F):
    """카드마다 (등장 시작, 뒤집기 시작, 뒤집기 길이) 프레임 번호. 그리고 전체 길이."""
    n = len(drawn)
    rise = [(i // cols) * 2 + (i % cols) * (2 if big else 0) for i in range(n)]
    rise_end = max(rise) + intro
    charge_end = rise_end + (12 if big else 9)
    flip_at, flip_len = [0] * n, [0] * n
    t = charge_end
    if big:
        # 낮은 등급부터 한 장씩. 같은 등급이면 왼쪽부터.
        for i in sorted(range(n), key=lambda i: (RANK[drawn[i]["grade"]], i)):
            g = drawn[i]["grade"]
            flip_at[i] = t
            flip_len[i] = FLIP_LOW if RANK[g] < 2 else FLIP_HIGH
            t += flip_len[i] + AFTER[g]
    else:
        # 연속뽑기: 일반·레어는 세 장씩 물결처럼, 🟣에픽은 **한꺼번에**, 🟡레전드만 한 장씩.
        #    (에픽까지 한 장씩 넘기면 에픽 5장 나온 10연이 134장·4.7MB가 됐어요)
        low = [i for i in range(n) if RANK[drawn[i]["grade"]] < 2]
        epics = [i for i in range(n) if drawn[i]["grade"] == "에픽"]
        legends = [i for i in range(n) if drawn[i]["grade"] == "레전드"]
        for k, i in enumerate(low):
            flip_at[i], flip_len[i] = t + k // 3, FLIP_LOW
        if low:
            t += (len(low) - 1) // 3 + FLIP_LOW + 3
        for i in epics:
            flip_at[i], flip_len[i] = t, FLIP_HIGH
        if epics:
            t += FLIP_HIGH + AFTER["에픽"]
        for i in legends:
            flip_at[i], flip_len[i] = t, FLIP_HIGH
            t += FLIP_HIGH + AFTER["레전드"]
    return rise, rise_end, charge_end, flip_at, flip_len, t + 1


def _ease_out(t):
    return 1 - (1 - t) ** 3


# ── 그리기 ───────────────────────────────────────────────────────────
def _build(drawn: list[dict], still_png: bytes, fuse: bool = False):
    """프레임(P 모드)과 시간 목록. 🚨 **처음부터 줄인 크기로** 그려요 — 원래 크기로 그린 뒤
    줄였더니 30장 격자에서 36초가 걸렸어요(프레임마다 1076×1547을 합성).

    `fuse=True`(⚒️ 합성)면 첫 장면만 달라요: 아래에서 올라오는 대신 **작은 재료 카드 3장이
    사방에서 모여들어 번쩍하고 한 장이 돼요.** 그 뒤(등급 빛·뒤집기)는 뽑기와 같아요."""
    full = Image.open(io.BytesIO(still_png)).convert("RGB")
    W, H = full.size
    n = len(drawn)
    cells_full, cols, use_thumb = _cells(n)
    big = not use_thumb
    sc = min(1.0, GIF_W / W)
    size = (max(1, round(W * sc)), max(1, round(H * sc)))
    still = full.resize(size, Image.LANCZOS) if sc < 1 else full
    del full

    def S(v):
        return int(round(v * sc))

    # 줄인 좌표계에서의 칸 (x, y, 카드 폭, 카드 높이, 라벨 포함 높이)
    cells = [(S(x), S(y), S(w), S(h), S(c)) for x, y, w, h, c in cells_full]
    cw, ch = cells[0][2], cells[0][3]
    bg = _vertical_gradient(size, BG_TOP, BG_BOTTOM).convert("RGBA")
    back = _card_back(cw, ch)
    spread = max(8, S(22 if big else 16))
    glows = {g: _glow(cw, ch, _rgb(GRADE_COLOR[g]), spread) for g in RANK}
    # 앞면 = 결과 그림에서 칸째 잘라 와요 (등급 테두리가 칸 밖으로 4px 나가서 조금 넉넉히)
    m = max(3, S(6))
    faces = [still.crop((x - m, y - m, x + w + m, y + h + m)).convert("RGBA") for x, y, w, h, _ in cells]
    labels = [still.crop((x - m, y + h + m, x + w + m, y + c)).convert("RGBA") for x, y, w, h, c in cells]
    rays = _rays_layer(int(max(cw, ch) * 0.85)) if any(d["grade"] == "레전드" for d in drawn) else None
    flash = _flash_layer(cw, ch, max(10, S(30)))

    # 🎨 팔레트를 **먼저** 정해요. 마지막 장(=결과 그림)은 처음부터 알고 있고, 나머지 색은
    #    뒷면·등급 빛뿐이라 미리 깔아볼 수 있어요. 그래야 프레임을 그리자마자 P 모드로 줄여
    #    쌓을 수 있어요(RGB로 쌓으면 30장 격자에서 100MB를 넘어요).
    sample = bg.copy()
    for k, g in enumerate(RANK):
        gx = int(size[0] * (k + 0.5) / 4 - cw / 2)
        _paste(sample, glows[g], gx - spread, 4)
        _paste(sample, back, gx, 4 + spread)
    palette = _palette([still, sample.convert("RGB")])

    intro = FUSE_F if fuse else RISE_F
    rise, rise_end, charge_end, flip_at, flip_len, total = _timeline(drawn, cols, big, intro)
    mini = back.resize((max(1, int(cw * 0.5)), max(1, int(ch * 0.5))), Image.BILINEAR) if fuse else None
    merge_spread = spread * 2
    merge_glow = _glow(cw, ch, GOLD, merge_spread) if fuse else None
    # 재료 3장이 출발하는 곳 (카드 가운데 기준, 왼쪽 위 · 오른쪽 위 · 아래)
    starts = [(-0.75, -0.35), (0.75, -0.35), (0.0, 0.7)]
    frames, durations = [], []

    def push(img, ms=FRAME_MS):
        frames.append(img.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE))
        durations.append(ms)

    for f in range(total):
        img = bg.copy()
        d = ImageDraw.Draw(img)
        for i, (x, y, w, h, c) in enumerate(cells):
            g = drawn[i]["grade"]
            rank = RANK[g]
            if f < rise[i]:
                continue
            if fuse:
                t_ = f - rise[i]
                gather = FUSE_F - 3
                if t_ < gather:
                    # ⚒️ 재료 3장이 가운데로 모여요 (가까워질수록 작아지며 겹쳐요)
                    e = _ease_out((t_ + 1) / gather)
                    cx, cy = x + w / 2, y + h / 2
                    for sxr, syr in starts:
                        px = cx + sxr * w * (1 - e) - mini.width / 2
                        py = cy + syr * h * (1 - e) - mini.height / 2
                        _paste(img, _with_alpha(mini, 0.55 + 0.45 * e), px, py)
                    continue
                if t_ < FUSE_F:
                    # 번쩍 → 한 장의 뒷면. 🚨 빛은 카드 **뒤에서** 터뜨려요 — 위에 덮었더니 팔레트가
                    #    중간 색을 못 내서 카드가 갈색 줄무늬로 얼룩졌어요.
                    strength = (1.0, 0.7, 0.4)[min(2, t_ - gather)]
                    _paste(img, _with_alpha(merge_glow, strength), x - merge_spread, y - merge_spread)
                    _paste(img, back, x, y)
                    continue
                k, dy, fade = 1.0, 0.0, 1.0
            else:
                k = min(1.0, (f - rise[i]) / RISE_F)
                dy = (1 - _ease_out(k)) * (h * 0.35)
                fade = min(1.0, 0.25 + k)
            fa, fl = flip_at[i], flip_len[i]
            if f >= fa + fl:
                # 뒤집힌 뒤
                _paste(img, faces[i], x - m, y - m)
                _paste(img, labels[i], x - m, y + h + m)
                since = f - (fa + fl)
                if g == "레전드" and since < 2:          # 번쩍임이 앞면 위로 빠르게 걷혀요
                    _paste(img, _with_alpha(flash, 0.5 - since * 0.25), x - (flash.width - w) / 2,
                           y - (flash.height - h) / 2)
                if g == "레전드" and since < SPARKLE_F:
                    _sparkles(d, x + w / 2, y + h / 2, w, h, since / SPARKLE_F, seed=i)
                elif g == "에픽" and since < 6:
                    _paste(img, _with_alpha(glows[g], (6 - since) / 6), x - spread, y - spread)
                continue
            # 등급 빛 — 1뽑기는 모든 카드, 연속뽑기는 에픽·레전드만 (전부 빛나면 정신없어요)
            jx = 0.0
            if rise_end <= f < fa and (big or rank >= 2):      # 뒤집기 시작하면 빛은 꺼요(좁아진 카드 뒤에 빛 상자만 남아요)
                pulse = 0.55 + 0.45 * math.sin((f - rise_end) / 6 * math.pi)
                strength = {0: 0.35, 1: 0.6, 2: 0.85, 3: 1.0}[rank] * pulse
                if rays is not None and g == "레전드":
                    r = rays.rotate(-f * 4, resample=Image.BILINEAR)
                    _paste(img, _with_alpha(r, 0.45 * pulse), x + w / 2 - r.width / 2, y + h / 2 - r.height / 2)
                _paste(img, _with_alpha(glows[g], strength), x - spread, y - spread + dy)
                if rank >= 2 and f >= charge_end - 6 and f < fa:
                    jx = (1.5 if g == "에픽" else 3) * (1 if f % 2 else -1) * (w / 190 + 0.3)
            # 뒤집기: 뒷면이 좁아졌다가 앞면이 넓어져요
            if f >= fa:
                p = (f - fa + 1) / fl
                if p <= 0.5:
                    layer = back.resize((max(1, int(w * (1 - p * 2))), h), Image.BILINEAR)
                    _paste(img, layer, x + (w - layer.width) / 2, y)
                else:
                    fw = max(1, int(faces[i].width * (p - 0.5) * 2))
                    layer = faces[i].resize((fw, faces[i].height), Image.BILINEAR)
                    _paste(img, layer, x - m + (faces[i].width - fw) / 2, y - m)
                if g == "레전드" and f - fa >= fl - 2:
                    # 🚨 번쩍임은 **반투명하게 짧게.** 진하게 두 장 이상 깔았더니 카드를 가린 노란 판이 됐어요.
                    k_ = 0.45 if f - fa == fl - 2 else 0.8
                    _paste(img, _with_alpha(flash, k_), x - (flash.width - w) / 2, y - (flash.height - h) / 2)
                continue
            _paste(img, _with_alpha(back, fade), x + jx, y + dy)
        push(img)

    push(still.convert("RGBA"), HOLD_MS)
    return frames, durations


def _palette(picks):
    """결과 그림 + 뒷면·빛 견본 + 등급 색 띠로 팔레트 한 벌 (fish_anim과 같은 방식, 디더링 끔)."""
    w = picks[0].width
    swatch = Image.new("RGB", (w, 48))
    sd = ImageDraw.Draw(swatch)
    keys = [_rgb(GRADE_COLOR[g]) for g in RANK] + [GOLD, (255, 250, 230), (255, 246, 200),
                                                   BACK_TOP, BACK_BOTTOM, (180, 140, 70)]
    bw = max(1, w // len(keys))
    for i, c in enumerate(keys):
        sd.rectangle((i * bw, 0, (i + 1) * bw, 48), fill=c)
    picks = list(picks) + [swatch]
    sheet = Image.new("RGB", (w, sum(p.height for p in picks)))
    y = 0
    for p in picks:
        sheet.paste(p, (0, y))
        y += p.height
    return sheet.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def render_pull_anim(drawn: list[dict], still_png: bytes, fuse: bool = False) -> tuple[bytes, float]:
    """(GIF, 연출 초). 마지막 장은 결과 PNG와 같은 그림이에요."""
    pal, durations = _build(drawn, still_png, fuse)
    buf = io.BytesIO()
    # loop 키 없음 = 한 번만 재생
    pal[0].save(buf, "GIF", save_all=True, append_images=pal[1:], duration=durations,
                disposal=1, optimize=True)
    return buf.getvalue(), sum(durations[:-1]) / 1000


async def pull_anim(drawn: list[dict], still_png: bytes | None, *,
                    fuse: bool = False) -> tuple[bytes, float] | None:
    """밖에서 부르는 문. 실패하면 None — 부른 쪽은 예전처럼 결과 그림만 보내요.
    `fuse=True`면 ⚒️ 합성용 첫 장면(재료 3장이 모여요)."""
    if not PILLOW_AVAILABLE or not drawn or not still_png:
        return None
    async with _RENDER_LOCK:
        try:
            out = await asyncio.to_thread(render_pull_anim, drawn, still_png, fuse)
        except Exception:                                # noqa: BLE001
            log.exception("🎴 뽑기 연출을 못 그렸어요 - 결과 그림만 보내요 (%s)",
                          [d.get("key") for d in drawn])
            return None
    # 🚨 보통 10연은 1~2MB인데, 에픽·레전드가 잔뜩 나오면 빛·떨림 장면이 늘어 20MB까지 커져요
    #    (테스트에서 30장 전부 에픽·레전드 → 19.6MB). 업로드 한도에 걸리면 실패하니 그땐 연출을 건너뛰어요.
    if len(out[0]) > MAX_BYTES:
        log.warning("🎴 뽑기 연출이 너무 커서(%.1fMB) 결과 그림만 보내요", len(out[0]) / 1e6)
        return None
    return out
