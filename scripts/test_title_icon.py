# -*- coding: utf-8 -*-
"""🎖️ 칭호 아이콘 검증 (2026-11-15).

**테스트 DB**(`agwi_profile_test`)를 써요 — 운영 DB는 건드리지 않아요.

    python scripts/test_title_icon.py

보는 것
- 이모지 거르기: 한 개짜리 이모지·ZWJ·키캡·국기는 통과, 글자·숫자·커스텀 이모지·여러 개는 거절
- 그림 손질: 작음/깨짐 거절, 정상은 128x128 PNG, 투명 배경 유지, 256KB 이하
- 신청: 대기 중이면 두 번째 신청 거절
- 꺼내기(승인·거절 공통): 처음 한 번만 그림과 낸 코인을 받고, 두 번째는 None (= 환불 두 번 금지)
- 칭호 연장(replace_one)이 대기 그림을 지우지 않아요 (컬렉션을 갈라둔 이유)
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

from utils import title_store as ts  # noqa: E402

failed = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failed.append(label)


def img_bytes(w, h, mode="RGB", color=(200, 80, 120), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), color).save(buf, format=fmt)
    return buf.getvalue()


UID = 990000000000000321


async def main():
    from cogs.title_shop import clean_emoji

    print("\n😀 이모지 거르기")
    for good in ("🔥", "🐉", "👑", "❤️", "👨‍👩‍👧", "1️⃣", "🇰🇷", "👍🏽"):
        e, err = clean_emoji(f" {good} ")
        check(f"통과: {good}", e == good, err)
    for bad, why in (("", "빈칸"), ("가", "한글"), ("abc", "영문"), ("12", "숫자"),
                     ("<:pepe:123456>", "커스텀 이모지"), (":fire:", "콜론 이름"),
                     ("🔥🔥🔥🔥🔥🔥🔥", "여러 개"), ("🔥a", "섞임")):
        e, err = clean_emoji(bad)
        check(f"거절: {why}", e is None, err)

    print("\n🖼️ 그림 손질")
    try:
        ts.prepare_icon(img_bytes(20, 20))
        check("너무 작은 그림은 거절", False)
    except ts.BadIcon as exc:
        check("너무 작은 그림은 거절", True, str(exc))
    try:
        ts.prepare_icon(b"not an image")
        check("깨진 파일은 거절", False)
    except ts.BadIcon:
        check("깨진 파일은 거절", True)
    out = ts.prepare_icon(img_bytes(900, 400, fmt="JPEG"))
    im = Image.open(io.BytesIO(out))
    check("결과는 128x128 PNG", im.size == (128, 128) and im.format == "PNG", f"{im.size} {im.format}")
    check("256KB 이하 (디스코드 한도)", len(out) < 256 * 1024, f"{len(out)}B")
    out = ts.prepare_icon(img_bytes(300, 300, mode="RGBA", color=(0, 0, 0, 0)))
    alpha = Image.open(io.BytesIO(out)).getpixel((5, 5))[3]
    check("투명 배경은 투명 그대로", alpha == 0, f"alpha={alpha}")

    print("\n📮 신청 · 꺼내기")
    ts._icons.delete_many({"_id": str(UID)})
    ts._titles.delete_many({"_id": str(UID)})
    png = ts.prepare_icon(img_bytes(200, 200))
    check("첫 신청 OK", await ts.icon_submit(UID, png, ts.TITLE_ICON_IMAGE_PRICE))
    check("대기 중 두 번째 신청은 거절", not await ts.icon_submit(UID, png, ts.TITLE_ICON_IMAGE_PRICE))
    check("대기 중으로 보여요", await ts.icon_pending(UID))

    # 칭호 연장은 titles 문서를 replace_one으로 갈아요 → 대기 그림이 살아 있어야 해요.
    await ts.save(UID, 1, 2, "테스트칭호", 0xFF0000, days=10)
    await ts.save(UID, 1, 2, "테스트칭호", 0xFF0000, days=10)
    check("칭호 연장해도 대기 그림은 그대로", await ts.icon_pending(UID))

    taken = await ts.icon_take(UID)
    check("꺼내면 그림과 낸 코인이 나와요",
          taken is not None and bytes(taken["pending"]) == png
          and taken["pendingPaid"] == ts.TITLE_ICON_IMAGE_PRICE)
    check("두 번째 꺼내기는 None (환불 두 번 금지)", await ts.icon_take(UID) is None)
    check("꺼낸 뒤엔 대기 아님", not await ts.icon_pending(UID))
    check("다시 신청할 수 있어요", await ts.icon_submit(UID, png, 30))

    ts._icons.delete_many({"_id": str(UID)})
    ts._titles.delete_many({"_id": str(UID)})

    print("\n" + ("✅ 전부 통과" if not failed else f"❌ 실패 {len(failed)}개: {failed}"))
    sys.exit(1 if failed else 0)


asyncio.run(main())
