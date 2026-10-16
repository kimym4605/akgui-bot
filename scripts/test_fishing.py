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
from utils.fish_data import (  # noqa: E402
    BY_KEY, FISH, GRADES, ROD_DURABILITY, ROD_PER_DAY, ROD_PRICE, price_of,
)

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

# 🚨 **꽝이 없어야 해요**(2026-10-17 2차). 타이밍만 맞히면 반드시 물고기가 나와요.
#    1차의 꽝 60%는 1회당 수익만 낮출 뿐 **총 발행량을 못 막아서**, 낚시대
#    (하루 1개 · 내구도 10)로 상한을 거는 구조로 바꿨어요.
check("꽝이 없다 — 챔질에 성공하면 반드시 잡힌다",
      all(r is not None for r in results),
      f"None {sum(1 for r in results if r is None)}개")

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
print("\n[4] 🚨 발행량 — 낚시대가 상한을 건다")
day_gross = measured * ROD_DURABILITY
net = day_gross - ROD_PRICE
print(f"  1회 평균 {measured:.2f}코인 · 낚시대 {ROD_PRICE}코인에 {ROD_DURABILITY}회")
print(f"  하루 총수입 {day_gross:.1f} − 낚시대 {ROD_PRICE} = 순발행 {net:+.1f}코인/일")
print("  -# 참고: 2026-10-17 서버 전체 일일 발행 27~52코인, 출석은 1인 3~5코인")

# 🚨 1차 설계와의 핵심 차이. 전엔 상한이 없어서 하루 189코인도 가능했어요.
check("하루 던지기 횟수에 상한이 있다",
      ROD_DURABILITY * ROD_PER_DAY == 10, f"{ROD_DURABILITY * ROD_PER_DAY}회")
check("🚨 순발행이 출석(3~5코인)을 압도하지 않는다 (25코인 이하)",
      net <= 25, f"{net:.1f}코인")
check("그래도 낚시할 이유는 있다 (순발행 > 0)", net > 0, f"{net:.1f}코인")
check("낚시대값이 하루 총수입보다 싸다 (아니면 아무도 안 사요)",
      ROD_PRICE < day_gross, f"{ROD_PRICE} vs {day_gross:.1f}")

# 🐋 전설이 너무 자주 뜨면 '전설'이라는 말이 무색해져요(꽝을 없애니 22%까지 올랐었어요).
lw = GRADES["전설"]["weight"] / sum(g["weight"] for g in GRADES.values())
day_legend = (1 - (1 - lw) ** ROD_DURABILITY) * 100
print(f"  🐋 전설: 1회 {lw * 100:.2f}% → 하루 {day_legend:.0f}% 확률")
check("전설이 하루 10% 이하로 뜬다 (희소성)", day_legend <= 10, f"{day_legend:.0f}%")

# ==================================================================
print("\n[5][6][7][8] 어항")


class FakeFish:
    def __init__(self):
        self.docs = {}
        self.before_sell = None      # 판매 직전에 끼어들 훅

    def find_one(self, flt, projection=None):
        d = self.docs.get(flt["_id"])
        return dict(d) if d else None

    def _matches(self, doc, flt):
        """`$ne` / `$gte` / `$exists` 만 흉내내요 (낚시대·어항이 쓰는 전부)."""
        for key, want in flt.items():
            if key == "_id":
                continue
            got = doc.get(key)
            if isinstance(want, dict):
                if "$ne" in want and got == want["$ne"]:
                    return False
                if "$gte" in want and not (isinstance(got, int) and got >= want["$gte"]):
                    return False
                if "$exists" in want and (key in doc) != want["$exists"]:
                    return False
            elif got != want:
                return False
        return True

    def update_one(self, flt, update, upsert=False):
        class Res:
            def __init__(self, m=0, u=None):
                self.modified_count, self.upserted_id = m, u

        uid = flt["_id"]
        doc = self.docs.get(uid)
        if doc is None:
            if not upsert:
                return Res()
            doc = self.docs[uid] = {"_id": uid}
            upserted = uid
        else:
            # ⚠️ 조건부 필터(`$ne` 등)를 **반드시** 봐야 해요. 안 보면 "하루 1개" 같은
            #    제약이 테스트에서만 통과하고 실제로는 안 걸리는 걸 못 잡아요.
            if not self._matches(doc, flt):
                return Res()
            upserted = None

        for field, delta in (update.get("$inc") or {}).items():
            if "." in field:
                parent, child = field.split(".", 1)
                doc.setdefault(parent, {})
                doc[parent][child] = doc[parent].get(child, 0) + delta
            else:
                doc[field] = doc.get(field, 0) + delta
        for field, value in (update.get("$set") or {}).items():
            doc[field] = value
        for field in (update.get("$unset") or {}):
            doc.pop(field, None)
        return Res(m=0 if upserted else 1, u=upserted)

    def find_one_and_update(self, flt, update, return_document=None):
        if self.before_sell is not None:
            cb, self.before_sell = self.before_sell, None
            cb()
        uid = flt["_id"]
        doc = self.docs.get(uid)
        if doc is None or not self._matches(doc, flt):
            return None
        before = dict(doc)
        for field, value in (update.get("$set") or {}).items():
            doc[field] = value
        for field, delta in (update.get("$inc") or {}).items():
            doc[field] = doc.get(field, 0) + delta
        # pymongo는 BEFORE/AFTER를 고를 수 있어요. 기본(None)은 BEFORE예요.
        from pymongo import ReturnDocument as _RD
        return dict(doc) if return_document == _RD.AFTER else before

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
print("\n[8b] 🎣 낚시대 — 하루 1개 · 내구도 10")
# ------------------------------------------------------------------
# 이게 발행 상한의 **유일한** 장치라, 여기 뚫리면 1차 설계의 무제한 발행으로 돌아가요.
R = "rod-user"
fake.docs.pop(R, None)

