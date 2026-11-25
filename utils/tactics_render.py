"""🗺️ 전술판 → 그림(JPEG) — 📤 디스코드에 올리기용 (2026-11-25).

브라우저 화면(`config/tactics/board.html`)과 **같은 규칙**으로 그려요. 서버에서 그리니까 폰·PC 어디서
눌러도 같은 그림이 나와요. 좌표는 판 자료의 0~1(u, v)이고 그림은 MAP_PX 정사각형 + 위 제목 띠예요.

- 미니맵·요원·스킬 아이콘은 valorant-api CDN에서 받아 **메모리에 기억**해요(아이콘 수십 개, 몇 MB).
- 그리기는 CPU 일이라 `render_scene`은 동기 함수 → 호출부가 `asyncio.to_thread`로 불러요.
- 🚨 나눔고딕은 이모지를 못 그려요 → 글은 `_clean`으로 걸러요(서버 배너와 같은 문제).
- 🎬 경기 장면의 요원(`rot` 시선·`dead` 처치됨·`me` 나)도 화면과 같은 모양으로 그려요. 💬 메모 핀은 안 그려요.
"""
from __future__ import annotations

import io
import logging
import math
import re

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from utils.profile_card import _font

log = logging.getLogger(__name__)

MAP_PX = 1000
HEAD_PX = 64
TEAM = {"ally": (79, 195, 247), "enemy": (255, 70, 85)}
SMOKE_FILL = {"ally": (150, 210, 240, 110), "enemy": (255, 140, 150, 105)}
ZONE_FILL = {"ally": (79, 195, 247, 52), "enemy": (255, 70, 85, 56)}
_IMG_CACHE: dict[str, Image.Image] = {}
_IMG_CACHE_MAX = 300
_DRAWABLE = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ ._\-~!?#&()\[\]+'\"/:,%·→]")   # → 는 경기 장면 제목(누가→누구)


def _clean(text: str) -> str:
    return _DRAWABLE.sub("", text or "").strip()


# ------------------------------------------------------------------
# 그림 받기
# ------------------------------------------------------------------
async def fetch_images(session: aiohttp.ClientSession, urls) -> dict[str, Image.Image]:
    out = {}
    for url in {u for u in urls if u}:
        img = _IMG_CACHE.get(url)
        if img is None:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    r.raise_for_status()
                    img = Image.open(io.BytesIO(await r.read())).convert("RGBA")
                    img.load()
            except Exception:  # noqa: BLE001 — 아이콘 하나 못 받아도 판은 그려요
                log.warning("🗺️ 그림을 못 받았어요: %s", url)
                continue
            if len(_IMG_CACHE) >= _IMG_CACHE_MAX:
                _IMG_CACHE.pop(next(iter(_IMG_CACHE)))
            _IMG_CACHE[url] = img
        out[url] = img
    return out


def needed_urls(mapinfo: dict, agents: dict, items: list[dict]) -> list[str]:
    urls = [mapinfo.get("minimap")]
    for it in items:
        a = agents.get(it.get("agent")) or {}
        if it.get("type") == "agent":
            urls.append(a.get("icon"))
        elif it.get("type") == "ability":
            ab = ability_of(agents, it)
            urls.append((ab or {}).get("icon"))
    return [u for u in urls if u]


def ability_of(agents: dict, it: dict) -> dict | None:
    a = agents.get(it.get("agent")) or {}
    return next((x for x in a.get("abilities") or [] if x.get("slot") == it.get("slot")), None)


