"""🎣 낚시 검증. 실제 DB·디스코드 없이 돌아가요.

🚨 낚시는 **코인을 찍어내는** 기능이에요. 확률·가격을 잘못 두면 경제가 바로 기울어요.
그래서 '동작하나'보다 **'얼마나 찍어내나'**를 먼저 재요.

여기서 확인하는 것:
  1) 꽝 확률이 설정(MISS_RATE)과 맞는다
  2) 잡혔을 때 등급 분포가 가중치와 맞는다
  3) 1회 기댓값이 계산식과 실측이 일치한다 (숫자를 바꾸면 여기서 드러나요)
  4) 🚨 발행량 - 낚시대 1개당 순이익이 설계값과 같나 (5차부터 상한이 없어요)
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
    BY_KEY, COIN_PIECES, FISH, GRADE_ORDER, GRADES, ROD_DURABILITY, ROD_PER_DAY,
    ROD_PRICE, SIZE_BY_KEY, SMALL_ROD_DURABILITY, SMALL_ROD_PRICE,
    pieces_of, roll_size,
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
print("\n[4] 🚨 발행량 — 상한이 없어요 (5차)")
day_gross = measured * ROD_DURABILITY
net = day_gross - ROD_PRICE
print(f"  1회 평균 {measured:.2f}코인 · 낚시대 {ROD_PRICE}코인에 {ROD_DURABILITY}회")
print(f"  낚시대 1개: 수입 {day_gross:.1f} − 값 {ROD_PRICE} = 순이익 {net:+.2f}코인")
print(f"  9명이 하루 1개씩 → {net * 9:+.0f}코인/일 · 한 명이 8개 사면 {net * 8:+.0f}코인")
print("  -# 참고: 2026-10-17 서버 전체 일일 발행 27~52코인, 출석은 1인 3~5코인")

# 🚨 **4차의 안전장치("순이익 ≈ 0")가 5차에서 없어졌어요.**
#
# 사용자가 "가격이 짜다"고 해서 일반 0.5~1.0 -> 0.8~1.5, 희귀 1.5~3.0 -> 2.0~3.8으로
# 올렸어요. 발행 증가를 **숫자를 보고 수용한 결정**이에요(2026-10-17 5차).
#
# ⭐ 그래서 이 테스트의 성격이 바뀌었어요. **"0 근처인지"를 재는 상한 가드가 아니라,
#    "의도한 값에서 벗어났는지"를 보는 회귀 가드예요.** 가드를 아예 지우면 발행량이
#    다음에 조용히 또 커져도 아무도 모르니까요.
#
# ⚠️ 이 값을 바꿀 땐 숫자를 같이 고치고, **커밋 메시지에 왜 바꿨는지 남겨주세요.**
EXPECTED_NET = 4.13          # 5차 설계값 (일반 8~15 · 희귀 20~38 · 낚시대 10코인)
check(f"🚨 낚시대 1개당 순이익이 설계값({EXPECTED_NET:+.2f})과 같다",
      abs(net - EXPECTED_NET) < 0.15,
      f"{net:+.2f}코인 — 의도한 변경이면 EXPECTED_NET을 같이 고쳐주세요")
check("낚시가 '벌이'가 된다 (4차의 본전 구조에서 벗어났는지)",
      net > 2.0, f"{net:+.2f}코인")
check("낚시대값이 총수입보다 싸다 (아니면 아무도 안 사요)",
      ROD_PRICE < day_gross, f"{ROD_PRICE} vs {day_gross:.1f}")

# ------------------------------------------------------------------
# ⭐ 🪝 입문용 소형 낚시대 (2026-10-18 · 분배 문제 대응)
#
# 🚨 **이 상품의 전부는 "비율이 같다"는 것이에요.** 횟수당 값이 같으면 발행 총량
#    구조가 전혀 안 바뀌고 **진입 문턱만** 낮아져요(실측 31% → 71%가 살 수 있게 됨).
#    비율을 깨면 그 순간 밸런스 변경이 되는데, 그건 사용자가 결정할 일이에요.
#    → 근거는 `utils/fish_data.SMALL_ROD_PRICE` 주석 / 분배 실측은 report_economy.py
print("\n[4-b] 🪝 소형 낚시대 — 비율이 큰 것과 같은가")
big_ratio = ROD_PRICE / ROD_DURABILITY
small_ratio = SMALL_ROD_PRICE / SMALL_ROD_DURABILITY
check("🚨 횟수당 값이 큰 낚시대와 **똑같다** (발행 구조 불변)",
      abs(big_ratio - small_ratio) < 1e-9,
      f"큰 것 {big_ratio:.3f}코인/회 vs 소형 {small_ratio:.3f}코인/회")
check("소형이 더 싸다 (진입용이니까)",
      SMALL_ROD_PRICE < ROD_PRICE, f"{SMALL_ROD_PRICE} < {ROD_PRICE}")
# ⚠️ 1회짜리로 쪼개면 "한 번 던지고 바로 팔기"가 되어 미니게임이 뽑기처럼 돼요.
check("소형도 최소 2번은 던진다", SMALL_ROD_DURABILITY >= 2,
      f"{SMALL_ROD_DURABILITY}번")
small_net = measured * SMALL_ROD_DURABILITY - SMALL_ROD_PRICE
print(f"  소형 1개: 수입 {measured * SMALL_ROD_DURABILITY:.1f} − 값 {SMALL_ROD_PRICE} "
      f"= 순이익 {small_net:+.2f}코인 (큰 것은 {net:+.2f})")
print(f"  -# 비율이 같으니 1코인당 순이익도 같아요 "
      f"({small_net / SMALL_ROD_PRICE:+.3f} vs {net / ROD_PRICE:+.3f})")

# 🚨 상한이 없다는 걸 **테스트가 알고 있게** 해둬요. 누가 `ROD_PER_DAY`를 되살리면
#    여기서 눈에 띄고, 그때는 발행 걱정 없이 순이익을 더 키울 수 있어요.
print(f"  ⚠️ 하루 구매 제한: {fish_data.ROD_PER_DAY or '무제한'} "
      f"→ 발행 총량 상한 {'있음' if fish_data.ROD_PER_DAY else '**없음**'}")
if fish_data.ROD_PER_DAY:
    print(f"     1인 하루 최대 발행 {net * fish_data.ROD_PER_DAY:+.1f}코인")

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

# 🚨 주간 대회 훅도 가짜로 바꿔요(2026-10-19에 발견).
#
# 2026-10-18에 `record_cast` 끝에 `fishing_week.record_catch`가 붙었는데, 가짜는
# `_fish` 컬렉션만 갈아끼우고 있었어요. 그래서 이 테스트가 **그날부터 조용히 깨져**
# 있었어요 - 캐스트마다 진짜 Atlas(없으면 localhost)로 붙으려 해서 [8a]에서 몇 분씩
# 멈추거나 ServerSelectionTimeoutError로 죽었어요.
#
# ⚠️ 적립이 **딱 한 번** 불리는지는 `scripts/test_fishing_contest.py`가 봐요
#    (여기서 세면 가짜가 진짜를 대신한 셈이라 의미가 없어요).
_week_calls = []


async def _fake_record_catch(*a, **k):
    _week_calls.append(a)


fishing_store.fishing_week.record_catch = _fake_record_catch

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
check("🚨 일반 물고기가 0.8~1.5코인 범위 (5차, 사용자 요청)",
      lo_p == 8 and hi_p == 15, f"{lo_p / 10:.1f}~{hi_p / 10:.1f}코인")

# 🚨 **등급 경계가 겹치면 상위 등급의 맛이 사라져요.**
#
# 5차에서 일반을 0.8~1.5로 올렸더니 희귀 최소(1.5)와 **딱 맞닿았어요** — "희귀를
# 잡았는데 일반 대물급과 같은 값"이 나오는 상태죠. 그래서 희귀도 2.0~3.8로 같이
# 올렸어요(사용자 결정 - 4.0으로 하면 이번엔 대물 최소와 맞닿아요). 다음에 한쪽만 또 올리면 여기서 걸려요.
# ⚠️ `GRADE_ORDER`는 **내림차순**(전설→일반)이에요. 방향에 기대지 말고 값으로 정렬해요.
_bounds = sorted(((g, GRADES[g]["pieces"]) for g in GRADE_ORDER),
                 key=lambda gp: gp[1][0])
_overlaps = [f"{a}({ap[0]}~{ap[1]}) ≥ {b}({bp[0]}~{bp[1]})"
             for (a, ap), (b, bp) in zip(_bounds, _bounds[1:]) if ap[1] >= bp[0]]
check("🚨 등급 간 값 범위가 겹치지 않는다", not _overlaps,
      " · ".join(_overlaps) if _overlaps
      else " < ".join(f"{g} {p[0]/10:.1f}~{p[1]/10:.1f}" for g, p in _bounds))
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
# ⚠️ **잔돈(`dust`)을 여기 더하면 안 돼요.** 판 조각(`sold_pieces`) 안에 이미 들어
#    있어요 - 그중 10의 배수만 코인이 되고 나머지가 `dust`로 이월되는 구조라
#    (바로 아래 검사가 그 관계를 봐요). 더하면 이중 계산이에요.
#
#    전엔 조각 합이 우연히 10의 배수여서 `dust`가 0이라 통과했는데, 5차에서 가격이
#    바뀌어 331조각이 되자 바로 드러났어요. **우연히 통과하던 식**이었던 거예요.
check("🚨 판매 중 낚은 물고기가 한 마리도 안 사라진다",
      sold_pieces + after["pieces"] == before_pieces + lo_p,
      f"판 {sold_pieces} + 남은어항 {after['pieces']} "
      f"vs 넣은 {before_pieces + lo_p}조각 (이월 잔돈 {after['dust']})")
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
# 일반 물고기 **최소 크기**는 1코인이 안 돼요(5차 기준 0.8코인). 팔 때마다 반올림했다면
# **한 마리씩 10번 팔아 10코인**(실제 8코인어치)을 받는 구멍이 생겨요.
# 나머지를 어항에 남기면 막혀요.
#
# ⚠️ 기대값을 숫자로 박지 말고 `lo_p`에서 계산해요 - 가격은 또 바뀌어요(5차에 깨졌어요).
S = "dust-user"
fake.docs.pop(S, None)
one_at_a_time = 0
for _ in range(10):
    run(fishing_store.record_cast(S, COMMON, C_LO))     # 일반 최소 크기
    _, c, _ = run(fishing_store.sell_all(S))
    one_at_a_time += c

T = "bulk-user"
fake.docs.pop(T, None)
for _ in range(10):
    run(fishing_store.record_cast(T, COMMON, C_LO))
_, bulk, _ = run(fishing_store.sell_all(T))

check("🚨 한 마리씩 팔아도 한 번에 판 것과 같다",
      one_at_a_time == bulk, f"한마리씩 {one_at_a_time} vs 한번에 {bulk}코인")
check(f"일반 최소({lo_p / 10:.1f}코인) 10마리 = {lo_p * 10 // COIN_PIECES}코인",
      bulk == lo_p * 10 // COIN_PIECES, f"{bulk}코인")

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
print("\n[8d] 🚨 cog의 /물고기판매·/낚시 경로를 직접 돌린다")
# ------------------------------------------------------------------
# 🚨 2026-10-17 사고: `sell_all`이 3개(tank, coins, dust)를 돌려주게 바뀌었는데
#    cog가 `tank, coins = ...`로 2개만 받아서 **판매가 통째로 죽었어요**
#    (ValueError: too many values to unpack). 유저가 신고할 때까지 몰랐어요.
#
#    원인은 **테스트가 store만 직접 불렀기** 때문이에요. 아무리 store를 잘 검사해도
#    호출부가 어긋나면 못 잡아요. 그래서 여기서는 **cog 함수를 실제로 호출**해요.
class FakeResp:
    def __init__(self): self.deferred = None
    async def defer(self, *, ephemeral=False, thinking=False): self.deferred = ephemeral


class FakeFollowup:
    def __init__(self): self.sent = []
    async def send(self, content=None, *, embed=None, file=None, view=None,
                   ephemeral=False):
        self.sent.append({"content": content, "embed": embed, "ephemeral": ephemeral})


class FakeInter:
    def __init__(self, uid):
        self.user = type("U", (), {"id": uid, "display_name": "tester"})()
        self.response = FakeResp()
        self.followup = FakeFollowup()
        self.edited = []

    async def edit_original_response(self, **kw):
        self.edited.append(kw)


class _FakeWallet:
    def __init__(self): self.bal = 0
    async def add(self, uid, amount, *, reason=""):
        self.bal += amount
        return self.bal
    async def get_balance(self, uid): return self.bal
    async def spend(self, uid, amount, *, reason=""): return False


_orig_wallet = fishing.coin_wallet
fishing.coin_wallet = _FakeWallet()

P = "cog-sell"
fake.docs.pop(P, None)
run(fishing_store.record_cast(P, COMMON, C_HI))     # 일반 최대 크기
run(fishing_store.record_cast(P, COMMON, C_HI))     # 일반 최대 크기
cog = fishing.Fishing(None)
inter = FakeInter(P)
run(cog.sell.callback(cog, inter))

check("🚨 /물고기판매가 예외 없이 끝난다", bool(inter.followup.sent),
      "아무것도 안 보냈어요 — 중간에 터진 거예요")
if inter.followup.sent:
    sent = inter.followup.sent[-1]
    check("결과 임베드를 보냈다", sent["embed"] is not None)
    check("본인에게만 보인다", sent["ephemeral"] is True)
check("코인이 실제로 들어갔다", fishing.coin_wallet.bal == hi_p * 2 // COIN_PIECES,
      f"{fishing.coin_wallet.bal}코인 (기대 {hi_p * 2 // COIN_PIECES})")
check("어항이 비었다", not run(fishing_store.get(P))["tank"])

# 빈 어항도 터지지 않아야 해요.
inter2 = FakeInter("cog-empty")
run(cog.sell.callback(cog, inter2))
check("빈 어항 판매도 안내만 하고 끝난다",
      bool(inter2.followup.sent) and inter2.followup.sent[0]["embed"] is None)

fishing.coin_wallet = _orig_wallet

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
# ⚠️ 2026-10-18에 분류 규칙이 `scripts/report_economy.py` 안에서
#    `utils/coin_ledger.py`로 옮겨졌어요(`/서버리포트`와 같은 규칙을 쓰려고).
#    예전엔 스크립트를 AST로 뜯어 `classify`만 꺼내 썼는데, 이제 그냥 import해요.
from pathlib import Path  # noqa: E402  (아래 [11]에서도 써요)

from utils.coin_ledger import classify  # noqa: E402

got = classify({"kind": "add", "note": fishing.COIN_LOG_NOTE})
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

# 🚨 여기에 이름을 더할 땐 **왜 ephemeral이 아니어도 되는지**를 같이 적을 것.
#    이 가드가 막는 건 "여러 명의 찌가 뒤섞이는 것"이라, **내 판이 걸린 화면**은
#    반드시 ephemeral이어야 해요. 아래 둘은 판과 무관한 **고정 안내**예요.
PUBLIC_OK = {
    "leaderboard",   # 🏆 순위표 — 같이 보는 게 맞아요
    "rates",         # 🎣 /낚시확률 — 확률·값 공개. 뒤섞일 내 판이 없고, 공개여야
                     #    옆사람이 보고 알게 돼요(`/카드확률`도 공개예요).
                     #    발견 경로가 좁은 게 지금 낚시의 실제 문제예요.
}

# 🚨 **클래스 안만 훑으면 안 돼요.** `run_cast`/`finish_cast`가 모듈 함수로 빠지면서
#    (2026-10-17 다시던지기) 검사 범위에서 조용히 사라졌었어요. 정작 `send_message`를
#    직접 부르는 건 지금 그 두 함수예요 - 검사 대상이 **본체를 비켜간** 셈이었죠.
#    클래스 메서드 + 모듈 함수를 **둘 다** 모아요.
_view_classes = {_c.name for _c in _tree.body if isinstance(_c, _ast.ClassDef)
                 and any(getattr(_b, "attr", "") == "View" for _b in _c.bases)}
_funcs = [(_c.name, _f) for _c in _tree.body if isinstance(_c, _ast.ClassDef)
          for _f in _c.body
          if isinstance(_f, (_ast.AsyncFunctionDef, _ast.FunctionDef))]
_funcs += [("<module>", _f) for _f in _tree.body
           if isinstance(_f, (_ast.AsyncFunctionDef, _ast.FunctionDef))]


def _contains(_node, _target):
    return any(_n is _target for _n in _ast.walk(_node))


def _has_eph_defer(_node):
    """이 가지 안에 `defer(ephemeral=True)`가 있나 = 슬래시 경로를 따로 처리했나."""
    return any(isinstance(_n, _ast.Call)
               and getattr(_n.func, "attr", "") == "defer"
               and any(_k.arg == "ephemeral"
                       and getattr(_k.value, "value", None) is True
                       for _k in _n.keywords)
               for _n in _ast.walk(_node))


leaks = []
if True:
    for _owner, _fn in _funcs:
        for _call in _ast.walk(_fn):
            if not isinstance(_call, _ast.Call):
                continue
            _name = getattr(_call.func, "attr", "")
            if _name not in ("send_message", "send", "defer"):
                continue
            # 🚨 **버튼 안의 인자 없는 `defer()`는 메시지를 만들지 않아요**
            #    (deferred_message_update - 원래 메시지를 그대로 둬요). 그래서
            #    `ephemeral`을 줄 수도 없고, 줄 필요도 없어요.
            #
            #    ⚠️ 전엔 `_fn.name == "strike"`로 **이름을 화이트리스트** 했는데,
            #    버튼을 하나 더 붙였더니(🎣 다시 던지기) 바로 오탐이 났어요. 이름이
            #    아니라 **조건**으로 막아요: View 안 + 인자 없는 defer.
            #
            #    슬래시 명령의 bare `defer()`는 반대로 "생각 중..."이 **공개로** 남아요.
            #    그래서 View 클래스 안일 때만 면제해요.
            #
            #    ⚠️ 2026-10-17: `run_cast`가 **두 경로를 같이** 처리하게 되면서
            #    (컴포넌트는 bare defer, 슬래시는 `ephemeral=True`) View 밖에도
            #    정당한 bare defer가 생겼어요. 그래서 면제 조건을 하나 더 둬요 -
            #    **같은 `if` 안에서 슬래시 경로가 ephemeral로 갈라져 있으면**
            #    이 bare defer는 컴포넌트 전용이라는 뜻이에요. 함수 이름을
            #    화이트리스트하는 짓(위 실수)을 되풀이하지 않으려고 조건으로 막아요.
            if (_name == "defer" and not _call.args and not _call.keywords
                    and (_owner in _view_classes
                         or any(_contains(_if, _call) and _has_eph_defer(_if)
                                for _if in _ast.walk(_fn)
                                if isinstance(_if, _ast.If)))):
                continue
            if _fn.name in PUBLIC_OK:
                continue
            eph = any(k.arg == "ephemeral" and getattr(k.value, "value", None) is True
                      for k in _call.keywords)
            if not eph:
                leaks.append(f"{_owner}.{_fn.name} {_name}() line {_call.lineno}")

check("🚨 /낚시·/어항·/물고기판매의 모든 응답이 ephemeral", not leaks,
      "공개로 남은 곳: " + ", ".join(leaks) if leaks else "")
check("/낚시왕은 공개 (순위표)", "leaderboard" in PUBLIC_OK)

# ==================================================================
print("\n[12] 🎣 다시 던지기")
# ------------------------------------------------------------------
# 결과 화면의 🎣 버튼으로 바로 또 던져요. 내구도가 10회라 `/낚시`를 열 번
# 치게 하는 건 번거로워요.
#
# 🚨 여기서 제일 위험한 건 **연타**예요. 내구도를 던지기 **전에** 깎으니까,
#    버튼이 두 번 먹히면 1판만 돌면서 2회가 사라져요 = 유저 돈이 녹아요.

check("CastAgainView가 있다", hasattr(fishing, "CastAgainView"))
check("run_cast가 모듈 함수로 빠져 있다", callable(getattr(fishing, "run_cast", None)))
check("finish_cast가 모듈 함수로 빠져 있다",
      callable(getattr(fishing, "finish_cast", None)))

# 🚨 로직 복붙 금지 - `/낚시`는 `run_cast` 한 줄만 불러야 해요. 복사본이 생기면
#    선차감·환불·타이밍 규칙 중 **한쪽만** 고쳐져서 조용히 어긋나요.
_fish_fn = next((f for c in _tree.body if isinstance(c, _ast.ClassDef)
                 for f in c.body
                 if isinstance(f, (_ast.AsyncFunctionDef, _ast.FunctionDef))
                 and f.name == "fish"), None)
check("/낚시는 run_cast에 그대로 넘긴다 (로직 복붙 없음)",
      _fish_fn is not None and len(_fish_fn.body) == 1
      and any(getattr(c.func, "id", "") == "run_cast"
              for c in _ast.walk(_fish_fn) if isinstance(c, _ast.Call)),
      f"본문 {len(_fish_fn.body) if _fish_fn else '?'}줄")

# 🚨 연타 방어: 두 번째 클릭은 **run_cast까지 가지 않아야** 해요.
_again_cls = next(c for c in _tree.body
                  if isinstance(c, _ast.ClassDef) and c.name == "CastAgainView")
_again_fn = next(f for f in _again_cls.body
                 if isinstance(f, (_ast.AsyncFunctionDef, _ast.FunctionDef))
                 and f.name == "again")
check("연타 방어 플래그(_started)를 본다",
      any(isinstance(n, _ast.Attribute) and n.attr == "_started"
          for n in _ast.walk(_again_fn)))
check("가드가 run_cast보다 **먼저** 있다",
      next(n.lineno for n in _ast.walk(_again_fn)
           if isinstance(n, _ast.Attribute) and n.attr == "_started")
      < next(n.lineno for n in _ast.walk(_again_fn)
             if isinstance(n, _ast.Call) and getattr(n.func, "id", "") == "run_cast"))


# 실제로 두 번 눌러봐요(가드가 동작하는지 눈으로 확인).
class _FakeResp:
    def __init__(self):
        self.defers = 0

    async def defer(self, *a, **k):
        self.defers += 1


class _FakeInter:
    def __init__(self, uid=1):
        self.user = type("U", (), {"id": uid})()
        self.response = _FakeResp()


_calls = []
_real_run = fishing.run_cast


async def _spy(interaction, *, edit):
    _calls.append(edit)
    return True          # ⚠️ 실제 `run_cast`처럼 "받아냈다"를 돌려줘야 가드가 유지돼요


fishing.run_cast = _spy
try:
    # ⚠️ discord.py는 뷰를 만들 때 버튼의 `callback`을 뷰에 묶어줘요
    #    (`_ViewCallback`). 그래서 `item.callback(interaction)` 한 번이면
    #    실제 클릭과 **같은 경로**로 들어가요.
    _v = fishing.CastAgainView(1, 7)
    _inter = _FakeInter(1)

    async def _press_twice():
        await _v.again.callback(_inter)
        first = len(_calls)
        await _v.again.callback(_FakeInter(1))     # 연타!
        return first

    _first = asyncio.run(_press_twice())
    check("한 번 누르면 run_cast가 1회 (edit=True로 메시지 재사용)",
          _first == 1 and _calls == [True], f"호출 {_calls}")
    check("🚨 두 번째 클릭은 막힌다 (내구도 2회 소모 방지)",
          len(_calls) == 1, f"run_cast가 {len(_calls)}번 불렸어요")
    check("막힌 클릭도 defer로 응답한다 (상호작용 실패 표시 방지)",
          _inter.response.defers + 1 >= 1)

    # 🚨 **한 판도 못 돌았으면 가드를 되돌려야** 해요. 안 되돌리면 그 화면의
    #    버튼이 영구히 죽어서, 낚시대가 남았는데도 `/낚시`를 다시 쳐야 해요.
    _calls.clear()

    async def _spy_dead(interaction, *, edit):
        _calls.append(edit)
        return False                 # 토큰이 죽어 아무것도 못 한 경우

    fishing.run_cast = _spy_dead
    _v2 = fishing.CastAgainView(1, 7)

    async def _press_twice_dead():
        await _v2.again.callback(_FakeInter(1))
        await _v2.again.callback(_FakeInter(1))

    asyncio.run(_press_twice_dead())
    check("🚨 던지지 못했으면 가드가 풀려서 다시 누를 수 있다",
          len(_calls) == 2, f"run_cast가 {len(_calls)}번 불렸어요")

    # ⚠️ 반대로, 판이 돈 뒤에 **화면만** 실패한 경우는 되돌리면 안 돼요
    #    (내구도가 두 번 깎여요). 실제 `run_cast`는 그 경우 True를 줘요.
    _calls.clear()

    async def _spy_boom(interaction, *, edit):
        _calls.append(edit)
        raise RuntimeError("터짐")

    fishing.run_cast = _spy_boom
    _v3 = fishing.CastAgainView(1, 7)

    async def _press_boom():
        try:
            await _v3.again.callback(_FakeInter(1))
        except RuntimeError:
            pass
        return _v3._started

    check("예외로 터져도 가드가 풀린다 (버튼이 죽지 않게)",
          asyncio.run(_press_boom()) is False)
finally:
    fishing.run_cast = _real_run

check("남은 횟수를 버튼 라벨에 적는다",
      "7" in fishing.CastAgainView(1, 7).again.label)
check("내구도 0이면 다시던지기 대신 구매 버튼",
      "BuyRodView(" in _src.split("async def finish_cast")[1].split("class ")[0])

# ==================================================================
print("\n[13] 🚨 3초 - 상호작용 토큰 만료")
# ------------------------------------------------------------------
# 2026-10-17 12:47 실제 사고: 🎣 다시 던지기가 `404 Unknown interaction (10062)`으로
# 터졌어요. 상호작용 토큰은 **3초**면 만료되는데, `use_rod()`로 Atlas를 다녀온
# **뒤에** 첫 화면을 띄우고 있었어요. 메모리가 빠듯해 왕복이 밀리면 그 3초를
# 넘겨요. 그리고 그 순서에선 **내구도는 이미 깎인 뒤**라, 유저는 아무 화면도 못 본
# 채 1회를 잃었어요.
#
# ⭐ 고친 방식: **DB보다 `defer()`가 먼저.** 받아두면 그 뒤로는 15분짜리 웹훅
#    토큰이라 DB가 얼마나 느리든 안전해요.

# ⚠️ 2026-10-18에 `run_cast`가 **가드 껍데기**로 바뀌고 실제 진행은 `_run_cast`가
#    맡게 됐어요(동시에 한 판만). 아래 3초 토큰 검사는 **던지는 쪽**을 봐야 하니
#    안쪽 함수를 대상으로 해요.
_run_fn = next(f for f in _tree.body
               if isinstance(f, (_ast.AsyncFunctionDef, _ast.FunctionDef))
               and f.name == "_run_cast")
_defer_line = next((n.lineno for n in _ast.walk(_run_fn)
                    if isinstance(n, _ast.Call)
                    and getattr(n.func, "attr", "") == "defer"), None)
_userod_line = next((n.lineno for n in _ast.walk(_run_fn)
                     if isinstance(n, _ast.Call)
                     and getattr(n.func, "attr", "") == "use_rod"), None)
check("🚨 defer가 use_rod보다 **먼저** 있다 (3초 안에 받아둔다)",
      _defer_line is not None and _userod_line is not None
      and _defer_line < _userod_line,
      f"defer {_defer_line}줄 / use_rod {_userod_line}줄")

# 🚨 첫 화면을 `interaction.response.*`로 띄우면 다시 3초 안에 묶여요.
#    `defer()` 뒤에는 **반드시** `edit_original_response`로 고쳐야 해요.
_direct = [f"line {n.lineno}" for n in _ast.walk(_run_fn) if isinstance(n, _ast.Call)
           and getattr(n.func, "attr", "") in ("send_message", "edit_message")]
check("첫 화면도 edit_original_response로 띄운다", not _direct,
      "response.send_message/edit_message가 남아 있어요: " + ", ".join(_direct)
      if _direct else "")

# 🚨 **가드 껍데기(`run_cast`)는 DB를 건드리면 안 돼요.**
#
# 거절 경로는 `defer()` 없이 바로 `send_message`로 답해요. 그게 가능한 이유는
# 메모리 dict만 보고 끝나기 때문이에요. 여기에 누가 Atlas 왕복(`fishing_store.*`,
# `coin_wallet.*`)을 끼워 넣으면 **3초 토큰이 다시 터져요** — 그것도 "이미 던져뒀어요"
# 라는 안내 한 줄 때문에요. 그래서 못 박아둬요.
_guard_fn = next(f for f in _tree.body
                 if isinstance(f, (_ast.AsyncFunctionDef, _ast.FunctionDef))
                 and f.name == "run_cast")
_guard_db = [f"line {n.lineno}: {getattr(n.func, 'attr', '?')}"
             for n in _ast.walk(_guard_fn) if isinstance(n, _ast.Call)
             and getattr(getattr(n.func, "value", None), "id", "")
             in ("fishing_store", "coin_wallet", "mission_store")]
check("🚨 동시 낚시 가드는 DB를 안 본다 (3초 토큰 재발 방지)", not _guard_db,
      ", ".join(_guard_db) if _guard_db else "메모리 dict만 봐요")

# 가드가 실제로 달려 있나 - 누가 지우면 병렬 낚시가 조용히 되살아나요.
_has_guard = any(getattr(getattr(n, "value", None), "id", "") == "_casting"
                 or getattr(n, "id", "") == "_casting"
                 for n in _ast.walk(_guard_fn))
check("🚨 `run_cast`에 동시 실행 가드가 있다", _has_guard,
      "_casting을 참조해요" if _has_guard else "⚠️ _casting 참조가 사라졌어요")


# 실제로 토큰이 죽은 상황을 흉내내요 - 낚시대가 깎이면 안 돼요.
class _FakeHTTPResp:
    status = 404
    reason = "Not Found"


def _unknown_interaction():
    import discord
    return discord.NotFound(_FakeHTTPResp(),
                            {"code": 10062, "message": "Unknown interaction"})


class _DeadResp:
    async def defer(self, *a, **k):
        raise _unknown_interaction()


class _DeadInter:
    def __init__(self, uid=1):
        self.user = type("U", (), {"id": uid})()
        self.response = _DeadResp()


_use_rod_calls = []
_real_use_rod = fishing.fishing_store.use_rod


async def _spy_use_rod(uid):
    _use_rod_calls.append(uid)
    return 5


fishing.fishing_store.use_rod = _spy_use_rod
try:
    _ok = asyncio.run(fishing.run_cast(_DeadInter(1), edit=True))
    check("🚨 토큰이 죽었으면 **내구도를 건드리지 않는다**",
          _use_rod_calls == [], f"use_rod가 {len(_use_rod_calls)}번 불렸어요")
    check("못 던졌다고 알려준다 (False)", _ok is False, f"반환 {_ok!r}")
finally:
    fishing.fishing_store.use_rod = _real_use_rod


# 정상 경로도 **끝까지** 돌려봐요. 순서만 맞아도 kwarg 하나 어긋나면 실사용에서
# 그대로 터지니까, 디스코드 호출 순서를 기록해서 눈으로 확인해요.
class _RecResp:
    def __init__(self, rec):
        self.rec = rec

    async def defer(self, *a, **k):
        self.rec.append(("defer", k.get("ephemeral", False)))

    async def send_message(self, *a, **k):
        self.rec.append(("send_message", k.get("ephemeral", False)))

    async def edit_message(self, *a, **k):
        self.rec.append(("edit_message", None))


class _RecInter:
    def __init__(self, rec, uid=1):
        self.rec = rec
        self.user = type("U", (), {"id": uid})()
        self.response = _RecResp(rec)

    async def edit_original_response(self, **k):
        self.rec.append(("edit_original", tuple(sorted(k))))

    class _FollowUp:
        def __init__(self, rec):
            self.rec = rec

        async def send(self, *a, **k):
            self.rec.append(("followup", k.get("ephemeral", False)))

    @property
    def followup(self):
        return self._FollowUp(self.rec)


_store_patch = {
    # ⚠️ `use_rod`를 **느리게** 만들어요. 고친 코드의 핵심이 "DB가 느려도 괜찮다"라,
    #    빠른 가짜로만 돌리면 정작 그 성질을 안 건드려요.
    "use_rod": lambda uid: 4,
    "record_cast": lambda uid, key, size: None,
    "give_back_rod": lambda uid: None,
    "get": lambda uid: {"tank": {}, "casts": 1, "caught": 1, "sold": 0},
}
_saved = {k: getattr(fishing.fishing_store, k) for k in _store_patch}


def _mk(fn, delay=0.0):
    async def _f(*a, **k):
        if delay:
            await asyncio.sleep(delay)
        return fn(*a, **k)
    return _f


for _k, _fn in _store_patch.items():
    setattr(fishing.fishing_store, _k, _mk(_fn, 0.05 if _k == "use_rod" else 0.0))

# 찌·입질 대기를 짧게 줄여요(테스트가 몇 초씩 멈추지 않게).
_saved_timing = (fishing.BITE_MIN, fishing.BITE_MAX, fishing.STRIKE_WAIT)
fishing.BITE_MIN, fishing.BITE_MAX, fishing.STRIKE_WAIT = 0.01, 0.02, 0.01
try:
    _rec = []
    _ok2 = asyncio.run(fishing.run_cast(_RecInter(_rec), edit=True))
    _kinds = [r[0] for r in _rec]
    check("🚨 정상 경로도 defer로 시작한다 (버튼)",
          _kinds[:1] == ["defer"], f"순서 {_kinds}")
    check("DB가 느려도 끝까지 돈다 (결과 화면까지)",
          _ok2 is True and _kinds.count("edit_original") >= 2, f"순서 {_kinds}")
    check("도중에 response.*를 다시 쓰지 않는다 (3초에 다시 묶이지 않게)",
          "send_message" not in _kinds and "edit_message" not in _kinds,
          f"순서 {_kinds}")

    _rec2 = []
    asyncio.run(fishing.run_cast(_RecInter(_rec2), edit=False))
    check("🚨 슬래시 경로의 defer는 ephemeral이다 (채널에 '생각 중'이 안 남게)",
          _rec2 and _rec2[0] == ("defer", True), f"첫 호출 {_rec2[:1]}")
finally:
    for _k, _v in _saved.items():
        setattr(fishing.fishing_store, _k, _v)
    fishing.BITE_MIN, fishing.BITE_MAX, fishing.STRIKE_WAIT = _saved_timing

# ==================================================================
print("\n[14] 🎣 /낚시확률 - 공개하는 숫자가 실제와 같나")
# ------------------------------------------------------------------
# 🚨 안내문이 옛값으로 남는 사고가 이 저장소에서 반복됐어요(`/악귀상점`의 "하루 1개"가
#    4차 이후로 거짓이었어요). 그래서 이 명령어는 **전부 fish_data에서 계산**하고,
#    여기서 ⒜ 계산이 실제 추첨과 맞는지 ⒝ 소스에 숫자를 손으로 박지 않았는지를 봐요.

import inspect  # noqa: E402
import types  # noqa: E402

_fd = fishing.fish_data

# ⒜ `expected_*`가 실제 추첨 함수와 맞나 — 치수가 작은 쪽으로 치우쳐 있어서
#    등급 중앙값으로 계산하면 과대평가돼요. 누가 "간단히" 고치면 여기서 걸려요.
_rng = Random(20261018)
_grades = list(_fd.GRADES)
_weights = [_fd.GRADES[g]["weight"] for g in _grades]
_keys = {g: [f["key"] for f in rows] for g, rows in _fd.FISH.items()}
_N, _sum = 200_000, 0
for _ in range(_N):
    _g = _rng.choices(_grades, weights=_weights, k=1)[0]
    _k = _rng.choice(_keys[_g])
    _sum += _fd.pieces_of(_k, _fd.roll_size(_k, _rng))
_mc = _sum / _N / _fd.COIN_PIECES
_calc = _fd.expected_coin_per_cast()
check("expected_coin_per_cast가 실제 추첨과 일치 (±3%)",
      abs(_calc - _mc) / _mc < 0.03,
      f"계산 {_calc:.3f} vs 몬테카를로 {_mc:.3f}")

_mid = sum(_fd.GRADES[g]["weight"] / sum(_weights) * sum(_fd.GRADES[g]["pieces"]) / 2
           for g in _grades) / _fd.COIN_PIECES
check("🚨 중앙값 근사보다 낮다 (치우침을 반영하고 있다)",
      _calc < _mid, f"계산 {_calc:.3f} < 중앙값근사 {_mid:.3f}")

# ⒝ 소스에 숫자를 손으로 박지 않았나
#    ⚠️ **독스트링·주석은 빼고** 봐요 — "중앙값으로 계산하면 14.8이 나오는데 14.1이
#    맞다"처럼 왜 그렇게 계산하는지 적어두는 건 오히려 필요한 설명이에요. 막으려는 건
#    유저에게 **보내는 문자열**에 박힌 숫자예요.
#
#    🚨 `__doc__`으로 지우려 했더니 안 됐어요 — 파이썬 3.13+는 독스트링을 컴파일할 때
#    **dedent**해서, 들여쓰기가 남은 원본 소스와 문자열이 안 맞아요. AST로 떼야 해요.
#    (`ast.unparse`는 주석도 같이 버려서 마침 원하는 결과예요.)
import textwrap  # noqa: E402

_rates_fn = fishing.Fishing.rates.callback
_fnode = _ast.parse(textwrap.dedent(inspect.getsource(_rates_fn))).body[0]
if (_fnode.body and isinstance(_fnode.body[0], _ast.Expr)
        and isinstance(getattr(_fnode.body[0].value, "value", None), str)):
    _fnode.body = _fnode.body[1:]
_src = _ast.unparse(_fnode)
_hard = [tok for tok in ("90.5", "6.7", "2.7", "14코인", "14.1", "4.13", "0.8~1.5")
         if tok in _src]
check("🚨 확률·값·평균을 소스에 하드코딩하지 않았다", not _hard, f"발견: {_hard}")


class _RatesResp:
    def __init__(self):
        self.calls = []
        self.embed = None

    async def send_message(self, *a, **kw):
        self.calls.append("send_message")
        self.embed = kw.get("embed")

    async def defer(self, **kw):
        self.calls.append("defer")


class _RatesInter:
    def __init__(self):
        self.response = _RatesResp()
        self.user = types.SimpleNamespace(id=1, display_name="t")


_ri = _RatesInter()
asyncio.run(fishing.Fishing.rates.callback(fishing.Fishing(None), _ri))
check("DB를 안 치니 defer 없이 한 방에 답한다",
      _ri.response.calls == ["send_message"], f"호출 {_ri.response.calls}")

_emb = _ri.response.embed
_blob = (_emb.description or "") + "".join(
    (f.name or "") + (f.value or "") for f in _emb.fields)

for _g in _fd.GRADE_ORDER:
    _pct = _fd.GRADES[_g]["weight"] / sum(_weights) * 100
    check(f"{_g} 확률 {_pct:.1f}%를 보여준다", f"{_pct:.1f}%" in _blob)

check("낚시대 값·내구도가 코드값과 같다",
      f"{_fd.ROD_PRICE}코인" in _blob and f"{_fd.ROD_DURABILITY}번" in _blob)
check("평균 벌이를 헬퍼값으로 보여준다",
      f"{_fd.expected_coin_per_day():.0f}코인" in _blob,
      f"{_fd.expected_coin_per_day():.0f}코인")
check("어종 14종을 전부 적는다",
      all(f["name"] in _blob for rows in _fd.FISH.values() for f in rows))
check("⚠️ 내림을 숨기지 않는다 (기대를 부풀리지 않게)", "내림" in _blob)
check("🚨 '하루 1개' 같은 옛 제한을 다시 쓰지 않는다", "하루 1개" not in _blob)

# ==================================================================
print("\n[15] 📏 치수 - 실제 크기로 바꿔도 경제는 그대로여야 한다")
# ------------------------------------------------------------------
# 2026-10-18에 치수를 실제 어종 크기로 전면 교정했어요(송사리 6→5, 철갑상어 200→350 등).
# 그걸 마음 놓고 하려면 **치수가 가격과 분리돼 있다**는 게 보장돼야 해요.

for _key, (_lo, _hi) in _fd.SIZE_BY_KEY.items():
    _name = _fd.BY_KEY[_key][1]
    check(f"{_name} 범위가 올바르다 ({_lo}~{_hi}cm)",
          isinstance(_lo, int) and isinstance(_hi, int) and 0 < _lo < _hi)

# ⭐ 핵심 성질: 범위를 아무리 늘려도 1회 기댓값이 같아야 해요. `pieces_of`가 치수를
#    **종 범위 안의 상대 위치**로 환산하기 때문이에요. 이게 깨지면 치수를 손볼 때마다
#    발행량이 조용히 따라 움직여요.
_base = _fd.expected_coin_per_cast()
_orig_sizes = dict(_fd.SIZE_BY_KEY)
try:
    _fd.SIZE_BY_KEY = {k: (lo * 5, hi * 5) for k, (lo, hi) in _orig_sizes.items()}
    _scaled = _fd.expected_coin_per_cast()

    def _mc(seed):
        _r = Random(seed)
        _gs = list(_fd.GRADES)
        _ws = [_fd.GRADES[g]["weight"] for g in _gs]
        _ks = {g: [f["key"] for f in rows] for g, rows in _fd.FISH.items()}
        _s = 0
        for _ in range(60_000):
            _g = _r.choices(_gs, weights=_ws, k=1)[0]
            _k = _r.choice(_ks[_g])
            _s += _fd.pieces_of(_k, _fd.roll_size(_k, _r))
        return _s / 60_000 / _fd.COIN_PIECES

    _mc_scaled = _mc(77)
finally:
    _fd.SIZE_BY_KEY = _orig_sizes
_mc_base = _mc(77)

check("⭐ 치수를 5배로 늘려도 기대값이 같다 (가격과 분리)",
      abs(_scaled - _base) < 1e-9, f"{_base:.4f} vs {_scaled:.4f}")
check("⭐ 실제 추첨으로도 같다", abs(_mc_scaled - _mc_base) < 0.02,
      f"원래 {_mc_base:.4f} vs 5배 {_mc_scaled:.4f}")

# 🚨 하한을 올리면 기존 치수가 **깎인다**는 걸 못 박아요. 이걸 모르고 lo를 올리면
#    어항에 든 물고기 값이 조용히 내려가요(유저 손해). 2026-10-18 교정 때 그래서
#    lo를 전부 "기존 최솟값 이하"로 잡았어요.
_k2 = "f11"                                   # 무지개송어
_lo2, _hi2 = _fd.SIZE_BY_KEY[_k2]
_small = _fd.pieces_of(_k2, _lo2 - 10)        # 하한보다 작은 물고기
check("🚨 하한보다 작으면 그 등급 **최저가**로 깎인다 (lo를 올릴 때의 대가)",
      _small == _fd.GRADES[_fd.BY_KEY[_k2][0]]["pieces"][0],
      f"{_small}조각")
_big = _fd.pieces_of(_k2, _hi2 + 10)
check("상한보다 크면 최고가 (상한을 내리는 건 안전)",
      _big == _fd.GRADES[_fd.BY_KEY[_k2][0]]["pieces"][1], f"{_big}조각")

# ==================================================================
print("\n[16] 🚨 '늦었다' 판정이 없다 (2026-10-19)")
# ------------------------------------------------------------------
# 🚨 사용자 신고(2026-10-19): **모바일에서 판정이 느리게 될 때가 있다.**
#
# 전엔 `monotonic() - bite_at > BITE_WINDOW`로 늦음을 쟀는데, 그 뺄셈에는 클릭이
# 봇까지 **오는 시간**이 섞여 있어요. 모바일은 앱이 백그라운드였거나 망이 느리면
# 그게 초 단위로 벌어져서, 제때 눌러도 놓치는 판이 생겼어요. 디스코드는 클라이언트가
# 언제 눌렀는지를 안 알려주니 받은 시각으로 재는 건 결국 회선 속도를 재는 거예요.
#
# 그래서 **입질 뒤 클릭은 언제 도착했든 성공**이에요. 이 테스트는 그 규칙을 못 박아요.
# 되돌아가면(= 시간 비교를 다시 넣으면) 여기가 FAIL이에요.
import asyncio as _aio2                                      # noqa: E402
import time as _time2                                        # noqa: E402

from cogs import fishing as _fish_cog                        # noqa: E402


class _StrikeInter:
    """챔질 버튼 하나만 받아주는 최소 상호작용."""

    def __init__(self, uid):
        class _R:
            async def defer(self_inner, *a, **k):
                pass
        self.user = type("U", (), {"id": uid})()
        self.response = _R()


def _press(bite_ago: float | None):
    """입질이 `bite_ago`초 전에 왔다고 두고 버튼을 누른 뒤 판정을 돌려줘요.

    `None`이면 아직 입질이 안 온 상태(= 성급)예요."""
    view = _fish_cog.FishingView(7)
    view.bite_at = None if bite_ago is None else _time2.monotonic() - bite_ago
    _aio2.run(view.strike.callback(_StrikeInter(7)))
    return view.result


# ⭐ 핵심: 옛 제한시간(2.5초)을 한참 넘겨도 잡혀야 해요.
for _ago in (0.0, 2.4, 2.6, 5.0, 30.0, 600.0):
    _res = _press(_ago)
    check(f"입질 {_ago:g}초 뒤에 눌러도 잡힌다", _res == "ok", f"판정 '{_res}'")

_v_late = _fish_cog.FishingView(7)
_v_late.bite_at = _time2.monotonic() - 99.0
_aio2.run(_v_late.strike.callback(_StrikeInter(7)))
check("늦은 챔질에도 어종과 치수가 둘 다 들어온다",
      _v_late.caught is not None and _v_late.size is not None,
      f"어종 {_v_late.caught} · 치수 {_v_late.size}")

# ⚠️ 미니게임은 **남아 있어야** 해요. '늦었다'만 없앤 거예요.
check("🚨 입질 **전**에 누르면 여전히 성급이다 (지연과 무관한 진짜 실수)",
      _press(None) == "early", f"판정 '{_press(None)}'")

# ⭐ 소스에서 '늦음' 비교가 사라졌는지도 확인해요. 위 동작 테스트만으로는
#    상수를 키우는 식으로 되돌려도 통과해버려요(그건 완화지 제거가 아니에요).
#
# 🚨 **AST로 봐요.** 처음엔 문자열로 `"bite_at >" not in 본문`을 봤는데, 바로 위에
#    적어둔 **설명 주석**("전엔 `monotonic() - bite_at > ...`였다")에 걸려서 FAIL이
#    났어요. 주석은 AST에 없으니 이 방식이 맞아요.
import ast as _ast16                                         # noqa: E402

_src16 = _Path(os.path.join(BOT_DIR, "cogs/fishing.py")).read_text(encoding="utf-8")
_strike_node = next(
    n for n in _ast16.walk(_ast16.parse(_src16))
    if isinstance(n, _ast16.AsyncFunctionDef) and n.name == "strike")


def _mentions_bite_at(node) -> bool:
    return any(isinstance(x, _ast16.Attribute) and x.attr == "bite_at"
               for x in _ast16.walk(node))


# `bite_at`을 쓰는 건 **`is None` 하나**만 허용해요(입질이 왔는지 깃발 확인).
#   - 뺄셈(`monotonic() - bite_at`)이 있으면 경과시간을 재는 거예요
#   - `<`/`>` 비교가 있으면 제한시간 판정이에요
_bad_ops = [
    x for x in _ast16.walk(_strike_node)
    if _mentions_bite_at(x) and (
        (isinstance(x, _ast16.BinOp) and isinstance(x.op, _ast16.Sub))
        or (isinstance(x, _ast16.Compare)
            and not all(isinstance(o, (_ast16.Is, _ast16.IsNot)) for o in x.ops)))
]
check("🚨 챔질 판정에 bite_at 경과시간 비교가 없다", not _bad_ops,
      f"시간 비교 {len(_bad_ops)}건이 돌아왔어요 — 모바일 지연이 다시 놓침이 돼요"
      if _bad_ops else "is None 깃발 확인만 남아 있어요")
check("🚨 결과 판정에 'late'가 남아 있지 않다", '"late"' not in _src16,
      "'늦었어요' 판정이 되살아났어요" if '"late"' in _src16 else "")

# 방치(아무것도 안 누름)는 여전히 놓침이에요 — 사유 문구가 '늦었다'가 아니어야 해요.
# ⚠️ `'"afk"' in 소스`로만 보면 약해요 — 결과 문구 표에 키만 남아 있어도 통과해버려요
#    (실제로 `result = "late"`로 되돌려 봤을 때 이 검사만 혼자 통과했어요).
#    **대입하는 자리**가 둘 다(run_cast의 타임아웃·on_timeout) 있는지를 봐요.
_afk_assigns = _src16.count('result = "afk"')
check("방치를 'afk'로 두는 자리가 둘 다 있다 (run_cast 타임아웃 · on_timeout)",
      _afk_assigns == 2, f"{_afk_assigns}곳 (기대 2)")
check("방치 안내 문구가 있다", '"afk": "챔질을 하지 않아서' in _src16)
check("방치 안내가 '늦었다'가 아니다", "늦었어요. 물고기가 도망갔어요." not in _src16)

# ⏱ 기다려주는 시간이 왕복 지연을 넉넉히 덮는가
check("입질 후 기다려주는 시간이 옛 제한시간(2.5초)보다 길다",
      _fish_cog.STRIKE_WAIT > 2.5, f"{_fish_cog.STRIKE_WAIT}초")
check("가드 TTL이 한 판 최대 길이보다 길다 (연타 가드가 먼저 안 풀리게)",
      _fish_cog.CAST_GUARD_TTL > _fish_cog.BITE_MAX + _fish_cog.STRIKE_WAIT,
      f"TTL {_fish_cog.CAST_GUARD_TTL:.0f}초")

# ==================================================================
# 🚨 요약은 **반드시 파일 맨 끝**에 있어야 해요. 여기보다 위에 두면 그 뒤에 추가한
#    섹션의 실패가 집계되지도, 종료코드에 반영되지도 않아요(2026-10-19에 실제로
#    [16]을 이 블록 **뒤에** 붙여서 조용히 통과했어요). 새 섹션은 이 위에.
print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
