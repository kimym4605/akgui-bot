"""출석 덮어쓰기 경쟁조건 재현 테스트. ⚠️ 별도 테스트 DB만 사용(실데이터 무관)."""
import os
import sys

BOT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "악귀봇프로젝트", "discord-bot-starter-py")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import dotenv_values

cfg = dotenv_values(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_URI"] = cfg["MONGODB_URI"]
os.environ["MONGODB_DB_NAME"] = "agwi_race_test"     # ★ 실 DB(pokemon_game) 아님
os.environ["BIRTHDAY_DB_NAME"] = "agwi_race_test"

from utils import pokemon_store, attend_service          # noqa: E402
from datetime import datetime, timedelta, timezone        # noqa: E402

assert pokemon_store._db.name == "agwi_race_test", "테스트 DB가 아니면 중단!"
print(f"사용 DB: {pokemon_store._db.name}  (실 DB 아님 확인)\n")

T = pokemon_store._trainers
KST = timezone(timedelta(hours=9))
YDAY = (datetime.now(KST).date() - timedelta(days=1)).isoformat()
TODAY = datetime.now(KST).date().isoformat()
UID = "999999999999999999"


def setup():
    T.delete_one({"_id": UID})
    T.insert_one({
        "_id": UID, "attendanceStreak": 10, "attendance": 40,
        "lastAttendanceDate": YDAY, "coin": 5,
        "daycare": {"slots": [None, None], "egg": None, "pairTicks": 3},
    })


def scenario(save_fn, label):
    """1) 키우미집이 문서를 읽음 → 2) 그 사이 /출석 → 3) 키우미집이 저장"""
    setup()
    stale = pokemon_store._get_trainer_sync(int(UID))          # 1) 읽음(낡은 스냅샷)
    ok, info = attend_service._attend_trainer_sync(int(UID))   # 2) 그 사이 출석
    assert ok, "출석 자체가 실패하면 테스트 의미 없음"
    daycare = stale.setdefault("daycare", {})
    daycare["pairTicks"] = daycare.get("pairTicks", 0) + 1     # 키우미집이 틱 1 올림
    daycare["voiceSessionStart"] = "2026-09-30T10:00:00+00:00"
    save_fn(stale, daycare)                                    # 3) 저장

    d = T.find_one({"_id": UID})
    kept = d.get("lastAttendanceDate") == TODAY and d.get("attendanceStreak") == 11
    ticked = (d.get("daycare") or {}).get("pairTicks") == 4
    print(f"[{label}]")
    print(f"   출석 결과 : 연속 {d.get('attendanceStreak')} (기대 11) / "
          f"마지막출석 {d.get('lastAttendanceDate')} (기대 {TODAY}) -> "
          f"{'OK 살아남음' if kept else 'X 날아감'}")
    print(f"   키우미집  : pairTicks {(d.get('daycare') or {}).get('pairTicks')} (기대 4) -> "
          f"{'OK 반영됨' if ticked else 'X 반영 안 됨'}")
    return kept, ticked


print("=" * 72)
old_kept, old_tick = scenario(
    lambda trainer, daycare: pokemon_store._save_trainer_sync(int(UID), trainer),
    "고치기 전 방식 (save_trainer = 문서 통째 저장)")
print()
new_kept, new_tick = scenario(
    lambda trainer, daycare: pokemon_store._save_daycare_sync(int(UID), daycare),
    "고친 방식 (save_daycare = daycare 칸만 저장)")
print("=" * 72)

T.delete_one({"_id": UID})
pokemon_store._client.drop_database("agwi_race_test")
print("\n테스트 DB 삭제 완료")

print("\n=== 판정 ===")
print(f"  옛 방식이 출석을 날렸나  : {'예 (버그 재현됨)' if not old_kept else '아니오'}")
print(f"  새 방식이 출석을 지켰나  : {'예 (수정 확인)' if new_kept else '아니오'}")
print(f"  새 방식도 부화 틱은 반영 : {'예' if new_tick else '아니오'}")
print("\n결과:", "성공 - 수정 확인됨" if (not old_kept and new_kept and new_tick) else "★ 재확인 필요")