# ------------------------------------------------------------------
# 기하
# ------------------------------------------------------------------
def smooth_points(pts: list[list[float]], steps: int = 8) -> list[tuple[float, float]]:
    """Catmull-Rom 곡선을 촘촘한 점으로(브라우저의 smoothD와 같은 곡선)."""
    P = [(u * MAP_PX, v * MAP_PX) for u, v in pts]
    if len(P) < 3:
        return P
    out = [P[0]]
    for i in range(len(P) - 1):
        p0 = P[i - 1] if i > 0 else P[i]
        p1, p2 = P[i], P[i + 1]
        p3 = P[i + 2] if i + 2 < len(P) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        for s in range(1, steps + 1):
            t = s / steps
            mt = 1 - t
            x = mt ** 3 * p1[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p2[0]
            y = mt ** 3 * p1[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p2[1]
            out.append((x, y))
    return out


def line_points(it: dict) -> list[tuple[float, float]]:
    if it.get("pts") and len(it["pts"]) > 1:
        return smooth_points(it["pts"])
    return [(it["u"] * MAP_PX, it["v"] * MAP_PX), (it["u2"] * MAP_PX, it["v2"] * MAP_PX)]


def _dashed(draw: ImageDraw.ImageDraw, pts, fill, width: int, dash=14, gap=9) -> None:
    on, left = True, dash
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        pos = 0.0
        while pos < seg:
            step = min(left, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                draw.line([(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a), (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)],
                          fill=fill, width=width)
            pos += step
            left -= step
            if left <= 0:
                on = not on
                left = dash if on else gap


def _arrowhead(draw, pts, fill, size=18) -> None:
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    tip = (x2 + math.cos(ang) * 6, y2 + math.sin(ang) * 6)
    left = (tip[0] - size * math.cos(ang - 0.45), tip[1] - size * math.sin(ang - 0.45))
    right = (tip[0] - size * math.cos(ang + 0.45), tip[1] - size * math.sin(ang + 0.45))
    draw.polygon([tip, left, right], fill=fill)


def _disc(base: Image.Image, cx: float, cy: float, r: int, icon: Image.Image | None, ring, *, pad=0.78) -> None:
    d = ImageDraw.Draw(base)
    d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(11, 13, 20, 255))
    if icon is not None:
        s = max(2, int(2 * r * pad))
        ic = icon.resize((s, s), Image.LANCZOS)
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, s - 1, s - 1], fill=255)
        alpha = Image.composite(ic.getchannel("A"), Image.new("L", (s, s), 0), mask)
        ic.putalpha(alpha)
        base.alpha_composite(ic, (int(cx - s / 2), int(cy - s / 2)))
    d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], outline=ring, width=4)


# ------------------------------------------------------------------
# 그리기
# ------------------------------------------------------------------
def _rank(agents: dict, it: dict) -> int:
    if it.get("type") == "ability":
        kind = ((ability_of(agents, it) or {}).get("shape") or {}).get("kind")
        return 0 if kind == "circle" else 1
    return 2 if it.get("type") == "arrow" else 3


