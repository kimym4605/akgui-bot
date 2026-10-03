"""내전 맵 기록 + 맵별 성적 회귀 테스트.

    python scripts/test_scrim_map_stats.py

⚠️ 실제 DB를 쓰므로 **테스트 전용 DB 이름**으로 돌려요(MONGODB_DB_NAME 덮어쓰기).
   운영 DB 이름으로 돌리면 실제 내전 전적에 쓰레기 경기가 들어가요.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
# ⚠️ 스토어를 import하기 전에 바꿔야 해요(import 시점에 DB 핸들이 굳어요).
os.environ["MONGODB_DB_NAME"] = "agwi_map_test"

from cogs.achievement import MAP_MARK_MIN_MATCHES, _map_stats_text  # noqa: E402
from utils import scrim_record_store, valorant_maps  # noqa: E402

passed = failed = 0
U1, U2, U3 = 9001, 9002, 9003


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


def by_map(rows):
    return {r["map"]: (r["wins"], r["losses"]) for r in rows}


def map_lines(rows):
    """맵 줄만 돌려줘요. 꼬리 안내문(`-#`)에도 💪/😵 글자가 들어있어서 걸러내야 해요."""
    return [l for l in _map_stats_text(rows).splitlines() if not l.startswith("-#")]


async def main():
    # 이전에 돌린 흔적을 지워요(같은 테스트 DB를 재사용해요).
    scrim_record_store._matches.delete_many({"note": "맵테스트"})
    scrim_record_store._records.delete_many({"userId": {"$in": [str(U1), str(U2), str(U3)]}})

    print("맵을 적어서 기록")
    mid = await scrim_record_store.record_match(
        1, [U1], [U2], note="맵테스트", map_name="어센트"
    )
    check("경기 id를 돌려줌", bool(mid), True)
    doc = scrim_record_store._matches.find_one({"note": "맵테스트"})
    check("맵이 저장됨", doc["map"], "어센트")
    check("통산 승패도 그대로 들어감",
          (await scrim_record_store.get_record(U1))["wins"], 1)

    print("\n맵을 안 적고 기록 (맵은 선택이에요)")
    mid2 = await scrim_record_store.record_match(1, [U1], [U2], note="맵테스트")
    check("맵 없이도 기록됨", bool(mid2), True)
    check("map은 None", scrim_record_store._matches.find_one({"_id": _oid(mid2)})["map"], None)
    check("통산 승패는 2승", (await scrim_record_store.get_record(U1))["wins"], 2)

    print("\n나중에 맵 채워 넣기 (승리 보고 뒤 드롭다운)")
    check("채워넣기 성공", await scrim_record_store.set_match_map(mid2, "바인드"), True)
    check("맵이 들어감", scrim_record_store._matches.find_one({"_id": _oid(mid2)})["map"], "바인드")
    check("없는 경기면 False",
          await scrim_record_store.set_match_map("ffffffffffffffffffffffff", "펄"), False)
    check("망가진 id도 안 터지고 False",
          await scrim_record_store.set_match_map("이건-id-가-아니야", "펄"), False)
    check("None으로 지울 수도 있음", await scrim_record_store.set_match_map(mid2, None), True)
    check("지워짐", scrim_record_store._matches.find_one({"_id": _oid(mid2)})["map"], None)
    await scrim_record_store.set_match_map(mid2, "바인드")  # 다시 채워두고 계속

    print("\n맵별 집계 (map_stats)")
    # 어센트 U1 3승 / 바인드 U1 1승 1패 / 펄 U1 0승 2패
    await scrim_record_store.record_match(1, [U1], [U2], note="맵테스트", map_name="어센트")
    await scrim_record_store.record_match(1, [U1], [U2], note="맵테스트", map_name="어센트")
    await scrim_record_store.record_match(1, [U2], [U1], note="맵테스트", map_name="바인드")
    await scrim_record_store.record_match(1, [U2], [U1], note="맵테스트", map_name="펄")
    await scrim_record_store.record_match(1, [U2], [U1], note="맵테스트", map_name="펄")
    stats = by_map(await scrim_record_store.map_stats(U1))
    check("어센트 3승", stats.get("어센트"), (3, 0))
    check("바인드 1승 1패", stats.get("바인드"), (1, 1))
    check("펄 2패", stats.get("펄"), (0, 2))
    # 어센트 3 + 바인드 2 + 펄 2 = 7판. (맵 없이 기록한 mid2는 위에서 바인드로 채워뒀어요)
    check("맵이 적힌 7판이 다 잡힘", sum(w + l for w, l in stats.values()), 7)
    await scrim_record_store.record_match(1, [U1], [U2], note="맵테스트")  # 맵 없는 1판 추가
    check("맵 안 적힌 경기는 집계에 안 들어감",
          sum(w + l for w, l in by_map(await scrim_record_store.map_stats(U1)).values()), 7)
    check("그래도 통산 승패엔 들어감",
          (await scrim_record_store.get_record(U1))["wins"]
          + (await scrim_record_store.get_record(U1))["losses"], 8)
    check("상대도 반대로 잡힘", by_map(await scrim_record_store.map_stats(U2)).get("어센트"),
          (0, 3))
    check("한 판도 안 한 사람은 빈 목록", await scrim_record_store.map_stats(U3), [])

    print("\n시즌으로 걸러내기")
    season = scrim_record_store.current_season()
    season_stats = by_map(await scrim_record_store.map_stats(U1, season))
    check("현재 시즌엔 다 들어있음", season_stats.get("어센트"), (3, 0))
    check("다른 시즌이면 비어 있음", await scrim_record_store.map_stats(U1, "S99"), [])

    print("\n화면 문구 (_map_stats_text)")
    text = _map_stats_text(await scrim_record_store.map_stats(U1))
    lines = [l for l in text.splitlines() if not l.startswith("-#")]
    check("승률 높은 순 (어센트가 맨 위)", lines[0].startswith("`어센트`"), True)
    check("가장 낮은 맵이 맨 아래", lines[-1].startswith("`펄`"), True)
    check("3판 이상 한 어센트에 💪", "💪" in lines[0], True)
    check("2판뿐인 펄엔 😵가 안 붙음", "😵" in lines[-1], False)
    check("승패가 보임", "**3승 0패**" in text, True)
    check("승률이 보임", "100%" in text, True)
    check("1024자 한도 안", len(text) <= 1024, True)

    print("\n딱지 규칙 (표본이 적으면 안 붙여요)")
    body = "\n".join(map_lines([{"map": "어센트", "wins": 1, "losses": 0}]))
    check("1판이면 💪 없음", "💪" in body, False)
    body = "\n".join(map_lines([{"map": "어센트", "wins": 3, "losses": 0}]))
    check("3판 전승이면 💪", "💪" in body, True)
    check("맵이 하나면 😵 없음", "😵" in body, False)
    body = "\n".join(map_lines([
        {"map": "어센트", "wins": 3, "losses": 0},
        {"map": "펄", "wins": 0, "losses": 3},
    ]))
    check("강점·약점 둘 다 붙음", ("💪" in body, "😵" in body), (True, True))
    body = "\n".join(map_lines([
        {"map": "어센트", "wins": 3, "losses": 0},
        {"map": "펄", "wins": 2, "losses": 1},
    ]))
    check("둘 다 승률 50% 넘으면 😵 안 붙음", "😵" in body, False)
    body = "\n".join(map_lines([
        {"map": "어센트", "wins": 1, "losses": 2},
        {"map": "펄", "wins": 0, "losses": 3},
    ]))
    check("전부 50% 미만이면 💪 안 붙음", "💪" in body, False)
    body = "\n".join(map_lines([
        {"map": "어센트", "wins": 5, "losses": 0},
        {"map": "펄", "wins": 0, "losses": 1},
    ]))
    check("약점 후보가 1판뿐이면 😵 안 붙음", "😵" in body, False)
    check("빈 목록은 '-'", _map_stats_text([]), "-")
    check("0판짜리 줄은 걸러짐",
          _map_stats_text([{"map": "펄", "wins": 0, "losses": 0}]), "-")

    print("\n맵이 많아도 필드 한도를 안 넘어요")
    many = [{"map": m, "wins": 12, "losses": 11} for m in valorant_maps.MAPS]
    check(f"{len(many)}개 맵", len(_map_stats_text(many)) <= 1024, True)
    check("그래도 몇 줄은 남음", len(_map_stats_text(many).splitlines()) >= 5, True)

    print("\n맵 목록 유틸 (valorant_maps)")
    check("로테이션 맵 판정", valorant_maps.is_known("어센트"), True)
    check("빠진 맵은 False", valorant_maps.is_known("옛날맵"), False)
    check("None도 False", valorant_maps.is_known(None), False)
    check("정렬은 목록 순서대로",
          sorted(["펄", "어센트", "바인드"], key=valorant_maps.sort_key),
          ["어센트", "바인드", "펄"])
    check("빠진 맵은 뒤로",
          sorted(["옛날맵", "어센트"], key=valorant_maps.sort_key), ["어센트", "옛날맵"])
    check("/맵추천과 같은 목록을 씀", __import__("cogs.map", fromlist=["MAPS"]).MAPS,
          valorant_maps.MAPS)

    # 뒷정리 — 테스트 DB지만 다음 실행에 섞이지 않게 지워요.
    scrim_record_store._matches.delete_many({"note": "맵테스트"})
    scrim_record_store._records.delete_many({"userId": {"$in": [str(U1), str(U2), str(U3)]}})

    print(f"\n{passed}개 통과, {failed}개 실패")
    return 1 if failed else 0


def _oid(match_id):
    from bson import ObjectId

    return ObjectId(match_id)


sys.exit(asyncio.run(main()))
