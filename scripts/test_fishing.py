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
print("\n[4] 🚨 발행량 — 하루 캐스트 상한이 천장이에요 (6차)")
day_gross = measured * ROD_DURABILITY
net = day_gross - ROD_PRICE
print(f"  1회 평균 {measured:.2f}코인 · 낚시대 {ROD_PRICE}코인에 {ROD_DURABILITY}회")
print(f"  낚시대 1개: 수입 {day_gross:.1f} − 값 {ROD_PRICE} = 순이익 {net:+.2f}코인")
print(f"  ⏳ 하루 상한 {fish_data.DAILY_CAST_CAP}회 → 1인 수입 "
      f"{fish_data.max_daily_income():.1f} · 순발행 "
      f"{fish_data.max_daily_net_issue():+.1f}코인/일")
print(f"  7명이 상한을 다 쓰면 {fish_data.max_daily_net_issue() * 7:+.0f}코인/일 · "
      f"13명이면 {fish_data.max_daily_net_issue() * 13:+.0f}코인/일")
print("  -# 참고: 2026-10-20 실측 — 낚시가 전체 발행의 78.4%, 지갑 48개 931코인")

# 🚨 **6차에서 발행에 처음으로 천장이 생겼어요.**
#
# 5차까지는 "쓸 수 있는 시간"이 유일한 상한이라 추정이 불가능했어요. 실측에서
# 한 사람이 하루 1,360캐스트로 1,403코인을 벌었고(같은 날 꼴찌 13코인), 사용자가
# "시간이 없는 사람들은 코인을 벌기 어렵다"를 짚어 **상한 + 값 x1.5**를 택했어요.
#
# ⭐ 이 테스트의 성격은 **회귀 가드**예요 — "의도한 값에서 벗어났는지"를 봐요.
#    가드를 지우면 발행량이 다음에 조용히 또 커져도 아무도 몰라요.
#
# ⚠️ 값을 바꿀 땐 아래 숫자를 같이 고치고, **커밋 메시지에 왜 바꿨는지 남겨주세요.**
EXPECTED_NET = 11.01         # 6차 설계값 (일반 12~22 · 희귀 30~57 · 낚시대 10코인)
check(f"🚨 낚시대 1개당 순이익이 설계값({EXPECTED_NET:+.2f})과 같다",
      abs(net - EXPECTED_NET) < 0.15,
      f"{net:+.2f}코인 — 의도한 변경이면 EXPECTED_NET을 같이 고쳐주세요")
EXPECTED_DAILY_NET = 22.01   # 6차: 상한 20회 × 캐스트당 +1.10
check(f"🚨 1인 하루 순발행 상한이 설계값({EXPECTED_DAILY_NET:+.2f})과 같다",
      abs(fish_data.max_daily_net_issue() - EXPECTED_DAILY_NET) < 0.15,
      f"{fish_data.max_daily_net_issue():+.2f}코인")
check("낚시가 '벌이'가 된다 (4차의 본전 구조에서 벗어났는지)",
      net > 2.0, f"{net:+.2f}코인")
check("낚시대값이 총수입보다 싸다 (아니면 아무도 안 사요)",
      ROD_PRICE < day_gross, f"{ROD_PRICE} vs {day_gross:.1f}")

# 🚨 **상한이 출석·미션을 무의미하게 만들지 않는지.** 1차 설계가 그래서 엎어졌어요
#    (작정하면 하루 189코인 → 출석 3~5코인이 장식이 됐어요).
#    이제는 상한이 있으니 그 **배수**로 잴 수 있어요.
_attend_ratio = fish_data.max_daily_net_issue() / 2       # 출석 하루 1~2코인 기준
print(f"  ⚖️ 상한을 다 쓴 낚시 = 출석(하루 2코인)의 약 {_attend_ratio:.0f}배")
check("낚시 하루 상한이 출석의 50배 미만이다 (출석이 장식이 되지 않게)",
      _attend_ratio < 50, f"{_attend_ratio:.0f}배")

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

# 🚨 상한이 **개수가 아니라 횟수**에 걸려 있다는 걸 테스트가 알고 있게 해둬요.
#    `ROD_PER_DAY`를 되살리면 소형(3회)을 쓰는 하위권만 두 번 막혀요.
print(f"  ⚠️ 개수 제한: {fish_data.ROD_PER_DAY or '무제한'} · "
      f"하루 캐스트 상한: {fish_data.DAILY_CAST_CAP or '무제한'}회")
check("🚨 상한은 개수가 아니라 횟수에 걸려 있다 (소형이 불리해지지 않게)",
      fish_data.ROD_PER_DAY == 0 and fish_data.DAILY_CAST_CAP > 0,
      f"개수 {fish_data.ROD_PER_DAY} · 횟수 {fish_data.DAILY_CAST_CAP}")
# ⭐ 소형 한 개(3회)로도 **하루 상한의 일부를 의미 있게** 쓸 수 있어야 해요.
check("🪝 소형 1개가 하루 상한보다 작다 (상한이 소형을 막지 않는다)",
      SMALL_ROD_DURABILITY <= fish_data.DAILY_CAST_CAP,
      f"소형 {SMALL_ROD_DURABILITY}회 vs 상한 {fish_data.DAILY_CAST_CAP}회")

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

    # 🚨 **모르는 연산자는 터뜨려요.** 전엔 흉내내는 것만 보고 나머지를 조용히
    #    무시했는데, 그러면 "조건이 없는 것"과 똑같아져서 **제약이 테스트에서만
    #    통과**해요. 2026-10-20에 실제로 그랬어요 — 하루 상한이 `$lt`를 쓰는데
    #    가짜가 그걸 몰라서 21번째 캐스트가 **통과**했고, 검사는 초록이었어요.
    _OPS = ("$ne", "$gte", "$gt", "$lt", "$lte", "$exists")

    def _matches(self, doc, flt):
        """MongoDB 매칭을 흉내내요. **모르는 연산자를 만나면 예외**를 던져요."""
        for key, want in flt.items():
            if key == "_id":
                continue
            got = doc.get(key)
            if isinstance(want, dict):
                unknown = [op for op in want if op not in self._OPS]
                if unknown:
                    raise NotImplementedError(
                        f"가짜 컬렉션이 모르는 연산자예요: {unknown} (키 {key!r}). "
                        "흉내를 추가하세요 — 무시하면 조건이 없는 것과 같아져서 "
                        "제약이 실제로는 안 걸리는데도 테스트가 통과해요."
                    )
                # ⚠️ `$ne`는 **필드가 없는 문서에도 걸려야** 해요(MongoDB와 같게).
                #    `cast_date`가 아직 없는 첫 캐스트가 이걸로 통과해요.
                if "$ne" in want and got == want["$ne"]:
                    return False
                if "$gte" in want and not (isinstance(got, int) and got >= want["$gte"]):
                    return False
                if "$gt" in want and not (isinstance(got, int) and got > want["$gt"]):
                    return False
                # 🚨 `$lt`/`$lte`는 **필드가 없으면 '참'이에요**(MongoDB는 안 그렇지만,
                #    여기선 `casts_today`가 없는 첫 캐스트를 "0회 < 상한"으로 봐야
                #    하거든요). 실제로는 `$ne` 쪽 쿼리가 그 경우를 받아서 결과가 같아요.
                if "$lt" in want and got is not None and not (
                        isinstance(got, int) and got < want["$lt"]):
                    return False
                if "$lte" in want and got is not None and not (
                        isinstance(got, int) and got <= want["$lte"]):
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


