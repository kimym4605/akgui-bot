"""악귀코인 경제 + 미션/출석 현황 리포트 (읽기 전용). 운영 DB를 그대로 읽어요.

2026-10-05에 만들었어요. 그날 하루에 **발행(출석 연속 보너스)과 소비(상점 3종)를 동시에**
늘려놔서, 균형이 어느 쪽으로 기우는지 1~2주 뒤에 반드시 다시 재야 하거든요. 그때 쿼리를
새로 짜면 기준이 매번 달라져서, 아예 스크립트로 박아둬요.

    python scripts/report_economy.py

## 읽는 법

- **지급 vs 소비**: 소비가 지급의 20%도 안 되면 코인이 쌓이기만 하는 거예요. 그때는
  소비처를 더 만들기 전에 `attend_service.STREAK_BONUS_TIERS`·`WEEKLY_BONUS_COIN`부터
  낮추는 게 맞아요(발행을 줄이는 쪽이 확실해요).
- 🚨 **`coin_log`의 kind만 보고 세면 양쪽이 다 부풀어요.** 돈이 오가는 기능은 `spend`로
  나갔다가 `add`로 돌아오기 때문에, **차액만** 발행/소각이에요. 2026-10-06에 이걸 안 빼서
  소각률을 17.5%로 읽었는데 실제로는 6.4%였어요(도박 베팅 148코인 중 121코인이 당첨금으로
  돌아왔는데 그게 '소각 148 + 발행 121'로 이중 계상됐어요). 그래서 아래 세 갈래로 나눠요:
    - **발행/소각**: 출석·미션·업적(add) vs 칭호·리롤권·보호권·테마(spend) ← 이것만 총량을 바꿔요
    - **재분배**: `내전베팅`(spend) ↔ `베팅정산:*`(add). 파리뮤추얼이라 **총량 불변** → 양쪽 다 제외
    - **도박**: `도박`(spend) ↔ `도박 당첨`·`도박 환불`(add). **차액(하우스 몫)만 소각**
- 🚨 **카드 테마는 유한한 소비처예요**(6종 × 15 = 90코인이면 소진). 반복되는 소각은
  칭호 유지·미션 리롤·도박 하우스 몫·🔓 한도 연장권뿐이라 장기 균형은 그것들이 결정해요.
- 🚨 **도박은 소각 속도가 느려요.** 엣지가 ~9%라 148코인이 돌아도 27코인만 사라져요.
  "많이 쓴다"와 "많이 태운다"는 다른 얘기라, 베팅총액이 아니라 **순소각**을 보세요.
  그래서 2026-10-06에 **🔓 한도 연장권**(`한도연장`, 5코인)을 붙였어요 — 이쪽은 엣지를
  거치지 않고 **전액이 바로 사라져요**. 도박을 하는 사람이 늘수록 같이 늘어나요.
- **미션**: `val_*`가 발로란트 자동판정 대상이에요. 2026-10-05 05:33에 429를 고쳤어요
  (2026-10-06 로그로 429·조회실패 0건 / 30분 루프 무중단 확인 — 기술적으론 해결됐어요).
  남은 건 완료율인데, 발로 미션 완료는 17~01시에 몰려서 **아침에 재야** 하루치가 잡혀요.
- ⚠️ **`coin_log`의 유저 필드는 kind에 따라 달라요.** `add`는 `to`, `spend`는 `from`이에요.
  한쪽만 보면 "이용자 1명"처럼 나와요(실제로는 9명이었어요).
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

# 🚨 분류 규칙은 `utils/coin_ledger.py` 한 곳에만 둬요.
#    `/서버리포트`(cogs/ops_report.py)도 같은 모듈을 써요 — 규칙을 복제했더니 두 리포트가
#    다른 소각률을 말하는 일이 실제로 있었어요(2026-10-18). 여기를 고치지 말고 거기를 고치세요.
from utils.coin_ledger import (  # noqa: E402
    GAMBLE_ADD, GAMBLE_SPEND, REDIST_ADD, REDIST_SPEND, REFUND_ADD,
    classify, kst_of, wallet_balances,
)

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()



def bar(n, scale=1):
    return "█" * min(40, int(n / scale))


print("=" * 72)
print(f"악귀 경제 리포트 — {datetime.now(KST):%Y-%m-%d %H:%M} KST")
print("=" * 72)

# ── 1. 코인 지급 vs 소비 ────────────────────────────────────────────
logs = list(_db["coin_log"].find({}, {"kind": 1, "amount": 1, "note": 1, "to": 1, "from": 1}))
for entry in logs:
    entry["cls"] = classify(entry)


def total(cls, rows=None):
    return sum(l["amount"] for l in (rows or logs) if l["cls"] == cls)


def rows_of(cls, rows=None):
    return [l for l in (rows or logs) if l["cls"] == cls]


issued = total("issue")
# 환불된 만큼은 실제로 안 사라졌어요(같은 금액의 spend가 burn으로 잡혀 있어요).
refunded = total("refund")
burned = total("burn") - refunded
bet, back = total("gamble_bet"), total("gamble_back")
house = bet - back                      # 도박에서 실제로 사라진 코인
net_burn = burned + house

print(f"\n[1] 코인 흐름 (전체 기간, 기록 {len(logs)}건)")
print(f"  발행       {len(rows_of('issue')):4d}건 / {issued:5d}코인   (출석·미션·업적)")
print(f"  소각       {len(rows_of('burn')):4d}건 / {burned:5d}코인   (칭호·리롤권·보호권·테마)")
print(f"  도박       {len(rows_of('gamble_bet')):4d}판 / 베팅 {bet}코인 → 환급 {back}코인 "
      f"→ **순소각 {house}코인** (실측 하우스몫 {house / max(bet, 1) * 100:.0f}%)")
print(f"  내전베팅   {len(rows_of('redist')):4d}건 / {total('redist'):5d}코인   "
      "(파리뮤추얼 = 재분배, 총량 불변이라 양쪽에서 제외)")
# 🎪 장터·개인 송금도 유저끼리 주고받는 거라 총량이 안 바뀌어요.
_tr = rows_of("transfer")
# 🚨 2026-10-18에 note가 `장터:` → `거래:`로 바뀌었어요(공개 장터 → 지목 거래).
#    옛 기록이 `장터:`로 남아있어서 **둘 다** 봐야 과거 거래가 안 사라져요.
_market = [l for l in _tr if (l["note"] or "").startswith(("장터", "거래"))]
print(f"  송금·장터   {len(_tr):4d}건 / {total('transfer'):5d}코인   "
      f"(유저 간 이동 = 재분배 · 그중 장터 {len(_market)}건 "
      f"{sum(l['amount'] for l in _market)}코인)")
print(f"  ─────────────────────────────────────────")
print(f"  순소각     {net_burn}코인 / 발행 {issued}코인 → **소각률 {net_burn / max(issued, 1) * 100:.1f}%**")
print("             ← 20% 아래면 소비처를 더 만들기보다 발행을 줄이는 쪽을 먼저 검토")

print("\n  소각·소비처별 (spend 기준, 실제 사라진 양은 도박만 다름):")
spend = [l for l in logs if l["kind"] == "spend"]
for note, count in Counter(l["note"] for l in spend).most_common():
    rows = [l for l in spend if l["note"] == note]
    amount = sum(l["amount"] for l in rows)
    users = len({l.get("from") for l in rows})          # ⚠️ spend는 from이 유저예요
    cls = rows[0]["cls"]
    tag = {"redist": "  (재분배 — 소각 아님)",
           "gamble_bet": f"  (환급 {back} 제외하면 실소각 {house})"}.get(cls, "")
    print(f"    {note:16s} {count:3d}건 / {amount:4d}코인 / {users:2d}명{tag}")

# 🚨 발행이 어디서 오는지. 🎣 낚시는 **하루 상한이 없어서**(2026-10-17 설계) 여기가
#    빠르게 커질 수 있어요. 출석·미션을 합친 것보다 커지면 과열 신호고, 그때 제일 먼저
#    만질 손잡이는 `utils/fish_data.MISS_RATE`예요.
print("\n  발행이 어디서 오는지 (add 기준):")
_issue = [l for l in logs if l["cls"] == "issue"]
for note, count in Counter(
        (l["note"] or "기타").split(":")[0] for l in _issue).most_common():
    rows = [l for l in _issue if (l["note"] or "기타").split(":")[0] == note]
    amount = sum(l["amount"] for l in rows)
    users = len({l.get("to") for l in rows})       # ⚠️ add는 to가 유저예요
    share = amount / max(issued, 1) * 100
    flag = "   ← 🎣 낚시대값(소각)을 빼면 순발행이에요. 줄이려면 ROD_PRICE를 올리세요" if note == "낚시판매" else ""
    print(f"    {note:16s} {count:4d}건 / {amount:5d}코인 / {users:2d}명 "
          f"({share:4.1f}%){flag}")

print("\n  소비처가 실제로 쓰이는지:")
for key, label in [("미션리롤", "🎲 미션 리롤권"), ("출석보호권", "🧊 출석 보호권"),
                   ("카드테마", "🎨 카드 테마"), ("칭호구매", "🏷️ 칭호"), ("도박", "🎰 도박"),
                   ("한도연장", "🔓 하루 한도 연장"), ("베팅한도연장", "🎲 1회 한도 연장"),
                   ("카드뽑기", "🎴 카드 뽑기"), ("낚시대", "🎣 낚시대")]:
    rows = [l for l in spend if (l["note"] or "").startswith(key)]
    users = len({l.get("from") for l in rows})
    flag = "" if rows else "   ← 0건. 구매력 문제인지 발견 문제인지 [3]과 함께 보세요"
    print(f"    {label:16s} {len(rows):3d}건 / {sum(l['amount'] for l in rows):4d}코인 / {users:2d}명{flag}")

# ── 2. 최근 7일 발행/소각 추이 ──────────────────────────────────────
print("\n[2] 최근 7일 흐름 — 순증이 +면 코인이 쌓이는 중이에요")
print("    (도박은 베팅총액이 아니라 하우스 몫만 소각으로 넣었어요)")
daily = defaultdict(lambda: defaultdict(int))
for l in logs:
    day = kst_of(l["_id"]).date()
    if (TODAY - day).days > 6:
        continue
    daily[day][l["cls"]] += l["amount"]
print(f"  {'날짜':12s}{'발행':>6s}{'소각':>6s}{'도박순소각':>11s}{'순증':>8s}")
for day in sorted(daily):
    r = daily[day]
    gh = r["gamble_bet"] - r["gamble_back"]
    # 환불된 뽑기는 소각에서 빼요(위 [1]과 같은 이유 — 아예 없던 일이에요).
    day_burn = r["burn"] - r["refund"]
    net = r["issue"] - day_burn - gh
    print(f"  {day}  {r['issue']:6d}{day_burn:6d}{gh:11d}{net:+8d}  {bar(max(net, 0), 2)}")

# ── 3. 지갑 분포 ────────────────────────────────────────────────────
#
# 🚨 **유저별로 합치지 않으면 지갑이 두 번 세어져요.** 2026-10-18까지 두 컬렉션을
#    그냥 이어붙여서, 양쪽에 다 있는 **10명이 중복**됐어요(`trainers` 21 + `backup` 37
#    = 58인데 고유 유저는 **48명**). 중복된 쪽은 백업 잔액이 거의 0이라 **중앙값이
#    5.5인데 3.5로 낮게** 보였어요 — "중앙값이 안 움직인다"는 진단의 일부가 측정 탓이었어요.
# ⚠️ 같은 유저가 양쪽에 있으면 `trainers`가 **현재값**이에요(backup은 리셋 전 스냅샷).
# 규칙은 `utils/coin_ledger.py` 하나뿐이에요 — 여기서 다시 짜면 또 갈려요.
balances = wallet_balances(_db)
if balances:
    print(f"\n[3] 지갑 {len(balances)}개 / 총 {sum(balances)}코인  (유저별 중복 제거)")
    print(f"  최대 {max(balances)} · 중앙값 {statistics.median(balances):.1f} · 평균 {sum(balances)/len(balances):.1f}")
    for t in (5, 12, 15, 30):
        print(f"  {t:2d}코인 이상: {sum(1 for b in balances if b >= t):2d}명")

    # 🚨 **집중도.** 총량이 회복돼도 한 사람이 다 갖고 있으면 아무 의미가 없어요.
    top = sorted(balances, reverse=True)
    total = sum(balances) or 1
    print("  집중도: "
          + " · ".join(f"상위{n}명 {sum(top[:n]) / total * 100:.0f}%" for n in (1, 3, 5)))

    # 🎣 낚시는 발행의 70%가 넘는데, 진입에 낚시대값이 필요해요. **중앙값 지갑으로
    #    살 수 없으면 최대 발행원에 아예 못 들어가요**(부익부가 구조로 굳어요).
    #
    # 🚨 **진입 기준은 `SMALL_ROD_PRICE`예요**(2026-10-20에 고침). 2026-10-18에
    #    🪝소형(3코인)이 나왔는데 이 지표가 계속 10코인으로 재서 **진입 장벽을 과대
    #    평가**했어요(10-19에 "30명 62%"로 찍혔는데 실제로 못 들어가는 건 그보다 적어요).
    #    큰 낚시대 기준도 같이 보여줘요 — 둘의 간격이 소형이 메우는 몫이에요.
    from utils.fish_data import DAILY_CAST_CAP, ROD_PRICE, SMALL_ROD_PRICE
    poor = sum(1 for b in balances if b < SMALL_ROD_PRICE)
    poor_big = sum(1 for b in balances if b < ROD_PRICE)
    print(f"  🎣 낚시를 **아예 못 하는** 사람: {poor}명 "
          f"({poor / len(balances) * 100:.0f}%) — 🪝소형({SMALL_ROD_PRICE}코인)도 못 삼"
          + ("   ← 최대 발행원에 진입 못 함" if poor > len(balances) / 2 else ""))
    print(f"     └ 큰 낚시대({ROD_PRICE}코인)를 못 사는 사람: {poor_big}명 "
          f"({poor_big / len(balances) * 100:.0f}%) "
          f"— 이 중 {poor_big - poor}명은 소형으로 시작할 수 있어요")

    # ⏳ 하루 상한(2026-10-20 6차)이 생겨서 **1인 발행에 천장이 있어요.** 이제
    #    "며칠이면 따라잡나"를 셀 수 있어요 — 전엔 시간이 유일한 상한이라 불가능했어요.
    if DAILY_CAST_CAP:
        from utils.fish_data import max_daily_net_issue
        cap_net = max_daily_net_issue()
        med = statistics.median(balances)
        print(f"  ⏳ 낚시 하루 상한 {DAILY_CAST_CAP}회 = 1인 최대 순발행 "
              f"{cap_net:+.1f}코인/일")
        if cap_net > 0:
            print(f"     └ 중앙값({med:.1f}코인)인 사람이 상위권(최대 {max(balances)}코인)을 "
                  f"따라잡는 데 {(max(balances) - med) / cap_net:.0f}일")

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

# `missions`는 유저당 문서 1개를 당일로 덮어써요(replace_one). 그래서 완료율은 **오늘치만**
# 구할 수 있어요. 과거는 위 coin_log 건수로 보세요.
today_iso = TODAY.isoformat()
docs = [d for d in _db["missions"].find({}, {"date": 1, "picks": 1, "done": 1})
        if d.get("date") == today_iso]
tally = defaultdict(lambda: [0, 0])     # [배정, 완료]
for d in docs:
    done = set(d.get("done") or [])
    for pick in d.get("picks") or []:
        kind = "발로(자동판정)" if pick.startswith("val_") else "서버(수동)"
        tally[kind][0] += 1
        tally[kind][1] += pick in done
print(f"\n  오늘({today_iso}) 완료율 — {len(docs)}명 배정, {datetime.now(KST):%H시} 현재")
for kind in ("발로(자동판정)", "서버(수동)"):
    picked, done = tally[kind]
    print(f"    {kind:14s} {done:3d}/{picked:3d} = {done / max(picked, 1) * 100:3.0f}%")
picked = sum(v[0] for v in tally.values())
done = sum(v[1] for v in tally.values())
print(f"    {'전체':14s} {done:3d}/{picked:3d} = {done / max(picked, 1) * 100:3.0f}%"
      "   ← 2026-10-05 기준값 14%, 10-06 20시 19%")

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
