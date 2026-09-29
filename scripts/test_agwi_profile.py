"""악귀 프로필/업적/내전전적 회귀 테스트.

실행:  .venv\Scripts\python.exe scripts/test_agwi_profile.py   (프로젝트 루트에서)

⚠️ MONGODB_DB_NAME을 `agwi_profile_test`로 덮어써서 **프로덕션 DB는 건드리지 않아요.**
   같은 Atlas 클러스터를 쓰지만 DB가 달라서 데이터가 섞이지 않고, 끝나면 전부 지워요.
   (맨 위 assert가 테스트 DB가 맞는지 한 번 더 확인해요 - 이게 유일한 안전장치예요.)

여기서 잡은 실제 버그 2개:
  - 주간 악귀력: 조건부 필터 + upsert=True 조합이 점수가 안 오를 때마다 DuplicateKeyError
  - 업적 해금: 같은 이유로 /프로필을 두 번 누르면 판정이 통째로 터질 수 있었음
둘 다 [5] 동시 호출 테스트가 회귀를 막아줘요.
"""

import asyncio
import os
import sys

BOT_DIR = r"C:\Users\user\Desktop\악귀봇프로젝트\discord-bot-starter-py"
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BOT_DIR, ".env"))

# ★ 프로덕션 DB 보호: 반드시 .env 로드 '뒤에' 덮어써요.
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_profile_test"

from utils import (  # noqa: E402
    achievement_data,
    achievement_store,
    agwi_weekly_store,
    scrim_record_store,
)
from utils.pokemon_store import _db  # noqa: E402

assert _db.name == "agwi_profile_test", f"테스트 DB가 아니에요: {_db.name}"
print(f"테스트 DB: {_db.name}\n")

U1, U2, U3 = 900000000000000001, 900000000000000002, 900000000000000003
PASS, FAIL = [], []


def check(label, condition, detail=""):
    (PASS if condition else FAIL).append(label)
    print(f"  {'✅' if condition else '❌'} {label}" + (f"  → {detail}" if detail else ""))


async def cleanup():
    for name in ("scrim_records", "scrim_matches", "agwi_weekly", "achievements",
                 "coin_reset_backup", "coin_log", "missions", "trainers"):
        _db[name].delete_many({})


async def test_scrim():
    print("[1] 내전 전적 · 연승 계산")
    # U1이 3연승 후 2연패
    for _ in range(3):
        await scrim_record_store.record_match(1, [U1], [U2], note="test")
    rec = await scrim_record_store.get_record(U1)
    check("3승 0패", rec["wins"] == 3 and rec["losses"] == 0, f"{rec['wins']}승 {rec['losses']}패")
    check("연승 3", rec["streak"] == 3, f"streak={rec['streak']}")
    check("최고 연승 3", rec["bestStreak"] == 3)

    for _ in range(2):
        await scrim_record_store.record_match(1, [U2], [U1], note="test")
    rec = await scrim_record_store.get_record(U1)
    check("3승 2패", rec["wins"] == 3 and rec["losses"] == 2)
    check("연승이 끊겨 -2(2연패)", rec["streak"] == -2, f"streak={rec['streak']}")
    check("최고 연승은 3으로 유지", rec["bestStreak"] == 3, f"best={rec['bestStreak']}")
    check("최다 연패 -2 기록", rec["worstStreak"] == -2, f"worst={rec['worstStreak']}")

    # 다시 이기면 연패가 끊기고 1연승부터
    await scrim_record_store.record_match(1, [U1], [U2], note="test")
    rec = await scrim_record_store.get_record(U1)
    check("다시 이기면 연승 1부터", rec["streak"] == 1, f"streak={rec['streak']}")

    # 상대편(U2)도 정확히 반대로 쌓였는지
    rec2 = await scrim_record_store.get_record(U2)
    check("상대는 2승 4패", rec2["wins"] == 2 and rec2["losses"] == 4,
          f"{rec2['wins']}승 {rec2['losses']}패")

    check("승률 계산", abs(scrim_record_store.win_rate(rec) - 4/6*100) < 0.1,
          f"{scrim_record_store.win_rate(rec):.1f}%")

    # 여러 명이 한 팀
    await scrim_record_store.record_match(1, [U1, U2, U3], [], note="한쪽만")
    rec3 = await scrim_record_store.get_record(U3)
    check("한쪽 팀이 비면 기록 안 됨", rec3["wins"] == 0, f"U3 {rec3['wins']}승")

    await scrim_record_store.record_match(1, [U1, U3], [U2], note="5:5 대체")
    rec3 = await scrim_record_store.get_record(U3)
    check("팀 단위로 전원 반영", rec3["wins"] == 1, f"U3 {rec3['wins']}승")

    # 시즌 문서가 통산과 따로 쌓이는지
    season = await scrim_record_store.get_season_record(U1)
    check("시즌 문서도 같이 쌓임", season["wins"] == 5, f"시즌 {season['wins']}승")

    top = await scrim_record_store.top(limit=5)
    check("랭킹 조회", len(top) >= 2 and top[0]["wins"] >= top[-1]["wins"],
          f"{len(top)}명, 1위 {top[0]['wins']}승")

    recent = await scrim_record_store.recent_matches(U1, limit=10)
    check("최근 경기 조회", len(recent) == 7, f"{len(recent)}경기")


