"""🎣 낚시 검증. 실제 DB·디스코드 없이 돌아가요.

🚨 낚시는 **코인을 찍어내는** 기능이에요. 확률·가격을 잘못 두면 경제가 바로 기울어요.
그래서 '동작하나'보다 **'얼마나 찍어내나'**를 먼저 재요.

여기서 확인하는 것:
  1) 꽝 확률이 설정(MISS_RATE)과 맞는다
  2) 잡혔을 때 등급 분포가 가중치와 맞는다
  3) 1회 기댓값이 계산식과 실측이 일치한다 (숫자를 바꾸면 여기서 드러나요)
  4) 🚨 발행량 시뮬레이션 - 하루 N번 던지면 얼마가 생기나
  5) 어항에 담기·총액 계산
  6) 🚨 판매는 **비우면서 받아오기**라 그 사이 낚은 물고기가 증발하지 않는다
  7) 판매 실패 시 어항이 되돌아온다
  8) 빈 어항을 팔면 0코인이고 아무 일도 안 일어난다
  9) 어종표 정합성 (등급·가격·중복 key 없음)
 10) coin_log의 note가 '낚시판매'라 발행으로 집계된다
"""
import os
import sys
from collections import Counter
from random import Random

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_fish_test"

from utils import fish_data, fishing_store  # noqa: E402
from utils.fish_data import BY_KEY, FISH, GRADES, MISS_RATE, price_of  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


import cogs.fishing as fishing  # noqa: E402

# ==================================================================
print("\n[1][2][3] 확률과 기댓값")
rng = Random(20261017)
N = 200_000
results = [fishing.roll_catch(rng) for _ in range(N)]
miss = sum(1 for r in results if r is None)
actual_miss = miss / N * 100
check(f"꽝 {MISS_RATE}% 기대", abs(actual_miss - MISS_RATE) < 0.5,
      f"실측 {actual_miss:.2f}%")

hits = [r for r in results if r]
dist = Counter(BY_KEY[k][0] for k in hits)
total_w = sum(g["weight"] for g in GRADES.values())
for grade, g in GRADES.items():
    expected = g["weight"] / total_w * 100
    got = dist[grade] / len(hits) * 100
    check(f"잡혔을 때 {grade} {expected:.1f}%", abs(got - expected) < 1.0,
          f"실측 {got:.2f}%")

coins = sum(price_of(k) for k in hits)
measured = coins / N
formula = fish_data.expected_coin_per_cast()
check("기댓값 계산식과 실측이 일치", abs(measured - formula) < 0.05,
      f"계산 {formula:.3f} vs 실측 {measured:.3f} 코인/회")

# ==================================================================
print("\n[4] 🚨 발행량 — 하루에 얼마가 생기나")
print(f"  1회 평균 {measured:.2f}코인")
for casts, label in [(20, "느긋하게"), (50, "열심히"), (200, "작정하고")]:
    print(f"  {label:8s} 하루 {casts:3d}번 → 약 {measured * casts:6.0f}코인")
print(f"  -# 참고: 2026-10-17 서버 전체 일일 발행이 27~52코인이었어요")
# 느긋한 플레이가 하루 출석(3~5코인)의 10배를 넘으면 출석이 무의미해져요.
check("느긋한 플레이(20회)가 하루 40코인을 안 넘는다",
      measured * 20 <= 40, f"{measured * 20:.0f}코인")

# ==================================================================
print("\n[5][6][7][8] 어항")


class FakeFish:
    def __init__(self):
        self.docs = {}
        self.before_sell = None      # 판매 직전에 끼어들 훅

    def find_one(self, flt, projection=None):
        d = self.docs.get(flt["_id"])
        return dict(d) if d else None

    def update_one(self, flt, update, upsert=False):
        uid = flt["_id"]
        doc = self.docs.get(uid)
        if doc is None:
            if not upsert:
                return
            doc = self.docs[uid] = {"_id": uid}
        for field, delta in (update.get("$inc") or {}).items():
            if "." in field:
                parent, child = field.split(".", 1)
                doc.setdefault(parent, {})
                doc[parent][child] = doc[parent].get(child, 0) + delta
            else:
                doc[field] = doc.get(field, 0) + delta
        for field, value in (update.get("$set") or {}).items():
            doc[field] = value

    def find_one_and_update(self, flt, update, return_document=None):
        if self.before_sell is not None:
            cb, self.before_sell = self.before_sell, None
            cb()
        uid = flt["_id"]
        doc = self.docs.get(uid)
        before = dict(doc) if doc else None
        if doc is not None:
            for field, value in (update.get("$set") or {}).items():
                doc[field] = value
        return before

    def find(self, flt, projection=None):
        class C:
            def __init__(self, rows): self.rows = rows
            def sort(self, *a, **k): return self
            def limit(self, n): self.rows = self.rows[:n]; return self
            def __iter__(self): return iter(self.rows)
        return C([dict(d) for d in self.docs.values()])


fake = FakeFish()
fishing_store._fish = fake
U = "777"

COMMON = FISH["일반"][0]["key"]
LEGEND = FISH["전설"][0]["key"]

import asyncio  # noqa: E402


def run(c):
    return asyncio.run(c)


