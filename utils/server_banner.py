"""🖼️ 서버 배너 그림 — 지난주 🏅 MVP와 🎣 낚시왕을 960x540에 그려요 (2026-11-15).

## 왜

부스트 2레벨이 되면서 서버 배너(채널 목록 맨 위)를 쓸 수 있게 됐어요. 주간결산 채널은
들어가 봐야 보이지만, 배너는 서버를 열 때마다 **모두가** 봐요. 상을 받은 사람이 보여야
상이에요.

## 🚨 작게 보여요

채널 목록 위에서는 폭 240px 정도로 줄어서 보여요(1/4). 그래서 글씨를 크게 쓰고
줄 수를 줄였어요. 작은 글씨(경기 수 같은 것)는 넣지 않아요.

## 배경

아트테마 그림을 주차마다 돌려 써요(케이오는 캐릭터라 글씨에 가려서 빼요).
그림이 없으면 단색 그라데이션으로 그려요 — 배너가 안 바뀌는 것보다 낫게.
"""
from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from utils.card_theme_assets import CHARACTER_THEMES
from utils.profile_card import _font

SIZE = (960, 540)
AVATAR = 168
SKIP_BG = {"케이오"}

GOLD = (255, 215, 0)
BLUE = (96, 165, 250)
WHITE = (245, 245, 250)
SOFT = (210, 212, 225)

# 나눔고딕에 없는 글자(이모지·특수문자)는 □로 나와요 → 그리기 전에 걸러요.
_DRAWABLE = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ ._\-~!?#&()\[\]+'\"/:]")


@dataclass
class Slot:
    label: str            # "주간 MVP"
    name: str             # 표시 이름
    line: str             # "악귀력 1,001점"
    avatar: bytes | None  # 아바타 PNG/JPG 바이트
    color: tuple


def clean_name(name: str, fallback: str = "익명") -> str:
    """그릴 수 있는 글자만 남기고 12자로 잘라요."""
    out = _DRAWABLE.sub("", name or "").strip()
    out = re.sub(r"\s{2,}", " ", out)
    if not out:
        return fallback
    return out if len(out) <= 12 else out[:11] + "…"


def background_for(week: str) -> Image.Image:
    """주차 문자열로 배경을 골라요. 같은 주면 언제 다시 그려도 같은 배경이에요."""
    keys = sorted(k for k in CHARACTER_THEMES if k not in SKIP_BG)
    if keys:
        key = keys[zlib.crc32(week.encode()) % len(keys)]
        try:
            with Image.open(CHARACTER_THEMES[key]["image"]) as src:
                bg = ImageOps.fit(src.convert("RGB"), SIZE, Image.LANCZOS)
            # 글씨가 읽히게 흐리고 어둡게.
            bg = bg.filter(ImageFilter.GaussianBlur(3))
            return Image.blend(bg, Image.new("RGB", SIZE, (8, 8, 16)), 0.55)
        except Exception:  # noqa: BLE001 - 배경 하나 때문에 배너가 멈추면 안 돼요
            pass
    bg = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(bg)
    for y in range(SIZE[1]):
        r = y / SIZE[1]
        draw.line([(0, y), (SIZE[0], y)],
                  fill=(int(30 + 20 * r), int(14 + 10 * r), int(40 + 30 * r)))
    return bg


def _circle_avatar(raw: bytes | None, ring: tuple) -> Image.Image:
    size = AVATAR + 12
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(out).ellipse([0, 0, size - 1, size - 1], fill=ring + (255,))
    face = None
    if raw:
        try:
            with Image.open(io.BytesIO(raw)) as src:
                face = ImageOps.fit(src.convert("RGBA"), (AVATAR, AVATAR), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            face = None
    if face is None:
        face = Image.new("RGBA", (AVATAR, AVATAR), (60, 62, 80, 255))
    mask = Image.new("L", (AVATAR, AVATAR), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, AVATAR - 1, AVATAR - 1], fill=255)
    out.paste(face, (6, 6), mask)
    return out


def _center_text(draw, cx, y, text, font, fill):
    w = draw.textlength(text, font=font)
    # 그림자 한 겹 — 밝은 배경에서도 읽히게.
    draw.text((cx - w / 2 + 2, y + 2), text, font=font, fill=(0, 0, 0))
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def _fit_font(draw, text, start, max_w):
    size = start
    while size > 24:
        font = _font("bold", size)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size -= 2
    return _font("bold", size)


def render(week: str, slots: list[Slot]) -> bytes:
    """배너 PNG 바이트. `slots`는 1~2개(빈 칸은 그리지 않아요)."""
    img = background_for(week).convert("RGBA")
    draw = ImageDraw.Draw(img)

    _center_text(draw, SIZE[0] / 2, 34, "이번 주의 악귀", _font("bold", 54), WHITE)
    _center_text(draw, SIZE[0] / 2, 98, week.replace("-W", "년 ") + "주차",
                 _font("regular", 26), SOFT)

    if not slots:
        _center_text(draw, SIZE[0] / 2, 260, "이번 주 주인공을 기다리는 중", _font("bold", 44), SOFT)
    else:
        col_w = SIZE[0] / len(slots)
        for i, slot in enumerate(slots):
            cx = col_w * i + col_w / 2
            av = _circle_avatar(slot.avatar, slot.color)
            img.alpha_composite(av, (int(cx - av.width / 2), 150))
            draw = ImageDraw.Draw(img)
            _center_text(draw, cx, 342, slot.label, _font("bold", 32), slot.color)
            name_font = _fit_font(draw, slot.name, 50, col_w - 40)
            _center_text(draw, cx, 384, slot.name, name_font, WHITE)
            _center_text(draw, cx, 452, slot.line, _font("bold", 30), SOFT)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
