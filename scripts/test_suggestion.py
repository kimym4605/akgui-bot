"""💡 건의함 검증. 디스코드 없이 돌아요(DB는 있으면 쓰고, 없으면 그 부분만 건너뛰어요).

    python scripts/test_suggestion.py

## 무엇을 막으려고 만들었나

1. 🚨 **영속 뷰가 상태를 들고 있는 것.** 봇 전체에 객체가 하나뿐이라, `self`에 담으면
   **모든 건의가 같은 상태를 공유**해요. `cogs/team.py`가 이걸 어겨서 "9/22 배포 이후
   내전 경기가 한 건도 기록되지 못한" 사고가 났어요.
2. 🚨 **같은 사람이 찬성·반대 양쪽에 들어가는 것.** 찬반 전환을 두 번의 update로
   나누면 중간에 끊겼을 때 그렇게 돼요.
3. custom_id가 고정이어야 재시작 뒤에도 버튼이 살아나요.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

# ⚠️ 실제 DB에 붙어서 찬반 전환까지 봐요. **테스트가 남긴 문서는 끝에서 지워요.**
#    (붙지 못하면 그 구간만 건너뛰고 나머지 검사는 그대로 돌아요)
load_dotenv(os.path.join(BOT_DIR, ".env"))

from cogs import suggestion  # noqa: E402
from utils import suggestion_store as store  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
print("⒜ 🚨 영속 뷰가 상태를 들고 있지 않다")

view = suggestion.VoteView()
check("timeout=None (시간이 지나도 안 죽는다)", view.timeout is None, f"{view.timeout}")

# View 인스턴스의 고유 속성 중 '건의별 상태'로 보일 만한 게 있으면 안 돼요.
#
# ⚠️ `up`/`down`은 `@discord.ui.button` 데코레이터가 붙여준 **버튼 객체**고, `id`는
#    discord.py 내부 값이에요. 건의 상태가 아니니 빼고 봐요(이걸 안 빼면 거짓 경보예요).
#    그래서 "discord UI 아이템이 아니고 내부 값도 아닌 것"만 남겨서 봐요.
import discord  # noqa: E402

DISCORD_INTERNAL = {"id", "children", "timeout"}
own = {
    k: v for k, v in vars(view).items()
    if not k.startswith("_")
    and k not in DISCORD_INTERNAL
    and not isinstance(v, discord.ui.Item)
}
check("인스턴스 속성에 건의 상태가 없다", not own, f"{set(own) or '없음'}")
check("버튼 2개가 UI 아이템으로만 붙어 있다",
      sum(isinstance(v, discord.ui.Item) for v in vars(view).values()) == 2,
      f"{[k for k, v in vars(view).items() if isinstance(v, discord.ui.Item)]}")

ids = sorted(
    item.custom_id for item in view.children if getattr(item, "custom_id", None)
)
check("버튼 custom_id가 고정되어 있다", len(ids) == 2, f"{ids}")
check("custom_id가 서로 다르다", len(set(ids)) == len(ids), f"{ids}")
check("custom_id에 메시지/유저 id가 안 박혀 있다 (모든 건의가 공유하는 버튼)",
      all(not any(c.isdigit() for c in cid) for cid in ids), f"{ids}")


# ------------------------------------------------------------------
print("\n⒝ 상태 표시")
for status in (store.OPEN, store.ACCEPTED, store.DONE, store.DECLINED):
    check(f"{status} 라벨이 있다", status in store.STATUS_LABEL)
    check(f"{status} 색이 있다", status in store.STATUS_COLOR)

doc = {"text": "낚시 대회 열어주세요", "up": ["1", "2", "3"], "down": ["4"],
       "status": store.ACCEPTED, "userId": "1"}
embed = suggestion.build_embed(doc, "피카츄")
check("임베드에 건의 내용", "낚시 대회" in (embed.description or ""), embed.description)
check("투표 수가 보인다",
      any("3" in (f.value or "") and "1" in (f.value or "") for f in embed.fields))
check("제안자가 보인다", "피카츄" in (embed.footer.text or ""), embed.footer.text)

doc_note = dict(doc, note="다음 주에 넣을게요")
embed2 = suggestion.build_embed(doc_note, "피카츄")
check("운영자 메모가 보인다",
      any("메모" in (f.name or "") for f in embed2.fields))


# ------------------------------------------------------------------
print("\n⒞ 🚨 찬반은 배타적 (DB가 있어야 돌아요)")


async def db_checks():
    MID = "999000000000000001"
    try:
        from utils.pokemon_store import _db
        _db["suggestions"].delete_one({"_id": MID})
    except Exception as exc:  # noqa: BLE001
        print(f"  ⏭️ DB에 못 붙어서 건너뛰어요 ({type(exc).__name__})")
        return

    await store.create(MID, 111, "테스트 건의")

    doc = await store.vote(MID, 222, up=True)
    check("찬성이 들어간다", doc["up"] == ["222"] and not doc["down"], f"{doc['up']}/{doc['down']}")

    doc = await store.vote(MID, 222, up=False)
    check("🚨 반대로 바꾸면 찬성에서 빠진다",
          doc["down"] == ["222"] and doc["up"] == [], f"{doc['up']}/{doc['down']}")

    doc = await store.vote(MID, 222, up=False)
    check("같은 걸 또 누르면 취소된다", not doc["up"] and not doc["down"],
          f"{doc['up']}/{doc['down']}")

    await store.vote(MID, 333, up=True)
    doc = await store.vote(MID, 444, up=True)
    check("여러 명이 찬성할 수 있다", set(doc["up"]) == {"333", "444"}, f"{doc['up']}")

    doc = await store.set_status(MID, store.DONE, "반영했어요")
    check("상태가 바뀐다", doc["status"] == store.DONE, doc["status"])
    check("메모가 붙는다", doc["note"] == "반영했어요", f"{doc['note']}")

    rows = await store.recent(5)
    check("목록에 나온다", any(r["_id"] == MID for r in rows), f"{len(rows)}건")

    # 🧹 테스트 기록은 지워요 (운영 DB를 더럽히지 않게)
    from utils.pokemon_store import _db as db2
    db2["suggestions"].delete_one({"_id": MID})
    left = db2["suggestions"].find_one({"_id": MID})
    check("테스트 기록을 정리했다", left is None)


asyncio.run(db_checks())


# ------------------------------------------------------------------
# 🚨 이 아래 섹션을 **요약 블록 뒤에 붙이지 마세요.** 2026-10-19에 그렇게 붙여서
#    FAIL이 찍혀도 종료코드가 0으로 나왔고, 배포 관문이 그냥 통과했어요.
# ------------------------------------------------------------------
print("\n⒟ ⭐ 평문 줍기 판정 — 실제 채널 로그로 만든 표")


class _FakeAuthor:
    def __init__(self, bot=False):
        self.bot = bot
        self.display_name = "테스터"
        self.id = 111


class _FakeMessage:
    """`_looks_like_suggestion`이 보는 것만 들고 있어요."""

    def __init__(self, content, *, bot=False, everyone=False, guild=True):
        self.content = content
        self.author = _FakeAuthor(bot)
        self.mention_everyone = everyone
        self.guild = object() if guild else None


# ⭐ 이 표는 `💡｜기능-추천방` 채널을 실제로 읽어서 뽑았어요(2026-08~10).
#    기대값을 바꾸고 싶으면 **먼저 채널을 다시 읽어보세요.**
PICKUP_CASES = [
    # (글, 주워야 하나, 왜)
    ("기술머신 상점에 추가해주세요", True, "08-04 실제 건의"),
    ("이거 미션 같은거 추가 언제 돼?", True, "08-07 실제 건의"),
    ("미션 내용 추천점", True, "08-08 실제 건의 — 문턱(8자)을 정한 기준"),
    ("랭크방 입장권 입장하고 다시 나가도 안 사라지고 계속 유지된다는 말인거 같아",
     True, "08-08 실제 버그 신고"),
    ("노래 듣다보면 갑자기 막 버벅 거리고 혼자서 나가고 그래여", True, "08-31 실제 버그 신고"),
    ("이거 기준으로 롤체봇 같은거도 만들어줘", True, "08-24 실제 건의"),
    # 주우면 안 되는 것
    ("확인", False, "08-08 잡담"),
    ("ㅇㅋ", False, "잡담"),
    ("흠 ㅇㅋ", False, "08-08 잡담"),
    ("야하", False, "10-16 잡담"),
    ("ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ", False, "🚨 길이만 보면 통과해버리는 글"),
    ("ㅠㅠㅠㅠㅠㅠㅠㅠㅠㅠ", False, "🚨 같은 함정"),
    ("?????????", False, "기호만"),
    ("", False, "빈 글"),
]

for text, expected, why in PICKUP_CASES:
    got = suggestion._looks_like_suggestion(_FakeMessage(text))
    check(f"{'줍는다' if expected else '넘긴다'}: {text[:28]!r} ({why})",
          got is expected, f"got={got}")

check("🚨 봇이 쓴 글은 안 줍는다",
      suggestion._looks_like_suggestion(
          _FakeMessage("기술머신 상점에 추가해주세요", bot=True)) is False)
check("🚨 @everyone 공지는 안 줍는다 (운영진 공지지 건의가 아니다)",
      suggestion._looks_like_suggestion(
          _FakeMessage("봇에서 원하는 기능들을 알려주면 구현해줘용", everyone=True)) is False)
check("DM은 안 줍는다",
      suggestion._looks_like_suggestion(
          _FakeMessage("기술머신 상점에 추가해주세요", guild=False)) is False)
check(f"{suggestion.MAX_LEN}자를 넘으면 안 줍는다",
      suggestion._looks_like_suggestion(
          _FakeMessage("가" * (suggestion.MAX_LEN + 1))) is False)


# ------------------------------------------------------------------
print("\n⒠ 🚨 찜이 원자적이다 — 동시에 💡 를 눌러도 한 번만 올라간다 (DB 필요)")


async def claim_checks():
    SRC = "999000000000000777"
    try:
        from utils.pokemon_store import _db
        _db["suggestion_claims"].delete_one({"_id": SRC})
    except Exception as exc:  # noqa: BLE001
        print(f"  ⏭️ DB에 못 붙어서 건너뛰어요 ({type(exc).__name__})")
        return

    check("처음 누른 사람은 찜한다", await store.claim_source(SRC) is True)
    check("🚨 두 번째는 막힌다 (같은 글이 두 번 올라가지 않는다)",
          await store.claim_source(SRC) is False)

    # 메시지 전송이 실패했을 때 — 안 풀어주면 그 글은 **영영** 못 올려요.
    await store.release_source(SRC)
    check("찜을 풀면 다시 누를 수 있다", await store.claim_source(SRC) is True)

    # 동시에 여러 번 눌린 상황을 그대로 재현해요(한 명만 이겨야 해요).
    await store.release_source(SRC)
    results = await asyncio.gather(*(store.claim_source(SRC) for _ in range(5)))
    check("🚨 다섯 명이 동시에 눌러도 한 명만 이긴다",
          results.count(True) == 1, f"{results}")

    from utils.pokemon_store import _db as db2
    db2["suggestion_claims"].delete_one({"_id": SRC})
    check("테스트 기록을 정리했다",
          db2["suggestion_claims"].find_one({"_id": SRC}) is None)


asyncio.run(claim_checks())


# ------------------------------------------------------------------
print("\n⒡ 평문 줍기가 배선돼 있다")

check("on_message 리스너가 있다", hasattr(suggestion.Suggestion, "on_message"))
check("🚨 raw 리액션을 쓴다 (며칠 전 글에도 💡 를 달 수 있어야 한다)",
      hasattr(suggestion.Suggestion, "on_raw_reaction_add"))
check("우클릭 메뉴 콜백이 있다", hasattr(suggestion.Suggestion, "pickup_context"))
check("💡 이모지가 리액션으로 쓸 수 있는 글자다",
      suggestion.PICKUP_EMOJI == "\U0001F4A1", suggestion.PICKUP_EMOJI)
check("sourceId를 넘기는 경로가 있다 (평문 줍기 건수를 셀 수 있어야 한다)",
      "source_id" in store.create.__code__.co_varnames)


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
