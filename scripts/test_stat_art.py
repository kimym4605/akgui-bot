# -*- coding: utf-8 -*-
"""📊 전적·순위 카드 그림 검사 (2026-11-23). DB·디스코드 없이 돌아가요.

    python scripts/test_stat_art.py

막으려는 사고:
- 재료(요원·맵·티어 그림)가 배포에 안 실려 카드가 전부 그림 없이 나오는 것
- 새 요원·모르는 맵·이모지 닉네임에서 카드가 터지는 것
- 그림을 붙였는데 글 칸도 그대로 남아 **같은 숫자가 두 벌** 보이는 것
- 반대로 그림을 못 그렸는데 글 칸까지 지워져서 **아무것도 안 보이는 것**
- 경기 알림 카드에 일반전 티어가 찍히는 것 (일반전 티어 값은 의미가 없어요)
"""
import asyncio
import io
import os
import sys
import time
import types

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")     # 접속하지 않아요

import discord  # noqa: E402
from PIL import Image  # noqa: E402

from utils import match_feed, stat_art  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


def size_of(png):
    return Image.open(io.BytesIO(png)).size


REAL = {k: getattr(stat_art, k) for k in ("match_card", "report_card", "board_card", "mvp_card", "scrim_card")}


async def none(*a, **k):
    return None


# ==================================================================
print("[1] 재료")
idx = stat_art._index()
check("요원 25명 이상", len(idx["agents"]) >= 25, str(len(idx["agents"])))
check("5대5 맵이 전부 있다", all(stat_art.map_image(m, 10, 10) is not None
                              for m in ("Ascent", "Bind", "Haven", "Lotus", "Split", "Abyss")))
check("한글 맵 이름(내전 기록)도 찾는다", stat_art.map_image("어센트", 10, 10) is not None)
check("'KAY/O'처럼 / 가 든 요원도 찾는다", stat_art.agent_icon("KAY/O", 32) is not None)
check("티어 엠블럼 (다이아 2 = 19)", stat_art.tier_icon(19, 32) is not None)
check("언랭(0)은 엠블럼 없음", stat_art.tier_icon(0, 32) is None)
check("모르는 요원·맵은 None (터지지 않아요)",
      stat_art.agent_icon("NewAgent2099", 32) is None and stat_art.map_image("Nowhere", 10, 10) is None)
check("이모지를 걷어낸다", stat_art._clean("🔥악귀✨ **님**") == "악귀 님", stat_art._clean("🔥악귀✨ **님**"))

# ==================================================================
print("[2] 다섯 카드가 모르는 값에서도 그려진다")
m = {"name": "🔥이모지닉🔥", "agent": "NewAgent2099", "agent_ko": "새요원", "result": "무승부", "score": "?",
     "map_en": "Nowhere", "map_ko": None, "mode": "기타", "kills": 0, "deaths": 0, "assists": 0,
     "kd": 0.0, "acs": 0, "adr": 0, "hs": 0, "tier_id": None}
check("경기 카드 900×300", size_of(stat_art._match(m)) == (900, 300))
r = {"riot": "A#1", "tier_name": None, "rr": None, "tier_id": None, "score": 0, "max_score": 2000, "grade": "F",
     "grade_color": 0x7F8C8D, "kd": 0, "win_rate": 0, "wins": 0, "losses": 1, "hs": 0, "adr": 0, "acs": 0,
     "sample": "", "agents": [], "position": None, "recent": []}
check("전적 카드 (요원·최근 경기 없음)", size_of(stat_art._report(r)) == (1000, 590))
check("순위표 (빈 칸)", size_of(stat_art._board("t", "", [{"title": "x", "rows": []}], 0xFFC850, {}))[0] == 550)
check("순위표 2칸이면 넓어진다", size_of(stat_art._board("t", "", [{"title": "a", "rows": []},
                                                              {"title": "b", "rows": []}], 0, {}))[0] == 1040)
