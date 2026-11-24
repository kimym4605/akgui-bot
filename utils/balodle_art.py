"""🧩 발로들 그림 — 스킬 아이콘 카드와 맵 확대 그림을 Pillow로 구워요.

- `ability_card(key)`      스킬 아이콘을 디자인 배경(`ui/ability_bg.png`) 가운데 320×320 안에 얹어요.
- `pick_focus(map_name)`   맵 그림에서 확대할 중심점을 골라요(밋밋한 하늘·벽을 피해요).
- `map_steps(map_name, …)` 확대 단계별 그림 6장 + 전체 1장을 **미리 구워** 돌려줘요.

🚨 **전부 동기 함수예요(CPU 일).** cog에서는 `asyncio.to_thread`로 불러야 이벤트 루프가 안 멈춰요.
🚨 **원본 맵 그림(1920×1080)은 자를 때만 열고 바로 닫아요.** 봇 메모리가 512MB라 원본을 들고
   있으면 안 돼요. 돌려주는 건 640×360으로 줄여 압축한 바이트(장당 수십 KB)뿐이에요.
🚨 서버에는 이모지 글꼴이 없어요 — 그림 안에 이모지를 글자로 넣지 않아요(볼트 `악귀봇 디자인`).
"""
import functools
import io
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageStat

from utils import balodle_data, balodle_logic

CARD = 512                       # 스킬 카드 한 변
ICON_BOX = (96, 96, 416, 416)    # 아이콘이 들어갈 자리 (디자인 D2)
VIEW = (640, 360)                # 맵 그림을 보여주는 크기
FRAME_SIZE = (680, 400)          # 맵 틀 (가운데 640×360이 투명, 디자인 D3)
FRAME_AT = (20, 20)
BG_TOP, BG_BOTTOM = (15, 17, 25), (26, 29, 46)   # 디자인 바탕색 #0F1119 → #1A1D2E
FOCUS_TRIES = 20                 # 확대 중심 후보 수