async def test_weekly():
    print("\n[2] 주간 악귀력")
    ok = await agwi_weekly_store.record(U1, 892, "악귀", "먹9름#KR1")
    check("첫 기록", ok)
    row = await agwi_weekly_store.get(U1)
    check("조회됨", row and row["score"] == 892, f"score={row and row['score']}")

    ok = await agwi_weekly_store.record(U1, 700, "악귀", "먹9름#KR1")
    row = await agwi_weekly_store.get(U1)
    check("더 낮은 점수는 덮어쓰지 않음", row["score"] == 892, f"score={row['score']}")

    ok = await agwi_weekly_store.record(U1, 1100, "상위악귀", "먹9름#KR1")
    row = await agwi_weekly_store.get(U1)
    check("더 높은 점수로는 갱신됨", row["score"] == 1100, f"score={row['score']}")

    await agwi_weekly_store.record(U2, 950, "악귀", "둘#KR1")
    top = await agwi_weekly_store.top(limit=5)
    check("주간 랭킹 정렬", top[0]["userId"] == str(U1) and top[1]["userId"] == str(U2),
          f"1위 {top[0]['score']}, 2위 {top[1]['score']}")

    # 프로필 카드의 간략 전적. 점수와 수명이 달라요 - 점수는 "그 주 최고"만 남지만
    # 전적은 **마지막 조회**가 남아야 해요. 이걸 payload에만 얹었다가, 그 주 최고점이
    # 이미 있는 흔한 경우에 전적이 통째로 안 써지는 버그를 냈어요(배포 직후 재현됨).
    await agwi_weekly_store.record(U1, 1100, "상위악귀", "먹9름#KR1",
                                   stats={"kd": 1.30, "winRate": 60.0, "hs": 25.0, "matches": 20})
    row = await agwi_weekly_store.get(U1)
    check("전적 스냅샷 저장", (row.get("stats") or {}).get("kd") == 1.30)

    await agwi_weekly_store.record(U1, 300, "D", "먹9름#KR1",
                                   stats={"kd": 0.80, "winRate": 40.0, "hs": 15.0, "matches": 12})
    row = await agwi_weekly_store.get(U1)
    check("점수가 안 올라도 전적은 최신으로 갱신됨",
          (row.get("stats") or {}).get("kd") == 0.80 and row["score"] == 1100,
          f"kd={(row.get('stats') or {}).get('kd')}, score={row['score']}")

    latest = await agwi_weekly_store.latest(U1)
    check("마지막 전적 스냅샷 조회", (latest.get("stats") or {}).get("kd") == 0.80)

    best = await agwi_weekly_store.best_ever(U1)
    check("역대 최고 조회", best["score"] == 1100)
    check("주차 키 형식", agwi_weekly_store.week_key().startswith("20"),
          agwi_weekly_store.week_key())