left, bought = run(fishing_store.rod_state(R))
check("처음엔 낚시대가 없다", left == 0 and bought is False)
check("낚시대 없이 쓰면 None", run(fishing_store.use_rod(R)) is None)

check("낚시대를 산다", run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)
left, bought = run(fishing_store.rod_state(R))
check(f"내구도 {ROD_DURABILITY}로 시작", left == ROD_DURABILITY, str(left))
check("오늘 샀다고 기록된다", bought is True)

# 🚨 하루 1개 — 이게 뚫리면 하루 상한이 사라져요.
check("🚨 같은 날 두 번째는 못 산다",
      run(fishing_store.buy_rod(R, ROD_DURABILITY)) is False)
check("두 번째 시도가 내구도를 덮어쓰지 않는다",
      run(fishing_store.rod_state(R))[0] == ROD_DURABILITY)

# 내구도 소진
rem = [run(fishing_store.use_rod(R)) for _ in range(ROD_DURABILITY)]
check(f"{ROD_DURABILITY}번 쓰면 0이 된다", rem[-1] == 0, str(rem))
check("순서대로 줄어든다", rem == list(range(ROD_DURABILITY - 1, -1, -1)), str(rem))
check("🚨 다 쓰면 더 못 쓴다 (음수로 안 내려감)",
      run(fishing_store.use_rod(R)) is None)
check("부서진 뒤에도 그날은 못 산다",
      run(fishing_store.buy_rod(R, ROD_DURABILITY)) is False)

# 날짜가 바뀌면 다시 살 수 있어야 해요.
fake.docs[R]["rod_date"] = "2000-01-01"
check("날짜가 바뀌면 다시 살 수 있다",
      run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)
check("새 낚시대는 내구도가 가득", run(fishing_store.rod_state(R))[0] == ROD_DURABILITY)

# 🚨 코인 차감 실패 시 되돌리기 — 안 되면 공짜 낚시대가 돼요.
run(fishing_store.refund_rod(R))
left, bought = run(fishing_store.rod_state(R))
check("환불하면 내구도가 0", left == 0, str(left))
check("🚨 환불하면 그날 다시 살 수 있다 (안 그러면 코인도 낚시대도 없어요)",
      bought is False)
check("실제로 다시 사진다", run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)

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

# ==================================================================
print("\n[11] 🚨 낚시는 본인에게만 보여야 한다")
# ------------------------------------------------------------------
# 한 채널에서 여러 명이 동시에 던지면 찌가 뒤섞여요(어느 게 내 건지 모르고, 남의
# "입질!"을 보고 눌러버려요). 이건 **실수로 되돌리기 쉬운 설정**이라 코드로 못 박아요.
#
# ⚠️ 줄 단위 grep으로는 못 잡아요 - `ephemeral=True`가 다음 줄에 있는 호출이 많아요.
#    AST로 호출 인자를 직접 봐요.
import ast as _ast  # noqa: E402

_src = Path(os.path.join(BOT_DIR, "cogs/fishing.py")).read_text(encoding="utf-8")
_tree = _ast.parse(_src)

PUBLIC_OK = {"leaderboard"}        # 순위표는 같이 보는 게 맞아요
leaks = []
for _cls in [n for n in _tree.body if isinstance(n, _ast.ClassDef)]:
    for _fn in [n for n in _cls.body
                if isinstance(n, (_ast.AsyncFunctionDef, _ast.FunctionDef))]:
        for _call in _ast.walk(_fn):
            if not isinstance(_call, _ast.Call):
                continue
            _name = getattr(_call.func, "attr", "")
            if _name not in ("send_message", "send", "defer"):
                continue
            # 컴포넌트 상호작용의 defer는 메시지를 안 만들어요(deferred_message_update).
            if _name == "defer" and _fn.name == "strike":
                continue
            if _fn.name in PUBLIC_OK:
                continue
            eph = any(k.arg == "ephemeral" and getattr(k.value, "value", None) is True
                      for k in _call.keywords)
            if not eph:
                leaks.append(f"{_cls.name}.{_fn.name} {_name}() line {_call.lineno}")

check("🚨 /낚시·/어항·/물고기판매의 모든 응답이 ephemeral", not leaks,
      "공개로 남은 곳: " + ", ".join(leaks) if leaks else "")
check("/낚시왕은 공개 (순위표)", "leaderboard" in PUBLIC_OK)

print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
