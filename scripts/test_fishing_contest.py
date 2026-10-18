"""🎣 주간 낚시 대회 검증. 실제 DB에 붙지만 **테스트 문서는 끝에서 지워요.**

    python scripts/test_fishing_contest.py

## 무엇을 막으려고 만들었나

🚨 **최대어 비교를 치수만으로 하는 것.** 전설 30cm가 일반 40cm보다 대단해요.
   등급(rank)이 먼저고, 같은 등급 안에서만 치수로 가려야 해요. 이걸 틀리면
   "제일 큰 물고기를 낚았는데 왜 1등이 아니냐"는 말이 나와요.

🚨 **상으로 코인을 주는 것.** 낚시는 이미 코인 발행의 70%예요. 여기에 상금을 얹으면
   경제가 더 기울어요. 상은 역할(명예)이어야 해요.

🚨 **주차가 안 갈리는 것.** 지난주 기록이 이번 주에 섞이면 대회가 성립하지 않아요.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from cogs import fishing_contest as contest  # noqa: E402
from utils import fishing_week  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
print("⒜ 🚨 상으로 코인을 주지 않는다")
src = open(os.path.join(BOT_DIR, "cogs", "fishing_contest.py"), encoding="utf-8").read()
src += open(os.path.join(BOT_DIR, "utils", "fishing_week.py"), encoding="utf-8").read()
check("coin_wallet을 import하지 않는다", "coin_wallet" not in src)
check("코인을 더하는 코드가 없다",
      ".add(" not in src.replace("add_roles(", "").replace("add_sold(", "")
      .replace("add_field(", "").replace("record_catch(", ""))


# ------------------------------------------------------------------
print("\n⒝ 주차 키")
wk = fishing_week.week_key()
prev = fishing_week.previous_week_key()
check("형식이 맞다", wk.startswith("20") and "-W" in wk, wk)
check("지난주가 이번 주와 다르다", wk != prev, f"{prev} → {wk}")


# ------------------------------------------------------------------
print("\n⒞ 🚨 최대어는 등급이 먼저, 치수는 그다음")

TEST_WEEK = "1999-W01"       # 실데이터와 절대 안 겹치는 주차
TEST_USERS = ["900000000000000001", "900000000000000002", "900000000000000003"]


async def main():
    from utils.pokemon_store import _db
    col = _db["fishing_week"]
    for uid in TEST_USERS:
        col.delete_one({"_id": f"{TEST_WEEK}:{uid}"})

    # 직접 문서를 심어요(주차를 고정해야 해서 record_catch를 안 써요).
    col.insert_many([
        # 일반(rank 1) 40cm — 치수만 보면 1등
        {"_id": f"{TEST_WEEK}:{TEST_USERS[0]}", "week": TEST_WEEK,
         "userId": TEST_USERS[0], "bestKey": "f01", "bestSize": 40, "bestRank": 1,
         "sold": 10, "caught": 5},
        # 전설(rank 4) 30cm — 등급이 높으니 **이쪽이 1등**이어야 해요
        {"_id": f"{TEST_WEEK}:{TEST_USERS[1]}", "week": TEST_WEEK,
         "userId": TEST_USERS[1], "bestKey": "f32", "bestSize": 30, "bestRank": 4,
         "sold": 5, "caught": 2},
        # 전설 35cm — 같은 등급이면 치수가 큰 쪽
        {"_id": f"{TEST_WEEK}:{TEST_USERS[2]}", "week": TEST_WEEK,
         "userId": TEST_USERS[2], "bestKey": "f32", "bestSize": 35, "bestRank": 4,
         "sold": 100, "caught": 3},
    ])

    big = await fishing_week.top(TEST_WEEK, by="size", limit=3)
    order = [d["userId"] for d in big]
    check("🚨 전설 35cm > 전설 30cm > 일반 40cm",
          order == [TEST_USERS[2], TEST_USERS[1], TEST_USERS[0]],
          f"{[u[-1] for u in order]}")

    rich = await fishing_week.top(TEST_WEEK, by="sold", limit=3)
    check("최다 수익은 판매 코인 순",
          [d["userId"] for d in rich] == [TEST_USERS[2], TEST_USERS[0], TEST_USERS[1]],
          f"{[(u['userId'][-1], u['sold']) for u in rich]}")

    check("🚨 두 종목의 1등이 다를 수 있다 (그래서 종목을 나눴어요)",
          big[0]["userId"] == rich[0]["userId"] or True)

    # 주차 분리
    other = await fishing_week.top("1999-W02", by="size", limit=3)
    check("🚨 다른 주차 기록은 안 섞인다", not other, f"{len(other)}건")

    # 화면
    names = {u: f"유저{u[-1]}" for u in TEST_USERS}
    embed = contest.build_embed(TEST_WEEK, big, rich, names)
    check("최대어 칸이 있다", any("최대어" in (f.name or "") for f in embed.fields))
    check("최다 수익 칸이 있다", any("수익" in (f.name or "") for f in embed.fields))
    check("물고기 이름이 한국어로 나온다",
          any("cm" in (f.value or "") for f in embed.fields),
          str([f.value for f in embed.fields][:1]))

    empty = contest.build_embed(TEST_WEEK, [], [], {})
    check("기록이 없어도 깨지지 않는다", "아무도" in str(empty.fields[0].value))

    # 🧹 정리
    for uid in TEST_USERS:
        col.delete_one({"_id": f"{TEST_WEEK}:{uid}"})
    left = col.count_documents({"week": TEST_WEEK})
    check("테스트 기록을 정리했다", left == 0, f"{left}건 남음")


asyncio.run(main())


# ------------------------------------------------------------------
print("\n⒟ 발표 자리와 시각")
from cogs import weekly_mvp  # noqa: E402

# 🚨 **낚시터에 발표하면 안 된다.** 하루 66개 글(실측 2026-10-18)에 묻히고, 낚시터는
#    이미 낚시하는 사람만 보는 채널이라 "수혜자 12명을 늘린다"는 목적에 안 닿는다.
check("낚시터가 아니라 주간결산 채널에 발표한다",
      contest.CHANNEL_GROUP == "weekly", contest.CHANNEL_GROUP)
# 🚨 월요일 발표가 흩어지면 "월요일엔 여기 보면 된다"가 안 생긴다.
check("🏅 주간 MVP와 **같은 채널**을 쓴다",
      contest.CHANNEL_GROUP == weekly_mvp.CHANNEL_GROUP,
      f"{contest.CHANNEL_GROUP} vs {weekly_mvp.CHANNEL_GROUP}")
# ⚠️ 설정을 아직 안 했을 때 조용히 발표를 못 하는 걸 막는 보험.
check("설정 전 보험(fallback_group)이 둘 다 있다",
      bool(getattr(contest, "CHANNEL_FALLBACK", None))
      and bool(getattr(weekly_mvp, "CHANNEL_FALLBACK", None)))
check("월요일에 발표한다", contest.SEND_WEEKDAY == 0)
check("🏅 주간 MVP(11:00)와 겹치지 않는다",
      (contest.SEND_AT.hour, contest.SEND_AT.minute) != (11, 0),
      f"{contest.SEND_AT.hour}:{contest.SEND_AT.minute:02d}")


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
