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
    BY_KEY, COIN_PIECES, FISH, GRADES, ROD_DURABILITY, ROD_PER_DAY, ROD_PRICE,
    SIZE_BY_KEY, pieces_of, roll_size,
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

pieces = sum(pieces_of(k, roll_size(k, rng)) for k in hits)
measured = pieces / N / COIN_PIECES
formula = fish_data.expected_coin_per_cast()
check("기댓값 계산식과 실측이 일치", abs(measured - formula) < 0.05,
      f"계산 {formula:.3f} vs 실측 {measured:.3f} 코인/회")

# ==================================================================
print("\n[4] 🚨 발행량 — 순이익 ≈ 0이 상한을 대신해요")
day_gross = measured * ROD_DURABILITY
net = day_gross - ROD_PRICE
print(f"  1회 평균 {measured:.2f}코인 · 낚시대 {ROD_PRICE}코인에 {ROD_DURABILITY}회")
print(f"  낚시대 1개: 수입 {day_gross:.1f} − 값 {ROD_PRICE} = 순이익 {net:+.2f}코인")
print(f"  시간당 5개를 써도 {net * 5:+.1f}코인 (무제한이지만 안전)")
print("  -# 참고: 2026-10-17 서버 전체 일일 발행 27~52코인, 출석은 1인 3~5코인")

# 🚨 **이게 지금 유일한 발행 안전장치예요.**
#
# 하루 구매 제한을 풀었으니(2026-10-17 4차) 상한은 "시간"뿐이에요. 1개당 순이익이
# 양수로 커지면 **시간만 쓰면 무한 발행**이 돼요. 제한이 있던 시절엔 +8.8이어도
# 하루 10회로 막혀 있었지만 지금은 아니에요.
check("🚨 낚시대 1개당 순이익이 0 근처다 (무제한이라 필수)",
      -0.5 <= net <= 1.0,
      f"{net:+.2f}코인 — 양수로 키우려면 하루 제한을 되살려야 해요")
check("그래도 아주 조금은 남는다 (0이면 절반이 손해라 아무도 안 해요)",
      net > 0, f"{net:+.2f}코인")
check("시간당(5개)으로도 안전하다",
      (net) * 5 <= 5, f"시간당 {net * 5:+.1f}코인")
check("낚시대값이 하루 총수입보다 싸다 (아니면 아무도 안 사요)",
      ROD_PRICE < day_gross, f"{ROD_PRICE} vs {day_gross:.1f}")

# 🐋 전설이 너무 자주 뜨면 '전설'이라는 말이 무색해져요(꽝을 없애니 22%까지 올랐었어요).
lw = GRADES["전설"]["weight"] / sum(g["weight"] for g in GRADES.values())
day_legend = (1 - (1 - lw) ** ROD_DURABILITY) * 100
print(f"  🐋 전설: 1회 {lw * 100:.2f}% → 낚시대 1개당 {day_legend:.1f}%")
check("전설이 낚시대 1개당 2% 이하로 뜬다 (희소성)", day_legend <= 2,
      f"{day_legend:.2f}%")

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
        # 📏 치수 시스템은 어항에 `$push`로 담아요(같은 어종도 각자 크기를 가져요).
        for field, value in (update.get("$push") or {}).items():
            parent, child = field.split(".", 1)
            doc.setdefault(parent, {}).setdefault(child, [])
            if isinstance(value, dict) and "$each" in value:
                doc[parent][child].extend(value["$each"])
            else:
                doc[parent][child].append(value)
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


C_LO, C_HI = SIZE_BY_KEY[COMMON]
run(fishing_store.record_cast(U, COMMON, C_LO))      # 제일 작은 놈
run(fishing_store.record_cast(U, COMMON, C_HI))      # 제일 큰 놈
run(fishing_store.record_cast(U, LEGEND, SIZE_BY_KEY[LEGEND][0]))
run(fishing_store.record_cast(U, None))              # 놓침
data = run(fishing_store.get(U))
check("어항에 치수까지 담긴다",
      data["tank"] == {COMMON: [C_LO, C_HI], LEGEND: [SIZE_BY_KEY[LEGEND][0]]},
      str(data["tank"]))
