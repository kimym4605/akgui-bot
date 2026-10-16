"""🎴 뽑기 결과 이미지 - 나온 카드를 PNG 한 장으로 합쳐요 (연속뽑기면 최대 30장).

## 왜 합성인가

임베드 3개에 이미지를 각각 붙일 수도 있어요. 그런데 그러면 메시지가 화면 세 개 높이로
길어져서 **한눈에 안 들어오고**, 모바일에서는 스크롤해야 세 번째 카드가 보여요.
뽑기의 재미는 "한 번에 쫙 펼쳐지는" 순간이라 한 장으로 합쳐요.

`profile_card`와 같은 이유로 이미지예요 - 임베드는 스크린샷을 찍어 밖으로 내보낼 때
초라해지는데, 그림은 그 자체로 자랑거리가 돼요.

## 메모리 (256MB 머신)

⚠️ `profile_card._RENDER_LOCK`을 **그대로 같이 써요.** 세마포어를 따로 만들면 프로필 카드
2장 + 뽑기 2장이 동시에 그려져서 상한이 사실상 두 배가 돼요. 이 봇은 메모리가 모자라
노래방이 끊긴 전력이 있어서(2026-09-04 먹통), 기능이 늘어도 **동시 렌더 총량**이 안 늘게
하나를 공유해요.

카드 원본은 긴 변 768px WebP(`scripts/build_card_assets.py`가 줄여둬요). 3장을 열어
썸네일로 줄이고 1020x640 캔버스에 합치면 순간 15MB 정도예요.

## 폰트

`profile_card._font`를 재사용해요. 나눔 -> 맑은고딕 -> 동봉본 순으로 찾는 로직이 이미
거기 있고, 두 벌로 들고 있으면 한쪽만 고치는 사고가 나요.

⚠️ 이모지는 안 그려요(컬러 이모지 폰트가 없어서 깨져요). 등급은 **색과 테두리**로 구분해요
- profile_card가 같은 이유로 같은 선택을 했어요.
"""
import asyncio
import io
import logging
from pathlib import Path

from utils.card_store import GRADE_COLOR

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
    PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover
    PILLOW_AVAILABLE = False
    log.warning("Pillow가 없어서 뽑기 결과 이미지를 그릴 수 없어요.")

# ⚠️ 폰트와 동시 렌더 상한을 profile_card와 공유해요 (파일 맨 위 설명 참고).
from utils.profile_card import _RENDER_LOCK, _font  # noqa: E402

CARD_DIR = Path(__file__).resolve().parent.parent / "assets" / "cards"
THUMB_DIR = CARD_DIR / "thumbs"      # 도감 그리드용 미리 구운 150x225 (_load_thumb 참고)

# 카드 한 장을 그릴 칸 크기. 원본이 대략 2:3이라 거기에 맞춰요.
SLOT_W, SLOT_H = 300, 450
GAP = 24                 # 카드 사이 간격
PAD = 28                 # 바깥 여백
LABEL_H = 76             # 카드 아래 이름·등급이 들어갈 높이

BG_TOP = (15, 17, 25)
BG_BOTTOM = (26, 29, 46)
TEXT_SUB = (139, 146, 168)   # 이미지를 못 열었을 때 쓰는 흐린 글씨
NEW_BG = (88, 214, 141)
NEW_TEXT = (10, 20, 14)


def _rgb(value: int) -> tuple[int, int, int]:
    """`0xRRGGBB` 정수를 Pillow가 쓰는 `(R, G, B)` 튜플로 바꿔요.

    🚨 **이 변환을 건너뛰면 빨강과 파랑이 뒤바뀌어요.** Pillow에 정수를 그대로 넘기면
    `0xBBGGRR`(리틀엔디언)로 읽어요. 그래서 레어 `0x3B82F6`(파랑)이 `(246,130,59)`
    주황으로, 레전드 `0xFFD700`(황금)이 `(0,215,255)` 청록으로 나왔어요.

    2026-10-17에 4등급을 한 장에 그려 **눈으로 보고서야** 발견했어요. 처음 미리보기에선
    카드 아트에 원래 들어있는 테두리와 겹쳐 보여서 못 알아챘어요
    (`profile_card`의 테마 색도 같은 식으로 두 번 고쳤던 전력이 있어요).

    ⚠️ 디스코드 임베드(`discord.Embed(color=...)`)는 정수를 `0xRRGGBB`로 **올바로** 읽어요.
    그래서 임베드만 보면 멀쩡해 보이고 그림만 틀려요 - 같은 상수를 쓰는데 해석이 달라요.
    """
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _vertical_gradient(size: tuple[int, int], top: tuple, bottom: tuple):
    """배경 그라데이션. 한 줄씩 칠해요(작은 캔버스라 충분히 빨라요)."""
    width, height = size
    image = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)),
        )
    return image


