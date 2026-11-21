# -*- coding: utf-8 -*-
"""🐟 물고기 그림 + 📖 낚시 도감 이미지 (2026-11-22).

그림은 `assets/fish/<key>.webp` — 512×512, **배경 투명**. Higgsfield(Nano Banana 2)로
악귀카드 그림체에 맞춰 뽑고 `scripts/build_fish_assets.py`가 배경을 빼서 넣었어요.

🚨 `data/`가 아니라 `assets/`예요. `data/`는 Fly 볼륨이 덮어써서 배포해도 안 올라가요.
⚠️ 그림이 없는 종도 죽지 않아요 — `art_path`가 None이면 호출부가 그림 없이 보여줘요.
   새 종을 넣고 그림을 깜빡해도 낚시는 그대로 돌아가야 하니까요.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from utils.fish_data import BY_KEY, FISH, GRADE_ORDER, GRADES
from utils.profile_card import _font

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


def render_dex(dex: dict[str, int], title: str = "낚시 도감") -> bytes:
    """`dex` = `{key: 잡은 마리 수}`. 등급별 한 줄씩, 높은 등급이 위예요."""
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

    y = HEADER_H + PAD
    for grade in GRADE_ORDER:
        g = GRADES[grade]
        accent = _rgb(g["color"])
        d.text((PAD, y + TILE // 2 - 18), grade, font=_font("bold", 30), fill=accent)
        x = PAD + LABEL_W
        for f in FISH[grade]:
            key, n = f["key"], int(dex.get(f["key"]) or 0)
            seen = n > 0
            d.rounded_rectangle((x, y, x + TILE, y + TILE), 18, fill=CARD,
                                outline=accent if seen else (80, 66, 110), width=3 if seen else 2)
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
            x += TILE + GAP
        y += TILE + 30 + GAP

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