check("던진 횟수가 센다", data["casts"] == 4, str(data["casts"]))
check("놓친 건 잡은 수에 안 들어간다", data["caught"] == 3, str(data["caught"]))
check("최고 기록이 전설로 갱신", (data.get("best") or {}).get("key") == LEGEND)

# 📏 같은 어종이라도 **치수에 따라 값이 달라야** 해요 (사용자 요청의 핵심).
lo_p, hi_p = pieces_of(COMMON, C_LO), pieces_of(COMMON, C_HI)
check("작은 놈보다 큰 놈이 비싸다", hi_p > lo_p, f"{lo_p} vs {hi_p}조각")
check("🚨 일반 물고기가 0.5~1.0코인 범위",
      lo_p == 5 and hi_p == 10, f"{lo_p / 10:.1f}~{hi_p / 10:.1f}코인")
check("어항 가치가 치수 합과 일치",
      data["pieces"] == lo_p + hi_p + pieces_of(LEGEND, SIZE_BY_KEY[LEGEND][0]),
      f"{data['pieces']}조각")

# 🚨 치수 시스템 **이전**에 잡은 물고기(마리수만 있는 옛 형식)도 읽혀야 해요.
#    11명이 이미 그 형식으로 어항을 갖고 있었어요.
fake.docs["old"] = {"_id": "old", "tank": {COMMON: 2, LEGEND: 1}}
legacy = run(fishing_store.get("old"))
check("🚨 옛 형식(마리수)도 읽힌다",
      legacy["tank"] == {COMMON: [None, None], LEGEND: [None]}, str(legacy["tank"]))
check("옛 물고기는 중앙 크기로 값이 매겨진다",
      legacy["pieces"] == pieces_of(COMMON) * 2 + pieces_of(LEGEND),
      f"{legacy['pieces']}조각")

# 🚨 판매 도중에 물고기를 더 낚아도 **한 마리도 사라지면 안 돼요.**
#
# ⚠️ 여기서 검사할 건 "정확히 몇 마리가 팔렸나"가 아니에요. `find_one_and_update`는
#    원자적이라 **읽기와 쓰기 사이가 없어서**, 끼어든 물고기가 같이 팔리든 남든 둘 다
#    정상이에요. 진짜 불변식은 **판 것 + 남은 것 = 그동안 넣은 것 전부**예요.
#    (처음엔 "끼어든 건 남아야 한다"고 단언했다가 틀렸어요 - 순서를 잘못 가정한 거예요.)
before_pieces = run(fishing_store.get(U))["pieces"]
fake.before_sell = lambda: run(fishing_store.record_cast(U, COMMON, C_LO))
tank, coins, dust = run(fishing_store.sell_all(U))
after = run(fishing_store.get(U))

sold_pieces = fishing_store.tank_pieces(tank)
check("🚨 판매 중 낚은 물고기가 한 마리도 안 사라진다",
      sold_pieces + after["pieces"] + after["dust"] == before_pieces + lo_p,
      f"판 {sold_pieces} + 남은어항 {after['pieces']} + 잔돈 {after['dust']} "
      f"vs 넣은 {before_pieces + lo_p}조각")
check("🚨 지급 코인 + 잔돈 = 판 물고기 값 (한 조각도 안 샌다)",
      coins * COIN_PIECES + dust == sold_pieces, f"{coins}코인 + {dust}조각 vs {sold_pieces}")

# 역검증: '읽고 나서 비우는' 옛날 방식이면 끼어든 물고기가 증발해요.
def broken_sell(uid):
    import copy

    doc = fake.find_one({"_id": uid}) or {}
    # ⚠️ **깊은 복사**여야 해요. 얕게 뜨면 어항 리스트를 그대로 공유해서, 그 사이에
    #    append된 물고기가 스냅샷에도 보여요 — 실제 DB는 별개 문서를 돌려주니
    #    그 상태로는 손실을 재현하지 못해요(처음에 이것 때문에 역검증이 헛돌았어요).
    snapshot = copy.deepcopy(doc.get("tank") or {})
    run(fishing_store.record_cast(uid, COMMON, C_LO))   # 그 사이에 한 마리 더
    fake.update_one({"_id": uid}, {"$set": {"tank": {}}})
    return snapshot

