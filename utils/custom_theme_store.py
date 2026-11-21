"""🖼️ 커스텀 카드 테마 — **내가 올린 그림**으로 프로필 카드 배경을 만들어요 (2026-11-15).

## 흐름

    /커스텀테마 그림:첨부  →  CUSTOM_THEME_PRICE(50코인) 차감 + `pending`에 보관
                          →  🛡️ 방장-매니저에 승인/거절 버튼
    승인 → `image`로 옮기고 '커스텀' 테마를 지급·선택
    거절 → `pending`을 지우고 **낸 코인을 전액 환불**

## 🚨 왜 승인을 거치나

프로필 카드는 채널에 **공개로** 올라가요. 바로 적용하면 부적절한 그림이 승인 없이
서버에 뿌려져요(사용자 결정, 2026-11-15).

## 🚨 그림은 **카드 크기로 줄여서** Mongo에 담아요

원본(최대 수 MB)을 그대로 담으면 프로필을 그릴 때마다 큰 그림을 내려받고 디코딩해요
(운영 머신 512MB). 받은 순간 **cover 맞춤 → 1000x630 JPEG**로 줄이면 ~100KB예요.
`data/`(Fly 볼륨)에 파일로 두지 않는 이유: 머신을 갈면 사라지고, 백업도 안 따라와요.

## 🚨 승인·거절은 **원자적**이어야 해요

두 매니저가 동시에 누르면 ⒜ 승인+거절이 둘 다 되거나 ⒝ 환불이 두 번 될 수 있어요.
`pending`이 **있을 때만** 바꾸는 `find_one_and_update` 하나로 처리해서, 늦게 누른
쪽은 None을 받아요(= "이미 처리됨").
"""
import asyncio
import io
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_col = _db["custom_themes"]

KST = timezone(timedelta(hours=9))

# 상점·프로필이 쓰는 테마 이름. `cosmetic_store.themes`에 이 이름이 들어가요.
THEME_KEY = "커스텀"

# 원본 파일 한도. 디스코드 무료 첨부가 10MB라 그보다 살짝 낮게.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# 🚨 디코딩 폭탄 방지 — 헤더의 가로×세로가 이걸 넘으면 **디코딩 전에** 거절해요.
MAX_PIXELS = 6000 * 6000
# 이보다 작으면 늘렸을 때 뭉개져요.
MIN_SIDE = (480, 300)
OUT_SIZE = (1000, 630)       # profile_card.CARD_WIDTH/HEIGHT와 같게
JPEG_QUALITY = 88


class BadImage(ValueError):
    """사용자에게 그대로 보여줄 수 있는 사유를 담아요."""


def _uid(user_id) -> str:
    return str(user_id)


