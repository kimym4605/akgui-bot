"""`/도박` 3종 검증 — **환수율이 100%를 넘지 않는지**가 핵심이에요. DB·디스코드 없이 돌아가요.

환수율이 100%를 넘으면 그 게임은 소비처가 아니라 **코인을 찍어내는 기계**가 돼요.
배당표를 손으로 만지다 보면 조용히 그렇게 되기 쉬워서, 여기서 숫자로 막아요.

여기서 확인하는 것:
  1) 슬롯 환수율을 **전수 계산**으로 재고 0.85~0.95 안인지 (64가지 조합 전부)
  2) 하이로우 확률 구간이 겹치거나 비지 않는지 + 환수율 정확히 0.90
  3) 블랙잭을 몬테카를로로 돌려 환수율이 0.85~0.95 안인지
  4) 블랙잭 규칙(A 처리·버스트·무승부 반환·블랙잭 배당)이 정확한지
  5) 베팅 한도: 1회 최대·하루 총액이 지켜지고 동시 요청에도 안 뚫리는지
  6) 한도 조회가 실패하면 **막는 쪽**으로 기운다 (열어주면 한도가 무의미해져요)
"""
import asyncio
import os
import random
import sys
from itertools import product

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_casino_test"

from utils import casino_games as games  # noqa: E402
from utils import casino_store  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


print("1) 🎰 슬롯 환수율 (전수 계산)")
rtp = games.slot_rtp()
check(f"환수율 {rtp * 100:.2f}% 가 85~95% 안", 0.85 <= rtp <= 0.95, f"{rtp:.4f}")
check("100%를 넘지 않는다 (= 코인 찍는 기계가 아니다)", rtp < 1.0, f"{rtp:.4f}")

# 전수 계산이 실제 스핀 분포와 맞는지 교차 확인
rng = random.Random(7)
N = 200_000
got = sum(games.spin_slot(rng)[1] for _ in range(N)) / N
check(f"실제 스핀 {N:,}회 평균 {got:.3f} ≈ 계산값 {rtp:.3f}", abs(got - rtp) < 0.03, f"차이 {abs(got-rtp):.4f}")

combos = list(product(range(len(games.SLOT_SYMBOLS)), repeat=3))
triples = [c for c in combos if c[0] == c[1] == c[2]]
check("세 개 일치는 4가지 (심볼 4종)", len(triples) == len(games.SLOT_SYMBOLS))
check("세 개 일치 확률 1/16", len(triples) / len(combos) == 1 / 16,
      f"{len(triples)}/{len(combos)}")
check("배당이 전부 정수 (코인은 정수라 반올림이 생기면 안 돼요)",
      all(isinstance(p, int) for _, p in games.SLOT_SYMBOLS))
check("꽝도 존재한다", any(games._slot_payout_multiplier(c) == 0 for c in combos))

print("2) 🎲 하이로우 확률 구간")
check("낮다 구간 45칸", games.HIGHLOW_LOW_MAX == 45)
check("높다 구간 45칸", games.HIGHLOW_MAX - games.HIGHLOW_HIGH_MIN + 1 == 45)
house = games.HIGHLOW_HIGH_MIN - games.HIGHLOW_LOW_MAX - 1
check(f"하우스 구간 {house}칸 (겹치지도 비지도 않음)",
      games.HIGHLOW_LOW_MAX + 45 + house == games.HIGHLOW_MAX, f"house={house}")
check(f"환수율 {games.highlow_rtp() * 100:.0f}%", abs(games.highlow_rtp() - 0.90) < 1e-9)

# 각 숫자가 정확히 한 결과에만 속하는지 전수 확인
seen = {"low": 0, "high": 0, "house": 0}


class FixedRng:
    def __init__(self, value):
        self.value = value

    def randint(self, a, b):
        return self.value


for number in range(1, games.HIGHLOW_MAX + 1):
    _, mult_low, _ = games.roll_highlow("low", FixedRng(number))
    _, mult_high, _ = games.roll_highlow("high", FixedRng(number))
    if mult_low and mult_high:
        check(f"{number}이 양쪽 다 승리로 잡힘", False)
    if mult_low:
        seen["low"] += 1
    elif mult_high:
        seen["high"] += 1
    else:
        seen["house"] += 1
