"""📅 일정 예약 검증. 디스코드 없이 돌아요(DB는 있으면 쓰고, 없으면 그 부분만 건너뛰어요).

    python scripts/test_events.py

## 무엇을 막으려고 만들었나

1. 🚨 **영속 뷰가 상태를 들고 있는 것.** 며칠 뒤 일정이라 그 사이 봇이 몇 번이나
   재시작돼요. `self`에 담으면 모든 일정이 같은 상태를 공유해요(team.py 사고와 같음).
2. 🚨 **리마인더가 두 번 가는 것.** 루프가 1분마다 도는데 "보냈다" 표시가 없으면
   같은 일정을 수십 번 알려요.
3. 🚨 **같은 사람이 참가·불참 양쪽에 들어가는 것.**
4. 🚨 **정원을 넘겨 받는 것.**
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

# ⚠️ 실제 DB에 붙어서 RSVP·리마인더까지 봐요. **남긴 문서는 끝에서 지워요.**
load_dotenv(os.path.join(BOT_DIR, ".env"))

import discord  # noqa: E402

from cogs import events  # noqa: E402
from utils import event_store, when_parser  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
print("⒜ 🚨 영속 뷰가 상태를 들고 있지 않다")

view = events.RsvpView()
check("timeout=None (며칠 뒤 일정도 버튼이 산다)", view.timeout is None, f"{view.timeout}")

DISCORD_INTERNAL = {"id", "children", "timeout"}
own = {k for k, v in vars(view).items()
       if not k.startswith("_") and k not in DISCORD_INTERNAL
       and not isinstance(v, discord.ui.Item)}
check("인스턴스 속성에 일정 상태가 없다", not own, f"{own or '없음'}")

ids = sorted(i.custom_id for i in view.children if getattr(i, "custom_id", None))
check("버튼 3개가 고정 custom_id를 갖는다", len(ids) == 3, f"{ids}")
check("custom_id에 일정 id가 안 박혀 있다",
      all(not any(c.isdigit() for c in cid) for cid in ids), f"{ids}")


# ------------------------------------------------------------------
print("\n⒝ 카드 표시")
UTC = timezone.utc
start = datetime.now(UTC) + timedelta(days=2)
doc = {
    "title": "토요일 내전", "startAt": start, "hostId": "1",
    "going": ["1", "2", "3"], "declined": ["4"], "capacity": 10, "canceledAt": None,
}
names = {"1": "노예", "2": "피카츄", "3": "라이츄", "4": "파이리"}
embed = events.build_embed(doc, names)
check("제목이 들어간다", "토요일 내전" in embed.title, embed.title)
check("디스코드 타임스탬프를 쓴다 (보는 사람 시간대로 보이게)",
      any("<t:" in (f.value or "") for f in embed.fields))
check("인원이 보인다", any("3" in (f.value or "") for f in embed.fields))
check("참가자 이름이 보인다", any("피카츄" in (f.value or "") for f in embed.fields))
check("주최자가 보인다", any("노예" in (f.value or "") for f in embed.fields))

canceled = dict(doc, canceledAt=datetime.now(UTC))
check("취소된 일정은 표시가 다르다", "취소" in events.build_embed(canceled, names).title,
      events.build_embed(canceled, names).title)


# ------------------------------------------------------------------
print("\n⒞ 🚨 RSVP·리마인더 (DB가 있어야 돌아요)")


async def db_checks():
    MID = "999000000000000777"
    try:
        from utils.pokemon_store import _db
        _db["events"].delete_one({"_id": MID})
    except Exception as exc:  # noqa: BLE001
        print(f"  ⏭️ DB에 못 붙어서 건너뛰어요 ({type(exc).__name__})")
        return

    soon = datetime.now(UTC) + timedelta(minutes=20)   # 리마인더 창(30분) 안
    await event_store.create(MID, 1, 2, 111, "테스트 내전", soon, 3)

    doc = await event_store.get(MID)
    check("주최자는 자동으로 참가된다", doc["going"] == ["111"], f"{doc['going']}")

    doc = await event_store.rsvp(MID, 222, going=True)
    check("참가가 들어간다", "222" in doc["going"], f"{doc['going']}")

    doc = await event_store.rsvp(MID, 222, going=False)
    check("🚨 불참으로 바꾸면 참가에서 빠진다",
          "222" in doc["declined"] and "222" not in doc["going"],
          f"going={doc['going']} declined={doc['declined']}")

    doc = await event_store.rsvp(MID, 222, going=False)
    check("같은 걸 또 누르면 취소된다", "222" not in doc["declined"], f"{doc['declined']}")

    # 정원 3명 — 주최자 포함해서 채워요.
    await event_store.rsvp(MID, 222, going=True)
    await event_store.rsvp(MID, 333, going=True)
    doc = await event_store.rsvp(MID, 444, going=True)
    check("🚨 정원을 넘겨 받지 않는다", len(doc["going"]) == 3, f"{doc['going']}")
    check("정원 초과자는 안 들어간다", "444" not in doc["going"], f"{doc['going']}")

    # 리마인더
    due = await event_store.due()
    check("리마인더 대상에 잡힌다", any(d["_id"] == MID for d in due), f"{len(due)}건")

    await event_store.mark_reminded(MID)
    due2 = await event_store.due()
    check("🚨 한 번 알린 일정은 다시 안 잡힌다",
          not any(d["_id"] == MID for d in due2), f"{len(due2)}건")

    # 취소는 주최자만
    nope = await event_store.cancel(MID, 999)
    check("주최자가 아니면 취소 못 한다", nope is None)
    doc = await event_store.cancel(MID, 111)
    check("주최자는 취소할 수 있다", doc is not None and doc.get("canceledAt") is not None)

    doc = await event_store.rsvp(MID, 555, going=True)
    check("취소된 일정엔 참가할 수 없다", doc is None)

    # 🧹 테스트 기록 정리
    _db["events"].delete_one({"_id": MID})
    check("테스트 기록을 정리했다", _db["events"].find_one({"_id": MID}) is None)


asyncio.run(db_checks())


# ------------------------------------------------------------------
print("\n⒟ 파서와 이어진다")
try:
    when = when_parser.parse("토요일 21시")
    check("일정 시각이 미래다", when > datetime.now(when_parser.KST),
          when_parser.format_kst(when))
except when_parser.ParseError as exc:
    check("파싱된다", False, str(exc))


# ------------------------------------------------------------------
# 🚨 이 아래 섹션을 **요약 블록 뒤에 붙이지 마세요.** 2026-10-19에 그렇게 붙여서
#    FAIL이 찍혀도 종료코드가 0으로 나왔고, 배포 관문이 그냥 통과했어요.
# ------------------------------------------------------------------
print("\n⒠ ⭐ 모집글 줍기 — 📅 를 달 글과 달면 안 되는 글 (실제 채널 로그로 만든 표)")

# '지금'을 고정해요. 안 그러면 "토요일 21시"가 요일에 따라 다르게 나와서
# 🚨 **하루는 통과하고 하루는 깨지는 테스트**가 돼요.
NOW = datetime(2026, 10, 23, 16, 0, tzinfo=when_parser.KST)  # 금요일 오후 4시

PICKUP_CASES = [
    # (모집글, 줍나, 왜)
    ("토요일 21시 내전 하실분", True, "전형적인 예약 모집"),
    ("@everyone 내일 9시 롤 내전 ㄱ?", True,
     "🚨 @everyone을 걸러내면 안 된다 — 여기선 가장 강한 모집 신호다"),
    ("10/25 21:00 내전 모집합니다", True, "날짜까지 적은 글"),
    ("<@&1234567890> 오후 10시에 폐관수련 하실분", True, "역할 멘션 + 시간"),

    # 🚨 줍지 말아야 하는 것들 — 전부 실제 로그에서 가져왔어요
    ("@everyone 지금 당장 라잇나우 롤 내전 하실분", False,
     "🚨 10-17 실제 글. '지금 당장'은 예약이 아니라 즉시 소집 — /방만들기가 할 일이다"),
    ("내일 까지 컴이 고쳐지면 할수있을것 같은데", False,
     "🚨 10-17 실제 글. '내일'은 있지만 **시각이 없다** → 일정이 될 수 없다"),
    ("까빙", False, "10-18 잡담"),
    ("ㅋㅋㅋㅋ", False, "잡담"),
    ("9시", False, f"한 마디는 모집글이 아니다 (최소 {events.MIN_PICKUP_LEN}자)"),
    ("", False, "빈 글"),
]

for content, expected, why in PICKUP_CASES:
    got = events.parse_pickup(content, now=NOW)
    ok = (got is not None) is expected
    detail = when_parser.format_kst(got) if got else "None"
    check(f"{'줍는다' if expected else '넘긴다'}: {content[:34]!r} ({why})", ok, detail)

# 🚨 한 달 넘게 먼 건 오해예요(파서가 연말에 내년으로 넘기는 경우가 있어요).
far = events.parse_pickup("12월 3일 20시 내전", now=NOW)
check(f"🚨 {events.MAX_PICKUP_DAYS}일보다 먼 건 안 줍는다 (오해일 가능성이 크다)",
      far is None, when_parser.format_kst(far) if far else "None")

# 시간 해석이 **그대로 카드에 찍혀야** 틀린 걸 사람이 보고 취소할 수 있어요.
when = events.parse_pickup("@everyone 내일 9시 롤 내전 ㄱ?", now=NOW)
check("해석한 시각이 미래다", when is not None and when > NOW,
      when_parser.format_kst(when) if when else "None")


print("\n⒡ 제목에서 멘션을 걷어낸다")

# 🚨 멘션을 그대로 제목에 넣으면 **일정 카드가 사람을 또 호출해요.**
title = events.pickup_title("<@907262335591268363> @everyone 내일 9시 내전 ㄱ?")
check("멘션 토큰이 안 남는다", "<@" not in title, title)
check("@everyone이 안 남는다", "@everyone" not in title, title)
check("내용은 남는다", "내전" in title, title)

multi = events.pickup_title("내일 9시 내전 하실분\n맵은 어센트\n빡겜 아님")
check("여러 줄이면 첫 줄만 제목이 된다", multi == "내일 9시 내전 하실분", multi)
check(f"제목이 {events.MAX_TITLE}자를 안 넘는다",
      len(events.pickup_title("가" * 300)) <= events.MAX_TITLE)


print("\n⒢ 🚨 찜이 원자적이다 — 동시에 📅 를 눌러도 한 번만 올라간다 (DB 필요)")


async def claim_checks():
    SRC = "999000000000000888"
    try:
        from utils.pokemon_store import _db
        _db["event_claims"].delete_one({"_id": SRC})
    except Exception as exc:  # noqa: BLE001
        print(f"  ⏭️ DB에 못 붙어서 건너뛰어요 ({type(exc).__name__})")
        return

    check("처음 누른 사람은 찜한다", await event_store.claim_source(SRC) is True)
    check("🚨 두 번째는 막힌다 (같은 모집이 두 번 올라가지 않는다)",
          await event_store.claim_source(SRC) is False)

    await event_store.release_source(SRC)
    check("찜을 풀면 다시 누를 수 있다", await event_store.claim_source(SRC) is True)

    await event_store.release_source(SRC)
    results = await asyncio.gather(*(event_store.claim_source(SRC) for _ in range(5)))
    check("🚨 다섯 명이 동시에 눌러도 한 명만 이긴다",
          results.count(True) == 1, f"{results}")

    from utils.pokemon_store import _db as db2
    db2["event_claims"].delete_one({"_id": SRC})
    check("테스트 기록을 정리했다",
          db2["event_claims"].find_one({"_id": SRC}) is None)


asyncio.run(claim_checks())


print("\n⒣ 모집글 줍기가 배선돼 있다")

check("on_message 리스너가 있다", hasattr(events.Events, "on_message"))
check("🚨 raw 리액션을 쓴다 (조금 전 글이 아니어도 📅 를 달 수 있어야 한다)",
      hasattr(events.Events, "on_raw_reaction_add"))
check("📅 이모지가 리액션으로 쓸 수 있는 글자다",
      events.PICKUP_EMOJI == "\U0001F4C5", events.PICKUP_EMOJI)


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
