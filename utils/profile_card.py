"""악귀 프로필 카드 - 한 사람의 서버 활동을 PNG 한 장으로 그려줘요.

## 왜 이미지인가

같은 내용을 임베드로도 띄울 수 있어요. 그런데 임베드는 **밖으로 못 나가요** - 스크린샷을
찍어 다른 채널이나 카톡에 올리면 글자만 남은 초라한 네모가 돼요. 카드는 그 자체가 그림이라
"내 프로필 올리고 비교하는" 재미가 생겨요. 그게 이 기능의 전부라서 이미지로 그려요.

## 폰트

`python:3.12-slim`에는 폰트가 **하나도 없어요.** 아무것도 안 하면 한글이 전부 두부(□)로
나와요. Dockerfile에서 `fonts-nanum`을 설치하고, 여기서는 나눔 -> 윈도우 맑은고딕 ->
`assets/fonts/` 동봉본 순으로 찾아요(로컬 개발도 그대로 되게).

⚠️ 이모지는 일부러 안 그려요. 컬러 이모지는 별도 폰트(Noto Color Emoji)가 필요하고,
Pillow 버전에 따라 렌더링이 깨지거나 통째로 실패해요. 대신 도형과 색으로 구분해요.

## 메모리

⚠️ 이 봇은 **256MB짜리 머신**에서 돌고, 메모리가 모자라 노래방이 끊긴 전력이 있어요
(swap 512MB로 완화한 상태). 카드 한 장은 1000x560 RGBA라 버퍼만 2.2MB지만, 합성 중간
레이어와 아바타까지 합치면 순간 10~20MB를 써요. 그래서:

  - `_RENDER_LOCK`(동시 2장)으로 **동시에 그리는 수를 묶어두고**
  - 실제 그리기는 `asyncio.to_thread`로 넘겨서 이벤트 루프를 막지 않아요

사람이 몰려도 메모리 사용량이 위로 튀지 않고 대기열이 길어질 뿐이에요.
"""
import asyncio
import io
import logging
import os
from pathlib import Path

from utils import card_theme_assets

log = logging.getLogger(__name__)

# Pillow가 없어도 봇 전체가 죽으면 안 돼요. 카드만 조용히 포기하고 임베드로 물러나요.
try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover
    PILLOW_AVAILABLE = False
    log.warning("Pillow가 없어서 프로필 카드를 그릴 수 없어요. requirements.txt를 확인하세요.")

# 동시에 그리는 카드 수. 256MB 머신이라 넉넉히 잡으면 안 돼요(파일 맨 위 설명 참고).
_RENDER_LOCK = asyncio.Semaphore(2)

CARD_WIDTH = 1000
# 🔄 2026-11-15 560 → 630: 통계 칸 **2번째 줄**(🎙️ 음성 레벨 · 🎣 낚시 · 📋 미션 · 📅 출석)을
#    넣으면서 키웠어요. 하단 출석 한 줄은 그 칸으로 옮겨서 없앴어요.
CARD_HEIGHT = 630
VOICE_COLOR = (120, 200, 255)
FISH_COLOR = (110, 220, 210)

# 색 (어두운 카드 위에 흰 글씨)
BG_TOP = (15, 17, 25)
BG_BOTTOM = (26, 29, 46)
PANEL = (23, 26, 40)
PANEL_EDGE = (44, 49, 72)
TEXT = (255, 255, 255)
TEXT_SUB = (139, 146, 168)
TEXT_DIM = (95, 101, 122)
GOLD = (255, 200, 80)
WIN_COLOR = (88, 214, 141)
LOSE_COLOR = (231, 106, 106)

# ── 카드 테마 (`/악귀상점`에서 코인으로 사요) ──────────────────────────────
# ⚠️ 전부 **어두운 색**으로만 만들어요. 패널(PANEL)·글씨(TEXT)가 어두운 배경 기준으로
# 맞춰져 있어서, 밝은 배경을 넣으면 글씨가 안 보여요. 바꾸는 건 배경 두 색뿐이에요.
THEMES: dict[str, dict] = {
    "기본":   {"emoji": "🌃", "top": BG_TOP,          "bottom": BG_BOTTOM,      "desc": "어두운 남색 (기본)"},
    "자정":   {"emoji": "🌑", "top": (10, 10, 12),    "bottom": (28, 28, 34),   "desc": "거의 검정, 가장 담백해요"},
    "라디안": {"emoji": "🔥", "top": (38, 14, 14),    "bottom": (72, 26, 22),   "desc": "발로란트 레드"},
    "심해":   {"emoji": "🌊", "top": (8, 24, 34),     "bottom": (14, 48, 64),   "desc": "짙은 청록"},
    "자수정": {"emoji": "🔮", "top": (26, 14, 38),    "bottom": (48, 26, 70),   "desc": "보라"},
    "숲":     {"emoji": "🌲", "top": (12, 26, 20),    "bottom": (20, 46, 34),   "desc": "깊은 초록"},
    "황혼":   {"emoji": "🌆", "top": (34, 18, 26),    "bottom": (62, 34, 30),   "desc": "노을빛 자주"},
}
for _t in THEMES.values():
    _t.setdefault("kind", "color")
del _t