run(fishing_store.record_cast(U, COMMON))
run(fishing_store.record_cast(U, COMMON))
run(fishing_store.record_cast(U, LEGEND))
run(fishing_store.record_cast(U, None))          # 꽝
data = run(fishing_store.get(U))
check("어항에 담긴다", data["tank"] == {COMMON: 2, LEGEND: 1}, str(data["tank"]))
check("던진 횟수가 센다", data["casts"] == 4, str(data["casts"]))
check("꽝은 잡은 수에 안 들어간다", data["caught"] == 3, str(data["caught"]))
check("최고 기록이 전설로 갱신", (data.get("best") or {}).get("key") == LEGEND)

# 🚨 판매 도중에 물고기를 더 낚아도 **한 마리도 사라지면 안 돼요.**
#
# ⚠️ 여기서 검사할 건 "정확히 몇 마리가 팔렸나"가 아니에요. `find_one_and_update`는
#    원자적이라 **읽기와 쓰기 사이가 없어서**, 끼어든 물고기가 같이 팔리든 남든 둘 다
#    정상이에요. 진짜 불변식은 **판 것 + 남은 것 = 그동안 넣은 것 전부**예요.
#    (처음엔 "끼어든 건 남아야 한다"고 단언했다가 틀렸어요 - 순서를 잘못 가정한 거예요.)
added = {COMMON: 3, LEGEND: 1}          # 앞서 2+1, 아래 훅에서 1 더
fake.before_sell = lambda: run(fishing_store.record_cast(U, COMMON))
tank, coins = run(fishing_store.sell_all(U))
after = run(fishing_store.get(U))

merged = dict(after["tank"])
for k, n in tank.items():
    merged[k] = merged.get(k, 0) + n
check("🚨 판매 중 낚은 물고기가 한 마리도 안 사라진다", merged == added,
      f"판매 {tank} + 남음 {after['tank']} = {merged} (기대 {added})")
check("받은 코인이 판매한 내용과 정확히 일치",
      coins == sum(price_of(k) * n for k, n in tank.items()),
      f"{coins}코인 vs {tank}")

# 역검증: '읽고 나서 비우는' 옛날 방식이면 끼어든 물고기가 증발해요.
def broken_sell(uid):
    doc = fake.find_one({"_id": uid}) or {}
    snapshot = dict(doc.get("tank") or {})
    run(fishing_store.record_cast(uid, COMMON))      # 그 사이에 한 마리 더
    fake.update_one({"_id": uid}, {"$set": {"tank": {}}})
    return snapshot

fake.docs["999"] = {"_id": "999", "tank": {COMMON: 2}}
lost = broken_sell("999")
left = (fake.find_one({"_id": "999"}) or {}).get("tank") or {}
check("(역검증) 읽고-비우기 방식이면 실제로 증발한다",
      sum(lost.values()) + sum(left.values()) < 3,
      f"판매 {lost} + 남음 {left} — 3마리여야 하는데 모자라요")

# 판매 실패 -> 어항 복구 (그 사이 낚은 것과 합쳐져야 해요)
run(fishing_store.restore(U, tank))
restored = run(fishing_store.get(U))
check("실패하면 어항이 되돌아온다",
      restored["tank"] == {COMMON: 3, LEGEND: 1}, str(restored["tank"]))

# 빈 어항
fake.docs["888"] = {"_id": "888", "tank": {}}
tank2, coins2 = run(fishing_store.sell_all("888"))
check("빈 어항은 0코인", coins2 == 0 and not tank2)

# ==================================================================
print("\n[9] 어종표 정합성")
keys = [f["key"] for rows in FISH.values() for f in rows]
check("어종 key가 겹치지 않는다", len(keys) == len(set(keys)), f"{len(keys)}종")
check("모든 등급에 어종이 있다", all(FISH.get(g) for g in GRADES), str(list(GRADES)))
check("BY_KEY가 전부 매핑된다", len(BY_KEY) == len(keys))
check("가격이 등급 순서대로 오른다",
      [GRADES[g]["price"] for g in ("일반", "희귀", "대물", "전설")]
      == sorted(GRADES[g]["price"] for g in GRADES),
      str({g: GRADES[g]["price"] for g in GRADES}))
check("가중치가 등급이 높을수록 작다",
      all(GRADES["일반"]["weight"] > GRADES[g]["weight"]
          for g in ("희귀", "대물", "전설")))

# ==================================================================
print("\n[10] 경제 리포트가 낚시 수입을 발행으로 세는가")
import ast  # noqa: E402
from pathlib import Path  # noqa: E402

tree = ast.parse(Path(os.path.join(BOT_DIR, "scripts/report_economy.py"))
                 .read_text(encoding="utf-8"))
keep = [n for n in tree.body
        if (isinstance(n, ast.Assign)
            and any(getattr(t, "id", "").endswith(("_SPEND", "_ADD")) for t in n.targets))
        or (isinstance(n, ast.FunctionDef) and n.name == "classify")]
ns = {}
exec(compile(ast.Module(body=keep, type_ignores=[]), "rules", "exec"), ns)
got = ns["classify"]({"kind": "add", "note": fishing.COIN_LOG_NOTE})
check("낚시판매가 '발행'으로 분류된다", got == "issue", f"-> {got}")
check("note가 도박/카드뽑기와 안 겹친다",
      not fishing.COIN_LOG_NOTE.startswith(("도박", "카드뽑기", "내전베팅")))

print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