def render_scene(*, mapinfo: dict, agents: dict, images: dict, items: list[dict], title: str,
                 subtitle: str = "", callouts: bool = True) -> bytes:
    W, H = MAP_PX, MAP_PX + HEAD_PX
    canvas = Image.new("RGBA", (W, H), (14, 16, 24, 255))
    mini = images.get(mapinfo.get("minimap"))
    if mini is not None:
        canvas.alpha_composite(mini.resize((MAP_PX, MAP_PX), Image.LANCZOS), (0, HEAD_PX))

    board = Image.new("RGBA", (MAP_PX, MAP_PX), (0, 0, 0, 0))
    d = ImageDraw.Draw(board)
    if callouts:
        f = _font("bold", 14)
        for c in mapinfo.get("callouts") or []:
            t = _clean(c["name"])
            w = d.textlength(t, font=f)
            x, y = c["u"] * MAP_PX - w / 2, c["v"] * MAP_PX - 8
            d.text((x, y), t, font=f, fill=(223, 226, 238, 190), stroke_width=2, stroke_fill=(0, 0, 0, 200))

    unit = mapinfo.get("unit") or 0.007
    for it in sorted(items, key=lambda i: _rank(agents, i)):
        team = "enemy" if it.get("team") == "enemy" else "ally"
        col = TEAM[team] + (255,)
        typ = it.get("type")
        if typ == "ability":
            ab = ability_of(agents, it) or {}
            sh = ab.get("shape") or {"kind": "icon"}
            style = sh.get("style") or "zone"
            icon = images.get(ab.get("icon"))
            if sh["kind"] in ("line", "path") and it.get("u2") is not None:
                pts = line_points(it)
                if style == "smoke":
                    d.line(pts, fill=SMOKE_FILL[team][:3] + (170,), width=14, joint="curve")
                    d.line(pts, fill=col, width=3, joint="curve")
                elif style == "wall":
                    d.line(pts, fill=col, width=9, joint="curve")
                else:
                    _dashed(d, pts, col, 8)
                mx, my = pts[len(pts) // 2]
                _disc(board, mx, my, 11, icon, col)
                d = ImageDraw.Draw(board)
                continue
            # 던진 경로가 있으면 떨어진 곳(u2,v2)에 놓아요
            if it.get("u2") is not None:
                pts = line_points(it)
                _dashed(d, pts, (255, 255, 255, 200), 3, dash=8, gap=7)
                cx, cy = pts[-1]
            else:
                cx, cy = it["u"] * MAP_PX, it["v"] * MAP_PX
            if sh["kind"] == "circle":
                r = max(10, sh.get("r", 4) * unit * MAP_PX)
                fill = SMOKE_FILL[team] if style == "smoke" else ZONE_FILL[team]
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=col, width=3)
                _disc(board, cx, cy, 11, icon, col)
            else:
                _disc(board, cx, cy, 14, icon, col)
            d = ImageDraw.Draw(board)
        elif typ == "agent":
            a = agents.get(it.get("agent")) or {}
            cx, cy = it["u"] * MAP_PX, it["v"] * MAP_PX
            if it.get("rot") is not None and not it.get("dead"):
                # 🎬 경기 장면: 보던 방향(시선 = (sin r, −cos r))에 작은 화살촉
                dx, dy = math.sin(it["rot"]), -math.cos(it["rot"])
                tip = (cx + dx * 36, cy + dy * 36)
                base = (cx + dx * 24, cy + dy * 24)
                d.polygon([tip, (base[0] - dy * 8, base[1] + dx * 8), (base[0] + dy * 8, base[1] - dx * 8)], fill=col)
            if it.get("me"):
                d.ellipse([cx - 28, cy - 28, cx + 28, cy + 28], outline=(245, 197, 24, 255), width=4)
            _disc(board, cx, cy, 21, images.get(a.get("icon")), col, pad=1.0)
            d = ImageDraw.Draw(board)
            if it.get("dead"):
                d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=(0, 0, 0, 120))
                d.line([(cx - 15, cy - 15), (cx + 15, cy + 15)], fill=(255, 70, 85, 255), width=6)
                d.line([(cx - 15, cy + 15), (cx + 15, cy - 15)], fill=(255, 70, 85, 255), width=6)
        elif typ == "arrow" and it.get("u2") is not None:
            pts = line_points(it)
            d.line(pts, fill=(0, 0, 0, 130), width=9, joint="curve")
            d.line(pts, fill=col, width=5, joint="curve")
            _arrowhead(d, pts, col)
        elif typ == "text":
            t = _clean(it.get("text") or "")
            if not t:
                continue
            f = _font("bold", 22)
            w = d.textlength(t, font=f)
            x, y = it["u"] * MAP_PX, it["v"] * MAP_PX
            d.text((x - w / 2, y - 14), t, font=f, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
            d.line([(x - w / 2, y + 14), (x + w / 2, y + 14)], fill=col, width=3)

    canvas.alpha_composite(board, (0, HEAD_PX))
    hd = ImageDraw.Draw(canvas)
    hd.rectangle([0, 0, W, HEAD_PX], fill=(23, 26, 38, 255))
    tf = _font("bold", 28)
    head = _clean(title) or "작전판"
    hd.text((18, 15), head, font=tf, fill=(232, 233, 240))
    if subtitle:
        sf = _font("regular", 20)
        s = _clean(subtitle)
        hd.text((W - 18 - hd.textlength(s, font=sf), 21), s, font=sf, fill=(154, 160, 181))

    # JPEG — 장면이 최대 10장이라 PNG(장당 ~1MB)면 디스코드 첨부 한도에 걸려요.
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()