def _fallback_bg() -> Image.Image:
    """디자인 배경 파일이 없을 때 쓰는 단색 그러데이션. 흰 아이콘이 보이게 어둡게만 해요."""
    im = Image.new("RGB", (CARD, CARD), BG_TOP)
    px = im.load()
    for y in range(CARD):
        t = y / (CARD - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        for x in range(CARD):
            px[x, y] = row
    return im


@functools.lru_cache(maxsize=4)
def ability_card(key: str) -> bytes:
    """스킬 아이콘 카드 PNG. 하루에 한 스킬만 쓰니 최근 몇 장만 기억해 둬요."""
    bg_path = balodle_data.ui_path("ability_bg.png")
    if os.path.exists(bg_path):
        with Image.open(bg_path) as src:
            card = src.convert("RGBA").resize((CARD, CARD), Image.LANCZOS)
    else:
        card = _fallback_bg().convert("RGBA")

    with Image.open(balodle_data.ability_icon_path(key)) as src:
        icon = src.convert("RGBA")
    box_w, box_h = ICON_BOX[2] - ICON_BOX[0], ICON_BOX[3] - ICON_BOX[1]
    scale = min(box_w / icon.width, box_h / icon.height)
    icon = icon.resize((max(1, round(icon.width * scale)), max(1, round(icon.height * scale))),
                       Image.LANCZOS)
    at = (ICON_BOX[0] + (box_w - icon.width) // 2, ICON_BOX[1] + (box_h - icon.height) // 2)
    card.alpha_composite(icon, at)

    out = io.BytesIO()
    card.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


def pick_focus(map_name: str, zoom_steps=None, rng: random.Random | None = None) -> list[float]:
    """확대 중심점 `[x, y]`(그림 너비·높이 대비 0~1).

    후보 20개 중 **첫 확대 단계로 잘랐을 때 밝기 표준편차가 가장 큰 곳**을 골라요. 하늘·벽처럼
    밋밋한 곳은 표준편차가 작아서 걸러져요. 그림을 못 열면 가운데(0.5, 0.5)예요."""
    zoom_steps = zoom_steps or balodle_data.SETTINGS["zoom_steps"]
    rng = rng or random.Random()
    try:
        with Image.open(balodle_data.map_path(map_name)) as src:
            gray = src.convert("L")
    except OSError:
        return [0.5, 0.5]
    best, best_score = [0.5, 0.5], -1.0
    for _ in range(FOCUS_TRIES):
        focus = [round(rng.uniform(0.1, 0.9), 3), round(rng.uniform(0.1, 0.9), 3)]
        box = balodle_logic.zoom_box(0, focus, gray.size, zoom_steps)
        score = ImageStat.Stat(gray.crop(box)).stddev[0]
        if score > best_score:
            best, best_score = focus, score
    return best


def _framed(view: Image.Image, frame: Image.Image | None) -> bytes:
    """맵 그림 한 장을 압축해요. 틀이 있으면 680×400 바탕에 그림을 붙이고 틀을 겹쳐요."""
    if frame is not None:
        canvas = Image.new("RGBA", FRAME_SIZE, BG_TOP + (255,))
        canvas.paste(view, FRAME_AT)
        canvas.alpha_composite(frame)
        view = canvas.convert("RGB")
    out = io.BytesIO()
    view.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def map_steps(map_name: str, focus, zoom_steps=None) -> list[bytes]:
    """확대 단계별 JPEG `len(zoom_steps)`장 + 마지막에 전체 그림 1장.

    `[0]`이 가장 크게 확대한 것(첫 문제 화면), `[-1]`이 전체(끝난 화면)예요."""
    zoom_steps = zoom_steps or balodle_data.SETTINGS["zoom_steps"]
    frame = None
    frame_path = balodle_data.ui_path("map_frame.png")
    if os.path.exists(frame_path):
        with Image.open(frame_path) as src:
            frame = src.convert("RGBA").resize(FRAME_SIZE, Image.LANCZOS)

    shots = []
    with Image.open(balodle_data.map_path(map_name)) as src:   # 🚨 여기서만 원본을 열어요
        full = src.convert("RGB")
        for step in range(len(zoom_steps) + 1):
            box = balodle_logic.zoom_box(step, focus, full.size, zoom_steps)
            view = full.crop(box).resize(VIEW, Image.LANCZOS)
            # 🔍 많이 늘린 그림은 뭉개져 보여서 윤곽을 살짝 세워요(2026-11-24 "잘 안 보여요").
            if VIEW[0] / max(1, box[2] - box[0]) > 1.4:
                view = view.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=2))
            shots.append(_framed(view, frame))
        full.close()
    return shots


# ------------------------------------------------------------------
# 🧩 요원 비교표 · 스킬 힌트판 (2026-11-24 — "비교표가 읽기 어렵고 힌트가 잘 안 보여요")
#
# 글 임베드의 `🟩🟨⬛⬆ **제트** — 결투가 · 한국 · 2020 · 여` 한 줄은 칸 색과 값이 따로 놀아서
# (특히 휴대폰에서 줄이 접히면) 무엇이 맞았는지 읽기 어려웠어요. 칸 안에 값을 적고 칸을 칠해요.
# 🚨 그림에 이모지는 못 써요(서버에 컬러 이모지 글꼴이 없어요). 화살표는 도형으로 그려요.
# 🚨 실패하면 부르는 쪽이 글 화면으로 물러나요 — 그림은 덤이에요.
# ------------------------------------------------------------------
TILE_COLOR = {
    balodle_logic.GREEN: (63, 164, 91),
    balodle_logic.YELLOW: (201, 162, 39),
    balodle_logic.BLACK: (58, 63, 85),
}
TEXT_MAIN = (240, 242, 248)
TEXT_DIM = (140, 146, 170)
DOT_WRONG, DOT_SOLVED, DOT_LEFT = (224, 86, 91), (63, 164, 91), (58, 63, 85)
BOARD_HEADS = ("요원", "역할군", "출신", "출시", "성별")
BOARD_COLS = (190, 130, 140, 140, 110)       # 칸 너비
BOARD_GAP, BOARD_PAD, BOARD_ROW, BOARD_HEAD = 8, 20, 84, 44


