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
CARD_HEIGHT = 560

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


def _gradient_background() -> "Image.Image":
    """위에서 아래로 어두운 남색 그라데이션. 세로줄 560개라 픽셀 루프보다 훨씬 빨라요."""
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(CARD_HEIGHT):
        ratio = y / CARD_HEIGHT
        color = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio) for i in range(3)
        )
        draw.line([(0, y), (CARD_WIDTH, y)], fill=color)
    return image


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


def _stat_box(draw, x, y, width, height, label: str, value: str, value_color=TEXT, sub: str = ""):
    """작은 통계 칸 하나. 라벨(위 작은 글씨) + 값(아래 큰 글씨) + 보조설명."""
    _rounded_panel(draw, (x, y, x + width, y + height))
    draw.text((x + 18, y + 16), label, font=_font("regular", 19), fill=TEXT_SUB)
    draw.text((x + 18, y + 44), value, font=_font("bold", 34), fill=value_color)
    if sub:
        draw.text((x + 18, y + 88), sub, font=_font("regular", 17), fill=TEXT_DIM)


def _progress_bar(draw, x, y, width, height, ratio: float, color=GOLD):
    ratio = max(0.0, min(1.0, ratio))
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=(38, 42, 62))
    filled = int(width * ratio)
    # 반지름보다 짧으면 rounded_rectangle이 에러를 내요(0%일 때 실제로 터졌어요).
    if filled > height:
        draw.rounded_rectangle((x, y, x + filled, y + height), radius=height // 2, fill=color)


def _render(data: dict, avatar_bytes: bytes | None) -> bytes:
    """실제 그리기. **동기 함수**라 반드시 to_thread로 불러야 해요."""
    image = _gradient_background()
    draw = ImageDraw.Draw(image)

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
            fill=PANEL, outline=accent, width=4,
        )

    # ── 닉네임 · 칭호 · 티어 ─────────────────────────────────
    text_x = avatar_x + avatar_size + 30
    name_font = _font("bold", 44)
    # 오른쪽 위에 워터마크("악귀 프로필" / "시즌 S1")가 있어서, 닉네임이 거기까지 뻗으면
    # 글자가 겹쳐요. 워터마크 자리(약 160px)를 미리 빼두고 그 안에서만 그려요.
    draw.text(
        (text_x, avatar_y + 2),
        _fit_text(draw, data["name"], name_font, CARD_WIDTH - text_x - 170),
        font=name_font, fill=TEXT,
    )

    title = data.get("title")
    if title:
        title_font = _font("bold", 24)
        title_color = data.get("title_color") or GOLD
        label = f"「{title}」"
        draw.text(
            (text_x, avatar_y + 58),
            _fit_text(draw, label, title_font, CARD_WIDTH - text_x - 60),
            font=title_font, fill=title_color,
        )

    tier_text = data.get("tier") or "티어 미확인"
    tier_y = avatar_y + (96 if title else 64)
    draw.text((text_x, tier_y), "VALORANT", font=_font("regular", 18), fill=TEXT_DIM)
    draw.text(
        (text_x + 96, tier_y - 4), tier_text, font=_font("bold", 26),
        fill=accent if data.get("tier") else TEXT_DIM,
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
                draw.text((x, stat_y + 2), "·", font=label_font, fill=TEXT_DIM)
                x += draw.textlength("·", font=label_font) + 12
            draw.text((x, stat_y + 2), label, font=label_font, fill=TEXT_SUB)
            x += draw.textlength(label, font=label_font) + 7
            draw.text((x, stat_y), value, font=value_font, fill=TEXT)
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
                font=tail_font, fill=TEXT_DIM,
            )

    # ── 통계 4칸 ─────────────────────────────────────────────
    box_y, box_h, gap = 218, 116, 16
    box_w = (CARD_WIDTH - 88 - gap * 3) // 4
    left = 44

    record = data["record"]
    total_games = record["wins"] + record["losses"]
    rate_sub = f"승률 {record['win_rate']:.0f}%" if total_games else "아직 기록 없음"

    _stat_box(draw, left, box_y, box_w, box_h, "악귀코인", f"{data['coin']:,}", GOLD)
    _stat_box(
        draw, left + (box_w + gap), box_y, box_w, box_h, "내전 전적",
        f"{record['wins']}승 {record['losses']}패",
        WIN_COLOR if record["wins"] >= record["losses"] and total_games else TEXT,
        rate_sub,
    )
    _stat_box(
        draw, left + (box_w + gap) * 2, box_y, box_w, box_h, "최고 연승",
        f"{record['best_streak']}", TEXT, data.get("streak_now", ""),
    )
    agwi = data.get("agwi")
    _stat_box(
        draw, left + (box_w + gap) * 3, box_y, box_w, box_h, "이번 주 악귀력",
        f"{agwi:,.0f}" if agwi else "-", accent,
        data.get("agwi_grade", "") if agwi else "/전적 을 돌려주세요",
    )

    # ── 업적 진행 ────────────────────────────────────────────
    ach_y = box_y + box_h + 24
    _rounded_panel(draw, (left, ach_y, CARD_WIDTH - 44, ach_y + 92))
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
    _progress_bar(draw, left + 160, ach_y + 56, CARD_WIDTH - 44 - left - 160 - 18, 16, percent / 100)

    # ── 하단 한 줄 (출석) ───────────────────────────
    footer_y = ach_y + 108
    footer_parts = []
    if data.get("attendance"):
        footer_parts.append(f"누적 출석 {data['attendance']}회")
    if data.get("attendance_streak"):
        footer_parts.append(f"연속 {data['attendance_streak']}일")

    if footer_parts:
        draw.text(
            (left, footer_y), "  ·  ".join(footer_parts),
            font=_font("regular", 20), fill=TEXT_SUB,
        )

    # ── 워터마크 ─────────────────────────────────────────────
    mark_font = _font("bold", 18)
    mark = "악귀 프로필"
    draw.text(
        (CARD_WIDTH - 44 - draw.textlength(mark, font=mark_font), 30),
        mark, font=mark_font, fill=TEXT_DIM,
    )
    if data.get("season"):
        season_font = _font("regular", 16)
        season_text = f"시즌 {data['season']}"
        draw.text(
            (CARD_WIDTH - 44 - draw.textlength(season_text, font=season_font), 54),
            season_text, font=season_font, fill=TEXT_DIM,
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
