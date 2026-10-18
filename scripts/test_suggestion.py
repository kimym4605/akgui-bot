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


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