fake.docs["999"] = {"_id": "999", "tank": {COMMON: [C_LO, C_LO]}}
lost = broken_sell("999")
left = (fake.find_one({"_id": "999"}) or {}).get("tank") or {}
n_lost = sum(len(v) if isinstance(v, list) else v for v in lost.values())
n_left = sum(len(v) if isinstance(v, list) else v for v in left.values())
check("(역검증) 읽고-비우기 방식이면 실제로 증발한다", n_lost + n_left < 3,
      f"판매 {n_lost}마리 + 남음 {n_left}마리 — 3마리여야 하는데 모자라요")

# 판매 실패 -> 어항 복구 (그 사이 낚은 것과 합쳐져야 해요)
restore_before = run(fishing_store.get(U))["pieces"] + run(fishing_store.get(U))["dust"]
run(fishing_store.restore(U, tank, dust))
restored = run(fishing_store.get(U))
check("실패하면 어항이 되돌아온다 (잔돈까지)",
      restored["pieces"] + restored["dust"] == restore_before + sold_pieces + dust,
      f"{restored['pieces']}+{restored['dust']} vs {restore_before + sold_pieces + dust}")

# 빈 어항
fake.docs["888"] = {"_id": "888", "tank": {}}
tank2, coins2, dust2 = run(fishing_store.sell_all("888"))
check("빈 어항은 0코인", coins2 == 0 and not tank2 and dust2 == 0)

# ==================================================================
print("\n[8a] 🚨 잔돈(조각) — 한 마리씩 팔아 이득 보는 구멍이 없어야 해요")
# ------------------------------------------------------------------
# 일반 물고기 하나가 0.5코인이에요. 팔 때마다 반올림했다면 **한 마리씩 10번 팔아
# 10코인**(실제 5코인어치)을 받는 구멍이 생겨요. 나머지를 어항에 남기면 막혀요.
S = "dust-user"
fake.docs.pop(S, None)
one_at_a_time = 0
for _ in range(10):
    run(fishing_store.record_cast(S, COMMON, C_LO))     # 0.5코인짜리
    _, c, _ = run(fishing_store.sell_all(S))
    one_at_a_time += c

T = "bulk-user"
fake.docs.pop(T, None)
for _ in range(10):
    run(fishing_store.record_cast(T, COMMON, C_LO))
_, bulk, _ = run(fishing_store.sell_all(T))

check("🚨 한 마리씩 팔아도 한 번에 판 것과 같다",
      one_at_a_time == bulk, f"한마리씩 {one_at_a_time} vs 한번에 {bulk}코인")
check("0.5코인 10마리 = 5코인", bulk == 5, f"{bulk}코인")

# ==================================================================
print("\n[8b] 🎣 낚시대 — 무제한 구매 · 내구도 누적")
# ------------------------------------------------------------------
# 이게 발행 상한의 **유일한** 장치라, 여기 뚫리면 1차 설계의 무제한 발행으로 돌아가요.
R = "rod-user"
fake.docs.pop(R, None)

left, bought = run(fishing_store.rod_state(R))
check("처음엔 낚시대가 없다", left == 0)
check("낚시대 없이 쓰면 None", run(fishing_store.use_rod(R)) is None)

check("낚시대를 산다", run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)
check(f"내구도 {ROD_DURABILITY}로 시작",
      run(fishing_store.rod_state(R))[0] == ROD_DURABILITY)

# 🚨 **하루 제한이 없어요**(2026-10-17 4차). 대신 1개당 순이익이 0 근처라 안전해요.
check("🚨 같은 날 또 살 수 있다 (제한 해제)",
      run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)

# 🚨 내구도가 **쌓여야** 해요. 덮어쓰면 남은 횟수가 날아가요.
check("🚨 내구도가 덮어쓰이지 않고 쌓인다",
      run(fishing_store.rod_state(R))[0] == ROD_DURABILITY * 2,
      f"{run(fishing_store.rod_state(R))[0]}회 (기대 {ROD_DURABILITY * 2})")

