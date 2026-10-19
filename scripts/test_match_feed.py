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
import time
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
#
# 🚨 `game_start`는 **상대 시각**이어야 해요. 전엔 `1791035008`(2026-10-03)로 박혀
#    있었는데, 2026-10-19에 `FEED_MAX_AGE_HOURS` 가드가 들어오자 **모든 픽스처가
#    "너무 오래된 경기"가 됐어요.** 고정 타임스탬프 + 시간 가드는 날짜가 지나면
#    저절로 터지는 조합이에요. 그래서 "지금으로부터 N시간 전"으로 만들어요.
def make_match(mid: str, won=True, mode="competitive", map_name="Ascent",
               age_hours: float = 0.5):
    return {
        "metadata": {"matchid": mid, "map": map_name, "mode": mode,
                     "game_start": time.time() - age_hours * 3600},
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

    # ── ⒤ 🚨 자정 유실 방지 — 날짜가 아니라 '경과 시간'으로 본다 ──────
    #
    # 2026-10-19 신고("패배만 올라온다")의 원인 둘 중 하나예요. 전엔 미션용
    # "오늘(KST)" 필터가 알림 범위까지 정해서, 23:30~24:00 경기는 다음 실행(30분 뒤)
    # 때 이미 '오늘'이 아니라 **영구히 사라졌어요.** 실측으로 `피카츄#PXG1` 님의
    # 23:28·23:55 승리 2건이 그렇게 날아갔어요.
    print("\n⒤ 🚨 자정을 넘긴 경기도 올라간다 (경과 시간 기준)")
    match_feed.notify_prefs = types.SimpleNamespace(is_enabled=enabled)  # type: ignore
    match_feed.get_allowed_channel_id = lambda *a, **k: 999  # type: ignore

    store3 = FakeStore()
    store3.db[str(USER)] = ["baseline"]       # 기준선은 이미 있음
    match_feed.match_feed_store = store3      # type: ignore[assignment]
    ch = FakeChannel()
    # ⭐ 어제 23:40에 한 경기를 오늘 00:10에 처리하는 상황 = 30분 전 경기예요.
    #    날짜로 걸렀다면 0건이 나와요.
    n = await match_feed.post_new_matches(
        FakeBot(ch), USER, RIOT, [make_match("midnight", age_hours=0.5)], stats_of)
    check("⭐ 30분 전 경기는 올린다 (날짜가 바뀌었어도)", n == 1, f"{n}건")

    # 그래도 **옛 경기 부활**은 막아야 해요 (seen 기록이 몇 건뿐인 기존 유저 보호)
    ch = FakeChannel()
    too_old = match_feed.FEED_MAX_AGE_HOURS + 1
    n = await match_feed.post_new_matches(
        FakeBot(ch), USER, RIOT, [make_match("ancient", age_hours=too_old)], stats_of)
    check(f"{match_feed.FEED_MAX_AGE_HOURS}시간보다 오래된 경기는 안 올린다",
          n == 0 and not ch.sent, f"{n}건 ({too_old:g}시간 전)")

    # ⚠️ 시각을 모르면 막지 않아요 (영원히 재시도되는 걸 피해요)
    ch = FakeChannel()
    no_ts = make_match("nots")
    no_ts["metadata"].pop("game_start")
    n = await match_feed.post_new_matches(FakeBot(ch), USER, RIOT, [no_ts], stats_of)
    check("game_start가 없으면 막지 않는다", n == 1, f"{n}건")


asyncio.run(main())


# ==================================================================
# ⒥ 🚨 알림이 미션에 종속되지 않는다 (2026-10-19)
# ------------------------------------------------------------------
# "패배만 올라온다"의 **주원인**이에요. `cogs/mission.py`가 그날 발로 미션을 다 깨면
# `_check_valorant`를 안 불렀고, 알림이 그 안에 있어서 같이 멈췄어요. `val_win`이
# 배정돼 있으면 **이기는 순간** 미션이 끝나니 그 뒤 경기(대개 승리)가 안 올라갔어요.
#
# ⭐ 그래서 검사는 "**남은 미션이 0일 때도 알림이 불리는가**"예요.
print("\n⒥ 🚨 미션을 다 깬 사람도 알림은 올라간다")

from cogs import mission as mission_cog  # noqa: E402

_posted: list[str] = []


async def _fake_post(bot, user_id, riot_id, matches, stats_of):
    _posted.append(riot_id)
    _got_matches.clear()
    _got_matches.extend(matches)
    return len(matches)


_completed: list[str] = []
_got_matches: list[dict] = []


async def _one(pending_keys, match=None):
    """`_check_valorant`를 실제로 돌려요. 남은 미션만 바꿔 끼워요.

    🚨 **`_fetch_recent_matches`는 가짜로 바꾸지 않아요.** 처음엔 그걸 통째로
    스텁했는데, 그러면 **자정 유실의 진짜 원인**(그 함수 안의 날짜 필터)을 되살려도
    테스트가 통과해버렸어요 — 일부러 깨 보고 알았어요. 그래서 **API 응답만** 가짜로
    주고 함수 본문은 실제로 돌려요."""
    _posted.clear()
    _completed.clear()
    # ⚠️ 이것도 비워야 해요. 알림이 아예 안 불린 경우에 **이전 실행의 잔값**이 남아서
    #    실패 메시지가 엉뚱한 경기를 가리켰어요(일부러 깨 보다가 발견).
    _got_matches.clear()
    cog = mission_cog.Mission.__new__(mission_cog.Mission)   # __init__ 건너뜀
    cog.bot = None
    cog._account_missing = {}
    payload = {"data": [match or make_match("m-feed", age_hours=0.2)]}

    async def fake_request(_session, _path, **_kw):
        return 200, payload

    async def complete(_uid, key, _channel):
        _completed.append(key)

    os.environ.setdefault("HENRIKDEV_API_KEY", "test-key")
    mission_cog.henrik_api = types.SimpleNamespace(request=fake_request)  # type: ignore
    # aiohttp 세션은 쓰지 않아요 (요청 자체를 가로챘으니까요).
    cog._get_session = lambda: asyncio.sleep(0, result=None)  # type: ignore[assignment]
    # ⚠️ 미션 완료는 DB를 건드려요. 여기선 알림 도달만 볼 거라 가짜로 막아요.
    cog._complete = complete                                 # type: ignore[assignment]
    mission_cog.riot_account_store = types.SimpleNamespace(   # type: ignore
        get_account=lambda _uid: ("피카츄", "PXG1"))
    mission_cog.match_feed = types.SimpleNamespace(post_new_matches=_fake_post)  # type: ignore
    mission_cog._extract_player_match_stats = lambda *_a: make_stat()  # type: ignore
    return await cog._check_valorant(USER, pending_keys, None)


asyncio.run(_one([]))
check("⭐ 남은 미션이 0이어도 알림이 올라간다", _posted == [RIOT], f"호출 {_posted}")

asyncio.run(_one(["val_win"]))
check("남은 미션이 있을 때도 당연히 올라간다", _posted == [RIOT], f"호출 {_posted}")
# ⭐ 미션 판정이 죽지 않았는지도 같이 봐요 — 알림을 떼어내다 미션을 끊으면 코인이 안 나가요.
check("⭐ 미션 판정도 그대로 돈다 (승리 미션이 깨진다)", _completed == ["val_win"],
      f"완료 {_completed}")

# 🚨 소스에서도 못 박아요. 동작 테스트만으로는 `_auto_check_one` 쪽에 조기 반환이
#    되살아나도 통과해버려요(알림은 `_check_valorant` 안에 있으니까요).
import ast as _ast  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_src = _Path(os.path.join(BOT_DIR, "cogs/mission.py")).read_text(encoding="utf-8")
_fn = next(n for n in _ast.walk(_ast.parse(_src))
           if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_auto_check_one")
# `pending`을 보고 바로 return 하는 if 문이 있으면 알림이 다시 막혀요.
_guards = [
    n for n in _ast.walk(_fn)
    if isinstance(n, _ast.If)
    and any(isinstance(x, _ast.Name) and x.id == "pending" for x in _ast.walk(n.test))
    and any(isinstance(x, _ast.Return) for x in _ast.walk(n))
]
check("🚨 pending이 비면 바로 돌아가는 조기 반환이 없다", not _guards,
      f"{len(_guards)}곳 — 알림이 다시 미션에 묶였어요" if _guards
      else "알림까지 항상 도달해요")

# ── ⒦ 🚨 미션 쪽이 알림에 넘기는 목록을 날짜로 걸러선 안 된다 ──────────
#
# ⒤가 `post_new_matches`를 직접 불러서 보는 거라, **그 앞단**(mission.py)에
# `_is_today_kst` 필터가 되살아나도 ⒤는 통과해버려요. 자정 유실의 진짜 원인이
# 거기였으니 여기서 따로 못 박아요.
print("\n⒦ 🚨 어제 경기도 알림까지 전달된다 (미션 쪽 날짜 필터 금지)")

from datetime import datetime, timedelta, timezone  # noqa: E402

_KST = timezone(timedelta(hours=9))
_yesterday = (datetime.now(_KST) - timedelta(days=1)).replace(hour=23, minute=40)
_late = make_match("late-night")
_late["metadata"]["game_start"] = _yesterday.timestamp()

asyncio.run(_one([], match=_late))
check("⭐ 어제 23:40 경기가 알림까지 도달한다",
      [((m.get('metadata') or {}).get('matchid')) for m in _got_matches] == ["late-night"],
      f"전달된 경기 {[(m.get('metadata') or {}).get('matchid') for m in _got_matches]}")

# ⚠️ 반대로 **미션**은 오늘 것만 봐야 해요 (일일 미션이 어제 경기로 깨지면 안 돼요)
asyncio.run(_one(["val_win"], match=_late))
check("🚨 그래도 미션은 어제 경기로 안 깨진다", _completed == [],
      f"완료 {_completed} — 일일 미션이 어제 전적으로 깨졌어요")

print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