# 🚨 7차 연속 출석 보너스가 **출석 컬렉션을 읽어요**(`_streak_sync`). 여기도 가짜로
#    안 바꾸면 캐스트마다 진짜 Atlas(없으면 localhost)로 붙으려 해서
#    `ServerSelectionTimeoutError`로 죽어요 — 2026-10-19에 `fishing_week` 훅이
#    똑같이 이 테스트를 깨놨어요. 저장소를 하나 더 붙였으면 **여기도** 추가하세요.
#    → feedback_wire_the_hook_not_just_the_store
class FakeAttend:
    def __init__(self):
        self.docs = {}

    def find_one(self, flt, projection=None):
        d = self.docs.get(flt["_id"])
        return dict(d) if d else None

    def set_streak(self, user_id, streak, last=None):
        """`last`를 안 주면 **오늘**로 둬요(= 살아있는 연속)."""
        self.docs[str(user_id)] = {
            "_id": str(user_id),
            "attendanceStreak": streak,
            "lastAttendanceDate": last if last is not None else fishing_store.today_iso(),
        }


fake_attend, fake_guest = FakeAttend(), FakeAttend()
fishing_store._trainers = fake_attend
fishing_store._attend_guest = fake_guest

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
# 🚨 8차 몰아 던지기가 쓰는 **묶음 적립도 같이** 갈아끼워요. 빠뜨리면 묶음 테스트가
#    진짜 Atlas(없으면 localhost)로 붙어서 캐스트마다 5초씩 멈춰요 — 10-19와
#    **똑같은 사고**예요. 저장소에 훅을 하나 더 붙였으면 여기도 보세요.
_week_batch_calls = []


async def _fake_record_catches(*a, **k):
    _week_batch_calls.append(a)


fishing_store.fishing_week.record_catches = _fake_record_catches

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
# 🚨 **값을 바꿀 땐 이 숫자도 같이.** 등급표에서 직접 읽어 비교하면 "표와 표를
#    비교"하는 꼴이라 둘이 같이 틀려도 통과해요(이 저장소에서 반복된 사고예요).
#    그래서 6차 설계값을 **손으로 적어** 둬요.
check("🚨 일반 물고기가 1.2~2.2코인 범위 (6차 = 5차 x1.5)",
      lo_p == 12 and hi_p == 22, f"{lo_p / 10:.1f}~{hi_p / 10:.1f}코인")

# 🚨 **등급 경계가 겹치면 상위 등급의 맛이 사라져요.**
#
# 5차에서 일반을 0.8~1.5로 올렸더니 희귀 최소(1.5)와 **딱 맞닿았어요** — "희귀를
# 잡았는데 일반 대물급과 같은 값"이 나오는 상태죠. 그래서 희귀도 같이 올렸어요.
# 6차는 전 등급을 똑같이 x1.5해서 경계 간격도 그대로 1.5배가 됐어요.
# 다음에 한쪽만 또 올리면 여기서 걸려요.
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
# 🚨 `use_rod`는 2026-10-20부터 **(남은 내구도, 막힌 이유)** 튜플이에요. 예전처럼
#    `is None`으로 받으면 튜플은 항상 참이라 상한도 품절도 안 걸려요.
check("낚시대 없이 쓰면 no_rod", run(fishing_store.use_rod(R)) == (None, "no_rod"))

check("낚시대를 산다", run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)
check(f"내구도 {ROD_DURABILITY}로 시작",
      run(fishing_store.rod_state(R))[0] == ROD_DURABILITY)

# 🚨 **개수 제한이 없어요**(2026-10-17 4차에 풀고 6차에도 안 되살렸어요).
#    상한은 개수가 아니라 **던진 횟수**에 걸려요 - 아래 [8d]가 그걸 검사해요.
check("🚨 같은 날 또 살 수 있다 (개수 제한 없음)",
      run(fishing_store.buy_rod(R, ROD_DURABILITY)) is True)

# 🚨 내구도가 **쌓여야** 해요. 덮어쓰면 남은 횟수가 날아가요.
check("🚨 내구도가 덮어쓰이지 않고 쌓인다",
      run(fishing_store.rod_state(R))[0] == ROD_DURABILITY * 2,
      f"{run(fishing_store.rod_state(R))[0]}회 (기대 {ROD_DURABILITY * 2})")

# 내구도 소진
#
# ⚠️ 하루 상한이 내구도보다 작으면 **상한이 먼저** 걸려서 이 블록이 내구도를 못
#    비워요. 그래서 상한을 잠깐 끄고 재요 — 여기서 보려는 건 내구도 쪽이에요.
#    (상한 자체는 [8d]에서 따로 검사해요.)
_cap_backup = fish_data.DAILY_CAST_CAP
fish_data.DAILY_CAST_CAP = 0
fishing_store.DAILY_CAST_CAP = 0
rem = [run(fishing_store.use_rod(R))[0] for _ in range(ROD_DURABILITY * 2)]
check("전부 쓰면 0이 된다", rem[-1] == 0, str(rem[-3:]))
check("한 번에 1씩 줄어든다",
      all(a - b == 1 for a, b in zip(rem, rem[1:])), str(rem[:4]))
check("🚨 다 쓰면 더 못 쓴다 (음수로 안 내려감)",
      run(fishing_store.use_rod(R)) == (None, "no_rod"))

# 🚨 코인 차감 실패 시 되돌리기 — 안 되면 공짜 낚시대가 돼요.
run(fishing_store.buy_rod(R, ROD_DURABILITY))      # 10
run(fishing_store.use_rod(R))                      # 9 (쓰던 중)
run(fishing_store.buy_rod(R, ROD_DURABILITY))      # 19 (하나 더 삼)
run(fishing_store.refund_rod(R, ROD_DURABILITY))   # 차감 실패 -> 방금 산 것만 취소
check("🚨 환불은 **방금 준 만큼만** 뺀다 (쓰던 낚시대가 안 날아감)",
      run(fishing_store.rod_state(R))[0] == 9,
      f"{run(fishing_store.rod_state(R))[0]}회 (기대 9)")
