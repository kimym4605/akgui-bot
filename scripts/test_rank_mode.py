# -*- coding: utf-8 -*-
"""🎮 `/전적`의 `모드: 일반전만` 검증. 디스코드·실제 API·DB 없이 돌아가요.

2026-11-18 `#💡｜기능-추천방` 건의("전적검색 일반전 전용도 하나 만들어주실수 있나요")로 만들었어요.
`/전적`은 원래 **경쟁전 우선**(모자라면 일반전으로 채움)만 됐어요.

여기서 확인하는 것:
  1) `/전적`에 `모드` 선택지가 있고, 안 고르면 **예전 동작 그대로**다
  2) 일반전만: 경쟁전 목록을 **아예 안 부른다** (HenrikDev 분당 30회를 봇 전체가 나눠 써요)
  3) 일반전만: 경쟁전이 한 판도 안 섞인다
  4) 🚨 일반전만 본 기록은 **보여주기만** 한다 — 아래 셋에 안 들어가요
       ⒜ 상위 % 표본  ⒝ 주간 악귀력  ⒞ 포지션 역할
     (⒝는 "그 주 최고 점수만 남는다"와 겹치면 일반전으로 주간 랭킹을 올리는 길이 돼요)
  5) 티어 역할은 모드와 상관없이 맞춘다 (티어는 MMR에서 나와요)
  6) 🚨 일반전 목록을 못 받아오면 "기록 없음"이 아니라 **조회 실패**로 알린다
  7) 기본 모드(회귀): 경쟁전·일반전을 둘 다 부르고, 기록·역할도 예전처럼 한다
"""
import asyncio
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
# pokemon_store가 import 시점에 Mongo 클라이언트를 만들어요(연결은 지연돼서 안 붙어요).
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_rank_mode_test"
os.environ["HENRIKDEV_API_KEY"] = "test-key"   # 없으면 `/전적`이 맨 앞에서 돌아가요

import discord  # noqa: E402

from cogs import rank as rank_cog  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def _mk_async(fn):
    async def _f(*a, **k):
        return fn(*a, **k)
    return _f


NAME, TAG, ME = "Tester", "KR1", 4242


def _match(mode, kills, agent, won=True):
    """`_extract_player_match_stats`가 읽는 모양 그대로의 경기 하나."""
    return {
        "metadata": {"mode": mode},
        "players": {"all_players": [{
            "name": NAME, "tag": TAG, "team": "Red", "character": agent,
            "stats": {"kills": kills, "deaths": 10, "assists": 3, "headshots": 6,
                      "bodyshots": 20, "legshots": 2, "score": 4500},
            "damage_made": 2800,
        }]},
        "teams": {"red": {"has_won": won, "rounds_won": 13 if won else 7,
                          "rounds_lost": 7 if won else 13},
                  "blue": {"has_won": not won, "rounds_won": 7 if won else 13,
                           "rounds_lost": 13 if won else 7}},
    }


# 경쟁전은 전부 10킬 · 제트(타격대), 일반전은 전부 30킬 · 세이지(감시자).
# → 섞였는지를 K/D와 포지션으로 바로 알 수 있어요(경쟁전 K/D 1.0 · 일반전 K/D 3.0).
COMP = [_match("Competitive", 10, "Jett") for _ in range(10)]
UNRATED = [_match("Unrated", 30, "Sage") for _ in range(10)]
MMR_OK = (200, {"data": {"current": {"tier": {"id": 12, "name": "Gold 1"}, "rr": 40}}})


class Rec:
    """부수 효과를 전부 받아 적어요."""

    def __init__(self):
        self.fetched = []          # 부른 경기 목록의 모드
        self.sample = []           # 상위 % 표본에 넣은 것
        self.weekly = []           # 주간 악귀력에 넣은 것
        self.position = []         # 포지션 역할 동기화
        self.tier = []             # 티어 역할 동기화
        self.replies = []          # (args, kwargs)


