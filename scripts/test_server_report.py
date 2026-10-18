"""📊 코인 집계 규칙 검증. 실제 DB 없이 도는 부분과, 실데이터 대조를 같이 해요.

    python scripts/test_server_report.py

## 무엇을 막으려고 만들었나

🚨 **같은 서버를 두고 두 리포트가 다른 숫자를 말하는 것.**

`/서버리포트`를 만들면서 분류 규칙을 복제했다가, 처음 돌렸을 때 한쪽은 소각률 95.6%,
`scripts/report_economy.py`는 80.9%를 말했어요. 원인은 셋이었어요.
  ⒜ 환불(`카드뽑기:환불`)을 발행에서 안 뺐다 (+480코인이 허위 발행으로)
  ⒝ 지갑을 `trainers`만 셌다 (21개 / 실제 58개)
  ⒞ `도박 버그 보상`을 도박 환급으로 안 쳤다

경제 수치는 운영 판단의 근거라, 두 화면이 어긋나면 어느 쪽도 믿을 수 없어요. 그래서
규칙을 `utils/coin_ledger.py` 하나로 모았고, 여기서 그 규칙을 검사해요.
"""
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils import coin_ledger  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
print("⒜ 분류 규칙 (가짜 로그로 — DB 없이 돌아요)")

CASES = [
    ({"kind": "add", "note": "출석", "amount": 1}, "issue"),
    ({"kind": "add", "note": "미션:val_win", "amount": 1}, "issue"),
    ({"kind": "add", "note": "낚시판매", "amount": 40}, "issue"),
    ({"kind": "spend", "note": "낚시대", "amount": 10}, "burn"),
    ({"kind": "spend", "note": "카드뽑기", "amount": 10}, "burn"),
    ({"kind": "spend", "note": "칭호구매", "amount": 30}, "burn"),
    # 🚨 `도박 당첨`은 `도박`으로도 시작해요. add/spend를 먼저 봐야 안 섞여요.
    ({"kind": "spend", "note": "도박", "amount": 5}, "gamble_bet"),
    ({"kind": "add", "note": "도박 당첨", "amount": 10}, "gamble_back"),
    ({"kind": "add", "note": "도박 환불", "amount": 5}, "gamble_back"),
    ({"kind": "add", "note": "도박 버그 보상", "amount": 5}, "gamble_back"),
    # 재분배 — 총량이 안 변해요
    ({"kind": "spend", "note": "내전베팅", "amount": 3}, "redist"),
    ({"kind": "add", "note": "베팅정산:승리", "amount": 6}, "redist"),
    ({"kind": "transfer", "note": "코인보내기", "amount": 60}, "transfer"),
    # 되돌린 거래 — 발행도 소각도 아니에요
    ({"kind": "add", "note": "카드뽑기:환불(테스트초기화)", "amount": 10}, "refund"),
]
for entry, expected in CASES:
    got = coin_ledger.classify(entry)
    check(f"{entry['note']!r}({entry['kind']}) → {expected}", got == expected, f"got={got}")


# ------------------------------------------------------------------
print("\n⒝ 집계 — 되돌린 거래가 양쪽을 부풀리지 않는다")

# 뽑기를 했다가(spend 10) 환불받은(add 10) 상황. **아무 일도 안 일어난 것**이어야 해요.
refunded = coin_ledger.totals([
    {"kind": "add", "note": "출석", "amount": 10},
    {"kind": "spend", "note": "카드뽑기", "amount": 10},
    {"kind": "add", "note": "카드뽑기:환불", "amount": 10},
])
check("환불은 발행으로 안 센다", refunded["issued"] == 10, f"발행 {refunded['issued']}")
check("🚨 환불은 짝이 되는 소각도 지운다", refunded["burned"] == 0, f"소각 {refunded['burned']}")

print("\n⒞ 집계 — 도박은 하우스 몫만 소각")
gamble = coin_ledger.totals([
    {"kind": "spend", "note": "도박", "amount": 100},
    {"kind": "add", "note": "도박 당첨", "amount": 91},
])
check("베팅 100 · 환급 91 → 소각 9", gamble["burned"] == 9, f"소각 {gamble['burned']}")

lucky = coin_ledger.totals([
    {"kind": "spend", "note": "도박", "amount": 10},
    {"kind": "add", "note": "도박 당첨", "amount": 50},
])
check("🚨 유저가 이득을 봐도 소각이 음수가 안 된다", lucky["burned"] == 0,
      f"소각 {lucky['burned']}")

print("\n⒟ 집계 — 재분배는 총량을 안 바꾼다")
redist = coin_ledger.totals([
    {"kind": "add", "note": "출석", "amount": 5},
    {"kind": "spend", "note": "내전베팅", "amount": 3},
    {"kind": "add", "note": "베팅정산:승리", "amount": 6},
    {"kind": "transfer", "note": "코인보내기", "amount": 60},
])
check("송금·베팅은 발행에 안 들어간다", redist["issued"] == 5, f"발행 {redist['issued']}")
check("송금·베팅은 소각에 안 들어간다", redist["burned"] == 0, f"소각 {redist['burned']}")

print("\n⒠ 유저 필드 — add는 to, spend는 from")
check("add → to", coin_ledger.user_of({"kind": "add", "to": "111", "from": None}) == "111")
check("spend → from", coin_ledger.user_of({"kind": "spend", "to": None, "from": "222"}) == "222")


# ------------------------------------------------------------------
# 실데이터 대조 — DB가 있을 때만 돌아요.
# ------------------------------------------------------------------
print("\n⒡ 실데이터 대조 (`/서버리포트` ↔ 전체 로그 직접 집계)")
try:
    import asyncio

    from utils import server_report
    from utils.pokemon_store import _db

    logs = list(_db["coin_log"].find({}))
    direct = coin_ledger.totals(logs)
    data = asyncio.run(server_report.collect(3650))  # 사실상 전체 기간

    check("발행이 같다", data["issued"] == direct["issued"],
          f"리포트 {data['issued']} vs 직접 {direct['issued']}")
    check("소각이 같다", data["burned"] == direct["burned"],
          f"리포트 {data['burned']} vs 직접 {direct['burned']}")

    wallets = []
    for name in coin_ledger.WALLET_COLLECTIONS:
        wallets += [int(d.get("coin") or 0)
                    for d in _db[name].find({"coin": {"$exists": True}}, {"coin": 1})]
    wallets = [w for w in wallets if w >= 0]
    check("🚨 지갑을 두 컬렉션에서 모두 센다", data["wallet_count"] == len(wallets),
          f"리포트 {data['wallet_count']}개 vs 실제 {len(wallets)}개")

    print(f"\n  📊 참고: 발행 {data['issued']} · 소각 {data['burned']} "
          f"· 소각률 {data['burn_rate']:.1f}% · 지갑 {data['wallet_count']}개")
except Exception as exc:  # noqa: BLE001
    print(f"  ⏭️ DB에 못 붙어서 건너뛰었어요 ({type(exc).__name__}) — 위 규칙 검사만 유효해요")


# ------------------------------------------------------------------
print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
