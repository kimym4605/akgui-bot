"""'자리잡고 못 한다'가 데이터에 보이나. 읽기 전용."""
import os, sys, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR); os.chdir(BOT_DIR)
from dotenv import load_dotenv
load_dotenv(os.path.join(BOT_DIR, ".env"))
from utils.pokemon_store import _db
from utils import fish_data as fd
from utils.coin_ledger import CURRENT_WALLET, WALLET_COLLECTIONS, kst_of

KST = timezone(timedelta(hours=9))
d0 = datetime.now(KST).date()
today = d0.isoformat()

wallets = {}
for name in WALLET_COLLECTIONS:
    for d in _db[name].find({"coin": {"$exists": True}}, {"coin": 1}):
        u = str(d["_id"])
        if name == CURRENT_WALLET or u not in wallets:
            wallets[u] = int(d.get("coin") or 0)

fish = list(_db["fish"].find({}))
print(f"=== 🎣 낚시 기록이 있는 사람 {len(fish)}명 / 지갑 {len(wallets)}개 ===\n")

print("[1] 낚시대 재고가 남아 있는데 '마지막으로 던진 날'이 오래된 사람")
print("    (= 사두고 못 하고 있다는 신호)")
stale = []
for d in fish:
    rod = int(d.get("rod") or 0)
    last = d.get("cast_date")
    if rod <= 0:
        continue
    gap = (d0 - datetime.fromisoformat(last).date()).days if last else 999
    stale.append((gap, rod, str(d["_id"])[-5:], last or "기록없음"))
stale.sort(reverse=True)
for gap, rod, uid, last in stale:
    tag = "  ← 🔴 오래 묵었다" if gap >= 2 else ""
    print(f"  …{uid}  재고 {rod:4d}회 · 마지막 {last} ({gap}일 전){tag}")
if not stale:
    print("  (재고 있는 사람 없음)")

print("\n[2] 낚시판매 기록으로 본 '활동일 수'와 하루 캐스트")
# coin_log 의 낚시판매로 '그 사람이 낚시한 날'을 셈
sell_days = defaultdict(set)
# 🚨 `coin_log`엔 시각 필드가 없어요 — `kst_of`는 **ObjectId**를 받아요(문서가 아니에요).
for l in _db["coin_log"].find({"note": "낚시판매"}, {"to": 1}):
    uid = str(l.get("to") or "")
    if uid:
        sell_days[uid].add(kst_of(l["_id"]).date())

rows = []
for d in fish:
    uid = str(d["_id"])
    casts = int(d.get("casts") or 0)
    days = len(sell_days.get(uid, ()))
    if casts:
        rows.append((casts / days if days else casts, casts, days, uid))
rows.sort(reverse=True)
print(f"  {'판매일당캐스트':>14} {'누적캐스트':>10} {'판매한날수':>10}")
for per, casts, days, uid in rows:
    flag = ""
    if days and per > fd.DAILY_CAST_CAP * 1.5:
        flag = "  ← 하루 상한보다 많음(여러 날 모아 판 것)"
    print(f"  {per:>14.1f} {casts:>10} {days:>10}{flag}")

print("\n[3] 코인은 있는데 낚시를 아예 안 해본 사람")
never = [u for u, c in wallets.items()
         if c >= fd.SMALL_ROD_PRICE and not any(str(d["_id"]) == u for d in fish)]
print(f"  🪝 소형({fd.SMALL_ROD_PRICE}코인)을 살 수 있는데 낚시 기록 0: **{len(never)}명**")

print("\n[4] 한 판에 걸리는 시간 (코드 상수)")
print(f"  입질 대기 {fd.__name__ and ''}{2.0}~{8.0}초 + 챔질 대기 {6.0}초")
print(f"  → 1판 최소 ~{2.0+1:.0f}초 · 평균 ~{(2.0+8.0)/2 + 2:.0f}초 · 최대 {8.0+6.0:.0f}초")
print(f"  → 하루 {fd.DAILY_CAST_CAP}번을 다 쓰려면 **순수 대기만 "
      f"{fd.DAILY_CAST_CAP * ((2.0+8.0)/2 + 2) / 60:.1f}분** + 클릭 "
      f"{fd.DAILY_CAST_CAP * 2}회")
print(f"  → 7차 보너스 최대({fd.DAILY_CAST_CAP + fd.STREAK_CAST_MAX}번)면 "
      f"**{(fd.DAILY_CAST_CAP + fd.STREAK_CAST_MAX) * ((2.0+8.0)/2 + 2) / 60:.1f}분**")

print("\n[5] 챔질 미스율 (일괄 낚시가 없애버리는 '세금')")
tot_c = sum(int(d.get("casts") or 0) for d in fish)
tot_g = sum(int(d.get("caught") or 0) for d in fish)
print(f"  전체 {tot_c}캐스트 중 {tot_g}마리 = 미스 {(1 - tot_g/tot_c)*100:.1f}%"
      if tot_c else "  (기록 없음)")
