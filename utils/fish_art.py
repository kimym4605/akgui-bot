# -*- coding: utf-8 -*-
"""🐟 물고기 그림 + 📖 낚시 도감 + 🪣 어항 카드 이미지 (2026-11-22).

그림은 `assets/fish/<key>.webp` — 512×512, **배경 투명**. Higgsfield(Nano Banana 2)로
"애니 몬스터" 화풍으로 뽑고 `scripts/build_fish_assets.py`가 배경을 빼서 넣었어요.
어항 배경은 `assets/tank/bg.webp`(1000×630) — 같은 도구로 뽑은 **물고기 없는 수조** 그림이에요.

🚨 `data/`가 아니라 `assets/`예요. `data/`는 Fly 볼륨이 덮어써서 배포해도 안 올라가요.
⚠️ 그림이 없는 종도 죽지 않아요 — `art_path`가 None이면 호출부가 그림 없이 보여줘요.
   새 종을 넣고 그림을 깜빡해도 낚시는 그대로 돌아가야 하니까요.
"""
from __future__ import annotations

import asyncio
import io
import logging
import random
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from utils.fish_data import BY_KEY, FISH, GRADE_ORDER, GRADES, SIZE_BY_KEY
from utils.profile_card import _RENDER_LOCK, _circle_avatar, _fit_text, _font

log = logging.getLogger(__name__)

ART_DIR = Path(__file__).resolve().parent.parent / "assets" / "fish"


def art_path(key: str) -> Path | None:
    p = ART_DIR / f"{key}.webp"
    return p if p.exists() else None


# ── 도감 ──────────────────────────────────────────────────────────────
TILE = 150           # 칸 크기
GAP = 12
PAD = 28
LABEL_W = 110        # 왼쪽 등급 이름 칸
HEADER_H = 84
ROW_TITLE = 0
BG = (36, 26, 56)
CARD = (58, 44, 88)
TEXT = (245, 238, 255)
MUTED = (170, 156, 200)

_cache: dict[tuple[str, bool], Image.Image] = {}


def _tile_art(key: str, seen: bool) -> Image.Image | None:
    """칸 안에 들어갈 그림. 못 잡은 종은 **실루엣**이에요(모양은 보이고 정체는 숨겨요)."""
    ck = (key, seen)
    if ck in _cache:
        return _cache[ck]
    p = art_path(key)
    if p is None:
        return None
    im = Image.open(p).convert("RGBA").resize((TILE - 16, TILE - 16), Image.LANCZOS)
    if not seen:
        alpha = im.getchannel("A")
        sil = Image.new("RGBA", im.size, (14, 10, 24, 255))
        sil.putalpha(alpha.point(lambda a: 235 if a > 40 else 0))
        im = sil
    _cache[ck] = im
    return im


def _rgb(color: int) -> tuple[int, int, int]:
    return (color >> 16) & 255, (color >> 8) & 255, color & 255


GOLD = (255, 205, 60)
GOLD_DARK = (176, 120, 14)