# ── 🎴 캐릭터 테마 (그림 배경) ────────────────────────────────────────────
# ⭐ 카탈로그를 **코드에 박지 않아요.** `assets/card_themes/`에 그림을 넣고
#    `themes.json`에 한 줄 적으면 상점에 떠요 → `utils/card_theme_assets.py`
# 🚨 그림이 없는 항목은 거기서 **이미 걸러져요**(돈만 받고 안 바뀌는 상품 방지).
CHARACTER_THEMES: dict[str, dict] = dict(card_theme_assets.CHARACTER_THEMES)

# 사는 쪽이 보는 전체 목록. 🚨 **이름이 겹치면 색 테마가 이깁니다**(기존 구매자 보호).
ALL_THEMES: dict[str, dict] = {**CHARACTER_THEMES, **THEMES}

# 기본은 공짜예요. 나머지만 코인을 받아요.
#
# 🚨🚨 **가격을 상수 하나로 들고 있지 마세요.** 캐릭터 테마가 더 비싸서(2026-11-03)
#    `price_of(key)`를 안 쓰면 "15코인이라 적고 25코인을 빼는" 사고가 나요.
#    2026-11-02에 미션 보상에서 똑같은 구조의 버그를 네 군데서 걷어냈어요.
COLOR_THEME_PRICE = 15
# 🎴 캐릭터는 25코인. 지갑 중앙값이 15.5(활동자 37)이라 색 테마보다 분명히 비싸지만,
#    "좋아하는 캐릭터"는 색 배경과 달리 **욕심이 나는** 품목이라 이 값으로 뒀어요
#    (사용자 결정, 2026-11-03). 📌 팔리는지 `coin_log`의 `카드테마:*`로 재볼 것.
CHARACTER_THEME_PRICE = 25
# 🖼️ 커스텀(내가 올린 그림)은 100코인. 낚시꾼 하루 벌이(~39)의 2~3일치예요.
#    🚨 **방장 승인 후 적용**이고 거절되면 전액 환불(사용자 결정, 2026-11-15).
#    그림을 바꿀 때도 같은 값이에요(새로 그려 넣는 것과 같으니까요).
#    ⚠️ 이 테마는 `ALL_THEMES`에 **넣지 않아요** — 드롭다운에서 25코인처럼 팔리면 안 되고,
#       그림이 사람마다 달라서 카탈로그 항목이 될 수 없어요. → utils/custom_theme_store.py
# 🔄 2026-11-22 100 → **50**. 출시 7일 동안 신청 0건이었어요. 100코인 이상 가진 사람이
#    10명뿐이었고(50 이상은 20명), 그림 테마(25)의 4배라 "그림 하나에 너무 비싸다"는 쪽.
#    50이면 그림 테마의 2배 — 방장 승인 수고값까지 친 값이에요. 대기 중 신청의 환불은
#    문서에 적힌 `paid`로 하니 가격을 바꿔도 안 꼬여요.
#    ⚠️ 또 0건이면 가격보다 "그림을 준비하는 수고"가 벽인 거라, 더 내리기 전에 안내부터 볼 것.
CUSTOM_THEME_PRICE = 50
CUSTOM_THEME_KEY = "커스텀"
CUSTOM_THEME = {"kind": "custom", "emoji": "🖼️", "desc": "내가 올린 그림",
                "top": BG_TOP, "bottom": BG_BOTTOM}


def price_of(key: str) -> int:
    """그 테마를 사는 값. 🚨 **차감·안내 모두 이 함수를 쓰세요.**"""
    info = ALL_THEMES.get(key)
    if info is None:
        # 모르는 이름이면 비싼 쪽으로 틀려요(공짜로 새는 것보다 낫습니다).
        return CHARACTER_THEME_PRICE
    return CHARACTER_THEME_PRICE if info.get("kind") == "character" else COLOR_THEME_PRICE


def is_character(key: str) -> bool:
    return (ALL_THEMES.get(key) or {}).get("kind") == "character"

FONT_DIRS = [
    # 배포 환경 (Dockerfile에서 fonts-nanum 설치)
    "/usr/share/fonts/truetype/nanum",
    # 윈도우 로컬 개발
    "C:/Windows/Fonts",
    # 레포에 직접 넣어둔 경우 (⚠️ data/ 말고 assets/ - Fly 볼륨이 data/를 덮어써요)
    str(Path(__file__).resolve().parent.parent / "assets" / "fonts"),
]

BOLD_CANDIDATES = ["NanumGothicBold.ttf", "NanumBarunGothicBold.ttf", "malgunbd.ttf", "NotoSansKR-Bold.ttf"]
REGULAR_CANDIDATES = ["NanumGothic.ttf", "NanumBarunGothic.ttf", "malgun.ttf", "NotoSansKR-Regular.ttf"]

_font_cache: dict[tuple[str, int], "ImageFont.FreeTypeFont"] = {}
_font_path_cache: dict[str, str | None] = {}


def _find_font(candidates: list[str]) -> str | None:
    for directory in FONT_DIRS:
        for name in candidates:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                return path
    return None


def font_status() -> str:
    """진단용. 어떤 폰트를 쓰고 있는지 한 줄로 알려줘요."""
    bold = _find_font(BOLD_CANDIDATES)
    return bold or "❌ 한글 폰트를 찾지 못했어요 (한글이 □로 나와요)"