async def test_achievements():
    print("\n[3] 업적 판정 · 보상")
    _db["trainers"].insert_one({
        "_id": str(U1), "attendance": 137, "attendanceStreak": 12, "coin": 50,
        "pokedex": ["a"] * 42, "level": 55, "basePokemon": "파이리",
    })
    _db["missions"].insert_one({"_id": str(U1), "totalDone": 12})

    stats = await achievement_store.collect_stats(U1, tier_index=20, riot_linked=True, birthday_set=True)
    check("출석 수집", stats["attendance"] == 137, str(stats["attendance"]))
    check("연속 출석 수집", stats["attendance_streak"] == 12)
    check("도감 수집", stats["pokedex"] == 42)
    check("레벨 수집", stats["level"] == 55)
    check("내전 승수 수집", stats["scrim_wins"] == 5, str(stats["scrim_wins"]))
    check("최고 연승 수집", stats["scrim_best_streak"] == 3)
    check("악귀력 수집", stats["agwi_best"] == 1100, str(stats["agwi_best"]))
    check("티어 수집", stats["tier_index"] == 20)
    check("미션 누적 수집", stats["mission_total"] == 12)
    check("연동 플래그", stats["riot_linked"] == 1 and stats["birthday_set"] == 1)

    before = _db["trainers"].find_one({"_id": str(U1)})["coin"]
    newly = await achievement_store.evaluate(U1, stats)
    expected_reward = sum(a["reward"] for a in newly)
    after = _db["trainers"].find_one({"_id": str(U1)})["coin"]
    check("업적이 여럿 열림", len(newly) > 10, f"{len(newly)}개")
    check("보상 코인 지급", after == before + expected_reward, f"{before} → {after} (+{expected_reward})")

    # 두 번째 판정은 아무것도 안 열려야 해요(중복 지급 방지)
    newly2 = await achievement_store.evaluate(U1, stats)
    after2 = _db["trainers"].find_one({"_id": str(U1)})["coin"]
    check("재판정 시 중복 해금 없음", len(newly2) == 0, f"{len(newly2)}개")
    check("재판정 시 코인 안 늘어남", after2 == after, f"{after} → {after2}")

    summary = await achievement_store.summary(U1, stats)
    check("요약 집계", summary["unlocked"] == len(newly) and summary["total"] == 60,
          f"{summary['unlocked']}/{summary['total']}")

    # 조건 근처 경계값
    tier_ach = achievement_data.BY_KEY["tier_asc"]  # 초월자 = 19
    check("경계값(19>=19) 해금", achievement_data.is_unlocked(tier_ach, {"tier_index": 19}))
    check("경계값(18<19) 미해금", not achievement_data.is_unlocked(tier_ach, {"tier_index": 18}))
    check("값 없으면 미해금", not achievement_data.is_unlocked(tier_ach, {}))

    # 기록이 하나도 없는 신규 유저
    fresh = await achievement_store.collect_stats(U3)
    newly3 = await achievement_store.evaluate(U3, fresh)
    check("신규 유저는 내전 업적만(기록 있는 만큼)", all(a["category"] == "scrim" for a in newly3),
          f"{[a['name'] for a in newly3]}")


async def test_card():
    print("\n[4] 프로필 카드 (실제 수집 데이터로)")
    from utils import profile_card
    stats = await achievement_store.collect_stats(U1, tier_index=20)
    rec = await scrim_record_store.get_record(U1)
    weekly = await agwi_weekly_store.get(U1)
    summary = await achievement_store.summary(U1, stats)

    data = {
        "name": "테스트유저", "title": "오퍼의 악마", "title_color": (255, 120, 180),
        "tier": "초월자 2", "accent_color": (155, 89, 232), "coin": stats["coin"],
        "record": {"wins": rec["wins"], "losses": rec["losses"],
                   "best_streak": rec["bestStreak"],
                   "win_rate": scrim_record_store.win_rate(rec) or 0},
        "streak_now": scrim_record_store.streak_text(rec),
        "agwi": weekly["score"], "agwi_grade": weekly["grade"],
        "achievements": summary["unlocked"], "achievements_total": summary["total"],
        "pokemon": "리자몽 Lv.55", "pokedex": stats["pokedex"],
        "attendance": stats["attendance"], "attendance_streak": stats["attendance_streak"],
        "season": scrim_record_store.current_season(),
    }
    png = await profile_card.render_card(data, None)
    check("카드 렌더링", png is not None and len(png) > 10000, f"{len(png or b''):,} bytes")
    if png:
        open(r"C:\tmp\card_real.png", "wb").write(png)
        print("     → C:\\tmp\\card_real.png 저장")


