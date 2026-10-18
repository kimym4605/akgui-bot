"""🔔 경기 결과 자동 알림 검증. 실제 DB·디스코드 없이 돌아요.

    python scripts/test_match_feed.py

## 무엇을 막으려고 만들었나

1. 🚨 **같은 경기를 반복해서 올리는 것.** 미션 루프는 30분마다 **오늘 경기 전체**를
   다시 가져와요. 그대로 올리면 한 경기가 하루에 수십 번 올라가요.
2. 🚨 **켜는 순간 폭탄.** 등록된 사람이 21명이고 각자 오늘 10경기까지 있을 수 있어요.
   첫 조회에서 다 올리면 200개가 한꺼번에 쏟아져요. 처음 보는 사람은 기준선만 잡아야 해요.
3. 🚨 **전송 실패를 '올린 것'으로 기록하는 것.** 그러면 그 경기는 영영 안 올라가요.
4. 채널 미설정·알림 끔 같은 **조용한 기본값**이 실제로 지켜지는지.
"""
import asyncio
import os
import sys
import types

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("MONGODB_DB_NAME", "agwi_feed_test")

from utils import match_feed  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ── 가짜 디스코드 ────────────────────────────────────────────────────
class FakeChannel:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.guild = None

    async def send(self, **kw):
        if self.fail:
            import discord
            # ⚠️ discord.HTTPException은 response에서 `.status`와 `.reason`을 둘 다 읽어요.
            raise discord.HTTPException(
                types.SimpleNamespace(status=500, reason="Internal Server Error"), "boom"
            )
        self.sent.append(kw.get("embed"))


class FakeBot:
    def __init__(self, channel):
        self._channel = channel

    def get_channel(self, _id):
        return self._channel


# ── 가짜 경기 데이터 (HenrikDev v3 모양) ─────────────────────────────
def make_match(mid: str, won=True, mode="competitive", map_name="Ascent"):
    return {
        "metadata": {"matchid": mid, "map": map_name, "mode": mode,
                     "game_start": 1791035008},
        "teams": {
            "red": {"has_won": won, "rounds_won": 13 if won else 9,
                    "rounds_lost": 9 if won else 13},
            "blue": {"has_won": not won, "rounds_won": 9 if won else 13,
                     "rounds_lost": 13 if won else 9},
        },
    }


def make_stat(won=True, kills=20, deaths=14):
    return {
        "kills": kills, "deaths": deaths, "assists": 5,
        "headshots": 30, "bodyshots": 60, "legshots": 10,
        "damage_made": 3400, "score": 6200, "total_rounds": 22,
        "won": won, "agent": "Jett",
    }


def stats_of(_match):
    return make_stat()


# ── 상태를 메모리로 갈아끼워요 (DB 없이 돌리려고) ────────────────────
class FakeStore:
    def __init__(self):
        self.db: dict[str, list[str]] = {}
        self.marked: list[str] = []

    async def prime(self, uid, ids):
        if str(uid) in self.db:
            return False
        self.db[str(uid)] = list(ids)
        return True

    async def seen(self, uid):
        return set(self.db.get(str(uid)) or [])

    async def mark(self, uid, ids):
        self.marked += list(ids)
        self.db.setdefault(str(uid), []).extend(ids)


USER = 12345
RIOT = "피카츄#PXG1"