def _fit_in_slot(card: "Image.Image") -> "Image.Image":
    """칸 안에 비율을 지켜 맞춰요. 자르지 않아요 - 카드 아트는 테두리에 그림이 있어요."""
    ratio = min(SLOT_W / card.width, SLOT_H / card.height)
    return card.resize(
        (max(1, int(card.width * ratio)), max(1, int(card.height * ratio))),
        Image.LANCZOS,
    )


def _pull_layout(n: int) -> tuple[int, int, int, bool]:
    """뽑은 장수에 맞는 (열 수, 칸 너비, 칸 높이, 썸네일 사용).

    ## 왜 장수에 따라 다른가

    처음엔 **무조건 한 줄**이었어요(1뽑기 = 3장이라 그걸로 충분했거든요). 그런데 연속뽑기가
    생기면서 10연 = 30장이 되자 가로로 9000px짜리 띠가 나왔어요 - 디스코드에서 알아볼 수가
    없어요.

    - **3장 이하**: 큰 카드(300x450)를 한 줄에. 1뽑기의 '펼쳐지는' 맛이 여기서 나와요.
    - **그보다 많으면**: 미리 구워둔 썸네일로 격자. 열 수는 디스코드 임베드 폭(~550px로
      축소돼 보여요)을 생각해서 정해요 - 6장을 6열로 깔면 한 장이 90px밖에 안 돼요.
    """
    if n <= 3:
        return n, SLOT_W, SLOT_H, False
    cols = 3 if n <= 9 else (5 if n <= 15 else 6)
    return cols, GRID_THUMB_W, GRID_THUMB_H, True


