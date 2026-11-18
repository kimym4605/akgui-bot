"""🧊 보호권을 '출석 후'에 사서 못 쓴 사람의 연속 출석을 되돌려요. (일회성 보정)

2026-11-05에 서아(`1274597436689743964`)가 신고해서 만들었어요.

    11-03 12:08  출석 +2      ← 연속 15일
    11-04        ❌ 빠짐
    11-05 07:35  출석 +1      ← 보호권 0개 → 연속 1로 초기화
    11-05 07:36  출석보호권 구매 -5   ← **1분 늦게** 샀다

🚨 코드 버그가 아니에요. `attend_service.attend()`는 출석 처리 **직전에** 인벤토리를
차감하므로(같은 파일 189~195줄), 출석을 누른 뒤에 산 보호권은 쓰일 수가 없어요.
연속이 끊긴 걸 **보고 나서** 사는 게 사람에게는 자연스러운 순서라서 생긴 일이에요.

그래서 "미리 사뒀다면 어땠을까"와 똑같은 상태로 되돌려요:
  ⒜ 보호권 1장 차감 (공짜로 살려주면 안 돼요 — 5코인은 이미 냈고 그게 값이에요)
  ⒝ 연속을 목표값으로 복구
  ⒞ 못 받은 연속 보너스 코인을 `출석:보정`으로 지급

    python scripts/restore_streak_protect_late_buy.py          # 미리보기만
    python scripts/restore_streak_protect_late_buy.py --apply  # 실제로 고침

🚨 가드가 전부 맞을 때만 씁니다. 하나라도 어긋나면(이미 고쳤거나 그 사이 출석이
   더 쌓였거나) 아무것도 안 하고 멈춰요.
"""

import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils.attend_service import streak_bonus, weekly_bonus  # noqa: E402
from utils.inventory_store import PROTECT_KEY  # noqa: E402
from utils.pokemon_store import COIN_PER_ATTENDANCE, _db, _trainers  # noqa: E402

# (유저ID, 오늘 날짜, 끊기기 직전 연속일, 그날 실제로 받은 코인)
TARGETS = [
    ("1274597436689743964", "2026-11-05", 15, 1),   # 서아
]

APPLY = "--apply" in sys.argv


def main() -> int:
    inventory = _db["inventory"]
    coin_log = _db["coin_log"]
    failed = 0

    for uid, today, prev_streak, got_coin in TARGETS:
        print(f"===== {uid} =====")
        tr = _trainers.find_one({"_id": uid}) or {}
        inv = inventory.find_one({"_id": uid}) or {}
        cur_streak = int(tr.get("attendanceStreak") or 0)
        tickets = int(inv.get(PROTECT_KEY) or 0)
        print(f"  [전] 연속 {cur_streak}일 · 마지막출석 {tr.get('lastAttendanceDate')} "
              f"· 지갑 {tr.get('coin')}코인 · 보호권 {tickets}장")

        target = prev_streak + 1          # 빠진 날을 보호하고 오늘 출석 → +1
        should_get = COIN_PER_ATTENDANCE + streak_bonus(target) + weekly_bonus(target)
        owed = should_get - got_coin
        print(f"  [목표] 연속 {target}일 · 그날 받아야 했던 코인 {should_get} "
              f"(실제 {got_coin}) → 보정 {owed:+d}코인")

        # 🚨 가드 — 내가 본 상태 그대로일 때만 손댄다
        problems = []
        if tr.get("lastAttendanceDate") != today:
            problems.append(f"마지막 출석일이 {today}가 아니다({tr.get('lastAttendanceDate')})")
        if cur_streak != 1:
            problems.append(f"연속이 1이 아니다({cur_streak}) — 이미 보정했을 수 있다")
        if tickets < 1:
            problems.append("보호권이 없다")
        if owed < 0:
            problems.append(f"이미 더 받았다({owed})")
        if problems:
            print("  🚨 건너뜀 — " + " · ".join(problems))
            failed += 1
            continue

        if not APPLY:
            print("  (미리보기 — 실제로 고치려면 --apply)")
            continue

        # ⒜ 보호권 차감 → ⒝ 연속 복구 → ⒞ 코인 보정
        r1 = inventory.update_one({"_id": uid, PROTECT_KEY: {"$gte": 1}},
                                  {"$inc": {PROTECT_KEY: -1}})
        r2 = _trainers.update_one({"_id": uid, "attendanceStreak": cur_streak,
                                   "lastAttendanceDate": today},
                                  {"$set": {"attendanceStreak": target}})
        if owed:
            _trainers.update_one({"_id": uid}, {"$inc": {"coin": owed}})
            coin_log.insert_one({"kind": "add", "from": None, "to": uid,
                                 "amount": owed, "note": "출석:보정"})

        # 🚨 "저장됐다"를 믿지 말고 다시 읽어서 확인한다
        tr2 = _trainers.find_one({"_id": uid}) or {}
        inv2 = inventory.find_one({"_id": uid}) or {}
        print(f"  [후] 연속 {tr2.get('attendanceStreak')}일 · 지갑 {tr2.get('coin')}코인 "
              f"· 보호권 {inv2.get(PROTECT_KEY)}장 (수정 {r1.modified_count}/{r2.modified_count})")
        ok = (int(tr2.get("attendanceStreak") or 0) == target
              and int(inv2.get(PROTECT_KEY) or 0) == tickets - 1
              and int(tr2.get("coin") or 0) == int(tr.get("coin") or 0) + owed)
        print("  " + ("✅ 복구 완료" if ok else "🚨 기대와 다르다"))
        if not ok:
            failed += 1

    print()
    print(f"실패/건너뜀 {failed}건")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
