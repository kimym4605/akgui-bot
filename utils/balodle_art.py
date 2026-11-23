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

from PIL import Image, ImageStat

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
            shots.append(_framed(full.crop(box).resize(VIEW, Image.LANCZOS), frame))
        full.close()
    return shots