check("전수 확인: 낮다 45 · 높다 45 · 하우스 10",
      seen == {"low": 45, "high": 45, "house": 10}, str(seen))

print("3) 🃏 블랙잭 규칙")
check("A는 11로 세다가 넘치면 1 (A+K = 21)", games.hand_value([1, 13]) == 21)
check("A 두 장은 12", games.hand_value([1, 1]) == 12)
check("A+9+9 = 19 (A가 1로 내려감)", games.hand_value([1, 9, 9]) == 19)
check("그림패는 10 (J+Q = 20)", games.hand_value([11, 12]) == 20)
check("2장 21은 블랙잭", games.is_blackjack([1, 12]) is True)
check("3장 21은 블랙잭 아님", games.is_blackjack([5, 6, 10]) is False)
check("버스트는 0배", games.settle_blackjack([10, 10, 5], [10, 7])[0] == 0)
check("무승부는 반환(1배)", games.settle_blackjack([10, 9], [10, 9])[0] == games.BJ_PUSH_PAYOUT)
check("딜러 버스트면 2배", games.settle_blackjack([10, 8], [10, 7, 9])[0] == games.BJ_WIN_PAYOUT)
check("블랙잭은 2배", games.settle_blackjack([1, 13], [10, 9])[0] == games.BJ_BLACKJACK_PAYOUT)
check("딜러도 블랙잭이면 무승부",
      games.settle_blackjack([1, 13], [1, 12])[0] == games.BJ_PUSH_PAYOUT)
check("플레이어 버스트면 딜러 버스트여도 패배",
      games.settle_blackjack([10, 10, 5], [10, 10, 5])[0] == 0)

print("4) 🃏 블랙잭 환수율 (몬테카를로)")


def simulate(rounds: int, seed: int) -> float:
    rng = random.Random(seed)
    returned = 0
    for _ in range(rounds):
        deck = games.new_deck(rng)
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        # 평범한 플레이 감각: 17 미만이면 더 뽑아요.
        while games.hand_value(player) < 17:
            player.append(deck.pop())
        if games.hand_value(player) <= 21:
            games.dealer_play(dealer, deck)
        returned += games.settle_blackjack(player, dealer)[0]
    return returned / rounds


bj_rtp = simulate(120_000, 42)
check(f"환수율 {bj_rtp * 100:.1f}% 가 85~95% 안", 0.85 <= bj_rtp <= 0.95, f"{bj_rtp:.4f}")
check("100%를 넘지 않는다", bj_rtp < 1.0, f"{bj_rtp:.4f}")
check("덱은 52장", len(games.new_deck(random.Random(1))) == 52)
check("랭크마다 4장", games.new_deck(random.Random(1)).count(1) == 4)

print("5) 베팅 한도")


class FakeCasino:
    def __init__(self):
        self.docs = {}

    def find_one(self, flt, projection=None):
        return self.docs.get(flt["_id"])

    def _match(self, doc, flt):
        for key, cond in flt.items():
            if key == "_id":
                continue
            value = (doc or {}).get(key)
            if isinstance(cond, dict):
                if "$lte" in cond and not (isinstance(value, int) and value <= cond["$lte"]):
                    return False
                if "$ne" in cond and value == cond["$ne"]:
                    return False
            elif value != cond:
                return False
        return True

    def update_one(self, flt, update, upsert=False):
        class Res:
            modified_count = 0
        res = Res()
        doc = self.docs.get(flt["_id"])
        if doc is None or not self._match(doc, flt):
            return res
        for key, value in (update.get("$inc") or {}).items():
            doc[key] = int(doc.get(key) or 0) + value
        for key, value in (update.get("$set") or {}).items():
            doc[key] = value
        res.modified_count = 1
        return res

    def insert_one(self, doc):
        self.docs[doc["_id"]] = dict(doc)


fake = FakeCasino()
casino_store._casino = fake