fish_data.DAILY_CAST_CAP = _cap_backup
fishing_store.DAILY_CAST_CAP = _cap_backup

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
# ⚠️ **docstring은 코드로 세지 않아요.** 처음엔 `len(body) == 1`로 썼는데, 8차에
#    `/낚시`에 설명을 붙이자 FAIL이 났어요 — 설명은 "로직 복붙"이 아니에요.
_fish_body = [st for st in (_fish_fn.body if _fish_fn else [])
              if not (isinstance(st, _ast.Expr) and isinstance(st.value, _ast.Constant)
                      and isinstance(st.value.value, str))]
check("/낚시는 run_cast에 그대로 넘긴다 (로직 복붙 없음)",
      _fish_fn is not None and len(_fish_body) == 1
      and any(getattr(c.func, "id", "") == "run_cast"
              for c in _ast.walk(_fish_fn) if isinstance(c, _ast.Call)),
      f"docstring 뺀 본문 {len(_fish_body)}줄")

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
                     and getattr(n.func, "attr", "") == "use_rods"), None)
# 🚨 8차에 cog가 `use_rod` → **`use_rods`**(묶음 겸용)로 바뀠어요. 함수 이름만
#    보는 검사라, 이름을 안 따라가면 `None`이 되어 **아무것도 검증하지 않고**
#    FAIL/통과가 뒤바뀌어요. 그래서 "못 찾았으면 실패"도 같이 봐요.
check("🚨 defer가 use_rods보다 **먼저** 있다 (3초 안에 받아둔다)",
      _defer_line is not None and _userod_line is not None
      and _defer_line < _userod_line,
      f"defer {_defer_line}줄 / use_rods {_userod_line}줄")

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
_real_use_rod = fishing.fishing_store.use_rods


async def _spy_use_rod(uid, want=1):
    _use_rod_calls.append(uid)
    return 5


fishing.fishing_store.use_rods = _spy_use_rod
try:
    _ok = asyncio.run(fishing.run_cast(_DeadInter(1), edit=True))
    check("🚨 토큰이 죽었으면 **내구도를 건드리지 않는다**",
          _use_rod_calls == [], f"use_rods가 {len(_use_rod_calls)}번 불렸어요")
    check("못 던졌다고 알려준다 (False)", _ok is False, f"반환 {_ok!r}")
