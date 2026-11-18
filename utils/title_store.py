"""칭호(커스텀 역할) 보유 기록이에요.

누가 어떤 역할을 언제까지 갖는지만 저장해요. 역할을 실제로 만들고 지우는 건
cogs/title_shop.py가 해요.

⚠️ 만료 시각은 **UTC ISO 문자열**로 저장해요. 봇이 재시작돼도 유지돼야 하고, 로컬 시간대에
의존하면 서버 시간대가 바뀔 때 어긋나요.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_titles = _db["titles"]

TITLE_PRICE = 30       # 악귀코인 (한 달 개근 = 30개)
TITLE_DAYS = 30        # 유지 기간

# 기간별 가격표. 2026-10-05에 10일권을 추가했어요.
#
# 그때까지 칭호는 30코인 한 종류뿐이었는데, 지갑 중앙값이 **3코인**이고 30코인 이상 가진
# 사람이 57명 중 **10명**이었어요. 코인을 쓸 곳이 사실상 아무에게도 없던 셈이에요
# (add 662건 vs spend 6건). 10코인권을 두면 손댈 수 있는 사람이 **22명**으로 늘어요.
#
# ⚠️ 10일권은 하루 단가가 **일부러 더 비싸요**(1.2 vs 1.0코인/일). 짧게 끊어 사는 게 더
# 싸지면 30일권을 아무도 안 사거든요. 긴 쪽이 이득이어야 요금제가 둘 다 의미가 생겨요.
# (처음엔 10코인으로 뒀다가 단가가 똑같아져서 2026-10-05에 12코인으로 올렸어요.)
# ⚠️ 가격을 바꿀 땐 `scripts/test_akgui_shop.py`가 단가 역전을 잡아줘요.
TITLE_PLANS: dict[int, int] = {
    10: 12,
    TITLE_DAYS: TITLE_PRICE,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_sync(user_id) -> dict | None:
    return _titles.find_one({"_id": str(user_id)})


def _save_sync(user_id, guild_id: int, role_id: int, name: str, color: int, days: int = TITLE_DAYS) -> dict:
    """새로 사거나 연장해요. 이미 있으면 남은 기간에 이어붙여요."""
    uid = str(user_id)
    existing = _titles.find_one({"_id": uid})

    base = _now()
    if existing:
        try:
            current_end = datetime.fromisoformat(existing["expiresAt"])
            # 아직 안 끝났으면 그 끝에서부터 연장해요(남은 기간을 잃지 않게).
            base = max(base, current_end)
        except (KeyError, ValueError):
            pass

    doc = {
        "_id": uid,
        "guildId": str(guild_id),
        "roleId": str(role_id),
        "name": name,
        "color": color,
        "expiresAt": (base + timedelta(days=days)).isoformat(),
        "createdAt": _now().isoformat(),
    }
    _titles.replace_one({"_id": uid}, doc, upsert=True)
    return doc


def _delete_sync(user_id) -> bool:
    return _titles.delete_one({"_id": str(user_id)}).deleted_count == 1


def _expired_sync() -> list[dict]:
    """만료 시각이 지난 칭호들이에요."""
    now_iso = _now().isoformat()
    # ISO 8601 문자열은 사전순 비교가 시간순 비교와 같아서 $lt로 그냥 걸러져요.
    return list(_titles.find({"expiresAt": {"$lt": now_iso}}))


def _all_sync() -> list[dict]:
    return list(_titles.find({}))


def remaining_days(doc: dict) -> int:
    try:
        delta = datetime.fromisoformat(doc["expiresAt"]) - _now()
    except (KeyError, ValueError):
        return 0
    return max(0, delta.days)


# ------------------------------------------------------------------
# 공개 API - 전부 async예요 (동기 pymongo를 루프에서 직접 부르면 봇이 멈춰요)
# ------------------------------------------------------------------
async def get(user_id) -> dict | None:
    return await asyncio.to_thread(_get_sync, user_id)


async def save(user_id, guild_id: int, role_id: int, name: str, color: int, days: int = TITLE_DAYS) -> dict:
    return await asyncio.to_thread(_save_sync, user_id, guild_id, role_id, name, color, days)


async def delete(user_id) -> bool:
    return await asyncio.to_thread(_delete_sync, user_id)


async def expired() -> list[dict]:
    return await asyncio.to_thread(_expired_sync)


async def all_titles() -> list[dict]:
    return await asyncio.to_thread(_all_sync)


# ==================================================================
# 🎖️ 칭호 아이콘 (2026-11-15, 부스트 2레벨 = 역할 아이콘 사용 가능)
#
# 칭호 역할 옆에 붙는 작은 아이콘이에요. **유료 추가 옵션**(사용자 결정):
#   - 😀 이모지 — 바로 적용
#   - 🖼️ 그림   — 방장 승인 후 적용, 거절되면 전액 환불 (/커스텀테마와 같은 흐름)
#
# 🚨 아이콘은 **칭호 역할에 붙어요.** 연장하면(같은 역할) 그대로 남고, 만료돼서 역할이
#    지워지면 같이 사라져요. 그래서 저장하는 건 '심사 대기 그림'뿐이에요 — 적용된 아이콘의
#    원본은 역할 자체예요(DB에 두 벌 두면 어긋나요).
# 🚨 `titles` 문서는 `_save_sync`가 **replace_one**으로 통째로 갈아요. 대기 그림을 거기
#    넣으면 칭호 연장 한 번에 날아가서 **환불할 근거가 사라져요.** 그래서 컬렉션을 따로 둬요.
#
# 가격 근거: 2026-11-15 실측 — 칭호는 출시 후 1건 팔렸고(9/30) 지금 0명이에요. 지갑 중앙값
# 30코인, 30코인 이상 31명이라 돈이 없어서는 아니에요. 이모지는 칭호 10일권(12)보다 싸게,
# 그림은 심사 품이 드니 30일권과 같게 뒀어요. 📌 팔리는지 coin_log `칭호아이콘:*`로 재볼 것.
# ==================================================================
TITLE_ICON_EMOJI_PRICE = 10
TITLE_ICON_IMAGE_PRICE = 30

_icons = _db["title_icons"]

ICON_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ICON_MAX_PIXELS = 6000 * 6000
ICON_MIN_SIDE = 32
ICON_SIZE = 128            # 디스코드 역할 아이콘은 64px 이상 권장, 업로드 한도 256KB


class BadIcon(ValueError):
    """사용자에게 그대로 보여줄 수 있는 사유를 담아요."""


def prepare_icon(raw: bytes) -> bytes:
    """정사각형으로 가운데를 잘라 128x128 PNG로. 투명 배경은 살려요.

    🚨 **동기 함수** — `asyncio.to_thread`로 불러요."""
    import io
    if len(raw) > ICON_MAX_UPLOAD_BYTES:
        raise BadIcon(f"파일이 너무 커요 ({len(raw) / 1024 / 1024:.1f}MB) — 8MB 이하로 올려주세요")
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:                          # pragma: no cover
        raise BadIcon("지금은 그림을 처리할 수 없어요 (서버 설정 문제)") from exc
    try:
        src = Image.open(io.BytesIO(raw))
        w, h = src.size                                 # 헤더만 읽어요(디코딩 폭탄 방지)
    except Exception as exc:                            # noqa: BLE001
        raise BadIcon("그림 파일로 읽을 수 없어요 (PNG·JPG·WEBP를 올려주세요)") from exc
    if w * h > ICON_MAX_PIXELS:
        raise BadIcon(f"그림이 너무 커요 ({w}x{h}) — 6000x6000 이하로 줄여주세요")
    if min(w, h) < ICON_MIN_SIDE:
        raise BadIcon(f"그림이 너무 작아요 ({w}x{h}) — 가로·세로 {ICON_MIN_SIDE} 이상이 필요해요")
    try:
        src = ImageOps.exif_transpose(src)
        if getattr(src, "is_animated", False):
            src.seek(0)                                 # 움짤은 첫 장만 (역할 아이콘은 안 움직여요)
        img = src.convert("RGBA")
    except Exception as exc:                            # noqa: BLE001
        raise BadIcon("그림을 여는 중에 문제가 생겼어요. 다른 파일로 해주세요") from exc

    img = ImageOps.fit(img, (ICON_SIZE, ICON_SIZE), Image.LANCZOS, centering=(0.5, 0.5))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _icon_submit_sync(user_id, png: bytes, paid: int) -> bool:
    """대기 중인 그림이 없을 때만 넣어요. 이미 있으면 False."""
    from pymongo.errors import DuplicateKeyError
    try:
        res = _icons.update_one(
            {"_id": str(user_id), "pending": {"$exists": False}},
            {"$set": {"pending": png, "pendingPaid": int(paid), "pendingAt": _now().isoformat()}},
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    return res.modified_count == 1 or res.upserted_id is not None


def _icon_take_sync(user_id) -> dict | None:
    """대기 그림을 **꺼내면서 지워요**(원자적). 승인·거절 둘 다 이걸로 해요 —
    두 매니저가 동시에 눌러도 한 명만 받아요. 이미 처리됐으면 None."""
    return _icons.find_one_and_update(
        {"_id": str(user_id), "pending": {"$exists": True}},
        {"$unset": {"pending": "", "pendingPaid": "", "pendingAt": "",
                    "reviewChannel": "", "reviewMessage": ""}},
        projection={"pending": 1, "pendingPaid": 1},
    )


def _icon_set_review_sync(user_id, channel_id: int, message_id: int) -> None:
    _icons.update_one({"_id": str(user_id), "pending": {"$exists": True}},
                      {"$set": {"reviewChannel": int(channel_id), "reviewMessage": int(message_id)}})


def _icon_pending_sync(user_id) -> bool:
    return _icons.find_one({"_id": str(user_id), "pending": {"$exists": True}}, {"_id": 1}) is not None


async def prepare_icon_async(raw: bytes) -> bytes:
    return await asyncio.to_thread(prepare_icon, raw)


async def icon_submit(user_id, png: bytes, paid: int) -> bool:
    return await asyncio.to_thread(_icon_submit_sync, user_id, png, paid)


async def icon_take(user_id) -> dict | None:
    """{pending: PNG bytes, pendingPaid: int} 또는 None(이미 처리됨)."""
    return await asyncio.to_thread(_icon_take_sync, user_id)


async def icon_set_review(user_id, channel_id: int, message_id: int) -> None:
    await asyncio.to_thread(_icon_set_review_sync, user_id, channel_id, message_id)


async def icon_pending(user_id) -> bool:
    return await asyncio.to_thread(_icon_pending_sync, user_id)
