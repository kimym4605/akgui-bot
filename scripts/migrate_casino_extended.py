"""🔓 도박 한도 연장 횟수를 **통산**으로 되살려요 (2026-10-14 일회성).

2026-10-14에 연장권 사양을 바꿨어요: 산 한도는 영구히 남고, 값도 통산 횟수로 올라가요.
문제는 그 전까지 `casino_daily.extended`를 **날짜마다 0으로 덮어썼다**는 거예요. 그래서
DB에는 "마지막으로 도박한 날의 횟수"만 남아 있고, 그 전에 산 연장권은 흔적이 없어요.

다행히 결제 기록은 `coin_log`에 note=`한도연장`으로 전부 남아 있어서, 사람별 통산 횟수를
**역산할 수 있어요**. 그걸로 `extended`를 채워 넣어요.

⚠️ `max(역산값, 지금값)`으로 올려요. 내려가는 경우는 없어야 하니까요(혹시 로그가 유실된
구간이 있으면 지금 값이 더 클 수 있어요 - 그럼 지금 값을 믿어요).

⚠️ 한 번만 돌리면 돼요. 여러 번 돌려도 같은 값이 나와요(멱등).

    python scripts/migrate_casino_extended.py          # 계산만 (dry-run)
    python scripts/migrate_casino_extended.py --apply  # 실제 반영
"""
import os
import sys
from collections import Counter

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils.pokemon_store import _db  # noqa: E402

EXTEND_NOTE = "한도연장"
DAILY_LIMIT = 20
EXTEND_BONUS = 10
EXTEND_BASE_PRICE = 5

apply = "--apply" in sys.argv

casino = _db["casino_daily"]
coin_log = _db["coin_log"]

# 🚨 연장권은 **소비**라 유저 ID가 `from`에 들어가요(`to`는 None). `to`로 세면 0건이 나와요.
bought = Counter()
paid = Counter()      # ⚠️ 실제로 낸 금액. 통산 공식값(5+10+15+…)과 **다를 수 있어요** -
                      #    예전엔 값이 매일 5코인부터 다시 시작했으니까요.
for doc in coin_log.find({"note": EXTEND_NOTE}, {"from": 1, "amount": 1}):
    uid = doc.get("from")
    if uid:
        bought[str(uid)] += 1
        paid[str(uid)] += int(doc.get("amount") or 0)

print(f"coin_log의 '{EXTEND_NOTE}' 결제 기록: {sum(bought.values())}건 / {len(bought)}명\n")

changes = []
for uid, times in sorted(bought.items(), key=lambda kv: -kv[1]):
    doc = casino.find_one({"_id": uid}, {"extended": 1, "date": 1})
    now = int((doc or {}).get("extended") or 0)
    target = max(times, now)
    if target == now:
        print(f"  = {uid}  통산 {times}번 · extended {now} (그대로)")
        continue
    changes.append((uid, now, target, doc is None))
    print(f"  ↑ {uid}  통산 {times}번(실제 {paid[uid]}코인 지출) · extended {now} → {target}"
          f"  한도 {DAILY_LIMIT + EXTEND_BONUS * now} → {DAILY_LIMIT + EXTEND_BONUS * target}"
          f" · 다음 연장 {EXTEND_BASE_PRICE * (now + 1)} → {EXTEND_BASE_PRICE * (target + 1)}코인"
          + ("  (문서 없음 → 새로 만들어요)" if doc is None else ""))

print(f"\n바꿀 사람: {len(changes)}명")
if not changes:
    print("할 일이 없어요.")
    sys.exit(0)

if not apply:
    print("dry-run이에요. 실제로 반영하려면 --apply 를 붙여주세요.")
    sys.exit(0)

for uid, _now, target, missing in changes:
    if missing:
        # ⚠️ 문서가 없으면 **지난 날짜**로 만들어요. 오늘 날짜로 만들면 `wagered`가 0인
        #    오늘 기록이 생기는데, 그건 거짓이에요(오늘 아직 안 걸었어요).
        casino.insert_one({"_id": uid, "date": "2000-01-01", "wagered": 0,
                           "extended": target})
    else:
        casino.update_one({"_id": uid}, {"$set": {"extended": target}})

print("\n반영 끝. 확인:")
for uid, _now, target, _m in changes:
    doc = casino.find_one({"_id": uid}, {"extended": 1, "date": 1, "wagered": 1})
    got = int((doc or {}).get("extended") or 0)
    mark = "✅" if got == target else "❌"
    print(f"  {mark} {uid}  extended={got} (목표 {target}) · 한도 "
          f"{DAILY_LIMIT + EXTEND_BONUS * got}코인 · date={doc.get('date')}")