check("MVP (성적 없음)", size_of(stat_art._mvp({"name": "x", "week": "W", "score": 0}, None)) == (900, 400))
s = {"name": "x", "wins": 1, "losses": 0, "rate": 100, "best": 1, "worst": 0, "season": "S1", "s_wins": 0,
     "s_losses": 0, "streak": "-", "recent": [], "kda": "", "maps": []}
check("내전 카드 (맵 기록 없음 → 낮아요)", size_of(stat_art._scrim(s, None)) == (1000, 520))
s["maps"] = [("어센트", 1, 0)] * 3
check("내전 카드 (맵 3개 → 그만큼 길어져요)", size_of(stat_art._scrim(s, None))[1] == 520 + 60 + 3 * 46)

# ==================================================================
print("[3] 🔔 경기 알림")


def make_match(mid, won=True, mode="competitive"):
    return {"metadata": {"matchid": mid, "map": "Ascent", "mode": mode, "game_start": time.time() - 600},
            "teams": {"red": {"has_won": won, "rounds_won": 13 if won else 9, "rounds_lost": 9 if won else 13},
                      "blue": {"has_won": not won, "rounds_won": 9 if won else 13,
                               "rounds_lost": 13 if won else 9}}}


STAT = {"kills": 20, "deaths": 10, "assists": 5, "headshots": 30, "bodyshots": 60, "legshots": 10,
        "damage_made": 3300, "score": 5500, "total_rounds": 22, "won": True, "agent": "KAY/O", "tier": 19}
cd = match_feed.card_data("악귀", make_match("a"), STAT)
check("승리 · 13 : 9", cd["result"] == "승리" and cd["score"] == "13 : 9", f"{cd['result']} {cd['score']}")
check("요원 한글 이름", cd["agent_ko"] not in ("", "KAY/O"), cd["agent_ko"])
check("맵 한글 이름", cd["map_ko"] == "어센트", str(cd["map_ko"]))
check("경쟁전이면 티어 엠블럼", cd["tier_id"] == 19)
check("🚨 일반전이면 티어 엠블럼 없음", match_feed.card_data("악귀", make_match("b", mode="unrated"), STAT)["tier_id"] is None)
check("K/D·ACS·ADR 계산", abs(cd["kd"] - 2.0) < 1e-9 and round(cd["acs"]) == 250 and round(cd["adr"]) == 150)


class FakeChannel:
    def __init__(self):
        self.sent, self.guild = [], None

    async def send(self, **kw):
        self.sent.append(kw)


class FakeStore:
    def __init__(self):
        self.db = {"12": ["old"]}

    async def prime(self, uid, ids):
        return False

    async def seen(self, uid):
        return {"old"}

    async def mark(self, uid, ids):
        pass


async def _enabled(*_a):
    return True

match_feed.match_feed_store = FakeStore()
match_feed.notify_prefs = types.SimpleNamespace(is_enabled=_enabled)
match_feed.get_allowed_channel_id = lambda *a, **k: 999
bot = types.SimpleNamespace(get_channel=lambda _i: ch)

ch = FakeChannel()
asyncio.run(match_feed.post_new_matches(bot, 12, "악귀#KR1", [make_match("n1")], lambda _m: dict(STAT)))
kw = ch.sent[0]
check("그림이 붙는다", getattr(kw.get("file"), "filename", "") == match_feed.CARD_FILE)
check("글 칸(KDA·ACS·ADR)은 걷어낸다 — 그림과 두 벌 X", not kw["embed"].fields and not kw["embed"].description)
check("제목(누가 이겼나)은 남긴다 — 알림 미리보기에 보여요", "승리" in (kw["embed"].title or ""))

stat_art.match_card = none
match_feed.stat_art.match_card = none
ch = FakeChannel()
asyncio.run(match_feed.post_new_matches(bot, 12, "악귀#KR1", [make_match("n2")], lambda _m: dict(STAT)))
kw = ch.sent[0]
check("🚨 그림을 못 그리면 예전 글 임베드 그대로 (칸 3개)", "file" not in kw and len(kw["embed"].fields) == 3)
stat_art.match_card = REAL["match_card"]