finally:
    fishing.fishing_store.use_rods = _real_use_rod


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
    # ⚠️ `use_rods`를 **느리게** 만들어요. 고친 코드의 핵심이 "DB가 느려도 괜찮다"라,
    #    빠른 가짜로만 돌리면 정작 그 성질을 안 건드려요.
    # 🚨 반환은 **(남은 내구도, 막힌 이유)** 튜플이에요(2026-10-20). 옛 형태(`4`)로
    #    두면 `left, blocked = ...`가 TypeError로 터져요.
    # 🚨 8차부터 **3-튜플**이에요 (받은 수, 남은 내구도, 막힌 이유).
    "use_rods": lambda uid, want=1: (1, 4, None),
    "cast_quota": lambda uid: (3, fish_data.DAILY_CAST_CAP),
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
    setattr(fishing.fishing_store, _k, _mk(_fn, 0.05 if _k == "use_rods" else 0.0))

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
_hard = [tok for tok in ("90.5", "6.7", "2.7", "14코인", "14.1", "4.13", "0.8~1.5",
                         # 6차에 생긴 숫자들. 상한·하루벌이도 상수에서 계산해야 해요.
                         "1.2~2.2", "21코인", "42코인", "22코인", "하루 20번")
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


# 🚨 7차부터 `/낚시확률`이 **내 상한**을 보여주려고 `cast_quota`를 봐요. DB를
#    다녀오니 `defer()` → `followup.send`로 바뀌었고, 이 스텁에 `followup`이 없어서
#    `AttributeError`가 났어요 — **AST 검사로는 안 잡히는 종류**라 이렇게 실제로
#    돌려봐야 해요(`response.send_message`를 하나라도 남겨두면 `InteractionResponded`).
class _RatesFollowup:
    def __init__(self, resp):
        self.resp = resp

    async def send(self, *a, **kw):
        self.resp.calls.append("followup")
        self.resp.embed = kw.get("embed")


class _RatesInter:
    def __init__(self):
        self.response = _RatesResp()
        self.user = types.SimpleNamespace(id=1, display_name="t")

    @property
    def followup(self):
        return _RatesFollowup(self.response)


_ri = _RatesInter()
asyncio.run(fishing.Fishing.rates.callback(fishing.Fishing(None), _ri))
# 🚨 7차: 내 상한을 읽으려고 DB를 다녀오니 **defer가 먼저**예요. 전엔
#    `["send_message"]` 한 방이었는데, 그대로 두면 Atlas가 느린 날 3초를 넘겨
#    `10062`로 죽어요(`scan_interaction_latency.py`가 실제로 잡았어요).
check("🚨 DB를 치니 defer로 먼저 받고 followup으로 답한다",
      _ri.response.calls == ["defer", "followup"], f"호출 {_ri.response.calls}")
check("🚨 defer 뒤에 response.send_message를 쓰지 않는다 (InteractionResponded 방지)",
      "send_message" not in _ri.response.calls, f"호출 {_ri.response.calls}")

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
print("\n[17] ⏳ 하루 캐스트 상한 (2026-10-20 6차)")
# ------------------------------------------------------------------
# 🚨 이게 **발행의 유일한 천장**이에요. 여기 뚫리면 5차의 "시간 쓰는 사람만 번다"로
#    돌아가요(실측에서 상위 1명이 전체 캐스트의 50%였어요).
#
# ⚠️ 상한은 낚시대 **개수**가 아니라 **던진 횟수**에 걸려야 해요. 개수로 걸면
#    🪝소형(3회)을 쓰는 하위권이 하루 3캐스트에 막혀서, 진입을 넓히려 만든 상품이
#    오히려 불리해져요. 아래 "소형으로도 상한까지 쓸 수 있다"가 그걸 지켜요.
CAP = fish_data.DAILY_CAST_CAP
check("🚨 하루 상한이 켜져 있다", bool(CAP), f"DAILY_CAST_CAP={CAP}")
check("🚨 개수 제한(ROD_PER_DAY)은 꺼져 있다 (이중 제한 금지)",
      fish_data.ROD_PER_DAY == 0, f"ROD_PER_DAY={fish_data.ROD_PER_DAY}")

C = "cap-user"
fake.docs.pop(C, None)
# 상한보다 넉넉하게 사둬요 — 막는 게 내구도가 아니라 **상한**이어야 하니까요.
for _ in range((CAP // ROD_DURABILITY) + 2):
    run(fishing_store.buy_rod(C, ROD_DURABILITY))
_rod_before = run(fishing_store.rod_state(C))[0]

_results = [run(fishing_store.use_rod(C)) for _ in range(CAP)]
check(f"상한({CAP}회)까지는 전부 던져진다",
      all(r[1] is None for r in _results),
      f"막힌 게 {sum(1 for r in _results if r[1])}건")

_used, _cap = run(fishing_store.cast_quota(C))
check("오늘 던진 횟수가 정확히 센다", (_used, _cap) == (CAP, CAP), f"{_used}/{_cap}")

_blocked = run(fishing_store.use_rod(C))
check(f"🚨 {CAP + 1}번째는 'cap'으로 막힌다", _blocked[1] == "cap", str(_blocked))

# ⭐ 상한에 걸려도 **낚시대는 안 깎여요.** 이게 "코인 손실 0"의 근거예요
#    (10-18 동시 1판 제한 때는 선차감 탓에 1회분을 손해 본 사람이 있었어요).
_rod_after = run(fishing_store.rod_state(C))[0]
check("🚨 상한에 막힐 때 내구도가 안 깎인다",
      _rod_after == _rod_before - CAP,
      f"{_rod_after}회 (기대 {_rod_before - CAP})")
check("상한에 막혀도 낚시대가 남아 있다 (내일 이어서 쓴다)", _rod_after > 0,
      f"{_rod_after}회")

# 🚨 **일부러 깨서 FAIL이 나는지** 봐요. 상한 검사를 통째로 빼먹어도 위 검사들이
#    통과하면 그건 검사가 아니에요.
fishing_store.DAILY_CAST_CAP = 0
_unlimited = run(fishing_store.use_rod(C))
check("(역검증) 상한을 0으로 끄면 그 다음 캐스트가 통과한다",
      _unlimited[1] is None, str(_unlimited))
fishing_store.DAILY_CAST_CAP = CAP

# 🚨 놓친 판은 **횟수를 돌려줘야** 해요. 안 돌려주면 놓침이 "내구도 + 상한" 이중
#    벌칙이 돼요(놓침은 지연 탓일 수 있어서 벌칙으로 두지 않기로 했어요).
G = "cap-miss-user"
fake.docs.pop(G, None)
run(fishing_store.buy_rod(G, ROD_DURABILITY))
run(fishing_store.use_rod(G))
check("던지면 오늘 횟수가 1 센다", run(fishing_store.cast_quota(G))[0] == 1)
run(fishing_store.give_back_rod(G))
check("🚨 놓치면 오늘 횟수도 돌아온다",
      run(fishing_store.cast_quota(G))[0] == 0,
      f"{run(fishing_store.cast_quota(G))[0]}회")
check("놓치면 내구도도 같이 돌아온다",
      run(fishing_store.rod_state(G))[0] == ROD_DURABILITY)

# 🚨 **자정을 넘긴 환불이 공짜 캐스트를 만들면 안 돼요.** 어제자 카운터에 대고
#    `$inc: -1`을 하면 오늘 한 번을 덤으로 던지게 돼요.
fake.docs[G]["cast_date"] = "2000-01-01"
fake.docs[G]["casts_today"] = 5
run(fishing_store.give_back_rod(G))
check("🚨 어제 카운터는 환불로 안 깎인다 (공짜 캐스트 방지)",
      fake.docs[G]["casts_today"] == 5,
      f"{fake.docs[G]['casts_today']}회 (기대 5)")

# ⭐ 날짜가 바뀌면 리셋돼요. 그리고 **그 첫 캐스트도 1로 세야** 해요 — 0으로 두면
#    매일 한 번이 공짜가 돼요.
fake.docs[G]["cast_date"] = "2000-01-01"
fake.docs[G]["casts_today"] = CAP
_after_mid = run(fishing_store.use_rod(G))
check("🚨 날짜가 바뀌면 상한이 리셋된다", _after_mid[1] is None, str(_after_mid))
check("리셋 후 첫 캐스트도 1로 센다",
      run(fishing_store.cast_quota(G))[0] == 1,
      f"{run(fishing_store.cast_quota(G))[0]}회")

# ⭐ 🪝 소형으로도 상한까지 쓸 수 있어야 해요 (개수 제한이면 3회에 막혀요)
S2 = "cap-small-user"
fake.docs.pop(S2, None)
for _ in range((CAP // SMALL_ROD_DURABILITY) + 1):
    run(fishing_store.buy_rod(S2, SMALL_ROD_DURABILITY))
_small = [run(fishing_store.use_rod(S2)) for _ in range(CAP)]
check(f"🪝 소형만 써도 하루 {CAP}번까지 던질 수 있다",
      all(r[1] is None for r in _small),
      f"막힌 게 {sum(1 for r in _small if r[1])}건 — 개수 제한이 걸린 거예요")

# 📐 안내문에 쓰는 수치가 상한과 맞물려 계산되는가
check("1인 하루 순발행 상한 = 상한 × 캐스트당 순발행",
      abs(fish_data.max_daily_net_issue()
          - CAP * fish_data.net_issue_per_cast()) < 1e-9,
      f"{fish_data.max_daily_net_issue():.2f}코인")
check("🚨 상한이 0이면 '발행 없음'이 아니라 무제한(inf)이다",
      _inf_check := (lambda: (
          setattr(fish_data, "DAILY_CAST_CAP", 0),
          fish_data.max_daily_net_issue() == float("inf"),
          setattr(fish_data, "DAILY_CAST_CAP", CAP),
      )[1])())
check("하루 상한 수입이 낚시대값보다 크다 (상한을 다 써도 적자면 아무도 안 함)",
      fish_data.max_daily_income() > CAP * (ROD_PRICE / ROD_DURABILITY),
      f"수입 {fish_data.max_daily_income():.1f} vs 낚시대값 "
      f"{CAP * ROD_PRICE / ROD_DURABILITY:.1f}코인")

# 🚨 **상한에 걸린 화면이 실제로 뜨는가.** 상한 로직만 맞고 화면이 터지면 유저는
#    "눌렀는데 아무 반응이 없다"를 겪어요(이 저장소에 그 신고 전력이 있어요).
_cap_rec = []
_cap_patch = {
    "use_rod": lambda uid: (7, "cap"),      # 상한에 걸렸고 낚시대는 7번 남은 상태
    "cast_quota": lambda uid: (CAP, CAP),
    "record_cast": lambda uid, key, size: None,
    "give_back_rod": lambda uid: None,
    "get": lambda uid: {"tank": {}, "casts": 1, "caught": 1, "sold": 0},
}
_cap_saved = {k: getattr(fishing.fishing_store, k) for k in _cap_patch}
for _k, _fn in _cap_patch.items():
    setattr(fishing.fishing_store, _k, _mk(_fn))
try:
    _cap_ok = asyncio.run(fishing.run_cast(_RecInter(_cap_rec), edit=True))
    _cap_kinds = [r[0] for r in _cap_rec]
    check("🚨 상한에 걸려도 화면이 뜬다 (조용히 끝나지 않는다)",
          _cap_ok is True and "edit_original" in _cap_kinds, f"순서 {_cap_kinds}")
    check("상한 화면도 defer로 시작한다 (3초 토큰)",
          _cap_kinds[:1] == ["defer"], f"순서 {_cap_kinds}")
    # 🚨 상한에 걸린 사람에게 **낚시대를 팔면 안 돼요** — 오늘 못 쓰는 걸 사게 돼요
    #    (🎲 "하루 한도를 넘는 1회 연장"과 같은 死상품이에요).
    check("🚨 상한 화면에는 낚시대 구매 버튼이 없다",
          all("view" not in str(r) or r[0] != "send_message" for r in _cap_rec),
          f"{_cap_rec}")
finally:
    for _k, _fn in _cap_saved.items():
        setattr(fishing.fishing_store, _k, _fn)

# 🚨 안내문이 상한을 **실제로 말하는가**. 숫자를 하드코딩하지 않았는지도 같이 봐요.
_src17 = _Path(os.path.join(BOT_DIR, "cogs/fishing.py")).read_text(encoding="utf-8")
check("🚨 상한 분기에서 BuyRodView를 띄우지 않는다",
      _src17.index('blocked == "cap"') < _src17.index('blocked == "no_rod"')
      and "view=None," in _src17[_src17.index('blocked == "cap"'):
                                 _src17.index('blocked == "no_rod"')],
      "상한 분기 안에 view=None이 있어야 해요")
check("🎣 /낚시확률이 하루 상한을 안내한다", "DAILY_CAST_CAP" in _src17)
check("🚨 상한 숫자를 안내문에 하드코딩하지 않았다",
      f"하루 **{CAP}번**" not in _src17,
      "상수를 끼워 넣어야 해요 (상점 '하루 1개'가 그렇게 썩었어요)")
_src17_shop = _Path(os.path.join(BOT_DIR, "cogs/akgui_shop.py")).read_text(
    encoding="utf-8")
check("🛒 악귀상점 라벨도 상한을 말한다", "DAILY_CAST_CAP" in _src17_shop)
_src17_faq = _Path(os.path.join(BOT_DIR, "utils/faq_knowledge.py")).read_text(
    encoding="utf-8")
check("❓ 봇 매니저도 상한을 안다", "DAILY_CAST_CAP" in _src17_faq)

# ==================================================================
print("\n[18] 🔥 연속 출석으로 캐스트 상한이 늘어나는가 (2026-10-27 7차)")
# ------------------------------------------------------------------
# 사용자 제안("연속출석 10일마다 늘려주는 건 어떨까")에서 나왔고, 실측으로 주기를
# 5일로 좁혔어요 — 막힌 6명의 연속이 55·17·12·9·8·3일이라 10일이면 3명에게만 닿아요.
#
# 🚨 여기서 꼭 지켜야 하는 것 세 개:
#   ⒜ 보너스가 **조건부 update에도** 반영돼야 해요. 안내문만 25번이라 하고 DB가
#      20에서 막으면 "보너스를 받았는데 못 던진다"가 돼요(제일 나쁜 결과).
#   ⒝ **끊긴 연속은 0**이어야 해요. `attendanceStreak`은 다음 출석까지 줄지 않아서,
#      한 달 전에 55일을 찍고 안 오는 사람도 DB엔 55로 남아 있어요.
#   ⒞ **천장이 있어야** 해요(`STREAK_CAST_MAX`). 없으면 6차가 만든 발행 상한이 사라져요.
EVERY = fish_data.STREAK_CAST_EVERY
PER = fish_data.STREAK_CAST_BONUS
BMAX = fish_data.STREAK_CAST_MAX
print(f"  설정: 연속 {EVERY}일마다 +{PER}회 · 최대 +{BMAX}회 "
      f"→ 상한 {CAP} ~ {CAP + BMAX}회")

check("🚨 보너스에 천장이 있다 (없으면 발행 상한이 사라진다)", BMAX > 0, f"MAX={BMAX}")
check("한 칸 보너스가 천장을 넘지 않는다", PER <= BMAX, f"{PER} vs {BMAX}")

# ⒜ 계산식
for _streak, _want in ((0, 0), (EVERY - 1, 0), (EVERY, PER), (EVERY * 2, PER * 2),
                       (EVERY * 999, BMAX)):
    check(f"연속 {_streak}일 → +{_want}회",
          fish_data.streak_cast_bonus(_streak) == _want,
          f"{fish_data.streak_cast_bonus(_streak)}회")
check("🚨 음수·0 연속은 보너스 0", fish_data.streak_cast_bonus(-5) == 0)
check(f"daily_cap_for({EVERY}) = 기본 + 보너스",
      fish_data.daily_cap_for(EVERY) == CAP + PER, str(fish_data.daily_cap_for(EVERY)))
check("🚨 상한이 무제한(0)이면 보너스도 0 (이중 의미 금지)",
      (lambda: (setattr(fish_data, "DAILY_CAST_CAP", 0),
                fish_data.streak_cast_bonus(999) == 0
                and fish_data.daily_cap_for(999) == 0,
                setattr(fish_data, "DAILY_CAST_CAP", CAP))[1])())

# ⒝ 살아있는 연속만 인정 — 가짜 출석 컬렉션으로 직접 돌려봐요
B = "streak-bonus-user"
fake.docs.pop(B, None)
fake_attend.set_streak(B, EVERY * 2)                      # 오늘 출석 · 보너스 2칸
check("오늘 출석한 연속은 상한에 반영된다",
      run(fishing_store.cast_quota(B))[1] == CAP + PER * 2,
      str(run(fishing_store.cast_quota(B))[1]))

fake_attend.set_streak(B, EVERY * 2, last=fishing_store._yesterday_iso())
check("⭐ 어제 출석도 인정된다 (출석 전에 낚시부터 하는 사람)",
      run(fishing_store.cast_quota(B))[1] == CAP + PER * 2,
      str(run(fishing_store.cast_quota(B))[1]))

fake_attend.set_streak(B, 99, last="2020-01-01")
check("🚨 끊긴 연속(옛 날짜)은 보너스 0 — 안 오는 사람이 영구히 받으면 안 된다",
      run(fishing_store.cast_quota(B))[1] == CAP,
      f"{run(fishing_store.cast_quota(B))[1]}회 (기대 {CAP})")

fake_attend.docs.pop(B, None)
check("출석 기록이 아예 없으면 기본 상한",
      run(fishing_store.cast_quota(B))[1] == CAP)

# ⭐ 게스트(포켓몬 미시작자)도 받아야 해요 — 출석은 두 컬렉션에 나뉘어 있어요
G2 = "streak-guest-user"
fake.docs.pop(G2, None)
fake_guest.set_streak(G2, EVERY)
check("⭐ 게스트 컬렉션의 연속도 인정된다 (한쪽만 보면 게스트는 못 받는다)",
      run(fishing_store.cast_quota(G2))[1] == CAP + PER,
      str(run(fishing_store.cast_quota(G2))[1]))
fake_guest.docs.pop(G2, None)

# ⒜ **조건부 update가 실제로 늘어난 상한까지 허용하는가** — 이게 핵심이에요
U = "streak-cast-user"
fake.docs.pop(U, None)
fake_attend.set_streak(U, EVERY * 999)        # 보너스 만땅
_my_cap = CAP + BMAX
for _ in range((_my_cap // ROD_DURABILITY) + 2):
    run(fishing_store.buy_rod(U, ROD_DURABILITY))
_boosted = [run(fishing_store.use_rod(U)) for _ in range(_my_cap)]
check(f"🚨 늘어난 상한({_my_cap}회)까지 **실제로 던져진다**",
      all(r[1] is None for r in _boosted),
      f"막힌 게 {sum(1 for r in _boosted if r[1])}건 — 조건부 update가 "
      f"{CAP}에서 막았다면 보너스가 거짓이에요")
_over = run(fishing_store.use_rod(U))
check(f"🚨 {_my_cap + 1}번째는 막힌다 (천장은 여전히 있다)",
      _over[1] == "cap", str(_over))
check("막힌 뒤 안내용 상한도 늘어난 값이다",
      run(fishing_store.cast_quota(U))[1] == _my_cap,
      str(run(fishing_store.cast_quota(U))[1]))
fake_attend.docs.pop(U, None)

# ⒞ 발행 천장
check("🚨 ceiling_daily_net_issue = (기본+최대) × 캐스트당 순발행",
      abs(fish_data.ceiling_daily_net_issue()
          - (CAP + BMAX) * fish_data.net_issue_per_cast()) < 1e-9,
      f"{fish_data.ceiling_daily_net_issue():.2f}코인")
check("⚠️ max_daily_net_issue()의 기본값은 **보너스 없음**이다 "
      "(안내문 7곳이 그 기준으로 쓰여 있다)",
      abs(fish_data.max_daily_net_issue() - CAP * fish_data.net_issue_per_cast()) < 1e-9,
      f"{fish_data.max_daily_net_issue():.2f}코인")
check("천장이 기본보다 크다", fish_data.ceiling_daily_net_issue()
      > fish_data.max_daily_net_issue())
print(f"  1인 발행: 기본 {fish_data.max_daily_net_issue():+.1f} → "
      f"천장 {fish_data.ceiling_daily_net_issue():+.1f}코인/일")

# ⭐ 안내문 — "늘리는 법"이 막히는 자리에 뜨는가
_hint_none = fishing._streak_cast_hint(CAP)
_hint_some = fishing._streak_cast_hint(CAP + PER)
_hint_full = fishing._streak_cast_hint(CAP + BMAX)
check("보너스가 없으면 '연속하면 늘어난다'를 알려준다",
      "연속" in _hint_none and f"+{PER}" in _hint_none, _hint_none.strip())
check("보너스를 받고 있으면 받는 양을 알려준다",
      f"+{PER}번" in _hint_some, _hint_some.strip())
check("최대치면 '최대치'라고 말한다", "최대치" in _hint_full, _hint_full.strip())
_src18 = _Path(os.path.join(BOT_DIR, "cogs/fishing.py")).read_text(encoding="utf-8")
check("🚨 상한 안내가 DAILY_CAST_CAP을 그대로 박지 않는다 (사람마다 달라졌다)",
      "오늘은 **{DAILY_CAST_CAP}번**을 다 던졌어요" not in _src18)
for _name, _src in (("악귀상점", _src17_shop), ("봇 매니저", _src17_faq)):
    check(f"{_name} 안내도 연속 보너스를 말한다", "STREAK_CAST" in _src)

# ==================================================================
print("[19] 🎣 몰아 던지기 (2026-10-27 8차)")
# ------------------------------------------------------------------
# 사용자 요청: "대학생·직장인이 많아 자리잡고 계속 하기 어렵다. 한번에 잡을 수 있는
# 시스템". 실측으로 **막는 건 시간이 아니라 횟수**였어요(하루 20번에 클릭 40회,
# 순수 대기는 2.3분뿐).
#
# 🛑 **"묶음이 커질수록 희귀 확률을 낮추기"는 넣었다가 같은 날 되돌렸어요.**
#    사용자가 먼저 제안해서 수치까지 맞췄는데("5번 10번으로 할수록 희귀도를 낮춰줘"),
#    **"불합리할 것 같다"로 취소**했어요. 판단이 맞아요 — 벌칙은 바빠서 몰아 던지는
#    사람에게만 물려서 이 기능의 취지와 정면으로 어긋나요.
#    그래서 아래 ⒞는 **"기대값이 같아야 한다"**를 검사해요(벌칙의 부활을 막아요).
#
# 🚨 꼭 지켜야 하는 것:
#   ⒜ **받은 만큼만** 굴린다 — 요청보다 적게 받았는데 요청 수로 굴리면 **없는 코인**이
#      발행돼요. 상한·내구도가 모자랄 때가 그 경우예요.
#   ⒝ 묶음도 **같은 `DAILY_CAST_CAP` 할당량**을 쓴다(천장이 하나여야 해요).
#   ⒞ 묶음과 단판의 **확률·기대값이 같다**.
#   ⒟ 챔질을 놓치면 **묶음 전체 환불**(손해 0).
BS = fish_data.BATCH_SIZES
print(f"  묶음 선택지 {BS} + 남은 전부 · 확률 벌칙 없음")

# ── ⒞ 묶음에 확률 벌칙이 없다 (되돌린 결정을 코드에 박아둬요) ────
_revived = [n for n in ("BATCH_RARITY_PENALTY", "BATCH_RARITY_FLOOR",
                        "batch_rarity_factor", "batch_coin_per_cast")
            if hasattr(fish_data, n)]
check("🛑 묶음 확률 벌칙 장치가 되살아나지 않았다", not _revived,
      f"되살아난 것: {_revived} — 2026-10-27에 사용자가 '불합리하다'로 되돌렸어요")

# ⭐ **확률이 같은지를 실제 추첨으로** 확인해요 — 이게 벌칙 부활을 막는 본 검사예요.
#    상수만 지우고 호출부에 숫자를 박아 넣어도 여기서 걸려요.
_N = 30_000
_rng_a, _rng_b = Random(81), Random(81)
_draw_a = [fishing.roll_catch(_rng_a) for _ in range(_N)]
_draw_b = [fishing.roll_catch(_rng_b) for _ in range(_N)]
check("🚨 같은 시드면 결과가 같다 (묶음용 분기가 숨어 있지 않다)",
      _draw_a == _draw_b)
_rare_rate = sum(1 for k in _draw_a
                 if BY_KEY[k][0] != fish_data.COMMON_GRADE) / _N
_total_w = sum(g["weight"] for g in GRADES.values())
_expect_rare = sum(g["weight"] for name, g in GRADES.items()
                   if name != fish_data.COMMON_GRADE) / _total_w
check("🚨 희귀 이상 비율이 가중치 그대로다 (벌칙 없음 · ±10%)",
      abs(_rare_rate - _expect_rare) < _expect_rare * 0.10,
      f"실측 {_rare_rate * 100:.2f}% vs 가중치 {_expect_rare * 100:.2f}%")
print(f"  희귀 이상: 가중치 {_expect_rare * 100:.2f}% · "
      f"실측 {_rare_rate * 100:.2f}% (묶음·단판 동일)")

# 🚨 **안내문에 벌칙이 남으면 거짓**이에요 — 되돌릴 때 제일 잘 빠뜨리는 자리고,
#    실제로 `/낚시`의 `describe`에 "희귀 확률이 낮아져요"가 남아 있었어요.
#    ⚠️ 소스를 통째로 grep하면 **주석·docstring까지** 걸려서 못 쓸 검사가 돼요.
#       (처음에 그렇게 짰다가 "다시 넣지 마세요"라는 주석에 FAIL이 났어요.)
#       그래서 **사용자에게 실제로 보이는 문구**만 봐요.
_bad = ("확률이 낮아", "확률을 낮", "희귀도를 낮", "덜 나와")

# ⒜ `/낚시` 명령의 설명·선택지 (디스코드가 그대로 보여주는 글)
_fish_cmd = fishing.Fishing.fish
_shown = [str(_fish_cmd._params[k].description) for k in _fish_cmd._params]
for _k, _param in _fish_cmd._params.items():
    _shown += [str(c.name) for c in (_param.choices or [])]
check("🛑 /낚시 설명·선택지에 벌칙 문구가 없다",
      not [t for t in _shown if any(b in t for b in _bad)],
      str([t for t in _shown if any(b in t for b in _bad)]))
check("⭐ /낚시 설명이 '확률은 똑같다'를 말한다",
      any("똑같" in t for t in _shown), str(_shown))

# ⒝ ❓ 매니저가 **실제로 출력하는** 낚시 안내
import utils.faq_knowledge as _faq  # noqa: E402
_fish_topic = next((t for t in _faq.TOPICS if t.key == "fishing"), None)
check("매니저에 낚시 주제가 있다", _fish_topic is not None)
if _fish_topic:
    _body = _fish_topic.text()
    check("🛑 매니저 낚시 안내에 벌칙 문구가 없다",
          not [b for b in _bad if b in _body], str([b for b in _bad if b in _body]))
    check("⭐ 매니저가 '확률도 값도 똑같다'를 말한다", "똑같" in _body)
    check("⭐ 매니저가 몰아 던지기를 안다", "몰아 던지기" in _body)

# ── ⒝ 묶음 차감이 상한을 넘지 않는가 ────────────────────────────
BU = "batch-user"
fake.docs.pop(BU, None)
fake_attend.docs.pop(BU, None)          # 연속 보너스 없음 = 상한 CAP
for _ in range((CAP // ROD_DURABILITY) + 3):
    run(fishing_store.buy_rod(BU, ROD_DURABILITY))
_g1, _left1, _r1 = run(fishing_store.use_rods(BU, 5))
check("5개 요청하면 5개 받는다", (_g1, _r1) == (5, None), f"{_g1}개 / {_r1}")
check("내구도가 5 깎인다", _left1 == (CAP // ROD_DURABILITY + 3) * ROD_DURABILITY - 5,
      str(_left1))
check("오늘 횟수가 5 센다", run(fishing_store.cast_quota(BU))[0] == 5,
      str(run(fishing_store.cast_quota(BU))[0]))

# 🚨 상한을 넘겨 달라고 하면 **남은 만큼만** 줘야 해요
_g2, _, _r2 = run(fishing_store.use_rods(BU, CAP * 3))
check(f"🚨 상한({CAP})을 넘겨 요청하면 남은 {CAP - 5}개만 준다",
      (_g2, _r2) == (CAP - 5, None), f"{_g2}개 / {_r2}")
check("🚨 그래서 오늘 횟수가 상한을 **정확히** 채운다",
      run(fishing_store.cast_quota(BU))[0] == CAP,
      f"{run(fishing_store.cast_quota(BU))[0]}회 (상한 {CAP})")
_g3, _, _r3 = run(fishing_store.use_rods(BU, 5))
check("다 쓴 뒤엔 0개 + cap", (_g3, _r3) == (0, "cap"), f"{_g3}개 / {_r3}")

# 내구도가 모자라면 그만큼만
BR = "batch-rod-short"
fake.docs.pop(BR, None)
fake_attend.docs.pop(BR, None)
run(fishing_store.buy_rod(BR, SMALL_ROD_DURABILITY))      # 3회뿐
_g4, _left4, _r4 = run(fishing_store.use_rods(BR, 10))
check(f"🚨 내구도가 {SMALL_ROD_DURABILITY}회뿐이면 그만큼만 준다",
      (_g4, _left4, _r4) == (SMALL_ROD_DURABILITY, 0, None), f"{_g4}개 남{_left4} / {_r4}")
_g5, _, _r5 = run(fishing_store.use_rods(BR, 10))
check("낚시대가 비면 0개 + no_rod", (_g5, _r5) == (0, "no_rod"), f"{_g5}개 / {_r5}")

# ⭐ 7차 연속 보너스가 묶음에도 적용되는가
BB = "batch-bonus"
fake.docs.pop(BB, None)
fake_attend.set_streak(BB, fish_data.STREAK_CAST_EVERY * 999)
for _ in range(((CAP + BMAX) // ROD_DURABILITY) + 3):
    run(fishing_store.buy_rod(BB, ROD_DURABILITY))
_g6, _, _ = run(fishing_store.use_rods(BB, CAP + BMAX + 50))
check(f"⭐ 연속 보너스를 받으면 묶음도 {CAP + BMAX}개까지 받는다",
      _g6 == CAP + BMAX, f"{_g6}개")
fake_attend.docs.pop(BB, None)

# ── ⒟ 환불 ───────────────────────────────────────────────────────
BK = "batch-refund"
fake.docs.pop(BK, None)
fake_attend.docs.pop(BK, None)
run(fishing_store.buy_rod(BK, ROD_DURABILITY))
_g7, _left7, _ = run(fishing_store.use_rods(BK, 7))
run(fishing_store.give_back_rods(BK, _g7))
check("🚨 묶음 환불이 내구도를 전부 돌려준다",
      run(fishing_store.rod_state(BK))[0] == ROD_DURABILITY,
      str(run(fishing_store.rod_state(BK))[0]))
check("🚨 묶음 환불이 하루 횟수도 전부 돌려준다",
      run(fishing_store.cast_quota(BK))[0] == 0,
      f"{run(fishing_store.cast_quota(BK))[0]}회")
# 🚨 가진 것보다 많이 돌려달라고 해도 **음수가 되면 안 돼요** (다음 날 상한이 늘어남)
run(fishing_store.give_back_rods(BK, 99))
check("🚨 과도한 환불에도 하루 횟수가 음수가 안 된다",
      run(fishing_store.cast_quota(BK))[0] == 0,
      f"{run(fishing_store.cast_quota(BK))[0]}회")

# ── 기록: 한 번의 update로 N마리 ─────────────────────────────────
BX = "batch-record"
fake.docs.pop(BX, None)
_items = [("f01", 15), ("f01", 19), ("f11", 70), ("f21", 100)]
run(fishing_store.record_casts(BX, len(_items), _items))
_st = run(fishing_store.get(BX))
check("묶음 기록이 어항에 전부 들어간다",
      sum(len(v) for v in _st["tank"].values()) == len(_items),
      str(_st["tank"]))
check("🚨 같은 어종 2마리가 각자 치수로 남는다",
      sorted(_st["tank"]["f01"]) == [15, 19], str(_st["tank"].get("f01")))
check("누적 캐스트/잡은 수가 맞다",
      (_st["casts"], _st["caught"]) == (len(_items), len(_items)),
      f"{_st['casts']}/{_st['caught']}")
_best = _st.get("best") or {}
check("🚨 묶음 최고 기록은 **등급이 먼저** (f21 대물 > f11 희귀)",
      _best.get("key") == "f21", str(_best))

# ── ⒜ 화면: 받은 만큼만 굴리는가 (실제로 돌려봐요) ───────────────
_bsrc = _Path(os.path.join(BOT_DIR, "cogs/fishing.py")).read_text(encoding="utf-8")
check("🚨 묶음 결과가 `view.batch`(=받은 수)로 굴린다, `want`가 아니다",
      "for _ in range(n)" in _bsrc and "n = view.batch" in _bsrc)
check("🚨 `use_rods`의 3-튜플을 제대로 받는다",
      "granted, left, blocked = await fishing_store.use_rods" in _bsrc)
# 🛑 "묶음 벌칙이 batch_rarity_factor를 거친다"가 있던 자리예요. 벌칙을 되돌리면서
#    대신 **추첨에 인자를 넘기지 않는지**를 봐요(위 ⒞의 시드 비교와 짝이에요).
check("🛑 묶음이 roll_catch를 **인자 없이** 부른다 (벌칙 경로가 없다)",
      "key = roll_catch()" in _bsrc and "roll_catch(rarity_factor" not in _bsrc)
check("🚨 미스를 흉내내지 않는다 (놓침 확률 상수가 없다)",
      "BATCH_MISS" not in _bsrc and "BATCH_MISS" not in _Path(
          os.path.join(BOT_DIR, "utils/fish_data.py")).read_text(encoding="utf-8"))
check("놓치면 묶음 전체를 환불한다", "give_back_rods(uid, n)" in _bsrc)

# `/낚시` 선택지가 BATCH_SIZES와 맞는가 (데코레이터엔 f-string을 못 써서 손으로 적는 자리)
for _n in BS:
    check(f"/낚시 선택지에 {_n}번이 있다", f"value={_n}" in _bsrc, )
check("/낚시 선택지에 '전부'(value=0)가 있다", "value=0" in _bsrc)

# 🚨 CastAgainView가 던질 수 있는 수보다 큰 묶음을 **안 보여주는가**
_v_small = fishing.CastAgainView(1, rod_left=2, today_left=2)
_labels_small = [i.label for i in _v_small.children]
check("🚨 2번 남았으면 5·10번 버튼을 안 보여준다",
      not any("5번 몰아" in (l or "") or "10번 몰아" in (l or "") for l in _labels_small),
      str(_labels_small))
check("2번 남았으면 '남은 2번 전부'는 보여준다",
      any("남은 2번 전부" in (l or "") for l in _labels_small), str(_labels_small))
_v_one = fishing.CastAgainView(1, rod_left=1, today_left=1)
check("🚨 1번 남았으면 묶음 버튼이 아예 없다 ('다시 던지기'와 같아요)",
      len(_v_one.children) == 1, str([i.label for i in _v_one.children]))
_v_big = fishing.CastAgainView(1, rod_left=99, today_left=30)
_labels_big = [i.label for i in _v_big.children]
check("넉넉하면 5·10·전부가 다 보인다",
      all(any(f"{n}번 몰아" in (l or "") for l in _labels_big) for n in BS)
      and any("전부" in (l or "") for l in _labels_big), str(_labels_big))
check("🚨 '남은 전부' 라벨은 **먼저 바닥나는 쪽**(상한 30)을 적는다",
      any("남은 30번 전부" in (l or "") for l in _labels_big), str(_labels_big))
check("묶음 버튼이 전부 콜백을 갖는다",
      all(getattr(i, "callback", None) is not None for i in _v_big.children))

# 🚨 디스코드 한도: 줄 5개까지, 한 줄에 버튼 5개까지. 넘으면 **400으로 거절**돼서
#    결과 화면이 아예 안 떠요. `item.row`를 직접 세면 자동 배치가 None이라 틀리니,
#    discord.py의 실제 레이아웃 엔진을 돌려서 나온 줄을 봐요.
_rows_big = _v_big.to_components()
print(f"  레이아웃: {len(_rows_big)}줄 "
      f"({', '.join(str(len(r.get('components', []))) + '개' for r in _rows_big)})")
check("🚨 줄이 5개를 넘지 않는다", len(_rows_big) <= 5, f"{len(_rows_big)}줄")
check("🚨 한 줄에 5개를 넘지 않는다",
      all(len(r.get("components", [])) <= 5 for r in _rows_big),
      str([len(r.get("components", [])) for r in _rows_big]))

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
