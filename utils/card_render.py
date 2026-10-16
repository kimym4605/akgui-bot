"""🎴 뽑기 결과 이미지 - 나온 카드 3장을 PNG 한 장으로 합쳐요.

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

# 카드 한 장을 그릴 칸 크기. 원본이 대략 2:3이라 거기에 맞춰요.
SLOT_W, SLOT_H = 300, 450
GAP = 24                 # 카드 사이 간격
PAD = 28                 # 바깥 여백
LABEL_H = 76             # 카드 아래 이름·등급이 들어갈 높이

BG_TOP = (15, 17, 25)
BG_BOTTOM = (26, 29, 46)
TEXT = (255, 255, 255)
TEXT_SUB = (139, 146, 168)
NEW_BG = (88, 214, 141)
NEW_TEXT = (10, 20, 14)


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


def _render(drawn: list[dict]) -> bytes:
    """실제 그리기. **동기 함수**라 반드시 to_thread로 불러야 해요."""
    n = len(drawn)
    width = PAD * 2 + SLOT_W * n + GAP * (n - 1)
    height = PAD * 2 + SLOT_H + LABEL_H

    canvas = _vertical_gradient((width, height), BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(canvas)

    name_font = _font("bold", 26)
    grade_font = _font("regular", 20)
    new_font = _font("bold", 18)

    for i, card in enumerate(drawn):
        slot_x = PAD + i * (SLOT_W + GAP)
        color = GRADE_COLOR.get(card["grade"], (150, 150, 150))

        path = CARD_DIR / f"{card['key']}.webp"
        art = None
        if path.is_file():
            try:
                with Image.open(path) as opened:
                    art = _fit_in_slot(opened.convert("RGBA"))
            except Exception:  # noqa: BLE001
                # 이미지 한 장이 깨져도 나머지 2장은 보여줘야 해요.
                log.warning("카드 이미지를 못 열었어요: %s", path.name, exc_info=True)

        if art is not None:
            # 칸 안에서 가운데 정렬
            ax = slot_x + (SLOT_W - art.width) // 2
            ay = PAD + (SLOT_H - art.height) // 2
            canvas.paste(art, (ax, ay), art)
            box = (ax - 4, ay - 4, ax + art.width + 3, ay + art.height + 3)
        else:
            # 이미지가 없으면 빈 칸이라도 등급 테두리로 그려요(뽑기 자체는 성립하게).
            box = (slot_x, PAD, slot_x + SLOT_W, PAD + SLOT_H)
            draw.text(
                (slot_x + SLOT_W // 2 - 40, PAD + SLOT_H // 2),
                "이미지 없음", font=grade_font, fill=TEXT_SUB,
            )

        # 등급 테두리. 레전드일수록 두껍게 해서 멀리서도 티가 나게 해요.
        thickness = 6 if card["grade"] == "레전드" else 4 if card["grade"] == "에픽" else 3
        draw.rectangle(box, outline=color, width=thickness)

        # 아래쪽 라벨 (등급 -> 이름 순서. 등급이 먼저 눈에 들어와야 해요)
        label_y = PAD + SLOT_H + 10
        draw.text((slot_x, label_y), card["grade"], font=grade_font, fill=color)

        name = card["name"]
        # 칸보다 긴 이름은 잘라요(세 칸 폭이 고정이라 넘치면 옆 카드와 겹쳐요).
        while name and draw.textlength(name, font=name_font) > SLOT_W - 8:
            name = name[:-1]
        draw.text((slot_x, label_y + 26), name, font=name_font, fill=TEXT)

        # NEW 배지 - 처음 얻은 카드에만. 중복은 아무 표시도 안 해요.
        if card["is_new"]:
            tw = draw.textlength("NEW", font=new_font)
            bx, by = box[0] + 6, box[1] + 6
            draw.rounded_rectangle(
                (bx, by, bx + tw + 16, by + 26), radius=6, fill=NEW_BG
            )
            draw.text((bx + 8, by + 3), "NEW", font=new_font, fill=NEW_TEXT)

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
