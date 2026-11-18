# -*- coding: utf-8 -*-
"""🖼️ 커스텀 카드 테마 저장소·그리기 검증 (2026-11-15).

**테스트 DB**(`agwi_profile_test`)를 써요 — 운영 DB는 건드리지 않아요.

    python scripts/test_custom_theme.py

보는 것
- 그림 손질: 너무 작음/깨진 파일/폭탄 크기 거절, 정상 그림은 1000x630 JPEG
- 신청: 대기 중이면 두 번째 신청 거절 (돈 빼고 중복 등록되는 사고 방지)
- 승인: pending → image 이동(파이프라인 업데이트), 두 번째 승인은 False
- 거절: 낸 코인을 돌려주고, 두 번째 거절은 -1 (= 환불 두 번 금지)
- 그리기: '커스텀' 테마 + 그림이면 그림 배경, 그림 없으면 기본으로 물러남
"""
import asyncio
import io
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_profile_test"

from PIL import Image  # noqa: E402

from utils import custom_theme_store as cts  # noqa: E402
from utils import profile_card  # noqa: E402

failed = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failed.append(label)


def png(w, h, color=(200, 80, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


UID = 990000000000000123
REVIEWER = 990000000000000999


async def main():
    assert cts._db.name == "agwi_profile_test", cts._db.name
    cts._col.delete_many({"_id": str(UID)})

    print("\n🖼️ 그림 손질")
    try:
        cts.prepare_image(png(200, 120))
        check("너무 작은 그림은 거절", False)
    except cts.BadImage as e:
        check("너무 작은 그림은 거절", "작아요" in str(e), str(e))
    try:
        cts.prepare_image(b"not an image at all")
        check("깨진 파일은 거절", False)
    except cts.BadImage as e:
        check("깨진 파일은 거절", True, str(e))
    try:
        cts.prepare_image(b"x" * (cts.MAX_UPLOAD_BYTES + 1))
        check("8MB 초과는 거절", False)
    except cts.BadImage as e:
        check("8MB 초과는 거절", "8MB" in str(e))
    # 세로로 긴 사진도 카드 비율로 잘려야 해요.
    jpeg, top, bottom = cts.prepare_image(png(900, 1600))
    with Image.open(io.BytesIO(jpeg)) as im:
        check("결과는 1000x630 JPEG", im.size == (1000, 630) and im.format == "JPEG",
              f"{im.size} {im.format} {len(jpeg) // 1024}KB")
    check("파생 색은 어두워요(글씨가 흰색)", max(top) <= 30 and max(bottom) <= 52, f"{top} {bottom}")
    check("테마 이름이 카드와 같아요", cts.THEME_KEY == profile_card.CUSTOM_THEME_KEY)

    print("\n📮 신청 · 승인")
    check("첫 신청 OK", await cts.submit(UID, jpeg, top, bottom, 100))
    check("대기 중 두 번째 신청은 거절", not await cts.submit(UID, jpeg, top, bottom, 100))
    st = await cts.status(UID)
    check("상태: 대기 중 · 그림 없음", st["pending"] and not st["has_image"] and st["pending_paid"] == 100, str(st))
    check("승인 전엔 카드용 그림이 없어요", await cts.approved_art(UID) is None)
    check("승인 OK", await cts.approve(UID, REVIEWER))
    check("두 번째 승인은 False", not await cts.approve(UID, REVIEWER))
    st = await cts.status(UID)
    check("상태: 그림 있음 · 대기 없음", st["has_image"] and not st["pending"], str(st))
    art = await cts.approved_art(UID)
    check("승인된 그림을 꺼내요", bool(art and art["image"] == jpeg), "")
    check("이미 처리된 신청 거절은 -1", await cts.reject(UID) == -1)

    print("\n❌ 재신청 · 거절")
    jpeg2, t2, b2 = cts.prepare_image(png(1200, 700, (40, 160, 220)))
    check("승인된 뒤 새 그림 재신청 OK", await cts.submit(UID, jpeg2, t2, b2, 100))
    check("거절하면 낸 코인(100)을 돌려줘요", await cts.reject(UID) == 100)
    check("두 번째 거절은 -1 (환불 두 번 금지)", await cts.reject(UID) == -1)
    art = await cts.approved_art(UID)
    check("거절돼도 예전 승인 그림은 그대로", bool(art and art["image"] == jpeg))

    print("\n🎴 카드 그리기")
    base = {"name": "테스트", "coin": 1, "record": {"wins": 0, "losses": 0, "best_streak": 0, "win_rate": 0},
            "achievements": 0, "achievements_total": 58, "attendance": 0, "attendance_streak": 0}
    plain = await profile_card.render_card({**base, "theme": "커스텀"}, None)
    custom = await profile_card.render_card({**base, "theme": "커스텀", "custom_art": art}, None)
    default = await profile_card.render_card({**base, "theme": "기본"}, None)
    check("그림 없는 '커스텀'은 기본 테마와 똑같이 그려져요", plain == default)
    with Image.open(io.BytesIO(custom)) as im:
        px = im.convert("RGB").getpixel((990, 620))   # 오른쪽 아래(스크림 옅은 곳)
    check("그림이 있으면 오른쪽에 그림 색(분홍)이 비쳐요", px[0] > px[2] and px[0] > 60, str(px))

    cts._col.delete_many({"_id": str(UID)})
    print("\n" + ("✅ 전부 통과" if not failed else f"❌ 실패 {len(failed)}개: {failed}"))
    sys.exit(1 if failed else 0)


asyncio.run(main())
