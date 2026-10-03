"""내전 KDA 가져오기 회귀 테스트 (경기 고르기 · 추출 · 누적 집계).

    python scripts/test_scrim_kda.py

API를 부르지 않아요. **실제 HenrikDev 응답을 그대로 베낀 가짜 payload**로 돌려요
(2026-10-03 카푸치노s#머그잔의 사용자 설정 경기 구조 기준).
⚠️ DB 집계 부분은 테스트 전용 DB 이름으로 돌아가요.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_map_test"

from utils import scrim_record_store, scrim_stats_fetch, valorant_maps  # noqa: E402

passed = failed = 0


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


# ── 실제 응답을 베낀 가짜 데이터 ────────────────────────────────────
def player(name, tag, team, kills, deaths, assists, *, dmg=3000, hs=10, bs=40, ls=5,
           agent="Astra", score=4000):
    return {
        "name": name, "tag": tag, "team": team, "character": agent,
        "damage_made": str(dmg), "damage_received": "2500",
        "stats": {"kills": kills, "deaths": deaths, "assists": assists,
                  "score": score, "headshots": hs, "bodyshots": bs, "legshots": ls},
    }


def match(*, queue="Standard", players=None, started=1_789_220_888, map_name="Lotus",
          rounds=24, red_won=True, match_id="m-1"):
    return {
        "metadata": {"queue": queue, "map": map_name, "rounds_played": rounds,
                     "game_start": started, "matchid": match_id, "mode_id": "custom"},
        "players": {"all_players": players or []},
        "teams": {"red": {"has_won": red_won, "rounds_won": 13 if red_won else 11},
                  "blue": {"has_won": not red_won, "rounds_won": 11 if red_won else 13}},
    }


SCRIM_PLAYERS = [
    player("OwO", "0583", "Red", 24, 17, 7, dmg=4200, hs=15, bs=61, ls=8, agent="Vyse"),
    player("카푸치노s", "머그잔", "Red", 14, 15, 8, dmg=3100),
    player("먹9름", "맨헤라진정", "Red", 19, 17, 12),
    player("Llien", "KR1", "Red", 18, 15, 13),
    player("che0ngi1", "0101", "Red", 23, 13, 1),
    player("피카츄", "PXG1", "Blue", 19, 18, 4),
    player("새털구름", "111", "Blue", 14, 18, 2),
    player("카드값줘체리", "산와머니", "Blue", 23, 19, 2),
    player("응애뉴비", "owo", "Blue", 10, 23, 7),
    player("뱅구뱅구", "1020", "Blue", 11, 20, 8),
]

# 등록된 사람만 디스코드 id와 이어져요(실제로도 10명 중 5명만 등록돼 있었어요).
RIOT_INDEX = {
    "owo#0583": 101,
    "카푸치노s#머그잔": 102,
    "먹9름#맨헤라진정": 103,
    "피카츄#pxg1": 104,
    "새털구름#111": 105,
}
ROSTER = {101, 102, 103, 104, 105}
REPORTED_AT = 1_789_220_888 + 600  # 경기 끝나고 10분 뒤에 보고


print("경기 걸러내기 (is_scrim_like)")
check("5대5 Standard는 통과", scrim_stats_fetch.is_scrim_like(match(players=SCRIM_PLAYERS)), True)
check("데스매치(Skirmish)는 걸러짐",
      scrim_stats_fetch.is_scrim_like(match(queue="Skirmish", players=SCRIM_PLAYERS[:4])), False)
check("Standard인데 4명이면 걸러짐",
      scrim_stats_fetch.is_scrim_like(match(players=SCRIM_PLAYERS[:4])), False)
check("참가자가 없으면 걸러짐", scrim_stats_fetch.is_scrim_like(match(players=[])), False)
check("8명은 통과(9대9·4대4로 돌리는 날)",
      scrim_stats_fetch.is_scrim_like(match(players=SCRIM_PLAYERS[:8])), True)

print("\n명단 겹침 (roster_overlap) — 대소문자·공백을 봐요")
check("등록된 5명을 찾음",
      scrim_stats_fetch.roster_overlap(match(players=SCRIM_PLAYERS), RIOT_INDEX),
      {101, 102, 103, 104, 105})
check("대문자/소문자가 달라도 찾음 (OwO ↔ owo#0583)",
      101 in scrim_stats_fetch.roster_overlap(match(players=SCRIM_PLAYERS), RIOT_INDEX), True)
spaced = [player("최 강", "1020", "Red", 1, 1, 1)]
check("이름에 공백이 있어도 찾음",
      scrim_stats_fetch.roster_overlap(match(players=spaced), {"최강#1020": 201}), {201})
check("아무도 등록 안 됐으면 빈 집합",
      scrim_stats_fetch.roster_overlap(match(players=SCRIM_PLAYERS), {}), set())

print("\n경기 고르기 (pick_match) — 엉뚱한 경기를 물어오면 안 돼요")
good = match(players=SCRIM_PLAYERS, match_id="방금-한-내전")
picked = scrim_stats_fetch.pick_match([good], RIOT_INDEX, ROSTER, REPORTED_AT)
check("맞는 경기를 고름", picked[0]["metadata"]["matchid"], "방금-한-내전")
check("겹친 사람도 돌려줌", picked[1], ROSTER)

old = match(players=SCRIM_PLAYERS, started=REPORTED_AT - 30 * 3600, match_id="어제-내전")
check("어제 경기는 시간 때문에 탈락",
      scrim_stats_fetch.pick_match([old], RIOT_INDEX, ROSTER, REPORTED_AT), None)
check("어제 경기와 방금 경기가 같이 있으면 방금 걸 고름",
      scrim_stats_fetch.pick_match([old, good], RIOT_INDEX, ROSTER, REPORTED_AT)[0]
      ["metadata"]["matchid"], "방금-한-내전")

strangers = [player(f"남{i}", f"t{i}", "Red" if i < 5 else "Blue", 10, 10, 5) for i in range(10)]
check("모르는 사람들끼리의 내전은 안 고름",
      scrim_stats_fetch.pick_match([match(players=strangers)], RIOT_INDEX, ROSTER, REPORTED_AT),
      None)

# 겹침이 2명뿐이면(최소 3명) 안 골라요 — 우리 내전이 아닐 수 있어요.
two = SCRIM_PLAYERS[:2] + strangers[:8]
check("겹침이 2명뿐이면 안 고름",
      scrim_stats_fetch.pick_match([match(players=two)], RIOT_INDEX, ROSTER, REPORTED_AT), None)

check("데스매치만 있으면 안 고름",
      scrim_stats_fetch.pick_match(
          [match(queue="Skirmish", players=SCRIM_PLAYERS)], RIOT_INDEX, ROSTER, REPORTED_AT), None)
check("후보가 없으면 None", scrim_stats_fetch.pick_match([], RIOT_INDEX, ROSTER, REPORTED_AT), None)

# 겹침이 더 많은 쪽을 고르는지 (시간이 더 가까운 쪽보다 우선)
near_few = match(players=two, started=REPORTED_AT - 60, match_id="가깝지만-2명")
far_many = match(players=SCRIM_PLAYERS, started=REPORTED_AT - 3000, match_id="멀지만-5명")
check("겹침이 많은 쪽을 고름",
      scrim_stats_fetch.pick_match([near_few, far_many], RIOT_INDEX, ROSTER, REPORTED_AT)[0]
      ["metadata"]["matchid"], "멀지만-5명")

print("\n기록 뽑아내기 (extract_stats)")
stats = scrim_stats_fetch.extract_stats(match(players=SCRIM_PLAYERS), RIOT_INDEX)
check("맵이 한글로 바뀜", stats["map"], "로터스")
check("라운드 스코어", (stats["rounds"]["red"], stats["rounds"]["blue"]), (13, 11))
check("이긴 팀", stats["wonTeam"], "red")
check("라운드 수", stats["roundsPlayed"], 24)
check("참가자 10명", len(stats["players"]), 10)
owo = next(p for p in stats["players"] if p["name"] == "OwO")
check("KDA", (owo["kills"], owo["deaths"], owo["assists"]), (24, 17, 7))
check("디스코드 id가 이어짐", owo["userId"], "101")
check("피해량이 숫자로", owo["damage"], 4200)
check("샷 합계(HS% 계산용)", owo["shots"], 15 + 61 + 8)
check("팀이 소문자로", owo["team"], "red")
stranger = next(p for p in stats["players"] if p["name"] == "Llien")
check("미등록자는 userId가 None", stranger["userId"], None)
check("미등록자도 명단엔 남음", stranger["kills"], 18)
check("요원 이름", owo["agent"], "Vyse")

print("\n계산 보조 (per_round · headshot_rate)")
check("ADR", round(scrim_stats_fetch.per_round(4200, 24), 1), 175.0)
check("라운드가 0이면 None", scrim_stats_fetch.per_round(4200, 0), None)
check("HS%", round(scrim_stats_fetch.headshot_rate(15, 84), 1), 17.9)
check("쏜 게 없으면 None", scrim_stats_fetch.headshot_rate(0, 0), None)

print("\n맵 이름 변환 (valorant_maps)")
check("영문 → 한글", valorant_maps.to_korean("Ascent"), "어센트")
check("서밋도 있음 (2026-10-03 목록에 추가)", valorant_maps.to_korean("Summit"), "서밋")
check("서밋이 맵 목록에도 있음", "서밋" in valorant_maps.MAPS, True)
check("데스매치 맵도 변환됨", valorant_maps.to_korean("Piazza"), "피아자")
check("모르는 맵은 그대로 (버리지 않아요)", valorant_maps.to_korean("NewMap"), "NewMap")
check("이미 한글이면 그대로", valorant_maps.to_korean("어센트"), "어센트")
check("None은 None", valorant_maps.to_korean(None), None)
check("맵 목록이 드롭다운 한도 안", len(valorant_maps.MAPS) <= valorant_maps.MAX_SELECT_OPTIONS, True)


async def db_part():
    from cogs.achievement import _kda_text

    scrim_record_store._matches.delete_many({"note": "KDA테스트"})
    scrim_record_store._records.delete_many({"userId": {"$in": ["101", "104"]}})

    print("\n경기에 기록 붙이기 (attach_stats)")
    mid = await scrim_record_store.record_match(1, [101, 102, 103], [104, 105],
                                                note="KDA테스트")
    check("맵이 아직 없음",
          scrim_record_store._matches.find_one({"note": "KDA테스트"})["map"], None)
    check("붙이기 성공", await scrim_record_store.attach_stats(mid, stats), True)
    doc = scrim_record_store._matches.find_one({"note": "KDA테스트"})
    check("stats가 저장됨", len(doc["stats"]["players"]), 10)
    check("비어 있던 맵이 채워짐", doc["map"], "로터스")
    check("없는 경기면 False",
          await scrim_record_store.attach_stats("ffffffffffffffffffffffff", stats), False)
    check("망가진 id도 안 터짐", await scrim_record_store.attach_stats("아무말", stats), False)

    print("\n사람이 고른 맵은 덮어쓰지 않아요 (엉뚱한 경기를 물어왔을 때 대비)")
    mid2 = await scrim_record_store.record_match(1, [101], [104], note="KDA테스트",
                                                 map_name="어센트")
    await scrim_record_store.attach_stats(mid2, stats)  # stats의 맵은 로터스
    kept = [d for d in scrim_record_store._matches.find({"note": "KDA테스트"})
            if str(d["_id"]) == mid2][0]
    check("사람이 고른 '어센트'가 유지됨", kept["map"], "어센트")
    check("그래도 stats는 붙음", kept["stats"]["map"], "로터스")

    print("\n누적 KDA (kda_summary)")
    summary = await scrim_record_store.kda_summary(101)
    check("2경기로 집계됨 (둘 다 stats가 붙었어요)", summary["matches"], 2)
    check("킬 합계", summary["kills"], 48)
    check("데스 합계", summary["deaths"], 34)
    check("한 경기 최다 킬", summary["bestKills"], 24)
    check("라운드 합계", summary["rounds"], 48)
    check("기록이 없는 사람은 matches 0",
          (await scrim_record_store.kda_summary(999))["matches"], 0)
    check("명단에 있어도 stats에 없으면 안 잡힘",
          (await scrim_record_store.kda_summary(102))["matches"] > 0, True)

    print("\n화면 문구 (_kda_text)")
    text = _kda_text(summary)
    print("   " + text.replace("\n", "\n   "))
    check("평균 KDA가 보임", "평균 **24.0 / 17.0 / 7.0**" in text, True)
    check("K/D가 보임", "K/D 1.41" in text, True)
    check("ADR이 보임", "ADR" in text, True)
    check("몇 판 기준인지 적힘", "2판 기준" in text, True)

    scrim_record_store._matches.delete_many({"note": "KDA테스트"})
    scrim_record_store._records.delete_many({"userId": {"$in": ["101", "104"]}})


asyncio.run(db_part())
print(f"\n{passed}개 통과, {failed}개 실패")
sys.exit(1 if failed else 0)