async def test_concurrency():
    """두 화면을 동시에 열었을 때(=같은 업적이 동시에 판정될 때) 코인이 두 번 나가지 않는지.

    여기가 실제로 DuplicateKeyError가 터지던 자리예요 - 조건부 필터에 upsert=True를 같이
    쓰면, 이미 열린 업적에 대해 매번 예외가 났어요."""
    print("\n[5] 동시 호출 (중복 지급 · 예외 없음)")
    _db["trainers"].insert_one({
        "_id": str(U2), "attendance": 400, "attendanceStreak": 100, "coin": 0,
        "pokedex": ["a"] * 151, "level": 100, "basePokemon": "파이리",
    })
    stats = await achievement_store.collect_stats(U2, tier_index=25, riot_linked=True, birthday_set=True)

    # 같은 사람에 대해 판정 5개를 동시에 굴려요.
    results = await asyncio.gather(
        *[achievement_store.evaluate(U2, stats) for _ in range(5)],
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    check("동시 판정에서 예외 없음", not errors, f"{[type(e).__name__ for e in errors]}")

    all_unlocked = [a["key"] for r in results if not isinstance(r, Exception) for a in r]
    check("같은 업적이 두 번 열리지 않음",
          len(all_unlocked) == len(set(all_unlocked)),
          f"{len(all_unlocked)}개 해금, 중복 {len(all_unlocked) - len(set(all_unlocked))}개")

    expected = sum(achievement_data.BY_KEY[k]["reward"] for k in set(all_unlocked))
    coin = _db["trainers"].find_one({"_id": str(U2)})["coin"]
    check("코인이 정확히 한 번씩만 지급됨", coin == expected, f"실제 {coin} / 기대 {expected}")

    # 주간 악귀력도 같은 함정이 있었어요 - 낮은 점수를 연달아 넣어봐요.
    await agwi_weekly_store.record(U2, 1500, "최고", "둘#KR1")
    lowers = await asyncio.gather(*[agwi_weekly_store.record(U2, 300, "낮음", "둘#KR1") for _ in range(5)])
    check("낮은 점수 반복 기록이 전부 조용히 무시됨", not any(lowers), str(lowers))
    row = await agwi_weekly_store.get(U2)
    check("최고 점수 유지", row["score"] == 1500, f"score={row['score']}")

    # 동시에 같은 주 첫 기록 (문서가 아직 없을 때의 경합)
    _db["agwi_weekly"].delete_many({})
    firsts = await asyncio.gather(
        *[agwi_weekly_store.record(U3, 800, "악귀", "셋#KR1") for _ in range(5)],
        return_exceptions=True,
    )
    check("첫 기록 경합에서 예외 없음",
          not [f for f in firsts if isinstance(f, Exception)],
          str([type(f).__name__ for f in firsts if isinstance(f, Exception)]))
    check("문서는 하나만 생김", _db["agwi_weekly"].count_documents({"userId": str(U3)}) == 1)


async def main():
    await cleanup()
    try:
        await test_scrim()
        await test_weekly()
        await test_achievements()
        await test_card()
        await test_concurrency()
    finally:
        await cleanup()
        print("\n테스트 DB 정리 완료")

    print(f"\n{'=' * 50}")
    print(f"통과 {len(PASS)} / 실패 {len(FAIL)}")
    if FAIL:
        print("실패 목록:")
        for f in FAIL:
            print(f"  - {f}")
        sys.exit(1)
    print("전부 통과 ✅")


asyncio.run(main())