# ------------------------------------------------------------------ 그림 손질 (동기)
def prepare_image(raw: bytes) -> tuple[bytes, tuple, tuple]:
    """(JPEG 바이트, top색, bottom색). 못 쓰는 그림이면 BadImage.

    🚨 **동기 함수**예요 — 반드시 `asyncio.to_thread`로 불러요(디코딩·리사이즈가 무거워요).
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadImage(f"파일이 너무 커요 ({len(raw) / 1024 / 1024:.1f}MB) — 8MB 이하로 올려주세요")
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:                          # pragma: no cover
        raise BadImage("지금은 그림을 처리할 수 없어요 (서버 설정 문제)") from exc

    try:
        src = Image.open(io.BytesIO(raw))
        w, h = src.size                                 # 헤더만 읽어요
    except Exception as exc:                            # noqa: BLE001
        raise BadImage("그림 파일로 읽을 수 없어요 (PNG·JPG·WEBP를 올려주세요)") from exc
    if w * h > MAX_PIXELS:
        raise BadImage(f"그림이 너무 커요 ({w}x{h}) — 6000x6000 이하로 줄여주세요")
    if w < MIN_SIDE[0] or h < MIN_SIDE[1]:
        raise BadImage(f"그림이 너무 작아요 ({w}x{h}) — 가로 {MIN_SIDE[0]}, 세로 {MIN_SIDE[1]} 이상이 필요해요")

    try:
        # 휴대폰 사진은 EXIF 회전값이 있어서 안 돌리면 옆으로 누워요.
        src = ImageOps.exif_transpose(src)
        if getattr(src, "is_animated", False):
            src.seek(0)                                 # 움짤은 첫 장만
        img = src.convert("RGB")
    except Exception as exc:                            # noqa: BLE001
        raise BadImage("그림을 여는 중에 문제가 생겼어요. 다른 파일로 해주세요") from exc

    # cover 맞춤: 꽉 채우고 넘치는 쪽을 잘라요. 세로는 위쪽을 조금 더 남겨요(얼굴 보호).
    tw, th = OUT_SIZE
    scale = max(tw / img.width, th / img.height)
    new = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(new, Image.LANCZOS)
    off_x = (new[0] - tw) // 2
    off_y = min((new[1] - th) // 2, max(0, (new[1] - th) // 4))
    img = img.crop((off_x, off_y, off_x + tw, off_y + th))

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    # 스크림·칸 색에 쓸 어두운 두 색 — 캐릭터 테마와 **같은 함수**로 뽑아요.
    from utils import card_theme_assets as cta
    small = img.resize((2, 2))
    px = [small.getpixel((x, y)) for x in (0, 1) for y in (0, 1)]
    avg = tuple(sum(c[i] for c in px) // 4 for i in range(3))
    top = cta._cap(tuple(max(8, int(avg[i] * 0.22)) for i in range(3)), 30)
    bottom = cta._cap(tuple(max(14, int(avg[i] * 0.38)) for i in range(3)), 52)
    return out.getvalue(), top, bottom


# ------------------------------------------------------------------ DB (동기)
def _submit_sync(user_id, jpeg: bytes, top, bottom, paid: int) -> bool:
    """대기 중인 신청이 없을 때만 넣어요. 이미 있으면 False."""
    from pymongo.errors import DuplicateKeyError
    try:
        res = _col.update_one(
            {"_id": _uid(user_id), "pending": {"$exists": False}},
            {"$set": {"pending": jpeg, "pendingTop": list(top), "pendingBottom": list(bottom),
                      "pendingPaid": int(paid), "pendingAt": datetime.now(KST)}},
            upsert=True,
        )
    except DuplicateKeyError:
        # 문서는 있는데 pending도 있어서 필터가 안 맞았고, upsert가 같은 _id로 새로
        # 만들려다 부딪힌 경우예요 = 이미 대기 중.
        return False
    return res.modified_count == 1 or res.upserted_id is not None


def _set_review_msg_sync(user_id, channel_id: int, message_id: int) -> None:
    _col.update_one({"_id": _uid(user_id), "pending": {"$exists": True}},
                    {"$set": {"reviewChannel": int(channel_id), "reviewMessage": int(message_id)}})


def _cancel_pending_sync(user_id) -> int:
    """대기 신청을 지우고 낸 코인을 돌려받을 수 있게 그 값을 돌려줘요. 없었으면 0."""
    before = _col.find_one_and_update(
        {"_id": _uid(user_id), "pending": {"$exists": True}},
        {"$unset": {"pending": "", "pendingTop": "", "pendingBottom": "", "pendingPaid": "",
                    "pendingAt": "", "reviewChannel": "", "reviewMessage": ""}},
        projection={"pendingPaid": 1},
    )
    return int((before or {}).get("pendingPaid") or 0) if before else -1


def _approve_sync(user_id, reviewer_id) -> bool:
    """pending → image. 이미 처리됐으면 False.

    ⚠️ 필드를 다른 필드 값으로 옮기려면 **파이프라인 업데이트**가 필요해요(MongoDB 4.2+).
    읽고 → 쓰기로 나누면 그 사이에 거절이 끼어들 수 있어요."""
    res = _col.update_one(
        {"_id": _uid(user_id), "pending": {"$exists": True}},
        [
            {"$set": {"image": "$pending", "top": "$pendingTop", "bottom": "$pendingBottom",
                      "approvedAt": datetime.now(KST), "approvedBy": str(reviewer_id)}},
            {"$unset": ["pending", "pendingTop", "pendingBottom", "pendingPaid", "pendingAt",
                        "reviewChannel", "reviewMessage"]},
        ],
    )
    return res.modified_count == 1


def _get_sync(user_id) -> dict:
    return _col.find_one({"_id": _uid(user_id)}, {"image": 1, "top": 1, "bottom": 1,
                                                 "pendingAt": 1, "pendingPaid": 1}) or {}


# ------------------------------------------------------------------ async 공개 API
async def prepare(raw: bytes) -> tuple[bytes, tuple, tuple]:
    return await asyncio.to_thread(prepare_image, raw)


async def submit(user_id, jpeg: bytes, top, bottom, paid: int) -> bool:
    return await asyncio.to_thread(_submit_sync, user_id, jpeg, top, bottom, paid)


async def set_review_message(user_id, channel_id: int, message_id: int) -> None:
    await asyncio.to_thread(_set_review_msg_sync, user_id, channel_id, message_id)


async def reject(user_id) -> int:
    """거절(또는 올리기 실패 되돌리기). 돌려줄 코인 수. **-1이면 이미 처리된 신청**이에요."""
    return await asyncio.to_thread(_cancel_pending_sync, user_id)


async def approve(user_id, reviewer_id) -> bool:
    return await asyncio.to_thread(_approve_sync, user_id, reviewer_id)


async def status(user_id) -> dict:
    """{has_image, pending, pending_paid} — 상점 화면 안내용."""
    doc = await asyncio.to_thread(_get_sync, user_id)
    return {
        "has_image": bool(doc.get("image")),
        "pending": bool(doc.get("pendingAt")),
        "pending_paid": int(doc.get("pendingPaid") or 0),
    }


async def approved_art(user_id) -> dict | None:
    """프로필을 그릴 때 써요: {image: bytes, top, bottom}. 없거나 조회 실패면 None.
    🚨 실패해도 카드는 그려져야 해요 → 예외를 삼키고 None(= 기본 배경)."""
    try:
        doc = await asyncio.to_thread(_get_sync, user_id)
    except Exception:                                   # noqa: BLE001
        log.warning("🖼️ 커스텀 테마 조회 실패 — 기본으로 그려요 (user=%s)", user_id, exc_info=True)
        return None
    if not doc.get("image"):
        return None
    return {
        "image": bytes(doc["image"]),
        "top": tuple(doc.get("top") or (18, 18, 26)),
        "bottom": tuple(doc.get("bottom") or (34, 34, 48)),
    }