def _font(weight: str, size: int):
    key = (weight, size)
    if key in _font_cache:
        return _font_cache[key]

    if weight not in _font_path_cache:
        _font_path_cache[weight] = _find_font(
            BOLD_CANDIDATES if weight == "bold" else REGULAR_CANDIDATES
        )
    path = _font_path_cache[weight]

    if path:
        loaded = ImageFont.truetype(path, size)
    else:
        # 폰트를 못 찾아도 그림 자체는 나와야 해요(한글은 깨지지만 배포 사고로 번지진 않게).
        loaded = ImageFont.load_default()
    _font_cache[key] = loaded
    return loaded


def _panel_colors(theme: dict) -> tuple[tuple, tuple]:
    """배경 두 색에서 패널·테두리 색을 뽑아요.

    테마마다 패널 색을 손으로 적지 않는 이유는, 빠뜨리거나 어긋나기 쉬워서예요. 기본 테마에
    넣고 돌려보면 원래 쓰던 PANEL(23,26,40)·PANEL_EDGE(44,49,72)와 거의 같은 값이 나와요
    (그게 `scripts/test_akgui_shop.py`가 고정하는 조건이에요). 배경이 빨강이면 패널도 같이
    붉어져서, 남색 패널이 혼자 겉도는 게 사라져요."""
    top, bottom = theme["top"], theme["bottom"]
    panel = tuple(int(top[i] + (bottom[i] - top[i]) * 0.7) for i in range(3))
    edge = tuple(min(255, int(bottom[i] * 1.55)) for i in range(3))
    return panel, edge


def _gradient_background(top=BG_TOP, bottom=BG_BOTTOM) -> "Image.Image":
    """위에서 아래로 그라데이션. 세로줄 560개라 픽셀 루프보다 훨씬 빨라요."""
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), top)
    draw = ImageDraw.Draw(image)
    for y in range(CARD_HEIGHT):
        ratio = y / CARD_HEIGHT
        color = tuple(
            int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)
        )
        draw.line([(0, y), (CARD_WIDTH, y)], fill=color)
    return image


# 🎴 캐릭터 테마 스크림(어둡게 덮는 정도). 왼쪽은 글씨가 올라가니 많이, 오른쪽은
# 그림이 보여야 하니 적게 덮어요.
#
# ⭐⭐ **이 가로 그라데이션이 이 기능의 핵심 설계예요.** 카드에서 글씨는 거의 전부
#    **왼쪽**에 있어요(닉네임·칭호·티어는 x 210~830, 통계 칸은 패널이 불투명해서 가려요).
#    오른쪽 위는 워터마크뿐이에요. 그래서 "왼쪽은 어둡게 · 오른쪽은 밝게" 덮으면
#    **글씨 가독성을 하나도 안 잃고** 그림이 보여요.
# 🚨 그 덕분에 패널·글씨 그리는 코드를 **한 줄도 안 고쳤어요.** 반투명 패널로 가려면
#    "패널 전부 → 합성 → 글씨" 순서로 `_render`를 쪼개야 하는데, 지금은 패널과 글씨가
#    `_stat_box` 안에서 번갈아 그려지니 통째로 뒤집어야 했어요. 그 위험을 피했어요.
# 🚨 겜악귀들의천국 메인 메뉴에서 배운 것과 같아요 — **배경은 연하게.**
#
# 🚨 **한 번에 쭉 옅어지게 했다가 고쳤어요.** 흰 배경 그림으로 뽑아보니 글씨가 있는
#    가운데(x 400~700)까지 밝아져서 "VALORANT"·하단 출석 줄이 묻혔어요. 그래서
#    **x가 SCRIM_HOLD까지는 진하게 유지**하다가 거기서부터 옅어지게 2단으로 바꿨어요.
#    글씨는 전부 왼쪽 62% 안에 있고, 오른쪽 38%가 그림 자리예요.
#
# 🚨🚨 **2026-11-15에 다시 옅게 바꿨어요.** 카드에 통계 2번째 줄이 생기면서 칸이
#    **가로 전체(x 44~956)**를 덮게 됐어요. 불투명 칸 + 0.90 스크림이면 그림은 칸
#    사이 틈과 오른쪽 위 귀퉁이에만 보였어요(그림 테마 8종을 실제로 뽑아보고 찾았어요).
#    → ⒜ 그림 테마에서는 칸을 **반투명**(`ART_PANEL_ALPHA`)으로 그리고
#      ⒝ 스크림을 옅게 내려서 칸 너머로 그림이 비치게 했어요.
#    글씨는 칸 위에 있으니 칸이 한 번 더 어둡게 받쳐줘요. 칸 밖 글씨에는 검은 테두리.
SCRIM_LEFT = 0.55
SCRIM_RIGHT = 0.18
SCRIM_HOLD = 0.40
# 그림 테마의 통계 칸 불투명도(0~255). 낮출수록 그림이 잘 보이지만 보조 글씨가 묻혀요.
ART_PANEL_ALPHA = 178