def _font(size: int, bold: bool = True):
    from utils.profile_card import _font as pf
    return pf("bold" if bold else "regular", size)


def _fit(d: ImageDraw.ImageDraw, text: str, size: int, width: int, bold: bool = True):
    """칸에 들어가게 글자 크기를 줄여요(최소 14)."""
    while size > 14 and d.textlength(text, font=_font(size, bold)) > width:
        size -= 2
    return _font(size, bold)


def _gradient(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), BG_TOP)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return im.convert("RGBA")


def _arrow(d: ImageDraw.ImageDraw, cx: int, cy: int, up: bool, size: int = 9):
    if up:
        pts = [(cx - size, cy + size // 2 + 2), (cx + size, cy + size // 2 + 2), (cx, cy - size)]
    else:
        pts = [(cx - size, cy - size // 2 - 2), (cx + size, cy - size // 2 - 2), (cx, cy + size)]
    d.polygon(pts, fill=TEXT_MAIN)


def agent_board(rows: list[tuple[str, list[tuple[str, str]]]]) -> bytes:
    """넣은 답마다 한 줄: [요원 아이콘+이름][역할군][출신][출시 ▲▼][성별]. PNG 바이트.

    `rows` = [(요원 키, compare_agent 결과)] — 넣은 순서대로."""
    from utils import stat_art
    w = BOARD_PAD * 2 + sum(BOARD_COLS) + BOARD_GAP * (len(BOARD_COLS) - 1)
    h = BOARD_PAD * 2 + BOARD_HEAD + len(rows) * (BOARD_ROW + BOARD_GAP) - BOARD_GAP
    img = _gradient(w, h)
    d = ImageDraw.Draw(img)

    xs, x = [], BOARD_PAD
    for cw in BOARD_COLS:
        xs.append(x)
        x += cw + BOARD_GAP
    for x, cw, head in zip(xs, BOARD_COLS, BOARD_HEADS):
        d.text((x + cw // 2, BOARD_PAD + BOARD_HEAD // 2 - 4), head, font=_font(20, False),
               fill=TEXT_DIM, anchor="mm")

    y = BOARD_PAD + BOARD_HEAD
    for key, cells in rows:
        agent = balodle_data.AGENTS.get(key) or {}
        # 요원 칸: 아이콘 + 이름
        x0, cw = xs[0], BOARD_COLS[0]
        d.rounded_rectangle((x0, y, x0 + cw, y + BOARD_ROW), radius=12, fill=(32, 36, 56),
                            outline=(52, 58, 84))
        icon = stat_art.agent_icon(agent.get("en"), BOARD_ROW - 16)
        tx = x0 + 12
        if icon is not None:
            img.alpha_composite(icon, (x0 + 8, y + 8))
            tx = x0 + 8 + icon.width + 10
        name = balodle_data.agent_name(key)
        d.text((tx, y + BOARD_ROW // 2), name, font=_fit(d, name, 24, x0 + cw - tx - 8),
               fill=TEXT_MAIN, anchor="lm")
        # 비교 칸 4개
        for col, (value, mark) in enumerate(cells, start=1):
            x0, cw = xs[col], BOARD_COLS[col]
            d.rounded_rectangle((x0, y, x0 + cw, y + BOARD_ROW), radius=12,
                                fill=TILE_COLOR.get(mark, TILE_COLOR[balodle_logic.BLACK]))
            arrow = None
            if value.endswith(balodle_logic.UP) or value.endswith(balodle_logic.DOWN):
                arrow = value.endswith(balodle_logic.UP)
                value = value[:-1]
            cy = y + BOARD_ROW // 2
            if arrow is None:
                d.text((x0 + cw // 2, cy), value, font=_fit(d, value, 26, cw - 16),
                       fill=TEXT_MAIN, anchor="mm")
            else:
                font = _fit(d, value, 26, cw - 40)
                tw = d.textlength(value, font=font)
                left = x0 + (cw - tw - 26) / 2
                d.text((left, cy), value, font=font, fill=TEXT_MAIN, anchor="lm")
                _arrow(d, round(left + tw + 16), cy, arrow)
        y += BOARD_ROW + BOARD_GAP

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


HINT_W = 400                     # 스킬 카드 오른쪽 힌트판 너비


def ability_board(key: str, hints: list[tuple[str, str]], heads: tuple[str, ...],
                  marks: list[str]) -> bytes:
    """스킬 카드(512) + 오른쪽 힌트판(400). PNG 바이트.

    - `hints` 열린 힌트 [(머리말, 값)], `heads` 전체 머리말(안 열린 건 흐리게 '🔒'대신 글로)
    - `marks` 기회마다 점 하나: 'wrong' · 'solved' · 'now' · 'left'
      카드 아래 장식 점(디자인 D2 '결과 칸 무늬')을 지우고 진짜 진행으로 다시 그려요 —
      장식인데 힌트처럼 보였어요."""
    with Image.open(io.BytesIO(ability_card(key))) as src:
        card = src.convert("RGBA")
    # 장식 점(y 448~466) 덮기 — **아이콘을 얹기 전** 배경에서 바로 위 무늬 없는 띠를 떠 와요
    # (아이콘을 얹은 카드에서 뜨면 아이콘 아랫단이 같이 복사돼 줄무늬가 생겨요).
    bg_path = balodle_data.ui_path("ability_bg.png")
    if os.path.exists(bg_path):
        with Image.open(bg_path) as src:
            bg = src.convert("RGBA").resize((CARD, CARD), Image.LANCZOS)
        card.paste(bg.crop((140, 420, 372, 444)).resize((232, 34)), (140, 440))
    dc = ImageDraw.Draw(card)
    n, r, gap = len(marks), 9, 30
    x = CARD // 2 - (n - 1) * gap // 2
    for m in marks:
        box = (x - r, 457 - r, x + r, 457 + r)
        if m == "wrong":
            dc.ellipse(box, fill=DOT_WRONG)
        elif m == "solved":
            dc.ellipse(box, fill=DOT_SOLVED)
        elif m == "now":
            dc.ellipse(box, outline=TEXT_MAIN, width=3)
        else:
            dc.ellipse(box, fill=DOT_LEFT)
        x += gap

    img = _gradient(CARD + HINT_W, CARD)
    img.alpha_composite(card, (0, 0))
    d = ImageDraw.Draw(img)
    x0 = CARD + 4
    d.text((x0, 40), "힌트", font=_font(30), fill=TEXT_MAIN, anchor="lm")
    d.text((x0 + 70, 42), "틀릴 때마다 하나씩 열려요", font=_font(18, False), fill=TEXT_DIM, anchor="lm")
    opened = dict(hints)
    row_h, y = 78, 76
    for i, head in enumerate(heads):
        box = (x0, y, CARD + HINT_W - 24, y + row_h - 12)
        label = head.split(" ", 1)[-1]               # '① 키' → '키'
        if head in opened:
            d.rounded_rectangle(box, radius=12, fill=(44, 40, 78), outline=(139, 92, 246), width=2)
            d.text((box[0] + 16, box[1] + 20), label, font=_font(17, False), fill=TEXT_DIM, anchor="lm")
            value = opened[head]
            d.text((box[0] + 16, box[1] + 46), value, font=_fit(d, value, 26, box[2] - box[0] - 32),
                   fill=TEXT_MAIN, anchor="lm")
        else:
            d.rounded_rectangle(box, radius=12, fill=(28, 31, 48), outline=(48, 52, 74))
            d.text((box[0] + 16, box[1] + 20), label, font=_font(17, False), fill=(96, 101, 128), anchor="lm")
            d.text((box[0] + 16, box[1] + 46), f"{i + 1}번 틀리면 열려요", font=_font(19, False),
                   fill=(96, 101, 128), anchor="lm")
        y += row_h
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