def _draw_crown(d: ImageDraw.ImageDraw, x: int, y: int, w: int = 38) -> None:
    """👑 금색 왕관을 (x, y) 왼쪽 위에서 폭 `w`로 그려요 (2026-11-24 도감 왕관).
    ⚠️ 이모지 글꼴이 없어서(나눔고딕) 글자 대신 도형으로 그려요."""
    h = int(w * 0.72)
    base = y + h
    pts = [(x, base), (x, y + h * 0.28), (x + w * 0.27, y + h * 0.58), (x + w * 0.5, y),
           (x + w * 0.73, y + h * 0.58), (x + w, y + h * 0.28), (x + w, base)]
    d.polygon(pts, fill=GOLD, outline=GOLD_DARK, width=2)
    d.rectangle((x, base - h * 0.2, x + w, base), fill=GOLD_DARK)
    r = max(2, w // 12)
    for cx, cy in ((x, y + h * 0.28), (x + w * 0.5, y), (x + w, y + h * 0.28)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD, outline=GOLD_DARK)


def render_dex(dex: dict[str, int], title: str = "낚시 도감",
               dexmax: dict[str, int] | None = None) -> bytes:
    """`dex` = `{key: 잡은 마리 수}`. 등급별 한 줄씩, 높은 등급이 위예요.
    `dexmax` = `{key: 잡아본 최대 치수}` — 왕관 기준(`fish_data.is_crown`)을 넘은 칸에 👑을 그려요."""
    from utils.fish_data import is_crown
    dexmax = dexmax or {}
    cols = max(len(FISH[g]) for g in GRADE_ORDER)
    width = PAD * 2 + LABEL_W + cols * TILE + (cols - 1) * GAP
    height = HEADER_H + PAD + len(GRADE_ORDER) * (TILE + 30 + GAP) + PAD
    img = Image.new("RGBA", (width, height), BG)
    d = ImageDraw.Draw(img)

    seen_n = sum(1 for k in BY_KEY if dex.get(k))
    # ⚠️ 그림 속 글자엔 이모지를 넣지 마세요 — 나눔고딕엔 이모지가 없어서 □로 나와요.
    d.text((PAD, 24), title, font=_font("bold", 34), fill=TEXT)
    prog = f"{seen_n} / {len(BY_KEY)}종"
    pw = d.textlength(prog, font=_font("bold", 28))
    d.text((width - PAD - pw, 28), prog, font=_font("bold", 28), fill=(255, 215, 120))
    crowned = sum(1 for k in BY_KEY if dex.get(k) and is_crown(k, dexmax.get(k)))
    if crowned:
        ct = f"{crowned}"
        cw = d.textlength(ct, font=_font("bold", 28))
        cx = width - PAD - pw - 36 - cw
        d.text((cx, 28), ct, font=_font("bold", 28), fill=GOLD)
        _draw_crown(d, int(cx - 44), 30, 36)

    y = HEADER_H + PAD
    for grade in GRADE_ORDER:
        g = GRADES[grade]
        accent = _rgb(g["color"])
        d.text((PAD, y + TILE // 2 - 18), grade, font=_font("bold", 30), fill=accent)
        x = PAD + LABEL_W
        for f in FISH[grade]:
            key, n = f["key"], int(dex.get(f["key"]) or 0)
            seen = n > 0
            crown = seen and is_crown(key, dexmax.get(key))
            d.rounded_rectangle((x, y, x + TILE, y + TILE), 18, fill=CARD,
                                outline=GOLD if crown else (accent if seen else (80, 66, 110)),
                                width=4 if crown else (3 if seen else 2))
            art = _tile_art(key, seen)
            if art is not None:
                if seen:
                    glow = Image.new("RGBA", art.size, accent + (0,))
                    glow.putalpha(art.getchannel("A").filter(ImageFilter.GaussianBlur(6)).point(lambda a: a // 3))
                    img.alpha_composite(glow, (x + 8, y + 8))
                img.alpha_composite(art, (x + 8, y + 8))
            name = f["name"] if seen else "???"
            fnt = _font("bold" if seen else "regular", 20)
            nw = d.textlength(name, font=fnt)
            d.text((x + (TILE - nw) / 2, y + TILE + 4), name, font=fnt, fill=TEXT if seen else MUTED)
            if seen:
                badge = f"×{n}"
                bf = _font("bold", 18)
                bw = d.textlength(badge, font=bf)
                d.rounded_rectangle((x + TILE - bw - 18, y + 6, x + TILE - 6, y + 32), 10, fill=(20, 14, 34))
                d.text((x + TILE - bw - 12, y + 8), badge, font=bf, fill=TEXT)
            if crown:
                # ⚠️ 다른 그림(`img.alpha_composite`) 뒤에 그려야 물고기에 안 가려져요.
                _draw_crown(d, x + 8, y + 6)
            x += TILE + GAP
        y += TILE + 30 + GAP

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


async def dex_card(dex: dict[str, int], title: str,
                   dexmax: dict[str, int] | None = None) -> bytes:
    """`render_dex`를 스레드에서 돌려요(Pillow는 CPU 일 — 루프에서 돌리면 워치독이 깨요).
    동시에 그리는 수는 프로필 카드와 **같은 자물쇠**로 묶어요(운영 머신 RAM이 넉넉지 않아요)."""
    async with _RENDER_LOCK:
        return await asyncio.to_thread(render_dex, dex, title, dexmax)


# ── 어항 카드 ─────────────────────────────────────────────────────────
# `/어항`에 붙는 그림(2026-11-22). 수조 배경 위에 **지금 어항에 든 물고기**를 띄워요.
#
# ⭐ 고르는 규칙 — 붕어가 12마리 있어도 12마리를 다 그리지 않아요.
#    ⒜ 종마다 **제일 큰 놈 한 마리**는 반드시 그려요(= 대표. 이름표가 붙어요).
#    ⒝ 자리가 남으면 종마다 `TANK_PER_SPECIES`마리까지 더 그려요(대표 곁에 무리 지어요).
#    ⒞ 이름표의 `×12`가 진짜 마리 수예요. 그림은 "뭐가 들었나", 정확한 수는 이름표·임베드가 말해요.
# ⭐ 크기 — 등급이 높을수록, 같은 종이면 치수(cm)가 클수록 크게. 몇 마리 없으면 전체를
#    키우고(`TANK_MAX_SCALE`), 종이 아주 많으면 줄여요(`TANK_MIN_SCALE`).
# ⭐ 같은 어항은 **같은 그림**이에요(씨앗 = 유저 + 어항 내용). 열 때마다 자리가 바뀌면
#    "내 어항"이 아니라 주사위처럼 보여요.
# 🚨 그림·배경을 **캐시하지 않아요.** profile_card와 같은 이유(운영 머신 RAM)예요. 그릴 때마다
#    디코딩하고, 동시에 그리는 수는 `_RENDER_LOCK`으로 묶어요.
TANK_W, TANK_H = 1000, 630                    # 프로필 카드와 같은 크기
TANK_BG = ART_DIR.parent / "tank" / "bg.webp"
TANK_HEAD = (20, 16, TANK_W - 20, 102)        # 머리띠 (이름 · 마리 수 · 팔면)
TANK_WATER = (26, 114, TANK_W - 26, 604)      # 물고기가 헤엄치는 범위
TANK_PX = {"전설": 214, "대물": 176, "희귀": 132, "일반": 100}   # 등급별 기본 크기(px)
TANK_PER_SPECIES = 3
TANK_FILL = 0.42             # 물 넓이 중 물고기 칸(정사각형 기준)이 차지해도 되는 몫
TANK_MAX_SPRITES = 26
TANK_MIN_SCALE, TANK_MAX_SCALE = 0.6, 1.45
TANK_FOLLOWER = 0.84         # 따라다니는 놈은 대표보다 작게
TANK_BOTTOM = frozenset({"f03", "f07", "f15", "f16", "f24"})     # 바닥에 붙어 사는 종
TANK_LABEL_H = 28
TANK_TIGHT, TANK_PACKED = 10, 15   # 종 수가 이만큼 넘으면 이름표를 줄여요 (render_tank 참고)
TANK_TRIES = 70              # 자리 후보를 몇 번 뽑아볼지 (제일 덜 겹치는 자리를 골라요)
TANK_SCAN_STEP = 20          # 그래도 겹치면 이 간격(px)으로 물 전체를 훑어요
TANK_WATER_RGB = (14, 58, 66)
TANK_ACCENT = (110, 220, 210)
TANK_GOLD = (255, 200, 80)
TANK_SUB = (160, 198, 206)


def _tank_background() -> Image.Image:
    """수조 그림. 못 읽으면 **물빛 그라데이션**으로 물러나요(어항은 나와야 해요)."""
    try:
        with Image.open(TANK_BG) as src:
            bg = src.convert("RGBA")
        return bg if bg.size == (TANK_W, TANK_H) else bg.resize((TANK_W, TANK_H), Image.LANCZOS)
    except Exception:                                    # noqa: BLE001
        log.warning("🪣 어항 배경을 못 읽었어요(%s) - 그라데이션으로 그려요", TANK_BG, exc_info=True)
    bg = Image.new("RGBA", (TANK_W, TANK_H))
    d = ImageDraw.Draw(bg)
    top, bottom = (10, 44, 58), (6, 22, 30)
    for y in range(TANK_H):
        t = y / TANK_H
        d.line([(0, y), (TANK_W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    return bg


def _tank_plan(tank: dict[str, list]) -> list[dict]:
    """어항(`{key: [치수…]}`)에서 **그릴 놈**과 크기를 정해요. 대표가 먼저, 높은 등급이 먼저예요."""
    rank = {g: i for i, g in enumerate(GRADE_ORDER)}
    rounds: list[list[dict]] = [[] for _ in range(TANK_PER_SPECIES)]
    for key in sorted(tank):
        sizes = tank[key]
        if key not in BY_KEY or not sizes:
            continue                       # 없어진 종 · 빈 목록은 조용히 건너뛰어요
        grade, name = BY_KEY[key]
        lo, hi = SIZE_BY_KEY.get(key, (0, 0))
        for i, s in enumerate(sorted(sizes, key=lambda v: -(v or 0))[:TANK_PER_SPECIES]):
            # ⚠️ 치수가 없는 옛 물고기(None)는 중간 크기로 그려요.
            rel = 0.5 if s is None or hi <= lo else max(0.0, min(1.0, (s - lo) / (hi - lo)))
            rounds[i].append({
                "key": key, "grade": grade, "name": name, "size": s, "count": len(sizes), "lead": i == 0,
                "px": TANK_PX[grade] * (0.86 + 0.28 * rel) * (1.0 if i == 0 else TANK_FOLLOWER),
            })
    for r in rounds:
        r.sort(key=lambda e: (rank[e["grade"]], -e["px"], e["key"]))

    x0, y0, x1, y1 = TANK_WATER
    budget = TANK_FILL * (x1 - x0) * (y1 - y0)
    picked = list(rounds[0])
    used = sum(e["px"] ** 2 for e in picked)
    for r in rounds[1:]:
        for e in r:
            if len(picked) < TANK_MAX_SPRITES and used + e["px"] ** 2 <= budget:
                picked.append(e)
                used += e["px"] ** 2
    scale = max(TANK_MIN_SCALE, min(TANK_MAX_SCALE, (budget / used) ** 0.5)) if used else 1.0
    for e in picked:
        e["px"] = max(24, int(e["px"] * scale))
    return picked


def _tank_source(key: str) -> Image.Image | None:
    """그 종의 원본 그림(512px). 없거나 깨졌으면 None — 그 종만 빼고 그려요."""
    p = art_path(key)
    if p is None:
        return None
    try:
        with Image.open(p) as src:
            return src.convert("RGBA")
    except Exception:                                    # noqa: BLE001
        log.warning("🐟 물고기 그림을 못 읽었어요(%s)", p, exc_info=True)
        return None


def _tank_sprite(src: Image.Image, px: int, flip: bool, angle: float) -> Image.Image:
    """한 마리 그림. 크기를 맞추고 뒤집고 살짝 기울인 뒤 **보이는 부분만** 남겨요."""
    im = src.resize((px, px), Image.LANCZOS, reducing_gap=2.0)
    if flip:
        im = ImageOps.mirror(im)
    if angle:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    box = im.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
    return im.crop(box) if box else im


def _overlap(a: tuple, b: tuple) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _tank_boxes(e: dict, x: float, y: float) -> list[tuple]:
    """자리 다툼에 쓰는 상자: 몸통(가장자리 12%는 겹쳐도 봐줘요) + 이름표."""
    w, h = e["im"].size
    boxes = [(x + w * 0.12, y + h * 0.12, x + w * 0.88, y + h * 0.88)]
    if e["lead"]:
        cx = x + w / 2
        boxes.append((cx - e["label_w"] / 2, y + h, cx + e["label_w"] / 2, y + h + e["label_h"] + 4))
    return boxes


def _tank_place(items: list[dict], rng: random.Random) -> None:
    """각 물고기에 `pos`(왼쪽 위)를 채워요.

    대표를 큰 놈부터 **서로 멀리** 앉히고, 나머지는 자기 종 대표 **곁에** 붙여요(무리).
    후보 자리를 `TANK_TRIES`번 뽑아 제일 덜 겹치는 곳을 골라요 — 꽉 찬 어항에서도 반드시 끝나요."""
    x0, y0, x1, y1 = TANK_WATER
    depth = y1 - y0
    taken: list[tuple] = []
    centers: dict[str, tuple[float, float, float]] = {}      # 종 → 대표의 (가운데 x, y, 크기)
    for e in sorted(items, key=lambda e: (not e["lead"], -e["im"].width * e["im"].height)):
        w, h = e["im"].size
        tag = e["label_h"] + 4 if e["lead"] else 0
        xmax = max(x0, x1 - w)
        ylo, yhi = y0, max(y0, y1 - h - tag)
        if e["key"] in TANK_BOTTOM:
            ylo = max(ylo, yhi - int(depth * 0.14))          # 바닥 근처에서만
        else:
            yhi = max(ylo, yhi - int(depth * 0.10))          # 나머지는 자갈 위로 띄워요
        home = None if e["lead"] else centers.get(e["key"])

        def score_at(x: float, y: float) -> tuple[float, float]:
            hit = sum(_overlap(b, t) for b in _tank_boxes(e, x, y) for t in taken)
            cx, cy = x + w / 2, y + h / 2
            if home is not None:    # 무리: 대표와 가까울수록 좋아요
                return hit, (cx - home[0]) ** 2 + (cy - home[1]) ** 2
            # 대표: 다른 대표와도, **벽과도** 멀수록 좋아요. 벽을 안 넣으면 한 마리짜리 어항에서
            # 물고기가 구석에 박혀요(2026-11-22 미리보기에서 찾았어요). 첫 마리는 가운데로 가요.
            far = min((((cx - c[0]) ** 2 + (cy - c[1]) ** 2) ** 0.5 for c in centers.values()), default=1e9)
            far = min(far, 1.6 * min(cx - x0, x1 - cx))
            if e["key"] not in TANK_BOTTOM:
                far = min(far, 2.2 * min(cy - y0, y1 - cy))
            return hit, -far

        best, best_score = (x0, ylo), None
        for _ in range(TANK_TRIES):
            if home is None:
                x, y = rng.uniform(x0, xmax), rng.uniform(ylo, yhi)
            else:
                x = min(max(x0, rng.gauss(home[0], home[2] * 0.95) - w / 2), xmax)
                y = min(max(ylo, rng.gauss(home[1], home[2] * 0.55) - h / 2), yhi)
            score = score_at(x, y)
            if best_score is None or score < best_score:
                best, best_score = (x, y), score
        if best_score is not None and best_score[0] > 0:
            # 🚨 운에 맡긴 후보가 전부 겹쳤어요 → **촘촘히 훑어서** 빈자리를 찾아요. 이게 없으면
            #    큰 놈 넷이 든 어항에서 자리가 있는데도 둘이 포개졌어요(전설 미리보기에서 찾았어요).
            step = TANK_SCAN_STEP
            for gy in range(int(ylo), int(yhi) + 1, step):
                for gx in range(int(x0), int(xmax) + 1, step):
                    score = score_at(gx, gy)
                    if score < best_score:
                        best, best_score = (gx, gy), score
        e["pos"] = (int(best[0]), int(best[1]))
        taken.extend(_tank_boxes(e, *e["pos"]))
        if e["lead"]:
            centers[e["key"]] = (e["pos"][0] + w / 2, e["pos"][1] + h / 2, float(max(w, h)))


def _paste(base: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """`alpha_composite`는 음수 좌표를 못 받아요 → 화면 안에 걸친 부분만 잘라 얹어요."""
    sx, sy = max(0, -x), max(0, -y)
    w = min(layer.width - sx, base.width - max(0, x))
    h = min(layer.height - sy, base.height - max(0, y))
    if w <= 0 or h <= 0:
        return
    if (sx, sy, w, h) != (0, 0, layer.width, layer.height):
        layer = layer.crop((sx, sy, sx + w, sy + h))
    base.alpha_composite(layer, (max(0, x), max(0, y)))


def _halo(im: Image.Image, color: tuple, radius: int, strength: float) -> tuple[Image.Image, int]:
    """그림 뒤에 까는 번짐(어두우면 물에서 떠 보이고, 등급색이면 빛나 보여요). `(그림, 여백)`."""
    pad = radius * 2
    a = Image.new("L", (im.width + pad * 2, im.height + pad * 2), 0)
    a.paste(im.getchannel("A"), (pad, pad))
    a = a.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: int(v * strength))
    halo = Image.new("RGBA", a.size, tuple(color) + (0,))
    halo.putalpha(a)
    return halo, pad


def _recede(im: Image.Image) -> Image.Image:
    """무리의 뒤쪽 놈 — 물빛을 섞어 한 발 물러나 보이게 해요."""
    alpha = im.getchannel("A")
    rgb = Image.blend(im.convert("RGB"), Image.new("RGB", im.size, TANK_WATER_RGB), 0.32)
    out = rgb.convert("RGBA")
    out.putalpha(alpha.point(lambda v: int(v * 0.94)))
    return out


def _tank_layout(tank: dict[str, list], seed: int = 0) -> list[dict]:
    """고르기 → 그림 준비 → 이름표 → 자리 잡기. 그리기 **직전**까지라 테스트가 자리를 직접 봐요.

    돌려주는 각 원소: `key`·`grade`·`lead`·`im`(잘라낸 그림)·`pos`(왼쪽 위), 대표는 `label`·`label_w`·`label_h`도."""
    rng = random.Random(zlib.crc32(repr((seed, sorted((k, list(v)) for k, v in tank.items()))).encode()))
    items = _tank_plan(tank)
    # 🚨 종이 많으면 **이름표가 물고기를 덮어요**(24종 어항을 뽑아보고 찾았어요). 그래서 붐빌수록
    #    이름표를 줄여요: 10종부터 일반은 치수를 빼고, 15종부터는 희귀도 빼고 글씨도 작게.
    #    대물·전설은 언제나 치수를 적어요(자랑거리예요). 정확한 치수는 임베드 글에 다 있어요.
    leads = sum(1 for e in items if e["lead"])
    tight, packed = leads >= TANK_TIGHT, leads >= TANK_PACKED
    tag_px = 16 if packed else 19
    tag_font = _font("bold", tag_px)
    tag_h = TANK_LABEL_H - 5 if packed else TANK_LABEL_H
    pose = {e["key"]: (rng.random() < 0.5, rng.uniform(-7.0, 7.0)) for e in items if e["lead"]}
    # ⚠️ 원본 디코딩이 제일 비싸요(카드 한 장 시간의 절반). 그래서 **종마다 한 번만** 풀고,
    #    그 종의 무리까지 다 만든 뒤 바로 버려요(한 번에 원본 1장 ≈ 1MB만 들고 있어요).
    for key in pose:
        src = _tank_source(key)
        for e in items:
            if e["key"] != key:
                continue
            flip, angle = pose[key]
            jitter = 0.0 if e["lead"] else rng.uniform(-6.0, 6.0)
            e["im"] = None if src is None else _tank_sprite(src, e["px"], flip, angle + jitter)
    for e in items:
        if e["lead"]:
            show_cm = e["size"] is not None and (
                e["grade"] in ("대물", "전설") or not (packed or (tight and e["grade"] == "일반")))
            text = e["name"] + (f" {e['size']}cm" if show_cm else "")
            count = f"×{e['count']}" if e["count"] > 1 else ""
            e["label"] = (text, count)
            e["label_w"] = int(tag_font.getlength(text) + (tag_font.getlength(count) + 8 if count else 0) + 24)
            e["label_h"] = tag_h
            e["label_px"] = tag_px            # 그릴 때 **같은 글씨 크기**를 써야 폭이 맞아요
    items = [e for e in items if e.get("im") is not None]   # 그림 없는 종은 빼요(글에는 그대로 나와요)
    _tank_place(items, rng)
    return items


def render_tank(tank: dict[str, list], *, name: str, sell_coins: int | None = None,
                dex_seen: int | None = None, avatar: bytes | None = None, seed: int = 0) -> bytes:
    """🪣 어항 카드(JPEG 바이트). **동기 함수**라 `tank_card`(스레드)로 불러요.

    `tank` = `fishing_store.get()["tank"]` 그대로(`{key: [치수 또는 None, …]}`)."""
    total = sum(len(v) for v in tank.values())
    img = _tank_background()
    d = ImageDraw.Draw(img, "RGBA")       # RGBA 모드라 알파 붙인 색이 반투명으로 섞여요
    items = _tank_layout(tank, seed)

    # 뒤 → 앞: 무리(작고 흐린 놈) 먼저, 대표는 작은 놈부터. 제일 큰 놈이 맨 앞이에요.
    for e in sorted(items, key=lambda e: (e["lead"], e["im"].width * e["im"].height)):
        im, (x, y) = e["im"], e["pos"]
        if not e["lead"]:
            im = _recede(im)
        if e["lead"] and e["grade"] in ("전설", "대물"):
            halo, pad = _halo(im, _rgb(GRADES[e["grade"]]["color"]), 14, 0.50)
        else:
            halo, pad = _halo(im, (2, 12, 18), 8, 0.55)
        _paste(img, halo, x - pad, y - pad)
        _paste(img, im, x, y)

    # ── 이름표 (물고기를 다 그린 뒤에 — 큰 놈에게 가려지면 안 돼요) ──
    wx0, _wy0, wx1, wy1 = TANK_WATER
    for e in items:
        if not e["lead"]:
            continue
        text, count = e["label"]
        lw, lh = e["label_w"], e["label_h"]
        tag_font = _font("bold", e["label_px"])
        lx = int(min(max(wx0, e["pos"][0] + e["im"].width / 2 - lw / 2), wx1 - lw))
        ly = int(min(e["pos"][1] + e["im"].height + 2, wy1 - lh + 12))
        accent = _rgb(GRADES[e["grade"]]["color"])
        d.rounded_rectangle((lx, ly, lx + lw, ly + lh), lh // 2,
                            fill=(6, 16, 26, 210), outline=accent + (255,), width=2)
        d.text((lx + 12, ly + 3), text, font=tag_font, fill=TEXT)
        if count:
            d.text((lx + 12 + tag_font.getlength(text) + 8, ly + 3), count, font=tag_font, fill=TANK_GOLD)

    if not total:
        # ⚠️ 그림 속 글자엔 이모지를 넣지 마세요 — 나눔고딕엔 이모지가 없어서 □로 나와요.
        for text, font, dy in (("어항이 비었어요", _font("bold", 44), -34),
                               ("/낚시 로 한 마리 낚아보세요", _font("regular", 24), 28)):
            tw = d.textlength(text, font=font)
            d.text(((TANK_W - tw) / 2, (TANK_WATER[1] + wy1) / 2 + dy), text, font=font, fill=TEXT,
                   stroke_width=3, stroke_fill=(4, 18, 26))

    # ── 머리띠 ──
    hx0, hy0, hx1, hy1 = TANK_HEAD
    d.rounded_rectangle(TANK_HEAD, 22, fill=(6, 20, 30, 190), outline=TANK_ACCENT + (120,), width=2)
    tx = hx0 + 20
    face = _circle_avatar(avatar, 62)
    if face is not None:
        d.ellipse((tx - 3, hy0 + 9, tx + 64, hy0 + 76), outline=TANK_ACCENT, width=3)
        _paste(img, face, tx, hy0 + 12)
        tx += 62 + 18
    stats = [("어항", f"{total:,}마리", TANK_ACCENT)]
    if sell_coins is not None:
        stats.append(("팔면", f"{sell_coins:,}코인", TANK_GOLD))
    right = hx1 - 26
    value_font, small_font = _font("bold", 30), _font("regular", 17)
    for label, value, color in reversed(stats):
        w = max(d.textlength(value, font=value_font), d.textlength(label, font=small_font))
        d.text((right - w, hy0 + 13), label, font=small_font, fill=TANK_SUB)
        d.text((right - w, hy0 + 37), value, font=value_font, fill=color)
        right -= w + 34
    title_font = _font("bold", 32)
    d.text((tx, hy0 + 11), _fit_text(d, f"{name}의 어항", title_font, max(60, right - tx - 8)),
           font=title_font, fill=TEXT)
    if dex_seen is not None:
        d.text((tx, hy0 + 53), f"도감 {dex_seen} / {len(BY_KEY)}종", font=_font("regular", 18), fill=TANK_SUB)

    buf = io.BytesIO()
    # 배경이 그림이라 PNG는 1MB를 넘어요 → JPEG(글자가 안 뭉개지게 색 줄임 없이).
    img.convert("RGB").save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
    return buf.getvalue()


async def tank_card(tank: dict[str, list], **kwargs) -> bytes | None:
    """`render_tank`을 스레드에서 돌려요. 실패하면 None — `/어항`은 **글만으로도** 나가야 해요."""
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(render_tank, tank, **kwargs)
        except Exception:                                # noqa: BLE001
            log.exception("🪣 어항 그림을 못 그렸어요 (name=%s)", kwargs.get("name"))
            return None