# 내구도 소진
rem = [run(fishing_store.use_rod(R)) for _ in range(ROD_DURABILITY * 2)]
check("전부 쓰면 0이 된다", rem[-1] == 0, str(rem[-3:]))
check("한 번에 1씩 줄어든다",
      all(a - b == 1 for a, b in zip(rem, rem[1:])), str(rem[:4]))
check("🚨 다 쓰면 더 못 쓴다 (음수로 안 내려감)",
      run(fishing_store.use_rod(R)) is None)

# 🚨 코인 차감 실패 시 되돌리기 — 안 되면 공짜 낚시대가 돼요.
run(fishing_store.buy_rod(R, ROD_DURABILITY))      # 10
run(fishing_store.use_rod(R))                      # 9 (쓰던 중)
run(fishing_store.buy_rod(R, ROD_DURABILITY))      # 19 (하나 더 삼)
run(fishing_store.refund_rod(R, ROD_DURABILITY))   # 차감 실패 -> 방금 산 것만 취소
check("🚨 환불은 **방금 준 만큼만** 뺀다 (쓰던 낚시대가 안 날아감)",
      run(fishing_store.rod_state(R))[0] == 9,
      f"{run(fishing_store.rod_state(R))[0]}회 (기대 9)")

# ==================================================================
print("\n[8c] 🎣 놓치면 횟수를 돌려준다 + 제한시간 시계")
# ------------------------------------------------------------------
# 🚨 2026-10-17 사용자 신고: "챔질 실패가 생각보다 많다". 원인이 둘이었어요.
#   1) 제한시간 시계를 **메시지 보내기 전**에 찍어서, 유저가 '입질!'을 보기도 전에
#      2.5초가 흐르기 시작했어요(디스코드 왕복 100~300ms를 통째로 손해).
#   2) 그렇게 놓친 것까지 내구도를 먹었어요.
M = "miss-user"
fake.docs.pop(M, None)
run(fishing_store.buy_rod(M, ROD_DURABILITY))
run(fishing_store.use_rod(M))                       # 던짐 -> 9
check("던지면 내구도가 준다", run(fishing_store.rod_state(M))[0] == ROD_DURABILITY - 1)
run(fishing_store.give_back_rod(M))                 # 놓침 -> 환불
check("🚨 놓치면 횟수가 돌아온다",
      run(fishing_store.rod_state(M))[0] == ROD_DURABILITY,
      f"{run(fishing_store.rod_state(M))[0]}회")

# ⚠️ 1회 환불(give_back_rod)과 한 세트 취소(refund_rod)를 섞어 쓰면 10씩 어긋나요.
run(fishing_store.give_back_rod(M))
check("give_back_rod는 **1만** 돌려준다",
      run(fishing_store.rod_state(M))[0] == ROD_DURABILITY + 1,
      f"{run(fishing_store.rod_state(M))[0]}회")

# 🚨 시계는 **메시지를 보낸 뒤**에 시작해야 해요. 소스 순서를 직접 확인해요 -
#    되돌려놓으면 유저가 보기도 전에 시간이 흘러서 '실력 아닌 지연'으로 놓쳐요.
from pathlib import Path as _Path  # noqa: E402

_src = _Path(os.path.join(BOT_DIR, "cogs/fishing.py")).read_text(encoding="utf-8")
_edit = _src.index("await interaction.edit_original_response(embed=bite")
_clock = _src.index("view.bite_at = time.monotonic()")
check("🚨 제한시간 시계가 입질 메시지 **이후**에 시작한다", _clock > _edit,
      "시계가 먼저면 왕복 지연만큼 유저가 손해를 봐요")

# ==================================================================
print("\n[9] 어종표 정합성")
keys = [f["key"] for rows in FISH.values() for f in rows]
check("어종 key가 겹치지 않는다", len(keys) == len(set(keys)), f"{len(keys)}종")
check("모든 등급에 어종이 있다", all(FISH.get(g) for g in GRADES), str(list(GRADES)))
check("BY_KEY가 전부 매핑된다", len(BY_KEY) == len(keys))
check("가격 범위가 등급 순서대로 오른다",
      [GRADES[g]["pieces"] for g in ("일반", "희귀", "대물", "전설")]
      == sorted(GRADES[g]["pieces"] for g in GRADES),
      str({g: GRADES[g]["pieces"] for g in GRADES}))
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