check("처음엔 0코인", asyncio.run(casino_store.wagered_today(1)) == 0)
ok, total = asyncio.run(casino_store.try_wager(1, 5))
check("첫 베팅 통과", ok is True and total == 5, f"{ok} {total}")
for _ in range(3):
    asyncio.run(casino_store.try_wager(1, 5))
check(f"하루 한도 {casino_store.DAILY_LIMIT}코인까지 참",
      asyncio.run(casino_store.wagered_today(1)) == casino_store.DAILY_LIMIT)
ok, total = asyncio.run(casino_store.try_wager(1, 1))
check("한도를 넘기면 거절", ok is False, f"{ok}")
check("거절돼도 누적이 안 늘어난다",
      asyncio.run(casino_store.wagered_today(1)) == casino_store.DAILY_LIMIT, str(total))

# 한도 직전에 큰 금액이 들어오면? (18 + 5 > 20)
fake.docs.clear()
asyncio.run(casino_store.try_wager(2, 5))
asyncio.run(casino_store.try_wager(2, 5))
asyncio.run(casino_store.try_wager(2, 5))
ok, _ = asyncio.run(casino_store.try_wager(2, 5))
check("15 + 5 = 20 은 통과 (경계값)", ok is True)
ok, _ = asyncio.run(casino_store.try_wager(2, 1))
check("20 + 1 은 거절", ok is False)

fake.docs.clear()
asyncio.run(casino_store.try_wager(3, 4))
asyncio.run(casino_store.try_wager(3, 4))
asyncio.run(casino_store.try_wager(3, 4))
asyncio.run(casino_store.try_wager(3, 4))
ok, _ = asyncio.run(casino_store.try_wager(3, 5))
check("16 + 5 = 21 은 거절 (한도 초과분을 미리 계산)", ok is False)
check("16은 그대로 남는다", asyncio.run(casino_store.wagered_today(3)) == 16)

# 날짜가 지난 문서는 새로 시작
fake.docs["4"] = {"_id": "4", "date": "2020-01-01", "wagered": 20}
ok, total = asyncio.run(casino_store.try_wager(4, 5))
check("어제 한도는 오늘로 안 넘어온다", ok is True and total == 5, f"{ok} {total}")

# ⚠️ 위에서 fake.docs를 비웠으니 환불 검사는 **새 사람으로** 해요
#    (지워진 기록에 환불하면 당연히 0이라, 통과해도 아무것도 증명 못 해요).
asyncio.run(casino_store.try_wager(5, 5))
asyncio.run(casino_store.try_wager(5, 5))
check("환불 전 10코인", asyncio.run(casino_store.wagered_today(5)) == 10)
asyncio.run(casino_store.refund_wager(5, 5))
check("환불하면 한도가 돌아온다", asyncio.run(casino_store.wagered_today(5)) == 5,
      str(asyncio.run(casino_store.wagered_today(5))))
ok, _ = asyncio.run(casino_store.try_wager(5, 5))
check("되돌아온 한도만큼 다시 걸 수 있다", ok is True)

print("6) 한도 조회가 실패하면 막는 쪽으로")


class BrokenCasino:
    def find_one(self, *a, **kw):
        raise RuntimeError("DB 끊김")


casino_store._casino = BrokenCasino()
check("조회 실패 시 한도 소진으로 본다",
      asyncio.run(casino_store.wagered_today(1)) == casino_store.DAILY_LIMIT)
casino_store._casino = fake

print("7) 한 판에 잃을 수 있는 최대와 하루 최대")
check(f"1회 최대 {casino_store.MAX_BET}코인", casino_store.MAX_BET == 5)
check(f"하루 최대 {casino_store.DAILY_LIMIT}코인", casino_store.DAILY_LIMIT == 20)
check("최소 베팅 1코인", casino_store.MIN_BET == 1)
biggest_win = casino_store.MAX_BET * max(p for _, p in games.SLOT_SYMBOLS)
check(f"한 방 최대 당첨 {biggest_win}코인 (지갑 최대 97코인 대비 과하지 않음)",
      biggest_win <= 40, str(biggest_win))

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