def install(rec, unrated_result=None):
    async def fake_mmr(session, headers, region, name, tag):
        return MMR_OK

    async def fake_matches(session, headers, region, name, tag, size, mode):
        rec.fetched.append(mode)
        if mode == "competitive":
            return 200, {"data": COMP[:size]}
        return unrated_result if unrated_result is not None else (200, {"data": UNRATED[:size]})

    rank_cog.fetch_current_mmr = fake_mmr
    rank_cog.fetch_matches_by_mode = fake_matches
    rank_cog.get_account = lambda uid: (NAME, TAG)
    rank_cog.is_matching_account = lambda uid, name, tag: True
    rank_cog.riot_account_store.get_region = lambda uid: "kr"
    rank_cog.record_stats = lambda riot_id, kd, score: rec.sample.append((riot_id, round(kd, 2)))
    rank_cog.get_kd_percentile = lambda kd: 12.0
    rank_cog.get_sample_size = lambda: 7
    rank_cog.agwi_weekly_store.record = _mk_async(
        lambda uid, score, grade, riot_id, stats=None: rec.weekly.append((uid, stats)))
    rank_cog.sync_tier_role = _mk_async(
        lambda member, tier, icon_bytes=None: rec.tier.append(tier) or {"status": "unchanged"})
    rank_cog.sync_position_role = _mk_async(
        lambda member, position: rec.position.append(position) or {"status": "unchanged"})
    rank_cog.valorant_coach.coach = _mk_async(lambda stats, tier_name: None)
    # 📊 1~7번은 **글 리포트**의 숫자를 봐요 → 그림 카드는 "못 그렸다"로 두고 예전 글 길을 타요.
    #    그림 길은 맨 아래 8번이 따로 봐요(2026-11-23).
    rank_cog.stat_art.report_card = CARD["fn"]


REAL_REPORT_CARD = rank_cog.stat_art.report_card
CARD = {"fn": _mk_async(lambda d: None)}


class FakeMember(discord.Member):
    """`isinstance(interaction.user, discord.Member)`를 통과해야 역할 동기화 길을 타요."""

    def __init__(self, uid):   # noqa: D401 — 진짜 생성자(state·guild 필요)를 건너뛰어요
        self._fake_id = uid

    @property
    def id(self):
        return self._fake_id


class FakeInter:
    def __init__(self, rec):
        self.user = FakeMember(ME)
        self.followup = type("F", (), {"send": _mk_async(
            lambda _self, *a, **k: rec.replies.append((a, k)))})()


def run(mode, unrated_result=None, count=None):
    rec = Rec()
    install(rec, unrated_result)
    cog = rank_cog.Rank.__new__(rank_cog.Rank)
    cog.session, cog.tier_icons = None, {}
    asyncio.run(cog.send_rank_report(FakeInter(rec), None, None, None, count, mode=mode))
    return rec


def embed_of(rec):
    for _a, k in rec.replies:
        if k.get("embed") is not None:
            return k["embed"]
    return None


def text_of(rec):
    """임베드가 아닌 글 답장들."""
    return [a[0] for a, _k in rec.replies if a and isinstance(a[0], str)]


print("1) `/전적`에 `모드` 선택지가 있다")
cmd = rank_cog.Rank.rank
params = {p.name: p for p in cmd.parameters}
check("`모드` 파라미터가 있다", "모드" in params, str(sorted(params)))
if "모드" in params:
    values = [c.value for c in params["모드"].choices]
    check("선택지는 '경쟁전 우선' · '일반전만' 두 개", values == [rank_cog.MODE_AUTO, rank_cog.MODE_UNRATED],
          str(values))
    check("필수가 아니다 (안 고르면 예전 그대로)", params["모드"].required is False)
    check("설명이 디스코드 한도(100자) 안이다", len(params["모드"].description) <= 100,
          f"{len(params['모드'].description)}자")
check("기본값은 MODE_AUTO",
      rank_cog.Rank.send_rank_report.__kwdefaults__.get("mode") == rank_cog.MODE_AUTO,
      str(rank_cog.Rank.send_rank_report.__kwdefaults__))


print("\n2) 일반전만: 경쟁전 목록을 아예 안 부른다")
u = run(rank_cog.MODE_UNRATED)
check("부른 목록이 일반전 하나뿐", u.fetched == ["unrated"], str(u.fetched))