async def main():
    store = FakeStore()
    match_feed.match_feed_store = store  # type: ignore[assignment]

    # 알림은 기본 켜짐, 채널은 설정됨으로 가정
    async def enabled(_uid, _key):
        return True

    match_feed.notify_prefs = types.SimpleNamespace(is_enabled=enabled)  # type: ignore
    match_feed.get_allowed_channel_id = lambda *a, **k: 999  # type: ignore

    # ── ⒜ 처음 보는 사람: 기준선만 잡고 아무것도 안 올린다 ───────────
    print("⒜ 🚨 처음 보는 사람 (켜는 순간 폭탄 방지)")
    ch = FakeChannel()
    bot = FakeBot(ch)
    first = [make_match(f"m{i}") for i in range(10)]
    n = await match_feed.post_new_matches(bot, USER, RIOT, first, stats_of)
    check("첫 조회에선 한 개도 안 올린다", n == 0 and not ch.sent, f"{n}건 · 전송 {len(ch.sent)}")
    check("대신 기준선을 잡아둔다", len(store.db.get(str(USER)) or []) == 10,
          f"{len(store.db.get(str(USER)) or [])}개 기억")

    # ── ⒝ 새 경기 하나가 추가되면 그것만 ─────────────────────────────
    print("\n⒝ 새 경기만 올린다")
    ch = FakeChannel()
    bot = FakeBot(ch)
    with_new = [make_match("new1")] + first
    n = await match_feed.post_new_matches(bot, USER, RIOT, with_new, stats_of)
    check("새 경기 1건만 올린다", n == 1 and len(ch.sent) == 1, f"{n}건")

    # ── ⒞ 같은 목록을 또 받아도 안 올린다 (30분 뒤 재조회) ───────────
    print("\n⒞ 🚨 30분 뒤 같은 목록을 또 받아도 안 올린다")
    ch = FakeChannel()
    bot = FakeBot(ch)
    n = await match_feed.post_new_matches(bot, USER, RIOT, with_new, stats_of)
    check("두 번째 호출은 0건", n == 0 and not ch.sent, f"{n}건")

    # ── ⒟ 한 번에 쏟아지지 않게 상한 ────────────────────────────────
    print("\n⒠ 밀린 경기가 많아도 한 번에 쏟지 않는다")
    ch = FakeChannel()
    bot = FakeBot(ch)
    many = [make_match(f"burst{i}") for i in range(8)] + with_new
    n = await match_feed.post_new_matches(bot, USER, RIOT, many, stats_of)
    check(f"한 번에 최대 {match_feed.MAX_POST_PER_RUN}건",
          n == match_feed.MAX_POST_PER_RUN, f"{n}건")

    # ── ⒡ 전송 실패는 '올린 것'으로 기록하지 않는다 ──────────────────
    print("\n⒡ 🚨 전송 실패를 올린 것으로 치지 않는다")
    store2 = FakeStore()
    store2.db[str(USER)] = ["old"]            # 기준선은 이미 있음
    match_feed.match_feed_store = store2      # type: ignore[assignment]
    ch = FakeChannel(fail=True)
    bot = FakeBot(ch)
    n = await match_feed.post_new_matches(bot, USER, RIOT, [make_match("willfail")], stats_of)
    check("실패하면 0건으로 센다", n == 0, f"{n}건")
    check("실패한 경기는 기록에 안 남는다", "willfail" not in store2.marked,
          f"marked={store2.marked}")

    # ── ⒢ 조용한 기본값 ─────────────────────────────────────────────
    print("\n⒢ 조용한 기본값")
    match_feed.match_feed_store = FakeStore()  # type: ignore[assignment]
    match_feed.get_allowed_channel_id = lambda *a, **k: None  # type: ignore
    ch = FakeChannel()
    n = await match_feed.post_new_matches(FakeBot(ch), USER, RIOT, with_new, stats_of)
    check("채널 미설정이면 안 올린다", n == 0 and not ch.sent)

    match_feed.get_allowed_channel_id = lambda *a, **k: 999  # type: ignore

    async def disabled(_uid, _key):
        return False

    match_feed.notify_prefs = types.SimpleNamespace(is_enabled=disabled)  # type: ignore
    ch = FakeChannel()
    n = await match_feed.post_new_matches(FakeBot(ch), USER, RIOT, with_new, stats_of)
    check("알림을 끈 사람은 안 올린다", n == 0 and not ch.sent)

    # ── ⒣ 카드 내용 ─────────────────────────────────────────────────
    print("\n⒣ 카드 내용")
    embed = match_feed.build_embed("노예", RIOT, make_match("x", won=True), make_stat())
    check("승리면 제목에 승리", "승리" in embed.title, embed.title)
    check("스코어가 들어간다", "13 : 9" in embed.title, embed.title)
    check("맵이 한국어로", "어센트" in (embed.description or ""), embed.description)
    check("KDA 필드", any("KDA" in (f.name or "") for f in embed.fields))

    lose = match_feed.build_embed("노예", RIOT, make_match("y", won=False),
                                  make_stat(won=False))
    check("패배면 제목에 패배", "패배" in lose.title, lose.title)
    check("패배 스코어가 뒤집힌다", "9 : 13" in lose.title, lose.title)


asyncio.run(main())

print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
