"""악귀코인 경제 + 미션/출석 현황 리포트 (읽기 전용). 운영 DB를 그대로 읽어요.

2026-10-05에 만들었어요. 그날 하루에 **발행(출석 연속 보너스)과 소비(상점 3종)를 동시에**
늘려놔서, 균형이 어느 쪽으로 기우는지 1~2주 뒤에 반드시 다시 재야 하거든요. 그때 쿼리를
새로 짜면 기준이 매번 달라져서, 아예 스크립트로 박아둬요.

    python scripts/report_economy.py

## 읽는 법

- **지급 vs 소비**: 소비가 지급의 20%도 안 되면 코인이 쌓이기만 하는 거예요. 그때는
  소비처를 더 만들기 전에 `attend_service.STREAK_BONUS_TIERS`·`WEEKLY_BONUS_COIN`부터
  낮추는 게 맞아요(발행을 줄이는 쪽이 확실해요).
- 🚨 **내전베팅은 소비가 아니에요.** 파리뮤추얼이라 진 쪽 판돈이 이긴 쪽으로 **재분배**될
  뿐 코인이 사라지지 않아요. 그래서 '진짜 소각'을 따로 세요.
- 🚨 **카드 테마는 유한한 소비처예요**(6종 × 15 = 90코인이면 소진). 반복되는 소각은
  칭호 유지와 미션 리롤뿐이라, 장기 균형은 그 둘이 결정해요.
- **미션**: `val_*`가 발로란트 자동판정 대상이에요. 2026-10-05 05:33에 429를 고쳤으니
  그 전후를 비교해요. 발로 미션 완료는 17~01시에 몰려서 **아침에 재야** 하루치가 잡혀요.
"""
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils.pokemon_store import _db  # noqa: E402

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()
# 재분배일 뿐 소각이 아닌 항목이에요. 진짜 소각을 셀 때 빼요.
NON_BURN_NOTES = ("내전베팅",)


def kst_of(oid):
    """coin_log에는 시각 필드가 없어요. ObjectId 앞 4바이트에 생성시각이 들어있어요."""
    return oid.generation_time.astimezone(KST)


def bar(n, scale=1):
    return "█" * min(40, int(n / scale))


print("=" * 72)
print(f"악귀 경제 리포트 — {datetime.now(KST):%Y-%m-%d %H:%M} KST")
print("=" * 72)

# ── 1. 코인 지급 vs 소비 ────────────────────────────────────────────
logs = list(_db["coin_log"].find({}, {"kind": 1, "amount": 1, "note": 1}))
add = [l for l in logs if l["kind"] == "add"]
spend = [l for l in logs if l["kind"] == "spend"]
burn = [l for l in spend if not l["note"].startswith(NON_BURN_NOTES)]

print(f"\n[1] 코인 흐름 (전체 기간, 기록 {len(logs)}건)")
print(f"  지급      {len(add):4d}건 / {sum(l['amount'] for l in add):5d}코인")
print(f"  소비      {len(spend):4d}건 / {sum(l['amount'] for l in spend):5d}코인")
print(f"  └ 진짜 소각 {len(burn):3d}건 / {sum(l['amount'] for l in burn):5d}코인"
      "   (내전베팅은 재분배라 제외)")
issued = sum(l["amount"] for l in add) or 1
print(f"  소각률    {sum(l['amount'] for l in burn) / issued * 100:.1f}%  "
      "← 20% 아래면 발행을 줄이는 걸 먼저 검토")

print("\n  소비처별:")
for note, count in Counter(l["note"] for l in spend).most_common():
    amount = sum(l["amount"] for l in spend if l["note"] == note)
    tag = "  (재분배)" if note.startswith(NON_BURN_NOTES) else ""
    print(f"    {note:22s} {count:3d}건 / {amount:4d}코인{tag}")

print("\n  2026-10-05에 만든 소비처:")
for key, label in [("미션리롤", "🎲 미션 리롤권"), ("출석보호권", "🧊 출석 보호권"),
                   ("카드테마", "🎨 카드 테마"), ("칭호구매", "🏷️ 칭호")]:
    rows = [l for l in spend if l["note"].startswith(key)]
    print(f"    {label:16s} {len(rows):3d}건 / {sum(l['amount'] for l in rows):4d}코인")