print("\n3) 일반전만: 경쟁전이 한 판도 안 섞인다")
ue = embed_of(u)
check("리포트가 나갔다", ue is not None, str(u.replies)[:200])
if ue is not None:
    desc = ue.description or ""
    check("제목에 '일반전'이 있다", "일반전" in (ue.title or ""), ue.title)
    check("요약 줄이 '최근 일반전 10경기'", "최근 일반전 10경기" in desc, desc[:300])
    check("K/D가 일반전 값(3.00)이다 — 경쟁전(1.00)이 섞이지 않았다", "**3.00**" in desc, desc[:300])
    check("주 포지션이 일반전 요원(감시자) 기준이다", "감시자" in desc and "타격대" not in desc, desc[-200:])
    check("'일반전만 모아 본 기록'이라고 알린다", "일반전만" in desc)
    check("🚨 상위 %를 붙이지 않는다 (경쟁전 우선 기록끼리 비교하는 숫자)", "상위" not in desc.split("일반전만")[0],
          desc[:300])
    check("'경쟁전 표본이 적어' 안내가 안 붙는다", "경쟁전 표본이 적어" not in desc)

# 경기수 옵션도 일반전 기준으로 먹는지
u3 = run(rank_cog.MODE_UNRATED, count=3)
check("경기수 3 → 일반전 3경기만", "최근 일반전 3경기" in ((embed_of(u3).description or "") if embed_of(u3) else ""),
      (embed_of(u3).description or "")[:200] if embed_of(u3) else "임베드 없음")


print("\n4) 🚨 일반전만 본 기록은 보여주기만 한다")
check("⒜ 상위 % 표본에 안 넣는다", u.sample == [], str(u.sample))
check("⒝ 주간 악귀력에 안 넣는다 (일반전으로 주간 랭킹 올리기 방지)", u.weekly == [], str(u.weekly))
check("⒞ 포지션 역할을 안 건드린다", u.position == [], str(u.position))


print("\n5) 티어 역할은 모드와 상관없이 맞춘다")
check("일반전만 볼 때도 티어 역할을 맞춘다", len(u.tier) == 1, str(u.tier))


print("\n6) 🚨 일반전 목록을 못 받아오면 '기록 없음'이 아니라 조회 실패로 알린다")
f = run(rank_cog.MODE_UNRATED, unrated_result=(500, {}))
check("임베드(리포트)가 안 나간다", embed_of(f) is None)
check("'불러오지 못했어요'라고 알린다", any("불러오지 못했어요" in t for t in text_of(f)), str(text_of(f)))
check("'기록을 찾지 못했어요'(= 일반전을 안 한 사람)로 보이지 않는다",
      not any("찾지 못했어요" in t for t in text_of(f)), str(text_of(f)))

r = run(rank_cog.MODE_UNRATED, unrated_result=(429, {"retry_after": 17}))
check("429면 기다리라고 알린다", any("잠시 막혔어요" in t for t in text_of(r)), str(text_of(r)))

# 진짜로 일반전을 안 한 사람(200 + 빈 목록)은 '기록 없음'이 맞아요
n = run(rank_cog.MODE_UNRATED, unrated_result=(200, {"data": []}))
ne = embed_of(n)
check("일반전이 0판이면 '일반전 기록을 찾지 못했어요'", ne is not None and "일반전" in (ne.description or "")
      and "찾지 못했어요" in (ne.description or ""), (ne.description if ne else "임베드 없음"))
check("   └ 그때도 기록은 아무 데도 안 넣는다", n.sample == [] and n.weekly == [] and n.position == [])


print("\n7) 기본 모드(회귀): 예전과 똑같이 동작한다")
a = run(rank_cog.MODE_AUTO)
check("경쟁전·일반전을 둘 다 부른다", sorted(a.fetched) == ["competitive", "unrated"], str(a.fetched))
ae = embed_of(a)
check("리포트가 나갔다", ae is not None)
if ae is not None:
    desc = ae.description or ""
    check("제목에 '일반전'이 없다", "일반전" not in (ae.title or ""), ae.title)
    check("요약 줄이 '최근 경쟁전 10경기'", "최근 경쟁전 10경기" in desc, desc[:300])
    check("K/D가 경쟁전 값(1.00)이다", "**1.00**" in desc, desc[:300])
    check("상위 %가 붙는다", "상위 12%" in desc, desc[:300])
check("상위 % 표본에 넣는다", len(a.sample) == 1 and a.sample[0][1] == 1.0, str(a.sample))
check("주간 악귀력에 넣는다", len(a.weekly) == 1 and a.weekly[0][0] == ME, str(a.weekly))
check("포지션 역할을 맞춘다 (타격대)", a.position == ["타격대"], str(a.position))
check("티어 역할을 맞춘다", len(a.tier) == 1, str(a.tier))