def _render(drawn: list[dict]) -> bytes:
    """실제 그리기. **동기 함수**라 반드시 to_thread로 불러야 해요."""
    n = len(drawn)
    cols, slot_w, slot_h, use_thumb = _pull_layout(n)
    rows = -(-n // cols)
    label_h = LABEL_H if not use_thumb else 54
    cell_h = slot_h + label_h

    width = PAD * 2 + slot_w * cols + GAP * (cols - 1)
    height = PAD * 2 + cell_h * rows + GAP * (rows - 1)

    canvas = _vertical_gradient((width, height), BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(canvas)

    big = not use_thumb
    name_font = _font("bold", 26 if big else 17)
    grade_font = _font("regular", 20 if big else 15)
    new_font = _font("bold", 18 if big else 14)

    for i, card in enumerate(drawn):
        slot_x = PAD + (i % cols) * (slot_w + GAP)
        slot_y = PAD + (i // cols) * (cell_h + GAP)
        # ⚠️ 반드시 _rgb를 거쳐야 해요. 정수를 그대로 넘기면 R/B가 뒤바뀌어요(_rgb 주석).
        color = _rgb(GRADE_COLOR.get(card["grade"], 0x969696))

        # 3장 이하면 원본에서 크게, 많으면 미리 구운 썸네일로 (_pull_layout 주석)
        if use_thumb:
            art = _load_thumb(card["key"])
        else:
            art = None
            path = CARD_DIR / f"{card['key']}.webp"
            if path.is_file():
                try:
                    with Image.open(path) as opened:
                        art = _fit_in_slot(opened.convert("RGBA"))
                except Exception:  # noqa: BLE001
                    # 이미지 한 장이 깨져도 나머지는 보여줘야 해요.
                    log.warning("카드 이미지를 못 열었어요: %s", path.name, exc_info=True)

        if art is not None:
            # 칸 안에서 가운데 정렬
            ax = slot_x + (slot_w - art.width) // 2
            ay = slot_y + (slot_h - art.height) // 2
            canvas.paste(art, (ax, ay), art)
            box = (ax - 4, ay - 4, ax + art.width + 3, ay + art.height + 3)
        else:
            # 이미지가 없으면 빈 칸이라도 등급 테두리로 그려요(뽑기 자체는 성립하게).
            box = (slot_x, slot_y, slot_x + slot_w, slot_y + slot_h)
            draw.text(
                (slot_x + 10, slot_y + slot_h // 2),
                "이미지 없음", font=grade_font, fill=TEXT_SUB,
            )

        # 등급 테두리. 레전드일수록 두껍게 해서 멀리서도 티가 나게 해요.
        thick = (6 if card["grade"] == "레전드" else 4 if card["grade"] == "에픽" else 3)
        if use_thumb:
            thick = max(2, thick - 1)      # 칸이 작으면 두꺼운 테두리가 그림을 덮어요
        draw.rectangle(box, outline=color, width=thick)

        # 아래쪽 라벨 (등급 -> 이름 순서. 등급이 먼저 눈에 들어와야 해요)
        label_y = slot_y + slot_h + (10 if big else 4)
        draw.text((slot_x, label_y), card["grade"], font=grade_font, fill=color)

        name = card["name"]
        # 칸보다 긴 이름은 잘라요(칸 폭이 고정이라 넘치면 옆 카드와 겹쳐요).
        while name and draw.textlength(name, font=name_font) > slot_w - 8:
            name = name[:-1]
        # 이름도 **등급 색**으로 칠해요(2026-10-17). 전에는 전부 흰색이라 등급이 테두리와
        # 작은 라벨에만 드러났는데, 제일 크게 보이는 글자가 색을 입으니 한눈에 구분돼요.
        draw.text((slot_x, label_y + (26 if big else 18)), name, font=name_font, fill=color)

        # NEW 배지 - 처음 얻은 카드에만. 중복은 아무 표시도 안 해요.
        if card["is_new"]:
            tw = draw.textlength("NEW", font=new_font)
            bh = 26 if big else 20
            bx, by = box[0] + 6, box[1] + 6
            draw.rounded_rectangle(
                (bx, by, bx + tw + 16, by + bh), radius=6, fill=NEW_BG
            )
            draw.text((bx + 8, by + (3 if big else 2)), "NEW", font=new_font, fill=NEW_TEXT)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer.getvalue()


async def render_pull(drawn: list[dict]) -> bytes | None:
    """뽑기 결과 PNG. Pillow가 없거나 그리다 실패하면 None(호출한 쪽이 글자로 물러나요)."""
    if not PILLOW_AVAILABLE or not drawn:
        return None
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(_render, drawn)
        except Exception:
            log.exception("뽑기 결과 렌더링 실패 (%s)", [d.get("key") for d in drawn])
            return None


# ==================================================================
# 📖 도감 - 한 등급을 통째로 펼쳐 보여줘요
#
# `/도감`이 글자 목록만 주던 때는 **정작 모은 카드를 볼 수가 없었어요.** 수집 기능인데
# 수집물을 못 보는 셈이라, 등급별로 전부 펼친 그리드를 그려요.
#
# 안 가진 카드는 **어두운 자물쇠 칸**으로 둬요. 아트를 어둡게 깔아주는 방법도 있지만
# 이 카드들은 전면 일러스트라 어둡게 깔면 그냥 사실상 다 보여요 - 처음 뽑았을 때의
# 재미를 미리 써버려요. 대신 **몇 장 중 몇 장**인지를 윗줄에 크게 보여줘요.
# ==================================================================
GRID_THUMB_W, GRID_THUMB_H = 150, 225
GRID_GAP = 12
GRID_PAD = 24
GRID_HEADER_H = 54
GRID_CAPTION_H = 24          # 썸네일 아래 이름 한 줄

LOCK_BG = (30, 33, 48)
LOCK_EDGE = (56, 61, 86)
LOCK_MARK = (88, 94, 120)


def _load_thumb(key: str):
    """도감 칸에 넣을 썸네일. 못 열면 None(호출부가 빈 칸으로 그려요).

    ⚡ `assets/cards/thumbs/`에 **미리 구워둔 150x225**를 먼저 봐요
    (`scripts/build_card_assets.py`). 없을 때만 768px 원본을 열어 줄여요.

    왜 미리 굽나: 에픽 30장짜리 도감을 그릴 때 매번 원본을 줄이면 윈도우 개발기에서도
    3.6초가 걸렸어요. 그동안 `_RENDER_LOCK`을 붙잡고 있어서 **다른 사람 뽑기까지 밀려요.**
    썸네일을 쓰면 열어서 붙이기만 하면 돼요.
    """
    thumb = THUMB_DIR / f"{key}.webp"
    path = thumb if thumb.is_file() else CARD_DIR / f"{key}.webp"
    if not path.is_file():
        return None
    try:
        with Image.open(path) as opened:
            src = opened.convert("RGBA")
            if src.width <= GRID_THUMB_W and src.height <= GRID_THUMB_H:
                return src.copy()      # 이미 알맞은 크기 - 줄일 필요 없어요
            ratio = min(GRID_THUMB_W / src.width, GRID_THUMB_H / src.height)
            return src.resize((max(1, int(src.width * ratio)),
                               max(1, int(src.height * ratio))), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        log.warning("도감 썸네일 실패: %s", path.name, exc_info=True)
        return None


def _grid_columns(n: int) -> int:
    """칸 수에 맞는 열 수. 13장(레전드)을 6열로 두면 마지막 줄이 1칸만 남아 허전해요."""
    return 5 if n <= 15 else 6


def _render_grid(grade: str, cards: list[dict], counts: dict[str, int]) -> bytes:
    """등급 하나를 전부 펼친 도감 페이지. **동기 함수**라 to_thread로 부르세요."""
    n = len(cards)
    cols = _grid_columns(n)
    rows = -(-n // cols)
    cell_h = GRID_THUMB_H + GRID_CAPTION_H

    width = GRID_PAD * 2 + cols * GRID_THUMB_W + (cols - 1) * GRID_GAP
    height = GRID_PAD * 2 + GRID_HEADER_H + rows * cell_h + (rows - 1) * GRID_GAP

    canvas = _vertical_gradient((width, height), BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(canvas)
    color = _rgb(GRADE_COLOR.get(grade, 0x969696))

    owned = sum(1 for c in cards if counts.get(c["key"]))
    draw.text((GRID_PAD, GRID_PAD), grade, font=_font("bold", 34), fill=color)
    tally = f"{owned} / {n}"
    tally_font = _font("bold", 30)
    draw.text((width - GRID_PAD - draw.textlength(tally, font=tally_font), GRID_PAD + 4),
              tally, font=tally_font, fill=color)

    name_font = _font("regular", 17)
    count_font = _font("bold", 17)
    lock_font = _font("bold", 46)

    for i, card in enumerate(cards):
        cx = GRID_PAD + (i % cols) * (GRID_THUMB_W + GRID_GAP)
        cy = GRID_PAD + GRID_HEADER_H + (i // cols) * (cell_h + GRID_GAP)
        have = counts.get(card["key"], 0)
        box = (cx, cy, cx + GRID_THUMB_W, cy + GRID_THUMB_H)

        if not have:
            # 아직 없는 카드 - 이름도 가려요(처음 뽑는 재미를 남겨둬요).
            draw.rounded_rectangle(box, radius=8, fill=LOCK_BG, outline=LOCK_EDGE, width=2)
            qm = "?"
            draw.text((cx + (GRID_THUMB_W - draw.textlength(qm, font=lock_font)) / 2,
                       cy + GRID_THUMB_H / 2 - 34), qm, font=lock_font, fill=LOCK_MARK)
            continue

        art = _load_thumb(card["key"])

        if art is not None:
            ax = cx + (GRID_THUMB_W - art.width) // 2
            ay = cy + (GRID_THUMB_H - art.height) // 2
            canvas.paste(art, (ax, ay), art)
            draw.rectangle((ax - 2, ay - 2, ax + art.width + 1, ay + art.height + 1),
                           outline=color, width=2)
        else:
            draw.rounded_rectangle(box, radius=8, fill=LOCK_BG, outline=color, width=2)

        # 중복 장수 배지 (일반·레어만 2장 이상이 돼요)
        if have > 1:
            tag = f"×{have}"
            tw = draw.textlength(tag, font=count_font)
            bx, by = cx + GRID_THUMB_W - tw - 16, cy + 6
            draw.rounded_rectangle((bx, by, bx + tw + 10, by + 22), radius=5, fill=color)
            draw.text((bx + 5, by + 2), tag, font=count_font, fill=(10, 12, 20))

        name = card["name"]
        while name and draw.textlength(name, font=name_font) > GRID_THUMB_W - 4:
            name = name[:-1]
        draw.text((cx + (GRID_THUMB_W - draw.textlength(name, font=name_font)) / 2,
                   cy + GRID_THUMB_H + 4), name, font=name_font, fill=color)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def render_grid(grade: str, cards: list[dict], counts: dict[str, int]) -> bytes | None:
    """등급 도감 페이지 PNG. 실패하면 None(호출한 쪽이 글자 목록으로 물러나요)."""
    if not PILLOW_AVAILABLE or not cards:
        return None
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(_render_grid, grade, cards, counts)
        except Exception:
            log.exception("도감 그리드 렌더링 실패 (grade=%s)", grade)
            return None


def card_file_path(key: str):
    """한 장 크게 보기용 원본 경로. 없으면 None. (stat 한 번이라 동기로 둬요)

    ⚠️ 크게 볼 때는 **다시 그리지 않고 원본 WebP를 그대로 올려요.** 이미 긴 변 768px로
    줄여둔 파일이라 더 손댈 이유가 없고, 256MB 머신에서 Pillow를 한 번 덜 돌리는 게 좋아요.
    """
    path = CARD_DIR / f"{key}.webp"
    return path if path.is_file() else None