# ── 2. 최근 7일 지급/소비 추이 ──────────────────────────────────────
print("\n[2] 최근 7일 흐름 (지급 ■ / 소각 □)")
daily = defaultdict(lambda: [0, 0])
for l in logs:
    day = kst_of(l["_id"]).date()
    if (TODAY - day).days > 6:
        continue
    if l["kind"] == "add":
        daily[day][0] += l["amount"]
    elif not l["note"].startswith(NON_BURN_NOTES):
        daily[day][1] += l["amount"]
for day in sorted(daily):
    give, take = daily[day]
    print(f"  {day}  지급 {give:3d} {bar(give, 2)}")
    print(f"              소각 {take:3d} {bar(take, 2)}")

# ── 3. 지갑 분포 ────────────────────────────────────────────────────
balances = []
for col in ("trainers", "coin_reset_backup"):
    balances += [int(d.get("coin") or 0) for d in _db[col].find({"coin": {"$exists": True}}, {"coin": 1})]
balances = sorted(b for b in balances if b >= 0)
if balances:
    print(f"\n[3] 지갑 {len(balances)}개 / 총 {sum(balances)}코인")
    print(f"  최대 {max(balances)} · 중앙값 {statistics.median(balances):.0f} · 평균 {sum(balances)/len(balances):.1f}")
    for t in (5, 12, 15, 30):
        print(f"  {t:2d}코인 이상: {sum(1 for b in balances if b >= t):2d}명")

# ── 4. 미션 완료 (429 수정 효과) ────────────────────────────────────
print("\n[4] 미션 완료 — 발로(자동판정) vs 서버(대조군)")
print("    ⚠️ 발로 미션은 17~01시에 몰려요. 하루치를 보려면 아침에 재세요.")
mission_logs = [l for l in _db["coin_log"].find({"note": {"$regex": "^미션:"}}, {"note": 1, "to": 1})]
by_day = defaultdict(lambda: {"val": 0, "server": 0, "users": set()})
for l in mission_logs:
    day = kst_of(l["_id"]).date().isoformat()
    key = l["note"].split(":", 1)[1]
    by_day[day]["val" if key.startswith("val_") else "server"] += 1
    by_day[day]["users"].add(l["to"])
print(f"  {'날짜':12s} {'발로':>5s} {'서버':>5s} {'인원':>5s}")
for day in sorted(by_day)[-10:]:
    r = by_day[day]
    mark = "  ← 429 수정 이후" if day >= "2026-10-05" else ""
    print(f"  {day:12s} {r['val']:5d} {r['server']:5d} {len(r['users']):5d}{mark}")

# ── 5. 연속 출석 ────────────────────────────────────────────────────
print("\n[5] 연속 출석 (2026-10-05 개편: 보호권·주간/구간 보너스)")
streaks, alive = [], 0
for col in ("trainers", "attendance_guest"):
    for d in _db[col].find({"lastAttendanceDate": {"$exists": True}},
                           {"attendanceStreak": 1, "lastAttendanceDate": 1}):
        s = int(d.get("attendanceStreak") or 0)
        streaks.append(s)
        try:
            gap = (TODAY - datetime.strptime(d["lastAttendanceDate"], "%Y-%m-%d").date()).days
            if gap <= 1:
                alive += 1
        except Exception:  # noqa: BLE001
            pass
if streaks:
    streaks.sort()
    print(f"  기록 {len(streaks)}명 · 중앙값 {statistics.median(streaks):.0f}일 · 최대 {max(streaks)}일")
    print(f"  살아있는 연속(오늘·어제 출석) {alive}명")
    for t in (3, 7, 14, 30, 60):
        print(f"  {t:2d}일 이상: {sum(1 for s in streaks if s >= t):2d}명")
    print(f"  분포: {streaks}")

# ── 6. 보호권 보유 ──────────────────────────────────────────────────
inv = list(_db["inventory"].find({}, {"streak_protect": 1}))
held = sum(int(d.get("streak_protect") or 0) for d in inv)
print(f"\n[6] 🧊 보호권: {len(inv)}명이 보유 중 / 총 {held}장")
themes = list(_db["cosmetics"].find({}, {"themes": 1, "theme": 1}))
owned = sum(len(d.get("themes") or []) for d in themes)
print(f"    🎨 테마: {len(themes)}명이 구매 / 총 {owned}개 보유")
print("\n" + "=" * 72)