# 모드를 안 넘긴 호출(`/프로필`의 🎯 버튼)도 기본 모드여야 해요
rec = Rec()
install(rec)
cog = rank_cog.Rank.__new__(rank_cog.Rank)
cog.session, cog.tier_icons = None, {}
asyncio.run(cog.send_rank_report(FakeInter(rec), ephemeral=True))
check("mode를 안 넘기면 기본 모드다 (`/프로필` 🎯 버튼 경로)",
      sorted(rec.fetched) == ["competitive", "unrated"] and len(rec.weekly) == 1, str(rec.fetched))


print("\n8) '자세히 보기'도 모드를 따라간다")
stats = rank_cog.aggregate_match_stats(UNRATED, NAME, TAG, tier_id=12, rr=40)
du = rank_cog.build_detail_embed(NAME, TAG, stats, 0, False, mode=rank_cog.MODE_UNRATED)
check("일반전만: 제목에 '일반전'", "일반전" in (du.title or ""), du.title)
check("일반전만: 표본 구성이 '일반전 10경기'",
      any(f.name == "표본 구성" and "일반전 10경기" in f.value for f in du.fields),
      str([(f.name, f.value) for f in du.fields][:2]))
check("일반전만: 꼬리말이 상위 % 표본 인원을 말하지 않는다", "명 기준" not in (du.footer.text or ""),
      du.footer.text)
da = rank_cog.build_detail_embed(NAME, TAG, stats, 10, False)
check("기본: 꼬리말이 예전 그대로다", "7명 기준" in (da.footer.text or ""), da.footer.text)


print("\n9) 📊 전적 카드 그림 (2026-11-23)")
CARD["fn"] = REAL_REPORT_CARD
c = run(rank_cog.MODE_UNRATED)
ce = embed_of(c)
sent = [k for _a, k in c.replies if k.get("embed") is not None]
check("그림이 붙어서 나간다", bool(sent) and getattr(sent[0].get("file"), "filename", "") == rank_cog.REPORT_CARD_FILE)
check("임베드가 그 그림을 가리킨다", ce is not None and (ce.image.url or "").endswith(rank_cog.REPORT_CARD_FILE))
cdesc = (ce.description or "") if ce else ""
check("숫자 덩어리는 글에서 빠진다 (그림과 두 벌이 안 되게)", "K/D 비율" not in cdesc and "헤드샷율" not in cdesc, cdesc[:200])
check("🚨 '일반전만' 안내는 그대로 남는다", "일반전만" in cdesc, cdesc[:200])
data = rank_cog.report_card_data(NAME, TAG, "Gold 1", 40, 12, stats, 0, False, rank_cog.MODE_UNRATED)
check("카드 표본 줄이 '최근 일반전 10경기'", data["sample"] == "최근 일반전 10경기", data["sample"])
check("카드 K/D가 일반전 값(3.0)", abs(data["kd"] - 3.0) < 0.01, str(data["kd"]))
check("카드 최근 경기 10개 · 전부 세이지", len(data["recent"]) == 10 and {a for _w, a in data["recent"]} == {"Sage"},
      str(data["recent"][:3]))
check("카드 선호 요원이 한글 이름도 갖는다", data["agents"][0][:2] == ("Sage", "세이지"), str(data["agents"]))
mixed = COMP[:3] + UNRATED[:2]
for i, m in enumerate(mixed):        # 일반전이 더 최근에 시작한 경기
    m = dict(m)
    m["metadata"] = {**m["metadata"], "game_start": 1000 + (100 if i >= 3 else 0) + i}
    mixed[i] = m
ms = rank_cog.aggregate_match_stats(mixed, NAME, TAG, tier_id=12, rr=40)
check("🚨 경쟁전+일반전을 이어 붙여도 '최근 경기'는 시작 시각 최신순",
      [a for _w, a in ms["recent"]][:2] == ["Sage", "Sage"], str(ms["recent"]))
CARD["fn"] = _mk_async(lambda d: None)


# 🚨 요약은 맨 마지막이어야 해요(뒤에 섹션을 붙이면 그 FAIL이 집계에서 빠져요).
print("\n" + "=" * 50)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f_ in failures:
        print(f"   - {f_}")
    sys.exit(1)
print("✅ /전적 모드(경쟁전 우선 · 일반전만) 전부 정상")
