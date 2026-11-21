# -*- coding: utf-8 -*-
"""🎰 도박장 그림 (2026-11-22) — 슬롯(움직이는 GIF) · 하이로우 · 블랙잭 · 현황 배너.

그림 재료는 `assets/casino/`에 있어요(`scripts/build_casino_assets.py`가 만들어요):
`hall.webp`(도박장 배경) · `felt.webp`(블랙잭 테이블) · `cardback.webp`(카드 뒷면) ·
`sym_*.webp`(슬롯 심볼, 배경 투명).

## 규칙

🚨 **그림은 덤이에요.** 여기 함수가 죽어도 게임은 돌아가야 해요 — 코인은 그림보다 먼저
   정산돼 있어요. 그래서 바깥에서 부르는 `*_card()`는 실패하면 **None**을 돌려주고, 부른 쪽
   (`cogs/casino.py`)은 그때 예전처럼 글만 보내요.
🚨 **확률·배당을 여기서 정하지 않아요.** 결과는 `utils/casino_games.py`가 정하고, 여기는 받은
   결과를 **그리기만** 해요. 숫자(배당·구간)도 전부 그쪽 상수에서 읽어요 — 손으로 적으면
   배당표를 고쳤을 때 그림만 옛 값으로 남아요.
⚠️ Pillow는 CPU 일이라 전부 스레드에서 돌리고, 동시에 그리는 수는 프로필 카드와 같은
   `_RENDER_LOCK`으로 묶어요. 재료를 **메모리에 캐시하지 않아요**(운영 머신 RAM).
⚠️ 그림 속 글자엔 이모지를 넣지 마세요 — 나눔고딕엔 이모지가 없어서 □로 나와요.
⚠️ 바탕(캔버스)은 **RGB**, 얹는 조각만 RGBA예요. RGBA 캔버스에 `ImageDraw`로 반투명 색을
   칠하면 섞이지 않고 **덮어써요**(알파까지 바뀌어요). RGB 캔버스 + `Draw(img, "RGBA")`라야 섞여요.
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import random
import re
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from utils import casino_games as games
from utils.profile_card import _RENDER_LOCK, _font

log = logging.getLogger(__name__)

ART_DIR = Path(__file__).resolve().parent.parent / "assets" / "casino"

GOLD = (255, 205, 96)
GOLD_DARK = (150, 104, 32)
INK = (22, 12, 40)             # 도박장 기본 어둠(보라빛 검정)
PANEL = (38, 22, 64)
TEXT = (248, 242, 255)
MUTED = (176, 160, 204)
WIN = (118, 236, 150)
LOSE = (176, 172, 190)
RED = (236, 78, 92)


# ── 공용 ──────────────────────────────────────────────────────────────
def _load(name: str, mode: str = "RGBA") -> Image.Image | None:
    """`assets/casino/<name>.webp`. 없거나 깨졌으면 None(부른 쪽이 물러나요)."""
    path = ART_DIR / f"{name}.webp"
    try:
        with Image.open(path) as src:
            im = src.convert(mode)
    except Exception:                                    # noqa: BLE001
        log.warning("🎰 도박장 그림 재료를 못 읽었어요(%s)", path.name, exc_info=True)
        return None
    # 🚨 WebP가 `info`에 남기는 `loop`·`background`·`duration`을 지워요. 안 지우면 이 그림에서
    #    만든 프레임을 GIF로 저장할 때 **그 값이 따라 들어가요**(슬롯 GIF가 `loop=1`로 저장돼
    #    두 번 돌았어요 - Pillow는 첫 프레임의 info를 저장 옵션의 기본값으로 써요).
    im.info.clear()
    return im


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """비율을 지키며 꽉 채우고 넘치는 쪽을 가운데 기준으로 잘라요."""
    scale = max(w / im.width, h / im.height)
    size = (max(w, round(im.width * scale)), max(h, round(im.height * scale)))
    if size != im.size:
        im = im.resize(size, Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _backdrop(w: int, h: int, *, dark: float = 0.5, blur: float = 2.5) -> Image.Image:
    """도박장 배경을 깔고 어둡게 눌러요(글씨·기계가 떠 보이게). RGB.

    그림이 없으면 보라 그라데이션으로 물러나요."""
    hall = _load("hall", "RGB")
    if hall is None:
        bg = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(bg)
        for y in range(h):
            t = y / max(1, h - 1)
            d.line([(0, y), (w, y)], fill=(int(52 - 28 * t), int(28 - 14 * t), int(88 - 44 * t)))
        return bg
    bg = _cover(hall, w, h)
    if blur:
        bg = bg.filter(ImageFilter.GaussianBlur(blur))
    return Image.blend(bg, Image.new("RGB", (w, h), INK), dark)


def _paste(base: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """RGBA 조각을 알파를 살려 얹어요. 화면 밖으로 삐져나가는 부분은 잘라요(음수 좌표 가능)."""
    x, y = int(x), int(y)
    sx, sy = max(0, -x), max(0, -y)
    w = min(layer.width - sx, base.width - max(0, x))
    h = min(layer.height - sy, base.height - max(0, y))
    if w <= 0 or h <= 0:
        return
    if (sx, sy, w, h) != (0, 0, layer.width, layer.height):
        layer = layer.crop((sx, sy, sx + w, sy + h))
    if base.mode == "RGBA":
        base.alpha_composite(layer, (max(0, x), max(0, y)))
    else:
        base.paste(layer, (max(0, x), max(0, y)), layer)


def _center(d: ImageDraw.ImageDraw, cx: float, y: float, text: str, font, fill, **kw) -> None:
    d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill, **kw)


def _jpeg(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=90, subsampling=0, optimize=True)
    return buf.getvalue()


def _clean(note: str) -> str:
    """`casino_games`의 결과 문구에서 그림에 적을 **앞 토막**만 남겨요.

    마크다운(`**`)·이모지를 걷어내고, 긴 설명(` — ` 뒤)은 잘라요(그건 글에 그대로 있어요)."""
    head = re.split(r"\s+[—–-]\s+", note, maxsplit=1)[0]
    return re.sub(r"\s+", " ", re.sub(r"[^0-9A-Za-z가-힣 !?…·()~.,:]", "", head)).strip()


# ── 🎰 슬롯 ───────────────────────────────────────────────────────────
# 심볼 그림. **이모지로 묶어요** — 순서(인덱스)로 묶으면 `SLOT_SYMBOLS` 순서를 바꿨을 때
# 그림만 엇갈려요(💎가 나왔는데 폭탄이 그려지는 식). test_casino_art가 짝을 검사해요.
SLOT_ART = {"💣": "sym_bomb", "🔫": "sym_gun", "🛡️": "sym_shield", "💎": "sym_diamond"}

SLOT_W, SLOT_H = 480, 300
SLOT_PANEL = (20, 12, SLOT_W - 20, 242)
REEL_W, REEL_H, REEL_GAP, REEL_TOP = 116, 126, 14, 58
REEL_LEFT = (SLOT_W - (REEL_W * 3 + REEL_GAP * 2)) // 2
# 릴이 들어앉는 어두운 칸. **움직이는 부분은 전부 이 칸 + 그 아래 결과 띠** 안이에요.
SLOT_BAY = (REEL_LEFT - 16, REEL_TOP - 10, REEL_LEFT + REEL_W * 3 + REEL_GAP * 2 + 16, REEL_TOP + REEL_H + 10)
SLOT_DYN = (SLOT_BAY[0], SLOT_BAY[1], SLOT_BAY[2], 236)     # 프레임마다 다시 그리는 범위
CELL = 106                 # 심볼 한 칸 높이(스크롤 단위)
SYMBOL_PX = 92
SMEAR_PX = 30              # 빠르게 돌 때 위아래로 번지는 길이
FRAME_MS = 70
REEL_STOP_MS = (910, 1470, 2030)      # 릴이 하나씩 멈추는 시각 (FRAME_MS의 배수여야 딱 멈춘 장이 나와요)
REEL_SPEED = 2.1                      # 도는 동안의 속도(px/ms)
BRAKE_MS, BRAKE_PX = 280, 150         # 멈추기 직전 감속 구간
FLASH_FRAMES, FLASH_MS = 6, 110       # 세 개 일치 때 번쩍이는 장 수 · 한 장 시간
HOLD_MS = 30_000                      # 마지막 장을 붙들어두는 시간(그 전에 정지 그림으로 바꿔요)
SLOT_COLORS = 224                     # GIF 색 수(256 한도. 남는 칸은 Pillow가 투명색으로 써요)


def slot_seconds(multiplier: int) -> float:
    """릴이 다 멈추고 번쩍임까지 끝나는 데 걸리는 시간(초). 부른 쪽이 이만큼 기다렸다 결과를 띄워요."""
    flash = FLASH_FRAMES * FLASH_MS if multiplier > games.SLOT_PAIR_PAYOUT else 0
    return (REEL_STOP_MS[-1] + flash) / 1000


def slot_banner(multiplier: int) -> tuple[str, tuple[int, int, int]]:
    """릴 아래 띠에 적을 한 줄. 배당 숫자는 받은 값 그대로 써요."""
    if multiplier > games.SLOT_PAIR_PAYOUT:
        return f"세 개 일치!  {multiplier}배", GOLD
    if multiplier == games.SLOT_PAIR_PAYOUT:
        return "두 개 일치 · 본전", TEXT
    return "꽝", LOSE


def _slot_sprites() -> dict[str, tuple[Image.Image, Image.Image]] | None:
    """이모지 → (또렷한 그림, 세로로 번진 그림). 하나라도 없으면 None."""
    out = {}
    for emoji, name in SLOT_ART.items():
        im = _load(name)
        if im is None:
            return None
        im = im.resize((SYMBOL_PX, SYMBOL_PX), Image.LANCZOS)
        # 빠르게 돌 때 쓰는 **세로 번짐**(위아래로만 뭉개요). 한 번만 만들어 프레임마다 재사용해요.
        # ⚠️ 번지기 전에 `RGBa`(알파를 미리 곱한 색)로 바꿔요. 그냥 RGBA로 번지면 투명한 칸의
        #    색(보통 검정)이 섞여 들어와 가장자리가 거뭇해져요.
        pad = Image.new("RGBA", (SYMBOL_PX, SYMBOL_PX + SMEAR_PX * 2), (0, 0, 0, 0))
        pad.paste(im, (0, SMEAR_PX))
        smear = pad.convert("RGBa").filter(ImageFilter.BoxBlur((0, SMEAR_PX))).convert("RGBA")
        out[emoji] = (im, smear)
    return out


def _reel_shade() -> Image.Image:
    """릴 창 위아래를 어둡게 눌러 원통처럼 보이게 하는 덮개(RGBA)."""
    shade = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    edge = 36
    for y in range(edge):
        a = int(170 * (1 - y / edge) ** 1.7)
        d.line([(0, y), (REEL_W, y)], fill=(34, 18, 56, a))
        d.line([(0, REEL_H - 1 - y), (REEL_W, REEL_H - 1 - y)], fill=(34, 18, 56, a))
    return shade


def _reel_offset(t_ms: float, stop_ms: int, cells: int) -> tuple[float, bool]:
    """그 시각의 릴 위치(px)와 '빠르게 도는 중인가'. 끝나면 정확히 `cells * CELL`에 서요."""
    final = cells * CELL
    if t_ms >= stop_ms:
        return float(final), False
    left = stop_ms - t_ms
    if left > BRAKE_MS:                       # 일정한 속도로 도는 구간
        return final - (BRAKE_PX + (left - BRAKE_MS) * REEL_SPEED), True
    q = 1 - left / BRAKE_MS                   # 0 → 1 : 감속하며 멈춰요
    return final - BRAKE_PX * (1 - q) ** 2, False


def _slot_reels(symbols: list[str]) -> list[tuple[int, int, list[str]]]:
    """릴마다 (멈추는 시각, 멈추는 칸 번호, 칸 목록). **`칸 목록[멈추는 칸]`이 진짜 결과**예요.

    나머지 칸은 도는 동안 스쳐 가는 꾸밈이에요. 같은 결과면 늘 같은 그림이 나오게 씨앗을 결과로 정해요."""
    rng = random.Random(zlib.crc32("".join(symbols).encode()))
    names = list(SLOT_ART)
    reels = []
    for r, stop in enumerate(REEL_STOP_MS):
        cells = math.ceil((BRAKE_PX + (stop - BRAKE_MS) * REEL_SPEED) / CELL) + 2
        seq: list[str] = []
        for _ in range(cells + 2):
            seq.append(rng.choice([n for n in names if not seq or n != seq[-1]]))
        seq[cells] = symbols[r]                 # 멈추는 칸 = 진짜 결과
        for j in (cells - 1, cells + 1):        # 위아래 칸이 결과와 같으면 '일치'로 보여요 → 바꿔요
            if seq[j] == symbols[r]:
                seq[j] = rng.choice([n for n in names if n != symbols[r]])
        reels.append((stop, cells, seq))
    return reels


def _slot_build(symbols: list[str], multiplier: int) -> tuple[list[Image.Image], list[int], Image.Image] | None:
    """(GIF 프레임들(P), 프레임별 시간, 마지막 정지 그림(RGB)). 재료가 없으면 None."""
    sprites = _slot_sprites()
    if sprites is None or len(symbols) != 3 or any(s not in sprites for s in symbols):
        return None

    # ── 안 움직이는 바탕 ──
    base = _backdrop(SLOT_W, SLOT_H)
    d = ImageDraw.Draw(base, "RGBA")
    d.rounded_rectangle(SLOT_PANEL, 24, fill=PANEL + (240,), outline=GOLD, width=3)
    d.rounded_rectangle((SLOT_PANEL[0] + 7, SLOT_PANEL[1] + 7, SLOT_PANEL[2] - 7, SLOT_PANEL[3] - 7), 18,
                        outline=GOLD_DARK + (180,), width=1)
    _center(d, SLOT_W / 2, 20, "악귀 슬롯", _font("bold", 23), GOLD, stroke_width=2, stroke_fill=INK)
    d.rounded_rectangle(SLOT_BAY, 16, fill=INK)
    # 배당표 한 줄 — `SLOT_SYMBOLS`에서 읽어요(손으로 적지 않아요).
    pay_font, note_font = _font("bold", 17), _font("regular", 15)
    pair_note = "두 개 = 본전" if games.SLOT_PAIR_PAYOUT == 1 else f"두 개 = {games.SLOT_PAIR_PAYOUT}배"
    note_w = d.textlength(pair_note, font=note_font)
    step = (SLOT_W - 52 - note_w - 14) / max(1, len(games.SLOT_SYMBOLS))
    d.rounded_rectangle((20, 252, SLOT_W - 20, 290), 14, fill=INK + (200,))
    for i, (emoji, mult) in enumerate(games.SLOT_SYMBOLS):
        x = 32 + int(i * step)
        if emoji in sprites:
            _paste(base, sprites[emoji][0].resize((30, 30), Image.LANCZOS), x, 256)
        d.text((x + 34, 261), f"×{mult}", font=pay_font, fill=TEXT)
    d.text((SLOT_W - 32 - note_w, 263), pair_note, font=note_font, fill=MUTED)

    # ── 릴 준비 ──
    reels = _slot_reels(symbols)
    cream = Image.new("RGB", (REEL_W, REEL_H), (247, 241, 229))
    shade = _reel_shade()
    mask = Image.new("L", (REEL_W, REEL_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, REEL_W - 1, REEL_H - 1), 12, fill=255)
    banner, banner_color = slot_banner(multiplier)
    banner_font = _font("bold", 24)
    counts = {s: symbols.count(s) for s in symbols}
    paired = max(counts.values()) >= 2
    dx0, dy0 = SLOT_DYN[0], SLOT_DYN[1]
    bay_w = SLOT_DYN[2] - SLOT_DYN[0]
    reel_y = REEL_TOP - dy0

    def frame_at(t_ms: float, *, done: bool, glow: bool) -> Image.Image:
        """움직이는 부분(`SLOT_DYN`)만 그려서 돌려줘요(RGB)."""
        dyn = base.crop(SLOT_DYN)
        dd = ImageDraw.Draw(dyn, "RGBA")
        for r, (stop, cells, seq) in enumerate(reels):
            s, fast = _reel_offset(t_ms, stop, cells)
            win = cream.copy()
            j0 = int(s // CELL)
            for j in range(j0 - 1, j0 + 3):
                if not 0 <= j < len(seq):
                    continue
                y = REEL_H / 2 - (j * CELL - s)                 # 번호가 큰 칸이 위에서 내려와요
                crisp, smear = sprites[seq[j]]
                art = smear if fast else crisp
                _paste(win, art, (REEL_W - art.width) // 2, round(y - art.height / 2))
            win.paste(shade, (0, 0), shade)
            hit = done and paired and counts[symbols[r]] >= 2          # 맞은 릴
            if done and not hit:                                       # 안 맞은 릴은 한 톤 죽여요
                win = Image.blend(win, Image.new("RGB", win.size, INK), 0.45)
            x = REEL_LEFT + r * (REEL_W + REEL_GAP) - dx0
            dyn.paste(win, (x, reel_y), mask)
            if hit:
                edge, width = (GOLD, 5) if glow else (GOLD_DARK, 3)
            else:
                edge, width = ((92, 72, 122) if t_ms < stop or done else GOLD_DARK), 3
            dd.rounded_rectangle((x - 2, reel_y - 2, x + REEL_W + 1, reel_y + REEL_H + 1), 14, outline=edge, width=width)
        # 가운데 줄(당첨선) 표시 — 양옆 세모
        mid = reel_y + REEL_H // 2
        mark = GOLD if not done or (paired and glow) else GOLD_DARK
        dd.polygon([(3, mid - 8), (12, mid), (3, mid + 8)], fill=mark)
        dd.polygon([(bay_w - 4, mid - 8), (bay_w - 13, mid), (bay_w - 4, mid + 8)], fill=mark)
        if done:
            color = banner_color if glow else TEXT
            _center(dd, bay_w / 2, SLOT_BAY[3] - dy0 + 7, banner, banner_font, color, stroke_width=2, stroke_fill=INK)
        return dyn

    # ── 프레임 계획: (시각, 끝났나, 번쩍, 시간) ──
    plan: list[tuple[float, bool, bool, int]] = []
    t = 0.0
    while t < REEL_STOP_MS[-1]:
        plan.append((t, False, False, FRAME_MS))
        t += FRAME_MS
    if multiplier > games.SLOT_PAIR_PAYOUT:
        plan += [(t, True, i % 2 == 0, FLASH_MS) for i in range(FLASH_FRAMES)]
    plan.append((t, True, True, HOLD_MS))

    # ── 색 줄이기(GIF는 256색) ──
    # 팔레트는 **한 벌**만 만들어 모든 프레임이 같이 써요(바탕 + 마지막 장 + 한창 도는 장에서 뽑아요).
    # 디더링은 꺼요: 켜면 프레임마다 점 무늬가 달라져서 안 바뀐 부분까지 다시 실리고(파일이 몇 배),
    # 화면도 지글거려요. 꺼 두면 Pillow가 **바뀐 네모만** 담아요.
    last = frame_at(plan[-1][0], done=True, glow=True)
    spin = frame_at(REEL_STOP_MS[0] / 2, done=False, glow=False)
    sheet = Image.new("RGB", (SLOT_W, SLOT_H + last.height * 2))
    sheet.paste(base, (0, 0))
    sheet.paste(last, (0, SLOT_H))
    sheet.paste(spin, (0, SLOT_H + last.height))
    palette = sheet.quantize(colors=SLOT_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    base_p = base.quantize(palette=palette, dither=Image.Dither.NONE)
    frames = []
    for t_ms, done, glow, _ms in plan:
        frame = base_p.copy()
        frame.paste(frame_at(t_ms, done=done, glow=glow).quantize(palette=palette, dither=Image.Dither.NONE), (dx0, dy0))
        frames.append(frame)
    still = base.copy()
    still.paste(last, (dx0, dy0))
    return frames, [ms for *_x, ms in plan], still


def render_slot(symbols: list[str], multiplier: int) -> tuple[bytes, bytes] | None:
    """(움직이는 GIF, 마지막 정지 JPEG). 재료가 없으면 None."""
    built = _slot_build(list(symbols), multiplier)
    if built is None:
        return None
    frames, durations, still = built
    buf = io.BytesIO()
    # ⚠️ `loop`를 안 줘요 = **한 번만** 돌아요. 반복하는 화면이어도 마지막 장을 30초 붙들어
    #    두니, 그 전에 부른 쪽이 정지 그림으로 바꿔요.
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                   disposal=1, optimize=True)
    return buf.getvalue(), _jpeg(still)


# ── 🎲 하이로우 ────────────────────────────────────────────────────────
HL_W, HL_H = 480, 250
HL_BAR = (40, 134, HL_W - 40, 166)
HL_LOW, HL_HOUSE, HL_HIGH = (78, 150, 255), (228, 64, 80), (255, 178, 60)


def highlow_banner(number: int, multiplier: int) -> tuple[str, tuple[int, int, int]]:
    if games.HIGHLOW_LOW_MAX < number < games.HIGHLOW_HIGH_MIN:
        return "하우스 구간", RED
    if multiplier > 0:
        return f"맞혔어요!  {multiplier}배", WIN
    return "빗나갔어요", LOSE


def render_highlow(number: int, choice: str, multiplier: int) -> bytes:
    return _jpeg(_highlow_image(number, choice, multiplier))


def _highlow_image(number: int, choice: str, multiplier: int) -> Image.Image:
    """1~100 눈금 위에 구간(낮다·하우스·높다)과 굴린 수를 그려요. 구간은 `casino_games` 상수에서 읽어요."""
    img = _backdrop(HL_W, HL_H)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((20, 12, HL_W - 20, HL_H - 12), 24, fill=PANEL + (240,), outline=GOLD, width=3)
    _center(d, HL_W / 2, 20, "하이로우", _font("bold", 23), GOLD, stroke_width=2, stroke_fill=INK)

    x0, y0, x1, y1 = HL_BAR
    top = games.HIGHLOW_MAX
    low_max, high_min = games.HIGHLOW_LOW_MAX, games.HIGHLOW_HIGH_MIN

    def at(n: float) -> float:            # 숫자 n 칸의 **오른쪽 끝** x좌표 (0이면 막대 시작)
        return x0 + n * (x1 - x0) / top

    zones = [("low", 0, low_max, HL_LOW, f"낮다 1~{low_max}"),
             ("house", low_max, high_min - 1, HL_HOUSE, f"하우스 {low_max + 1}~{high_min - 1}"),
             ("high", high_min - 1, top, HL_HIGH, f"높다 {high_min}~{top}")]
    bar = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    for name, a, b, color, _label in zones:
        # 내가 고른 쪽만 밝게. 하우스 구간은 늘 또렷하게(숨기지 않는 게 원칙이에요).
        bd.rectangle((at(a), y0, at(b), y1), fill=color + (255 if name in (choice, "house") else 80,))
    clip = Image.new("L", img.size, 0)
    ImageDraw.Draw(clip).rounded_rectangle(HL_BAR, 12, fill=255)
    img.paste(bar, (0, 0), Image.composite(bar.getchannel("A"), Image.new("L", img.size, 0), clip))
    d.rounded_rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), 13, outline=GOLD_DARK, width=2)

    small = _font("bold", 15)
    for name, a, b, color, label in zones:
        cx = (at(a) + at(b)) / 2
        if name == choice:                # 내가 고른 쪽은 **색 칩**으로 (막대 밝기만으로는 헷갈려요)
            tw = d.textlength(label, font=small)
            d.rounded_rectangle((cx - tw / 2 - 9, y1 + 6, cx + tw / 2 + 9, y1 + 28), 11, fill=color)
            _center(d, cx, y1 + 9, label, small, INK)
        else:
            _center(d, cx, y1 + 9, label, small, color if name == "house" else MUTED)

    # 굴린 수 — 그 칸 **가운데**에 핀을 꽂아요.
    banner, color = highlow_banner(number, multiplier)
    cx = at(number - 0.5)
    d.line([(cx, y0 - 2), (cx, y1 + 2)], fill=INK, width=7)
    d.line([(cx, y0 - 2), (cx, y1 + 2)], fill=TEXT, width=3)
    d.polygon([(cx - 11, y0 - 17), (cx + 11, y0 - 17), (cx, y0 - 2)], fill=TEXT, outline=INK)
    num_font = _font("bold", 56)
    nw = d.textlength(str(number), font=num_font)
    nx = min(max(36.0, cx - nw / 2), HL_W - 36 - nw)
    d.text((nx, 48), str(number), font=num_font, fill=color, stroke_width=3, stroke_fill=INK)
    _center(d, HL_W / 2, 197, banner, _font("bold", 24), color, stroke_width=2, stroke_fill=INK)
    return img


# ── 🃏 블랙잭 ──────────────────────────────────────────────────────────
BJ_W, BJ_H = 640, 400
CARD_W, CARD_H = 86, 122
CARD_FACE = (252, 250, 244)
SUIT_RED, SUIT_BLACK = (212, 46, 62), (30, 24, 46)
SUITS = ("spade", "heart", "diamond", "club")
BJ_ROW_DEALER, BJ_ROW_PLAYER = 30, BJ_H - 30 - CARD_H
BJ_CARDS_LEFT, BJ_CARDS_RIGHT = 138, BJ_W - 26      # 카드가 놓이는 가로 범위(왼쪽은 이름표 자리)


class SuitBook:
    """한 판의 **카드 무늬 장부**예요. 규칙에는 숫자만 있어서(`casino_games`의 덱은 숫자 목록)
    무늬는 그림용 꾸밈이에요. 그래도 한 판에서 같은 카드(♠K 두 장)가 나오면 이상하니,
    숫자마다 이미 쓴 무늬를 적어 두고 안 쓴 것 중에서 골라요."""

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self._used: dict[int, list[str]] = {}

    def extend(self, suits: list[str], ranks: list[int]) -> list[str]:
        """`suits`가 `ranks`보다 짧으면 **모자란 만큼만** 뒤에 채워요(이미 정한 무늬는 안 바꿔요)."""
        for rank in ranks[len(suits):]:
            used = self._used.setdefault(rank, [])
            suit = self._rng.choice([s for s in SUITS if s not in used] or list(SUITS))
            used.append(suit)
            suits.append(suit)
        return suits


def _suit_icon(suit: str, size: int) -> Image.Image:
    """무늬를 도형으로 그려요(RGBA). 글꼴에 맡기면 서버(나눔)·로컬(맑은고딕)에서 모양이 달라져요."""
    s = size * 4                                         # 크게 그려 줄이면 가장자리가 매끈해요
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    color = (SUIT_RED if suit in ("heart", "diamond") else SUIT_BLACK) + (255,)
    if suit == "diamond":
        d.polygon([(s / 2, s * 0.04), (s * 0.86, s / 2), (s / 2, s * 0.96), (s * 0.14, s / 2)], fill=color)
    elif suit == "heart":
        r = s * 0.27
        d.ellipse((s * 0.06, s * 0.08, s * 0.06 + 2 * r, s * 0.08 + 2 * r), fill=color)
        d.ellipse((s * 0.94 - 2 * r, s * 0.08, s * 0.94, s * 0.08 + 2 * r), fill=color)
        d.polygon([(s * 0.085, s * 0.46), (s * 0.915, s * 0.46), (s / 2, s * 0.95)], fill=color)
    elif suit == "spade":
        r = s * 0.25
        d.polygon([(s / 2, s * 0.03), (s * 0.90, s * 0.50), (s * 0.10, s * 0.50)], fill=color)
        d.ellipse((s * 0.07, s * 0.34, s * 0.07 + 2 * r, s * 0.34 + 2 * r), fill=color)
        d.ellipse((s * 0.93 - 2 * r, s * 0.34, s * 0.93, s * 0.34 + 2 * r), fill=color)
        d.polygon([(s / 2, s * 0.56), (s * 0.67, s * 0.96), (s * 0.33, s * 0.96)], fill=color)
    else:                                                # club
        r = s * 0.21
        for cx, cy in ((s / 2, s * 0.27), (s * 0.27, s * 0.57), (s * 0.73, s * 0.57)):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        d.polygon([(s / 2, s * 0.46), (s * 0.67, s * 0.96), (s * 0.33, s * 0.96)], fill=color)
    return im.resize((size, size), Image.LANCZOS)


def _card_face(rank: int, suit: str) -> Image.Image:
    """앞면(RGBA, 모서리만 투명). 글자는 **불투명한 흰 바탕 위에** 바로 써요 — 투명한 층에 쓰고
    얹으면 글자 가장자리가 거뭇해져요."""
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), 10, fill=CARD_FACE + (255,),
                                           outline=(60, 44, 84, 255), width=2)
    color = SUIT_RED if suit in ("heart", "diamond") else SUIT_BLACK
    label = games.card_label(rank)
    font = _font("bold", 27 if len(label) == 1 else 23)
    corner = Image.new("RGB", (34, 52), CARD_FACE)
    cd = ImageDraw.Draw(corner)
    cd.text(((34 - cd.textlength(label, font=font)) / 2, 0 if len(label) == 1 else 3), label, font=font, fill=color)
    small = _suit_icon(suit, 17)
    corner.paste(small, (8, 33), small)
    card.paste(corner, (5, 5))
    card.paste(corner.rotate(180), (CARD_W - 39, CARD_H - 57))
    big = _suit_icon(suit, 40)
    card.paste(big, ((CARD_W - 40) // 2, (CARD_H - 40) // 2), big)
    return card


def _card_back() -> Image.Image:
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), 10, fill=255)
    art = _load("cardback", "RGB")
    back = _cover(art, CARD_W, CARD_H) if art is not None else Image.new("RGB", (CARD_W, CARD_H), (70, 38, 122))
    card.paste(back, (0, 0), mask)
    ImageDraw.Draw(card).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), 10, outline=GOLD + (255,), width=2)
    return card


def blackjack_banner(note: str, outcome: int | None) -> tuple[str, tuple[int, int, int]]:
    """가운데 띠에 적을 글과 색. `outcome`은 정산 뒤의 배당 배수(None이면 진행 중)."""
    if outcome is None:
        return _clean(note), TEXT
    if outcome > games.BJ_PUSH_PAYOUT:
        return _clean(note), WIN
    return _clean(note), (TEXT if outcome == games.BJ_PUSH_PAYOUT else LOSE)


def _bj_row(n: int) -> tuple[int, int]:
    """카드 n장을 한 줄에 놓을 때 (첫 장 x, 장 사이 간격). 많아지면 겹쳐서 줄 안에 넣어요."""
    span = BJ_CARDS_RIGHT - BJ_CARDS_LEFT
    step = min(CARD_W + 10, (span - CARD_W) // (n - 1)) if n > 1 else 0
    return BJ_CARDS_LEFT + (span - (CARD_W + step * (n - 1))) // 2, step


def render_blackjack(dealer: list[int], player: list[int], **kwargs) -> bytes:
    return _jpeg(_blackjack_image(dealer, player, **kwargs))


def _blackjack_image(dealer: list[int], player: list[int], *, dealer_suits: list[str], player_suits: list[str],
                     reveal: bool, note: str = "", outcome: int | None = None, bet: int | None = None) -> Image.Image:
    """블랙잭 테이블. `reveal=False`면 딜러의 둘째 장부터 뒤집어 둬요(합계도 첫 장만 세요).

    🚨 뒤집힌 카드는 **숫자·무늬를 아예 읽지 않아요**(뒷면 그림만 얹어요). 그림에서 패가 새면
       안 되니까요 - test_casino_art가 "숨긴 카드를 바꿔도 그림이 똑같은지" 봐요.
    `note`는 `casino_games.settle_blackjack`의 문구, `outcome`은 그 배당 배수예요."""
    felt = _load("felt", "RGB")
    img = _cover(felt, BJ_W, BJ_H) if felt is not None else Image.new("RGB", (BJ_W, BJ_H), (58, 30, 104))
    d = ImageDraw.Draw(img, "RGBA")
    back = None

    def row(y: int, name: str, cards: list[int], suits: list[str], hidden_from: int | None) -> None:
        nonlocal back
        n = len(cards)
        x, step = _bj_row(n)
        shown = cards if hidden_from is None else cards[:hidden_from]
        value = games.hand_value(shown)
        # 이름표 + 합계
        d.rounded_rectangle((24, y + 30, 122, y + 92), 16, fill=INK + (205,), outline=GOLD_DARK, width=2)
        _center(d, 73, y + 35, name, _font("bold", 19), MUTED)
        total = f"{value}+?" if hidden_from is not None and hidden_from < n else str(value)
        _center(d, 73, y + 58, total, _font("bold", 25), RED if value > 21 else TEXT)
        shadow = Image.new("RGBA", (CARD_W + 8, CARD_H + 8), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((3, 4, CARD_W + 4, CARD_H + 5), 11, fill=(8, 2, 20, 110))
        for i, rank in enumerate(cards):
            if hidden_from is not None and i >= hidden_from:
                face = back = back or _card_back()
            else:
                face = _card_face(rank, suits[i] if i < len(suits) else SUITS[i % len(SUITS)])
            _paste(img, shadow, x + i * step - 1, y)
            _paste(img, face, x + i * step, y)

    row(BJ_ROW_DEALER, "딜러", dealer, dealer_suits, None if reveal else 1)
    row(BJ_ROW_PLAYER, "나", player, player_suits, None)

    cy = BJ_H // 2
    tag_w = 0.0
    if bet is not None:
        tag, tag_font = f"베팅 {bet}코인", _font("bold", 16)
        tag_w = d.textlength(tag, font=tag_font) + 28
        d.rounded_rectangle((BJ_W - 22 - tag_w, cy - 16, BJ_W - 22, cy + 16), 16, fill=INK + (195,))
        d.text((BJ_W - 22 - tag_w + 14, cy - 10), tag, font=tag_font, fill=GOLD)
    text, color = blackjack_banner(note, outcome)
    if text:
        # 띠는 **가운데**에 두되 베팅 꼬리표와 안 겹치게, 넘치면 글자를 줄여요.
        room = BJ_W - 2 * (22 + tag_w + 14) - 48
        size = 27
        while size > 15 and d.textlength(text, font=_font("bold", size)) > room:
            size -= 1
        font = _font("bold", size)
        tw = d.textlength(text, font=font)
        d.rounded_rectangle(((BJ_W - tw) / 2 - 24, cy - 23, (BJ_W + tw) / 2 + 24, cy + 23), 23,
                            fill=INK + (225,), outline=GOLD if outcome else GOLD_DARK, width=2)
        d.text(((BJ_W - tw) / 2, cy - size * 0.62), text, font=font, fill=color)
    return img


# ── 현황 배너 ─────────────────────────────────────────────────────────
LOBBY_W, LOBBY_H = 800, 260


def render_lobby() -> bytes:
    """`/도박 현황` 아래에 붙는 도박장 그림. 사람별 값은 안 넣어요(글에 있어요)."""
    img = _backdrop(LOBBY_W, LOBBY_H, dark=0.2, blur=0)
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(110):                                 # 아래쪽만 어둡게 눌러 글자가 읽히게
        d.line([(0, LOBBY_H - 110 + y), (LOBBY_W, LOBBY_H - 110 + y)], fill=INK + (int(215 * (y / 110) ** 0.8),))
    d.text((30, LOBBY_H - 92), "악귀 도박장", font=_font("bold", 42), fill=GOLD, stroke_width=3, stroke_fill=INK)
    d.text((33, LOBBY_H - 38), "슬롯 · 하이로우 · 블랙잭", font=_font("regular", 20), fill=TEXT,
           stroke_width=2, stroke_fill=INK)
    return _jpeg(img)


# ── 바깥에서 부르는 문 (스레드 + 자물쇠 + 실패하면 None) ────────────────
async def _safe(label: str, fn, *args, **kwargs):
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception:                                # noqa: BLE001
            log.exception("🎰 도박장 그림을 못 그렸어요 (%s) - 글만 보내요", label)
            return None


async def slot_card(symbols: list[str], multiplier: int) -> tuple[bytes, bytes] | None:
    return await _safe("슬롯", render_slot, list(symbols), multiplier)


async def highlow_card(number: int, choice: str, multiplier: int) -> bytes | None:
    return await _safe("하이로우", render_highlow, number, choice, multiplier)


async def blackjack_card(dealer: list[int], player: list[int], **kwargs) -> bytes | None:
    return await _safe("블랙잭", render_blackjack, list(dealer), list(player), **kwargs)


async def lobby_card() -> bytes | None:
    return await _safe("현황", render_lobby)