# ==================================================================
print("[4] 🏆 순위표 공통")


class G:
    def get_member(self, uid):
        return types.SimpleNamespace(display_name=f"멤버{uid}") if int(uid) < 100 else None


emb = discord.Embed(title="t")
f = asyncio.run(stat_art.board_attach(emb, G(), "순위", "", [
    {"title": "x", "rows": [{"rank": 1, "uid": 7, "value": "10"}, {"rank": 2, "uid": 555, "value": "5"}]}], 0))
check("그림 파일 + 임베드가 그 그림을 가리킨다", f is not None and emb.image.url == "attachment://ranking.png")
emb = discord.Embed(title="t")
sec = [{"title": "x", "rows": [{"rank": 1, "uid": 555, "value": "5"}]}]
asyncio.run(stat_art.board_attach(emb, G(), "순위", "", sec, 0))
check("서버에 없는 사람은 '탈퇴한 사람'", sec[0]["rows"][0]["name"] == "탈퇴한 사람")
stat_art.board_card = none
emb = discord.Embed(title="t")
check("🚨 못 그리면 None + 임베드는 그대로", asyncio.run(stat_art.board_attach(emb, G(), "a", "", sec, 0)) is None
      and emb.image.url is None)
stat_art.board_card = REAL["board_card"]

# ==================================================================
print("[5] 🏅 주간 MVP · ⚔️ 내전")
from cogs import weekly_mvp  # noqa: E402
md = weekly_mvp.mvp_card_data({"score": 1840, "grade": "악귀", "stats": {"kd": 1.4, "winRate": 60, "hs": 22,
                                                                        "matches": 9}}, "W47", "피츄", 9)
check("MVP 카드 값이 글 임베드와 같다", (md["kd"], md["win_rate"], md["hs"], md["matches"]) == (1.4, 60, 22, 9))

from cogs import achievement  # noqa: E402


async def _rec(uid, *a, **k):
    return {"wins": 5, "losses": 3, "bestStreak": 3, "worstStreak": -2, "streak": 2}


async def _recent(uid, limit=5):
    return [{"winners": [str(uid)], "map": "어센트"}, {"winners": [], "map": None}]


async def _kda(uid, *a):
    return {"matches": 2, "kills": 30, "deaths": 20, "assists": 10}


async def _maps(uid, *a):
    return [{"map": "어센트", "wins": 1, "losses": 0}]

store = achievement.scrim_record_store
saved = (store.get_record, store.get_season_record, store.recent_matches, store.kda_summary, store.map_stats)
store.get_record, store.get_season_record = _rec, _rec
store.recent_matches, store.kda_summary, store.map_stats = _recent, _kda, _maps
from utils import profile_service  # noqa: E402
profile_service.avatar_for = none
target = types.SimpleNamespace(id=42, display_name="먹9름")
emb = discord.Embed(title="t")
emb.add_field(name="통산", value="5승 3패")
f = asyncio.run(achievement.attach_scrim_card(target, emb))
check("내전 카드가 붙고 글 칸은 걷어낸다", f is not None and not emb.fields
      and emb.image.url == f"attachment://{achievement.SCRIM_CARD_FILE}")
stat_art.scrim_card = none
achievement.stat_art.scrim_card = none
emb = discord.Embed(title="t")
emb.add_field(name="통산", value="5승 3패")
check("🚨 못 그리면 글 칸이 그대로 남는다", asyncio.run(achievement.attach_scrim_card(target, emb)) is None
      and len(emb.fields) == 1)
stat_art.scrim_card = REAL["scrim_card"]
(store.get_record, store.get_season_record, store.recent_matches, store.kda_summary, store.map_stats) = saved

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