def _cover_resize(art: "Image.Image") -> "Image.Image":
    """카드 비율에 맞춰 **꽉 채우고 넘치는 쪽을 잘라요**(CSS의 object-fit: cover).

    ⚠️ 그냥 resize하면 비율이 깨져서 캐릭터가 홀쭉해져요. 맞춰 넣으면(contain) 여백이
    생기고, 그 여백이 그라데이션도 아니라 더 지저분해요."""
    target_w, target_h = CARD_WIDTH, CARD_HEIGHT
    src_w, src_h = art.size
    scale = max(target_w / src_w, target_h / src_h)
    new = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    art = art.resize(new, Image.LANCZOS)
    # 가로는 가운데, 세로는 **위쪽**을 남겨요 — 인물 그림은 얼굴이 위에 있어요.
    off_x = (new[0] - target_w) // 2
    off_y = min((new[1] - target_h) // 2, max(0, (new[1] - target_h) // 4))
    return art.crop((off_x, off_y, off_x + target_w, off_y + target_h))


def _art_background(image_path: str, top=BG_TOP, bottom=BG_BOTTOM,
                    scrim: tuple[float, float] | None = None) -> "Image.Image":
    """🎴 캐릭터 그림을 배경으로 깔아요. 실패하면 **그라데이션으로 물러나요.**

    🚨 그림이 깨져 있어도 카드는 나와야 해요. 2026-10에 유니티에서 *"파괴된 스프라이트도
    '그림 없음'이 된다"*로 한 번 당했어요 - 여기선 예외를 잡아 기본 배경으로 떨어뜨려요.
    ⚠️ **캐시하지 않아요.** 1000x560 배경 하나가 ~1.7MB인데 운영 머신의 여유 RAM이
       55MB대예요. `_RENDER_LOCK`(동시 2장) 안에서 그때그때 디코딩하는 게 안전해요.
    """
    try:
        with Image.open(image_path) as source:
            art = _cover_resize(source.convert("RGB"))
    except Exception:                        # noqa: BLE001
        log.warning("🎴 카드 테마 그림을 못 읽었어요(%s) - 그라데이션으로 그려요",
                    image_path, exc_info=True)
        return _gradient_background(top, bottom)

    # 가로 스크림: 왼쪽 SCRIM_LEFT → 오른쪽 SCRIM_RIGHT 만큼 검정을 덮어요.
    # 🐰 테마가 `scrim`을 적어두면(밝은 그림) 그 값으로 덮어요 → card_theme_assets.load
    left, right = scrim if scrim else (SCRIM_LEFT, SCRIM_RIGHT)
    mask = Image.new("L", (CARD_WIDTH, 1))
    mdraw = ImageDraw.Draw(mask)
    hold_px = CARD_WIDTH * SCRIM_HOLD
    for x in range(CARD_WIDTH):
        if x <= hold_px:
            alpha = left                             # 글씨 영역 — 진하게 유지
        else:
            ratio = (x - hold_px) / max(1.0, CARD_WIDTH - 1 - hold_px)
            alpha = left + (right - left) * ratio
        mdraw.point((x, 0), fill=int(alpha * 255))
    mask = mask.resize((CARD_WIDTH, CARD_HEIGHT))
    # 덮는 색은 테마에서 뽑은 어두운 색이에요(순검정보다 그림과 어울려요).
    veil = _gradient_background(top, bottom)
    return Image.composite(veil, art, mask)


def _circle_avatar(avatar_bytes: bytes | None, size: int) -> "Image.Image | None":
    """아바타를 정사각형으로 맞춘 뒤 원형으로 잘라요."""
    if not avatar_bytes:
        return None
    try:
        with Image.open(io.BytesIO(avatar_bytes)) as source:
            avatar = source.convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        log.warning("아바타 이미지를 읽지 못했어요", exc_info=True)
        return None

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    avatar.putalpha(mask)
    return avatar


def _rounded_panel(draw, box, radius=16, fill=PANEL, outline=PANEL_EDGE):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def _fit_text(draw, text: str, font, max_width: int) -> str:
    """칸을 넘치면 뒤를 잘라내고 …을 붙여요. 닉네임이 길어도 카드가 안 깨지게."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and draw.textlength(trimmed + ellipsis, font=font) > max_width:
        trimmed = trimmed[:-1]
    return trimmed + ellipsis


def _stat_box(draw, x, y, width, height, label: str, value: str, value_color=TEXT, sub: str = "",
              panel=PANEL, edge=PANEL_EDGE, sub_color=TEXT_DIM):
    """작은 통계 칸 하나. 라벨(위 작은 글씨) + 값(아래 큰 글씨) + 보조설명.
    ⚠️ 그림 테마는 칸이 반투명이라 `sub_color`를 한 단계 밝게 넘겨받아요."""
    _rounded_panel(draw, (x, y, x + width, y + height), fill=panel, outline=edge)
    draw.text((x + 18, y + 16), label, font=_font("regular", 19), fill=TEXT_SUB)
    draw.text((x + 18, y + 44), value, font=_font("bold", 34), fill=value_color)
    if sub:
        # 칸이 좁아서(약 216px) "최대 철갑상어 210cm" 같은 줄이 넘칠 수 있어요 → 잘라요.
        sub_font = _font("regular", 17)
        draw.text((x + 18, y + 88), _fit_text(draw, sub, sub_font, width - 30),
                  font=sub_font, fill=sub_color)


def _short_minutes(minutes: int) -> str:
    """칸이 좁아서 "1시간 5분" 대신 "1시간"/"35분"처럼 짧게. 60분 이상은 시간만(올림)."""
    if minutes >= 60:
        return f"{-(-minutes // 60)}시간"
    return f"{max(1, minutes)}분"


def _progress_bar(draw, x, y, width, height, ratio: float, color=GOLD, track=(38, 42, 62)):
    """⚠️ 바탕(track)도 테마 색을 받아요. 예전엔 남색으로 박혀 있어서, 빨강 테마 카드에서
    진행바만 혼자 파랗게 떠 보였어요(2026-10-05에 실제 카드를 뽑아보고 찾았어요)."""
    ratio = max(0.0, min(1.0, ratio))
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=track)
    filled = int(width * ratio)
    # 반지름보다 짧으면 rounded_rectangle이 에러를 내요(0%일 때 실제로 터졌어요).
    if filled > height:
        draw.rounded_rectangle((x, y, x + filled, y + height), radius=height // 2, fill=color)


# ── 🧩 발로들 연속 배지 (2026-11-24, 볼트 `악귀봇 디자인` D7) ─────────────────
# 오른쪽 위 작은 알약 모양이에요. 통계 칸은 그대로 두고, 연속이 0인 사람의 카드는 전혀 안 바뀌어요.
# 숫자는 디자이너 기준 구현(`발로들그림/make_mockups.py`의 `draw_balodle_badge`)을 그대로 옮겼어요.
BALODLE_BADGE_RIGHT = CARD_WIDTH - 44     # 통계 칸 오른쪽 끝과 같은 선 (956)
BALODLE_BADGE_TOP = 100                   # 워터마크("시즌 S1") 아래
BALODLE_BADGE_H = 36
BALODLE_BADGE_PAD = 14
BALODLE_ICON = 22
BALODLE_GAP = 8
BALODLE_BADGE_FILL = (23, 26, 40, 225)    # 색 테마·그림 테마 모두 같은 어두운 바탕
BALODLE_EDGE = (44, 49, 72)               # 1~6일
BALODLE_EDGE_7 = (110, 220, 170)          # 7일 이상 = 「발로들 단골」 색
BALODLE_EDGE_30 = (180, 140, 255)         # 30일 이상 = 「발로들 박사」 색
BALODLE_LABEL = (190, 196, 215)
BALODLE_NUMBER = (87, 199, 133)
# 🚨 서버에는 이모지 글꼴이 없어서 퍼즐 조각을 글자(🧩)로 못 그려요 → 그림 파일로 넣어요.
BALODLE_ICON_PATH = (Path(__file__).resolve().parent.parent
                     / "assets" / "valorant" / "balodle" / "ui" / "streak_icon.png")


def _balodle_badge(image, streak: int) -> int | None:
    """발로들 연속 배지를 그리고 **배지 왼쪽 끝 x**를 돌려줘요(칭호 줄 폭을 줄이는 데 써요).
    연속이 0이면 아무것도 안 그리고 `None`이에요."""
    if streak <= 0:
        return None
    # ⭐ `Draw(image, "RGBA")`라 RGB 카드 위에서도 반투명 바탕이 섞여요.
    draw = ImageDraw.Draw(image, "RGBA")
    label_font, num_font = _font("regular", 18), _font("bold", 20)
    label, number = "발로들 연속", f"{streak}일"
    label_w = draw.textlength(label, font=label_font)
    number_w = draw.textlength(number, font=num_font)
    has_icon = BALODLE_ICON_PATH.exists()
    icon_w = BALODLE_ICON + BALODLE_GAP if has_icon else 0
    width = int(BALODLE_BADGE_PAD + icon_w + label_w + 6 + number_w + BALODLE_BADGE_PAD)
    x0, y0 = BALODLE_BADGE_RIGHT - width, BALODLE_BADGE_TOP
    edge = (BALODLE_EDGE_30 if streak >= 30 else BALODLE_EDGE_7 if streak >= 7 else BALODLE_EDGE)
    draw.rounded_rectangle(
        (x0, y0, BALODLE_BADGE_RIGHT, y0 + BALODLE_BADGE_H), radius=BALODLE_BADGE_H // 2,
        fill=BALODLE_BADGE_FILL, outline=(*edge, 255), width=2)
    if has_icon:
        with Image.open(BALODLE_ICON_PATH) as src:
            icon = src.convert("RGBA").resize((BALODLE_ICON, BALODLE_ICON), Image.LANCZOS)
        image.paste(icon, (x0 + BALODLE_BADGE_PAD, y0 + (BALODLE_BADGE_H - BALODLE_ICON) // 2), icon)
    cy = y0 + BALODLE_BADGE_H // 2
    tx = x0 + BALODLE_BADGE_PAD + icon_w
    draw.text((tx, cy), label, font=label_font, fill=BALODLE_LABEL, anchor="lm")
    draw.text((tx + label_w + 6, cy), number, font=num_font, fill=BALODLE_NUMBER, anchor="lm")
    return x0


def _render(data: dict, avatar_bytes: bytes | None) -> bytes:
    """실제 그리기. **동기 함수**라 반드시 to_thread로 불러야 해요."""
    # 모르는 테마 이름이 들어와도(테마를 지웠거나 데이터가 낡았거나) 기본으로 그려요.
    # 🚨 **`ALL_THEMES`를 봐야 해요** — `THEMES`만 보면 캐릭터 테마를 산 사람이
    #    조용히 기본 배경을 받아요(돈만 내고 안 바뀌는, 제일 나쁜 결과).
    theme = ALL_THEMES.get(data.get("theme") or "", THEMES["기본"])
    # 🖼️ 커스텀 테마: 그림이 파일이 아니라 **DB 바이트**예요(profile_service가 넣어줘요).
    #    Image.open이 파일 객체도 받으니 BytesIO로 감싸서 같은 길로 그려요.
    #    ⚠️ 그림이 없으면(승인 전·조회 실패) 위에서 고른 기본 테마로 물러나요.
    custom = data.get("custom_art")
    if data.get("theme") == CUSTOM_THEME_KEY and custom and custom.get("image"):
        theme = {**CUSTOM_THEME, "image": io.BytesIO(custom["image"]),
                 "top": custom["top"], "bottom": custom["bottom"]}
    if theme.get("image"):
        image = _art_background(theme["image"], theme["top"], theme["bottom"], theme.get("scrim"))
    else:
        image = _gradient_background(theme["top"], theme["bottom"])

    # 🚨🚨 **패널 밖에 있는 흐린 글씨**는 그림 테마에서 묻힐 수 있어요. 패널 위 글씨는
    #    패널이 불투명해서 안전한데, 배경에 바로 얹는 글씨(VALORANT 라벨 · 전적 꼬리말 ·
    #    하단 출석 줄 · 워터마크)는 그림이 밝으면 그대로 사라져요. 실제로 흰 배경
    #    그림으로 뽑아보고 찾았어요. → 그림 테마일 때만 **검은 테두리**를 둘러요.
    #    ⚠️ 색 테마는 배경이 늘 어두우니 손대지 않아요(괜히 바꾸면 촌스러워져요).
    on_art = bool(theme.get("image"))
    art_stroke = {"stroke_width": 2, "stroke_fill": (0, 0, 0)} if on_art else {}
    panel, panel_edge = _panel_colors(theme)
    if on_art:
        # ⭐ `Draw(image, "RGBA")`는 RGB 그림 위에서도 **알파 섞기**를 해줘요. 그래서
        #    칸 색에 알파만 붙이면 반투명 칸이 돼요(그리기 순서를 바꿀 필요가 없어요).
        #    글씨 색은 3채널이라 그대로 불투명하게 찍혀요.
        # 🚨 **밝은 그림은 칸을 더 진하게.** 케이오(밝은 보라)로 뽑아보니 오른쪽 칸의
        #    보라 글씨(악귀력)가 연보라 칸 위에서 묻혔어요. 스크림까지 덮인 배경의
        #    오른쪽 절반 밝기를 재서, 밝을수록 알파를 올려요(어두운 그림은 그대로).
        try:
            from PIL import ImageStat
            right = image.crop((CARD_WIDTH // 2, 0, CARD_WIDTH, CARD_HEIGHT)).convert("L")
            lum = ImageStat.Stat(right).mean[0]
        except Exception:                    # noqa: BLE001
            lum = 255.0                      # 못 재면 진한 쪽으로 틀려요(가독성 우선)
        alpha = ART_PANEL_ALPHA + int(max(0.0, min(1.0, (lum - 45) / 60)) * 50)
        panel = (*panel, min(235, alpha))
        panel_edge = (*panel_edge, 220)
        draw = ImageDraw.Draw(image, "RGBA")
    else:
        draw = ImageDraw.Draw(image)
    sub_color = TEXT_SUB if on_art else TEXT_DIM

    accent = data.get("accent_color") or (88, 101, 242)

    # ── 상단 악센트 띠 (티어 색) ──────────────────────────────
    draw.rectangle((0, 0, CARD_WIDTH, 6), fill=accent)

    # ── 아바타 ───────────────────────────────────────────────
    avatar_size = 136
    avatar_x, avatar_y = 44, 46
    avatar = _circle_avatar(avatar_bytes, avatar_size)
    if avatar is not None:
        # 아바타 둘레에 티어 색 링을 둘러요.
        draw.ellipse(
            (avatar_x - 4, avatar_y - 4, avatar_x + avatar_size + 3, avatar_y + avatar_size + 3),
            outline=accent, width=4,
        )
        image.paste(avatar, (avatar_x, avatar_y), avatar)
    else:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill=panel, outline=accent, width=4,
        )

    # ── 닉네임 · 칭호 · 티어 ─────────────────────────────────
    text_x = avatar_x + avatar_size + 30
    name_font = _font("bold", 44)
    # 오른쪽 위에 워터마크("악귀 프로필" / "시즌 S1")가 있어서, 닉네임이 거기까지 뻗으면
    # 글자가 겹쳐요. 워터마크 자리(약 160px)를 미리 빼두고 그 안에서만 그려요.
    draw.text(
        (text_x, avatar_y + 2),
        _fit_text(draw, data["name"], name_font, CARD_WIDTH - text_x - 170),
        font=name_font, fill=TEXT, **art_stroke,
    )

    # 🧩 발로들 연속 배지 (오른쪽 위). 연속이 0이면 안 그려요.
    # 🚨 배지가 있으면 **칭호 줄의 최대 폭을 줄여요** — 그대로 두면 긴 칭호가 배지에 닿아요.
    badge_left = _balodle_badge(image, int(data.get("balodle_streak") or 0))
    title_max = (badge_left - 16 - text_x) if badge_left else (CARD_WIDTH - text_x - 60)

    title = data.get("title")
    if title:
        title_font = _font("bold", 24)
        title_color = data.get("title_color") or GOLD
        label = f"「{title}」"
        draw.text(
            (text_x, avatar_y + 58),
            _fit_text(draw, label, title_font, title_max),
            font=title_font, fill=title_color, **art_stroke,
        )

    tier_text = data.get("tier") or "티어 미확인"
    tier_y = avatar_y + (96 if title else 64)
    draw.text((text_x, tier_y), "VALORANT", font=_font("regular", 18), fill=TEXT_DIM,
              **art_stroke)
    draw.text(
        (text_x + 96, tier_y - 4), tier_text, font=_font("bold", 26),
        fill=accent if data.get("tier") else TEXT_DIM, **art_stroke,
    )

    # ── 발로란트 간략 전적 (티어 줄 바로 아래 한 줄) ─────────
    # `/전적`이 남겨둔 스냅샷이라 여기서 API를 부르지 않아요(profile_service 설명 참고).
    # 값이 없으면(= /전적을 한 번도 안 돌림) 이 줄을 통째로 빼요 - 빈칸을 그리면 지저분해요.
    valorant = data.get("valorant") or {}
    pairs = [
        (label, fmt(valorant[key]))
        for label, key, fmt in (
            ("K/D", "kd", lambda v: f"{v:.2f}"),
            ("승률", "winRate", lambda v: f"{v:.0f}%"),
            ("HS", "hs", lambda v: f"{v:.0f}%"),
        )
        if valorant.get(key) is not None
    ]
    if pairs:
        stat_y = tier_y + 36
        label_font, value_font = _font("regular", 18), _font("bold", 20)
        x = text_x
        for index, (label, value) in enumerate(pairs):
            if index:
                draw.text((x, stat_y + 2), "·", font=label_font, fill=TEXT_DIM, **art_stroke)
                x += draw.textlength("·", font=label_font) + 12
            draw.text((x, stat_y + 2), label, font=label_font, fill=TEXT_SUB, **art_stroke)
            x += draw.textlength(label, font=label_font) + 7
            draw.text((x, stat_y), value, font=value_font, fill=TEXT, **art_stroke)
            x += draw.textlength(value, font=value_font) + 12

        tail_font = _font("regular", 16)
        tail_parts = []
        if valorant.get("matches"):
            tail_parts.append(f"최근 {valorant['matches']}경기")
        if data.get("riot_id"):
            tail_parts.append(data["riot_id"])
        if tail_parts:
            tail = " · ".join(tail_parts)
            draw.text(
                (x + 4, stat_y + 4),
                _fit_text(draw, tail, tail_font, max(CARD_WIDTH - 44 - x - 4, 0)),
                font=tail_font, fill=TEXT_DIM, **art_stroke,
            )

    # ── 통계 4칸 ─────────────────────────────────────────────
    box_y, box_h, gap = 218, 116, 16
    box_w = (CARD_WIDTH - 88 - gap * 3) // 4
    left = 44

    record = data["record"]
    total_games = record["wins"] + record["losses"]
    rate_sub = f"승률 {record['win_rate']:.0f}%" if total_games else "아직 기록 없음"

    _stat_box(draw, left, box_y, box_w, box_h, "악귀코인", f"{data['coin']:,}", GOLD,
              panel=panel, edge=panel_edge, sub_color=sub_color)
    _stat_box(
        draw, left + (box_w + gap), box_y, box_w, box_h, "내전 전적",
        f"{record['wins']}승 {record['losses']}패",
        WIN_COLOR if record["wins"] >= record["losses"] and total_games else TEXT,
        rate_sub, panel=panel, edge=panel_edge, sub_color=sub_color,
    )
    _stat_box(
        draw, left + (box_w + gap) * 2, box_y, box_w, box_h, "최고 연승",
        f"{record['best_streak']}", TEXT, data.get("streak_now", ""),
        panel=panel, edge=panel_edge, sub_color=sub_color,
    )
    agwi = data.get("agwi")
    _stat_box(
        draw, left + (box_w + gap) * 3, box_y, box_w, box_h, "이번 주 악귀력",
        f"{agwi:,.0f}" if agwi else "-", accent,
        data.get("agwi_grade", "") if agwi else "/전적 을 돌려주세요",
        panel=panel, edge=panel_edge, sub_color=sub_color,
    )

    # ── 통계 2번째 줄 (2026-11-15) ───────────────────────────
    # 🚨 값이 없는 사람(통화·낚시 0)도 칸은 그려요. 줄마다 칸 수가 달라지면 카드끼리
    #    비교할 때 자리가 엇갈려요. 대신 값 자리에 "-"와 시작 안내를 적어요.
    row2_y = box_y + box_h + gap
    voice = data.get("voice") or {}
    v_level = int(voice.get("level") or 0)
    v_left = max(0, int(voice.get("need") or 0) - int(voice.get("into") or 0))
    if voice.get("minutes"):
        v_value, v_sub = f"Lv.{v_level}", f"Lv.{v_level + 1}까지 {_short_minutes(v_left)}"
    else:
        v_value, v_sub = "-", "통화하면 쌓여요"
    _stat_box(draw, left, row2_y, box_w, box_h, "음성 레벨", v_value, VOICE_COLOR, v_sub,
              panel=panel, edge=panel_edge, sub_color=sub_color)

    fishing = data.get("fishing") or {}
    caught = int(fishing.get("caught") or 0)
    best = fishing.get("best") or {}
    if best.get("name"):
        f_sub = f"최대 {best['name']}" + (f" {best['size']}cm" if best.get("size") else "")
    else:
        f_sub = "/낚시 로 시작" if not caught else ""
    _stat_box(draw, left + (box_w + gap), row2_y, box_w, box_h, "낚시",
              f"{caught:,}마리" if caught else "-", FISH_COLOR, f_sub,
              panel=panel, edge=panel_edge, sub_color=sub_color)

    missions = int(data.get("mission_total") or 0)
    _stat_box(draw, left + (box_w + gap) * 2, row2_y, box_w, box_h, "누적 미션",
              f"{missions:,}개" if missions else "-", TEXT, "/미션 으로 확인",
              panel=panel, edge=panel_edge, sub_color=sub_color)

    streak = int(data.get("attendance_streak") or 0)
    attend_total = int(data.get("attendance") or 0)
    _stat_box(draw, left + (box_w + gap) * 3, row2_y, box_w, box_h, "연속 출석",
              f"{streak}일" if streak else "-", GOLD,
              f"누적 {attend_total:,}회" if attend_total else "/출석 으로 시작",
              panel=panel, edge=panel_edge, sub_color=sub_color)

    # ── 업적 진행 ────────────────────────────────────────────
    ach_y = row2_y + box_h + 24
    _rounded_panel(draw, (left, ach_y, CARD_WIDTH - 44, ach_y + 92),
                   fill=panel, outline=panel_edge)
    unlocked, total = data["achievements"], data["achievements_total"]
    draw.text((left + 18, ach_y + 16), "업적", font=_font("regular", 19), fill=TEXT_SUB)
    draw.text(
        (left + 18, ach_y + 42), f"{unlocked} / {total}",
        font=_font("bold", 30), fill=TEXT,
    )
    percent = unlocked / total * 100 if total else 0
    percent_font = _font("bold", 22)
    percent_text = f"{percent:.0f}%"
    draw.text(
        (CARD_WIDTH - 62 - draw.textlength(percent_text, font=percent_font), ach_y + 22),
        percent_text, font=percent_font, fill=GOLD,
    )
    _progress_bar(draw, left + 160, ach_y + 56, CARD_WIDTH - 44 - left - 160 - 18, 16,
                  percent / 100, track=panel_edge)

    # (하단 출석 한 줄은 2026-11-15에 2번째 줄 '연속 출석' 칸으로 옮겼어요.)

    # ── 워터마크 ─────────────────────────────────────────────
    #
    # 🚨🚨 **여기만 오른쪽에 있는 글씨예요.** 캐릭터 테마는 오른쪽 스크림이 옅어서
    #    (그림을 보여주려고) 밝은 그림을 깔면 회색 워터마크가 **그대로 묻혀요.**
    #    실제로 샘플 테마의 달과 겹쳐 안 보였어요. 그래서 그림 테마일 때만
    #    ⒜ 글씨를 밝게 ⒝ 검은 테두리(stroke)를 둘러요 — **어떤 그림 위에서도** 읽혀요.
    #    ⚠️ 색 테마는 배경이 늘 어두우니 원래 모양 그대로 둬요(괜히 바꾸면 촌스러워져요).
    mark_fill = TEXT_SUB if on_art else TEXT_DIM
    mark_stroke = art_stroke

    mark_font = _font("bold", 18)
    mark = "악귀 프로필"
    draw.text(
        (CARD_WIDTH - 44 - draw.textlength(mark, font=mark_font), 30),
        mark, font=mark_font, fill=mark_fill, **mark_stroke,
    )
    if data.get("season"):
        season_font = _font("regular", 16)
        season_text = f"시즌 {data['season']}"
        draw.text(
            (CARD_WIDTH - 44 - draw.textlength(season_text, font=season_font), 54),
            season_text, font=season_font, fill=mark_fill, **mark_stroke,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer.getvalue()


async def render_card(data: dict, avatar_bytes: bytes | None = None) -> bytes | None:
    """카드 PNG 바이트를 돌려줘요. Pillow가 없거나 그리다 실패하면 None(호출한 쪽이 임베드로 물러나요)."""
    if not PILLOW_AVAILABLE:
        return None
    async with _RENDER_LOCK:
        try:
            return await asyncio.to_thread(_render, data, avatar_bytes)
        except Exception:
            log.exception("프로필 카드 렌더링 실패 (user=%s)", data.get("name"))
            return None
