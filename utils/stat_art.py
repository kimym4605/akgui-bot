"""📊 전적·순위 카드 그림 (2026-11-23). 글 임베드였던 다섯 화면을 한 장짜리 그림으로 바꿔요.

| 함수 | 화면 |
|---|---|
| `match_card` | 🔔 경기 결과 자동 알림 (맵 배경 · 요원 · 승패 · 점수 · KDA) |
| `report_card` | 📊 `/전적` 리포트 (티어 엠블럼 · 악귀 스코어 게이지 · 5칸 · 선호 요원 · 최근 경기) |
| `board_card` | 🏆 순위표 공통 (`/주간랭킹` `/출석순위` `/음성랭킹` `/낚시왕`) |
| `mvp_card` | 🏅 주간 MVP 발표 |
| `scrim_card` | ⚔️ `/내전전적` |

## 지키는 것

- **라이엇 API를 더 부르지 않아요.** 원래 화면이 이미 손에 쥔 값으로만 그려요(분당 30회를 서버
  전체가 나눠 써요 — `utils/henrik_api.py`).
- 요원·맵·티어 그림은 `assets/valorant/`에 **미리 구워 둔 것**만 써요(`scripts/build_valorant_assets.py`).
  없는 요원·맵이면 이니셜 원·그라데이션으로 물러나요 — 새 요원이 나와도 카드가 안 깨져요.
- **실패하면 None.** 부르는 쪽은 예전 글 임베드를 그대로 보내요. 그림은 덤이에요.
- `profile_card`의 폰트·동시 렌더 자물쇠를 같이 써요(메모리 512MB 머신에서 렌더 총량이 안 늘게).
- 🚨 **이모지는 그림에 못 써요**(컬러 이모지 폰트가 없어서 네모로 깨져요). 이름·문구에서 걷어내요(`_clean`).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path

from utils.profile_card import (GOLD, LOSE_COLOR, PANEL, PANEL_EDGE, TEXT, TEXT_DIM, TEXT_SUB, WIN_COLOR,
                                _RENDER_LOCK, _circle_avatar, _fit_text, _font)

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter
    PILLOW = True
except ImportError:  # pragma: no cover
    PILLOW = False

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "valorant"
BG_TOP = (15, 17, 25)
BG_BOTTOM = (26, 29, 46)
DRAW_COLOR = (160, 166, 190)
SILVER = (205, 212, 226)
BRONZE = (214, 150, 96)
MEDAL = {1: GOLD, 2: SILVER, 3: BRONZE}


# ── 재료 ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _index() -> dict:
    try:
        return json.loads((ASSET_DIR / "index.json").read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        log.warning("📊 전적 그림 재료 목록(index.json)이 없어요 - 요원·맵 그림 없이 그려요")
        return {"agents": {}, "maps": {}, "tiers": {}}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _open(path: Path, mode: str):
    try:
        with Image.open(path) as im:
            out = im.convert(mode)
        out.info.clear()
        return out
    except Exception:                                    # noqa: BLE001
        return None


def agent_icon(name: str | None, size: int):
    """HenrikDev가 주는 영문 요원 이름(`Jett`, `KAY/O`) → 정사각 RGBA. 없으면 None."""
    if not name:
        return None
    key = _index()["agents"].get(name) or _slug(name)
    im = _open(ASSET_DIR / "agents" / f"{key}.webp", "RGBA")
    return im.resize((size, size), Image.LANCZOS) if im else None


def _map_key(name: str | None) -> str | None:
    """영문(`Ascent`)도 한글(`어센트`)도 받아요 — 내전 기록은 한글로 남아 있어요."""
    if not name:
        return None
    from utils.valorant_maps import EN_TO_KO
    ko_to_en = {ko: en for en, ko in EN_TO_KO.items()}
    en = ko_to_en.get(name, name)
    return _index()["maps"].get(en) or _slug(en)


def map_image(name: str | None, w: int, h: int, *, dark: float = 0.0):
    """맵 그림을 (w, h)에 꽉 차게. 없으면 None."""
    key = _map_key(name)
    im = _open(ASSET_DIR / "maps" / f"{key}.webp", "RGB") if key else None
    if im is None:
        return None
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((x, y, x + w, y + h))
    if dark:
        im = Image.blend(im, Image.new("RGB", (w, h), BG_TOP), dark)
    return im


def tier_icon(tier_id: int | None, size: int):
    if tier_id is None or tier_id < 3:                   # 0~2 = 언랭·미사용
        return None
    im = _open(ASSET_DIR / "tiers" / f"{int(tier_id)}.webp", "RGBA")
    return im.resize((size, size), Image.LANCZOS) if im else None


# ── 그리기 도구 ───────────────────────────────────────────────────────
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⬀-⯿⌀-⏿]")


def _clean(text) -> str:
    """이모지·마크다운을 걷어요(그림 폰트에 이모지가 없어서 네모로 나와요)."""
    text = _EMOJI.sub("", str(text or ""))
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()


def _rgb(c) -> tuple:
    if isinstance(c, int):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    return tuple(c)


def _canvas(w: int, h: int, top=BG_TOP, bottom=BG_BOTTOM):
    img = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img.convert("RGBA")


def _panel(d, box, r=16, fill=PANEL, edge=PANEL_EDGE):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=edge, width=1)


def _text(d, xy, text, size, fill=TEXT, bold=False, anchor="la", stroke=0):
    kw = {"stroke_width": stroke, "stroke_fill": (0, 0, 0)} if stroke else {}
    d.text(xy, text, font=_font("bold" if bold else "regular", size), fill=fill, anchor=anchor, **kw)


def _tile(d, box, label, value, color=TEXT, sub="", vsize=34):
    x0, y0, x1, y1 = box
    _panel(d, box, r=14)
    _text(d, (x0 + 16, y0 + 14), label, 18, TEXT_SUB)
    font = _font("bold", vsize)
    _text(d, (x0 + 16, y0 + 40), _fit_text(d, value, font, x1 - x0 - 26), vsize, color, bold=True)
    if sub:
        sf = _font("regular", 16)
        _text(d, (x0 + 16, y1 - 26), _fit_text(d, sub, sf, x1 - x0 - 26), 16, TEXT_DIM)


def _avatar(img, data: bytes | None, xy, size, name="", ring=None, ring_w=4):
    """원형 아바타. 없으면 이름 첫 글자 원."""
    x, y = xy
    if ring:
        ImageDraw.Draw(img).ellipse((x - ring_w, y - ring_w, x + size + ring_w - 1, y + size + ring_w - 1),
                                    fill=ring)
    av = _circle_avatar(data, size) if data else None
    if av is None:
        av = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ad = ImageDraw.Draw(av)
        ad.ellipse((0, 0, size - 1, size - 1), fill=(58, 64, 92))
        ch = _clean(name)[:1] or "?"
        ad.text((size / 2, size / 2), ch, font=_font("bold", int(size * 0.45)), fill=TEXT, anchor="mm")
    img.alpha_composite(av, (int(x), int(y)))


def _agent_tile(img, name_en, size, xy, border=None, label=""):
    """요원 얼굴 정사각 + 테두리. 그림이 없으면 이니셜."""
    x, y = xy
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x, y, x + size, y + size), radius=max(6, size // 8), fill=(34, 38, 58),
                        outline=border or PANEL_EDGE, width=3 if border else 1)
    icon = agent_icon(name_en, size - 8)
    if icon is not None:
        m = Image.new("L", icon.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, icon.width - 1, icon.height - 1),
                                            radius=max(4, size // 9), fill=255)
        icon.putalpha(Image.composite(icon.getchannel("A"), Image.new("L", icon.size, 0), m))
        img.alpha_composite(icon, (x + 4, y + 4))
    else:
        _text(d, (x + size / 2, y + size / 2), _clean(label or name_en or "?")[:1], int(size * 0.4),
              TEXT_SUB, bold=True, anchor="mm")


def _ring(d, box, ratio, color, width=14, track=(38, 42, 62)):
    d.arc(box, 0, 360, fill=track, width=width)
    ratio = max(0.0, min(1.0, ratio))
    if ratio > 0.005:
        d.arc(box, -90, -90 + 360 * ratio, fill=color, width=width)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ── 1. 🔔 경기 결과 ────────────────────────────────────────────────────
def _match(d: dict) -> bytes:
    W, H = 900, 300
    result = d.get("result", "패배")
    color = WIN_COLOR if result == "승리" else LOSE_COLOR if result == "패배" else DRAW_COLOR
    img = _canvas(W, H)
    bg = map_image(d.get("map_en"), W, H, dark=0.45)
    if bg is not None:
        img.paste(bg)
    # 왼쪽이 글자 자리라 왼쪽을 더 어둡게
    shade = Image.new("RGBA", (W, H))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=(10, 12, 20, int(215 * max(0.0, 1 - x / (W * 0.85)))))
    img.alpha_composite(shade)
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, 8, H), fill=color)

    _agent_tile(img, d.get("agent"), 128, (34, 30), border=color, label=d.get("agent_ko"))
    nf = _font("bold", 30)
    _text(dr, (184, 30), _fit_text(dr, _clean(d.get("name")), nf, 430), 30, TEXT, bold=True)
    _text(dr, (186, 68), _clean(d.get("agent_ko") or d.get("agent") or ""), 20, TEXT_SUB)
    _text(dr, (184, 96), result, 64, color, bold=True, stroke=2)
    rw = dr.textlength(result, font=_font("bold", 64))
    _text(dr, (184 + rw + 22, 112), d.get("score", ""), 44, TEXT, bold=True, stroke=2)
    _text(dr, (186, 172), f"{_clean(d.get('map_ko') or d.get('map_en') or '?')} · {d.get('mode', '')}",
          21, TEXT_SUB)
    ti = tier_icon(d.get("tier_id"), 84)
    if ti is not None:
        img.alpha_composite(ti, (W - 84 - 30, 26))

    chips = [("KDA", f"{d['kills']} / {d['deaths']} / {d['assists']}"), ("K/D", f"{d['kd']:.2f}"),
             ("ACS", f"{d['acs']:.0f}"), ("ADR", f"{d['adr']:.0f}"), ("헤드샷", f"{d['hs']:.0f}%")]
    x, gap, cw = 34, 10, (W - 68 - 40) / 5
    widths = [cw * 1.35] + [(W - 68 - 40 - cw * 1.35) / 4] * 4
    for (label, value), w in zip(chips, widths):
        dr.rounded_rectangle((x, 212, x + w, 274), radius=12, fill=(18, 20, 32, 220), outline=PANEL_EDGE)
        _text(dr, (x + 14, 220), label, 16, TEXT_SUB)
        _text(dr, (x + 14, 240), value, 26, TEXT, bold=True)
        x += w + gap
    return _png(img)


# ── 2. 📊 /전적 리포트 ──────────────────────────────────────────────────
def _report(d: dict) -> bytes:
    W, H = 1000, 590
    grade_c = _rgb(d.get("grade_color", 0xFFC850))
    img = _canvas(W, H)
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, W, 6), fill=grade_c)

    ti = tier_icon(d.get("tier_id"), 132)
    if ti is not None:
        img.alpha_composite(ti, (40, 34))
    else:
        dr.ellipse((40, 34, 172, 166), fill=(34, 38, 58))
        _text(dr, (106, 100), "?", 50, TEXT_DIM, bold=True, anchor="mm")
    nf = _font("bold", 38)
    _text(dr, (198, 42), _fit_text(dr, _clean(d.get("riot")), nf, 560), 38, TEXT, bold=True)
    tier_line = _clean(d.get("tier_name") or "언랭크") + (f"  ·  {d['rr']} RR" if d.get("rr") is not None else "")
    _text(dr, (200, 96), tier_line, 28, GOLD, bold=True)
    _text(dr, (200, 138), _clean(d.get("sample", "")), 19, TEXT_SUB)

    # 악귀 스코어 게이지
    cx0, cy0, size = 806, 26, 160
    _ring(dr, (cx0, cy0, cx0 + size, cy0 + size), d["score"] / max(1.0, d.get("max_score", 2000)), grade_c)
    _text(dr, (cx0 + size / 2, cy0 + 62), f"{d['score']:.0f}", 38, TEXT, bold=True, anchor="mm")
    _text(dr, (cx0 + size / 2, cy0 + 102), _clean(d.get("grade", "")), 24, grade_c, bold=True, anchor="mm")
    _text(dr, (cx0 + size / 2, cy0 + size + 16), "악귀 스코어", 17, TEXT_SUB, anchor="mm")

    tiles = [("K/D", f"{d['kd']:.2f}", WIN_COLOR if d["kd"] >= 1 else LOSE_COLOR, ""),
             ("승률", f"{d['win_rate']:.0f}%", WIN_COLOR if d["win_rate"] >= 50 else LOSE_COLOR,
              f"{d['wins']}승 {d['losses']}패"),
             ("헤드샷", f"{d['hs']:.1f}%", TEXT, ""),
             ("평균 딜량", f"{d['adr']:.0f}", TEXT, "ADR"),
             ("전투 점수", f"{d['acs']:.0f}", TEXT, "ACS")]
    x, y, gap = 40, 222, 14
    tw = (W - 80 - gap * 4) / 5
    for label, value, c, sub in tiles:
        _tile(dr, (x, y, x + tw, y + 118), label, value, c, sub, vsize=36)
        x += tw + gap

    # 선호 요원
    _panel(dr, (40, 358, 470, 560))
    _text(dr, (60, 372), "선호 요원", 19, TEXT_SUB)
    ax = 60
    for name_en, name_ko, count in (d.get("agents") or [])[:3]:
        _agent_tile(img, name_en, 92, (ax, 404), label=name_ko)
        _text(dr, (ax + 46, 508), _clean(name_ko), 18, TEXT, bold=True, anchor="mm")
        _text(dr, (ax + 46, 532), f"{count}경기", 15, TEXT_DIM, anchor="mm")
        ax += 132
    if d.get("position"):
        _text(dr, (452, 372), f"주 포지션 {_clean(d['position'])}", 18, GOLD, anchor="ra")

    # 최근 경기 (왼쪽 위가 최신)
    _panel(dr, (486, 358, 960, 560))
    recent = (d.get("recent") or [])[:20]
    _text(dr, (506, 372), f"최근 {len(recent)}경기", 19, TEXT_SUB)
    if recent:
        wins = sum(1 for r in recent if r[0])
        _text(dr, (940, 372), f"{wins}승 {len(recent) - wins}패", 18, TEXT, bold=True, anchor="ra")
    sz, gx, gy = 38, 8, 8
    for i, (won, agent) in enumerate(recent):
        col, row = i % 10, i // 10
        px, py = 506 + col * (sz + gx), 410 + row * (sz + gy + 18)
        c = WIN_COLOR if won else LOSE_COLOR
        _agent_tile(img, agent, sz, (px, py), border=c)
        dr.rectangle((px + 4, py + sz + 4, px + sz - 4, py + sz + 9), fill=c)
    return _png(img)


# ── 3. 🏆 순위표 ───────────────────────────────────────────────────────
ROW_H = 60


def _board(title: str, subtitle: str, sections: list[dict], accent, avatars: dict) -> bytes:
    cols = max(1, min(2, len(sections)))
    col_w = 470
    W = 40 + cols * col_w + (cols - 1) * 20 + 40
    rows_max = max((len(s["rows"]) for s in sections), default=0)
    H = 110 + 46 + max(1, rows_max) * ROW_H + 36
    accent = _rgb(accent)
    img = _canvas(W, H)
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, W, 6), fill=accent)
    _text(dr, (40, 30), _clean(title), 36, TEXT, bold=True)
    if subtitle:
        _text(dr, (42, 78), _clean(subtitle), 18, TEXT_SUB)
    for ci, sec in enumerate(sections[:2]):
        x0 = 40 + ci * (col_w + 20)
        y = 118
        _text(dr, (x0, y), _clean(sec.get("title", "")), 22, accent, bold=True)
        y += 40
        if not sec["rows"]:
            _text(dr, (x0, y + 10), _clean(sec.get("empty", "아직 기록이 없어요")), 19, TEXT_DIM)
        for row in sec["rows"]:
            rank = row["rank"]
            cy = y + (ROW_H - 8) // 2          # 행 세로 중심 — 메달·아바타·값·이름 묶음을 여기 맞춰요
            if rank == 1:
                dr.rounded_rectangle((x0 - 8, y - 4, x0 + col_w, y + ROW_H - 4), radius=12,
                                     fill=(48, 42, 28), outline=(110, 90, 40))
            mc = MEDAL.get(rank)
            if mc:
                dr.ellipse((x0, cy - 16, x0 + 32, cy + 16), fill=mc)
                _text(dr, (x0 + 16, cy), str(rank), 18, (30, 24, 10), bold=True, anchor="mm")
            else:
                _text(dr, (x0 + 16, cy), str(rank), 19, TEXT_DIM, bold=True, anchor="mm")
            _avatar(img, avatars.get(row.get("uid")), (x0 + 44, cy - 19), 38, row.get("name", ""))
            vf = _font("bold", 22)
            value = _clean(row.get("value", ""))
            vw = dr.textlength(value, font=vf)
            _text(dr, (x0 + col_w - 14, cy), value, 22, accent if rank <= 3 else TEXT, bold=True, anchor="rm")
            name_w = col_w - 100 - vw - 30
            nf = _font("bold" if rank <= 3 else "regular", 21)
            name = _fit_text(dr, _clean(row.get("name", "")), nf, name_w)
            if row.get("sub"):
                # 이름(21)과 보조 글씨(15)를 두 줄 묶음으로 보고 중심에 맞춰요 — 줄 사이 5px
                sf = _font("regular", 15)
                _text(dr, (x0 + 94, cy - 3), name, 21, TEXT, bold=rank <= 3, anchor="ls")
                _text(dr, (x0 + 95, cy + 5), _fit_text(dr, _clean(row["sub"]), sf, name_w), 15, TEXT_DIM,
                      anchor="lt")
            else:
                _text(dr, (x0 + 94, cy), name, 21, TEXT, bold=rank <= 3, anchor="lm")
            y += ROW_H
    return _png(img)


# ── 4. 🏅 주간 MVP ─────────────────────────────────────────────────────
def _mvp(d: dict, avatar: bytes | None) -> bytes:
    W, H = 900, 400
    img = _canvas(W, H, (30, 18, 46), (16, 12, 26))
    # 아바타 뒤로 퍼지는 금빛 줄기
    cx, cy = 170, 200
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for k in range(16):
        a = k * math.pi / 8
        rd.polygon([(cx, cy), (cx + math.cos(a) * 520, cy + math.sin(a) * 520),
                    (cx + math.cos(a + 0.12) * 520, cy + math.sin(a + 0.12) * 520)], fill=(255, 200, 80, 34))
    img.alpha_composite(rays.filter(ImageFilter.GaussianBlur(4)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - 130, cy - 130, cx + 130, cy + 130), fill=(255, 200, 80, 90))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))
    _avatar(img, avatar, (cx - 95, cy - 95), 190, d.get("name", ""), ring=GOLD, ring_w=6)
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, W, 6), fill=GOLD)

    x = 340
    _text(dr, (x, 46), "WEEKLY  MVP", 26, GOLD, bold=True)
    _text(dr, (x + dr.textlength("WEEKLY  MVP", font=_font("bold", 26)) + 14, 52), _clean(d.get("week", "")),
          19, TEXT_SUB)
    nf = _font("bold", 52)
    _text(dr, (x, 86), _fit_text(dr, _clean(d.get("name")), nf, W - x - 40), 52, TEXT, bold=True)
    line = f"악귀력 {d.get('score', 0):,.0f}점" + (f"  ·  {_clean(d['grade'])} 등급" if d.get("grade") else "")
    _text(dr, (x + 2, 158), line, 26, GOLD, bold=True)

    chips = []
    if d.get("kd") is not None:
        chips.append(("K/D", f"{d['kd']}"))
    if d.get("win_rate") is not None:
        chips.append(("승률", f"{d['win_rate']}%"))
    if d.get("hs") is not None:
        chips.append(("헤드샷", f"{d['hs']}%"))
    if d.get("matches"):
        chips.append(("경기", f"{d['matches']}"))
    cx0 = x
    for label, value in chips:
        w = 118
        _tile(dr, (cx0, 214, cx0 + w, 304), label, value, TEXT, vsize=28)
        cx0 += w + 12
    _text(dr, (x + 2, 336), f"지난주 기록을 남긴 {d.get('total', 0)}명 중 악귀력 1위", 18, TEXT_SUB)
    return _png(img)


# ── 5. ⚔️ /내전전적 ────────────────────────────────────────────────────
def _scrim(d: dict, avatar: bytes | None) -> bytes:
    W = 1000
    maps = (d.get("maps") or [])[:6]
    H = 520 + (60 + len(maps) * 46 if maps else 0)
    rate = d.get("rate", 0)
    accent = WIN_COLOR if rate >= 50 else LOSE_COLOR
    img = _canvas(W, H)
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, W, 6), fill=accent)

    _avatar(img, avatar, (40, 34), 112, d.get("name", ""), ring=accent, ring_w=4)
    nf = _font("bold", 38)
    _text(dr, (178, 40), _fit_text(dr, _clean(d.get("name")), nf, 560), 38, TEXT, bold=True)
    _text(dr, (180, 92), "내전 전적", 20, TEXT_SUB)
    _text(dr, (180, 118), f"{d['wins']}승 {d['losses']}패", 30, TEXT, bold=True)

    cx0, cy0, size = 820, 26, 140
    _ring(dr, (cx0, cy0, cx0 + size, cy0 + size), rate / 100, accent, width=13)
    _text(dr, (cx0 + size / 2, cy0 + size / 2 - 8), f"{rate:.0f}%", 34, TEXT, bold=True, anchor="mm")
    _text(dr, (cx0 + size / 2, cy0 + size / 2 + 26), "통산 승률", 16, TEXT_SUB, anchor="mm")

    s_total = d.get("s_wins", 0) + d.get("s_losses", 0)
    tiles = [
        (f"시즌 {_clean(d.get('season', ''))}",
         f"{d.get('s_wins', 0)}승 {d.get('s_losses', 0)}패" if s_total else "기록 없음", TEXT,
         f"승률 {d['s_wins'] / s_total * 100:.0f}%" if s_total else ""),
        ("최고 연승", f"{d.get('best', 0)}", WIN_COLOR, ""),
        ("최다 연패", f"{d.get('worst', 0)}", LOSE_COLOR, ""),
        ("지금", _clean(d.get("streak", "")) or "-", TEXT, ""),
    ]
    x, y, gap = 40, 196, 14
    tw = (W - 80 - gap * 3) / 4
    for label, value, c, sub in tiles:
        _tile(dr, (x, y, x + tw, y + 110), label, value, c, sub, vsize=30)
        x += tw + gap

    # 최근 5경기 — 맵 그림 위에 승/패
    y = 330
    _text(dr, (40, y), "최근 경기 (왼쪽이 최신)", 19, TEXT_SUB)
    recent = (d.get("recent") or [])[:5]
    cw_, ch_, gap = 170, 120, 13
    for i, (won, map_ko) in enumerate(recent):
        px = 40 + i * (cw_ + gap)
        py = y + 32
        c = WIN_COLOR if won else LOSE_COLOR
        mi = map_image(map_ko, cw_, ch_, dark=0.35)
        tile = Image.new("RGBA", (cw_, ch_), (34, 38, 58, 255))
        if mi is not None:
            tile.paste(mi)
        m = Image.new("L", (cw_, ch_), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, cw_ - 1, ch_ - 1), radius=14, fill=255)
        tile.putalpha(m)
        img.alpha_composite(tile, (px, py))
        dr.rounded_rectangle((px, py, px + cw_, py + ch_), radius=14, outline=c, width=3)
        _text(dr, (px + cw_ / 2, py + 48), "승리" if won else "패배", 30, c, bold=True, anchor="mm", stroke=2)
        _text(dr, (px + cw_ / 2, py + 90), _clean(map_ko) or "맵 미기록", 17, TEXT, anchor="mm", stroke=2)
    if not recent:
        _text(dr, (40, y + 50), "아직 기록이 없어요", 18, TEXT_DIM)

    if d.get("kda"):
        _text(dr, (W - 40, y), _clean(d["kda"]), 18, GOLD, anchor="ra")

    # 맵별 성적
    if maps:
        y = 520
        _text(dr, (40, y), "맵별 성적", 19, TEXT_SUB)
        y += 36
        for map_ko, w_, l_ in maps:
            tot = w_ + l_
            r = w_ / tot if tot else 0
            mi = map_image(map_ko, 72, 36, dark=0.2)
            if mi is not None:
                img.alpha_composite(mi.convert("RGBA"), (40, y))
            _text(dr, (126, y + 6), _clean(map_ko), 19, TEXT, bold=True)
            bx0, bx1 = 250, 800
            dr.rounded_rectangle((bx0, y + 12, bx1, y + 26), radius=7, fill=(38, 42, 62))
            fill_w = int((bx1 - bx0) * r)
            if fill_w > 14:
                dr.rounded_rectangle((bx0, y + 12, bx0 + fill_w, y + 26), radius=7,
                                     fill=WIN_COLOR if r >= 0.5 else LOSE_COLOR)
            _text(dr, (W - 40, y + 6), f"{w_}승 {l_}패  {r * 100:.0f}%", 18, TEXT, anchor="ra")
            y += 46
    return _png(img)


# ── 바깥에서 부르는 문 ─────────────────────────────────────────────────
async def _run(label: str, fn, *args):
    if not PILLOW:
        return None
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception:                                # noqa: BLE001
            log.exception("📊 %s 카드를 못 그렸어요 - 글로 보내요", label)
            return None


async def match_card(d: dict) -> bytes | None:
    return await _run("경기 결과", _match, d)


async def report_card(d: dict) -> bytes | None:
    return await _run("전적 리포트", _report, d)


async def board_card(title: str, subtitle: str, sections: list[dict], accent,
                     avatars: dict | None = None) -> bytes | None:
    return await _run("순위표", _board, title, subtitle, sections, accent, avatars or {})


async def mvp_card(d: dict, avatar: bytes | None) -> bytes | None:
    return await _run("주간 MVP", _mvp, d, avatar)


async def scrim_card(d: dict, avatar: bytes | None) -> bytes | None:
    return await _run("내전 전적", _scrim, d, avatar)


def member_name(guild, uid) -> str:
    member = guild.get_member(int(uid)) if guild else None
    return member.display_name if member else "탈퇴한 사람"


async def board_attach(embed, guild, title: str, subtitle: str, sections: list[dict], accent,
                       filename: str = "ranking.png"):
    """🏆 순위표 카드를 그려 `embed`에 붙여요. 붙였으면 `discord.File`, 못 그렸으면 None.

    `sections`: [{"title", "rows": [{"rank", "uid", "value", "sub"?}], "empty"?}] — 이름은 여기서 채워요.
    네 순위표(`/주간랭킹` `/출석순위` `/음성랭킹` `/낚시왕`)가 같이 써요."""
    import discord
    uids = []
    for sec in sections:
        for row in sec["rows"]:
            row.setdefault("name", member_name(guild, row["uid"]))
            uids.append(str(row["uid"]))
            row["uid"] = str(row["uid"])
    avatars = await avatars_for(guild, list(dict.fromkeys(uids)))
    png = await board_card(title, subtitle, sections, accent, avatars)
    if png is None:
        return None
    embed.set_image(url=f"attachment://{filename}")
    return discord.File(io.BytesIO(png), filename=filename)


async def avatars_for(guild, user_ids, size: int = 64, timeout: float = 4.0) -> dict:
    """순위표에 올릴 아바타를 한꺼번에 받아요. 못 받은 사람은 빠져요(이니셜 원으로 그려요).

    ⚠️ 한 명씩 차례로 받으면 10명 × 왕복이라 느려요 → 동시에. 전체에 시간 제한을 둬요."""
    async def one(uid):
        member = guild.get_member(int(uid)) if guild else None
        if member is None:
            return uid, None
        try:
            return uid, await member.display_avatar.replace(size=size, format="png").read()
        except Exception:                                # noqa: BLE001
            return uid, None
    try:
        pairs = await asyncio.wait_for(asyncio.gather(*(one(u) for u in user_ids)), timeout)
    except asyncio.TimeoutError:
        return {}
    return {uid: data for uid, data in pairs if data}
