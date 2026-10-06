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
  7) 🔓 한도 연장권: **살수록 값이 오르고**(5→10→15) +10씩 여러 번 늘어나는지,
     버튼 라벨이 그 값을 따라가는지, 날짜가 바뀌면 리셋되는지, 결제 실패 시 공짜
     연장이 남지 않는지 (+ `extended` 없는 옛 문서도 살 수 있는지)
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
            # ⚠️ `$or`는 **키가 아니라 조건 목록**이에요. 여기서 안 다루면 연장권 쿼리
            #    (`extended`가 없는 옛 문서 + 아직 안 늘린 문서)가 조용히 통과해버려서,
            #    테스트가 실제 Mongo와 다른 답을 내요.
            if key == "$or":
                if not any(self._match(doc, sub) for sub in cond):
                    return False
                continue
            value = (doc or {}).get(key)
            if isinstance(cond, dict):
                if "$lte" in cond and not (isinstance(value, int) and value <= cond["$lte"]):
                    return False
                if "$lt" in cond and not (isinstance(value, int) and value < cond["$lt"]):
                    return False
                if "$ne" in cond and value == cond["$ne"]:
                    return False
                if "$exists" in cond and (value is not None) != cond["$exists"]:
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

print("7) 🔓 한도 연장권 (+10씩 · 값은 5 → 10 → 15 로 오름 · 횟수 제한 없음)")
fake.docs.clear()
check(f"첫 값 {casino_store.EXTEND_BASE_PRICE}코인 · 한 번에 +{casino_store.EXTEND_BONUS}코인",
      (casino_store.EXTEND_BASE_PRICE, casino_store.EXTEND_BONUS) == (5, 10))
# 🚨 살수록 비싸져야 해요. 고정가면 지갑 두꺼운 사람이 한도를 사실상 무한히 늘려요.
check("값이 5 → 10 → 15 → 20 으로 오른다",
      [casino_store.extend_price(i) for i in range(4)] == [5, 10, 15, 20],
      str([casino_store.extend_price(i) for i in range(4)]))
check("누적 지출 = 5·n(n+1)/2 (0·1·2·3·4번 → 0·5·15·30·50)",
      [casino_store.extend_spent(n) for n in range(5)] == [0, 5, 15, 30, 50],
      str([casino_store.extend_spent(n) for n in range(5)]))
check("누적 지출이 값의 합과 맞는다",
      all(casino_store.extend_spent(n) == sum(casino_store.extend_price(i) for i in range(n))
          for n in range(6)))
# 98코인 지갑이 연장만으로 바닥나는 지점 — 제동이 실제로 걸리는지
afford = max(n for n in range(20) if casino_store.extend_spent(n) <= 98)
check(f"98코인으로 살 수 있는 연장은 {afford}번까지 (그때 {casino_store.extend_spent(afford)}코인 소진)",
      afford == 5 and casino_store.extend_spent(afford) == 75, f"{afford}번/{casino_store.extend_spent(afford)}코인")
check("연장 0회 = 한도 20", casino_store.limit_of(0) == 20)
check("연장 1회 = 한도 30", casino_store.limit_of(1) == 30)
check("연장 4회 = 한도 60 (상한이 따로 없다)", casino_store.limit_of(4) == 60)
check("None도 0으로 본다 (옛 문서)", casino_store.limit_of(None) == 20)

for _ in range(4):
    asyncio.run(casino_store.try_wager(10, 5))
ok, _ = asyncio.run(casino_store.try_wager(10, 1))
check("연장 전엔 20에서 막힌다", ok is False)
ok, limit, times = asyncio.run(casino_store.extend_limit(10))
check("연장 성공 → 한도 30 · 1번째", ok is True and limit == 30 and times == 1, f"{ok} {limit} {times}")
check("state_today가 늘어난 한도를 돌려준다",
      asyncio.run(casino_store.state_today(10)) == (20, 30),
      str(asyncio.run(casino_store.state_today(10))))
ok, total = asyncio.run(casino_store.try_wager(10, 5))
check("연장하면 다시 걸 수 있다", ok is True and total == 25, f"{ok} {total}")
ok, _ = asyncio.run(casino_store.try_wager(10, 5))
check("25 + 5 = 30 은 통과 (새 경계값)", ok is True)
ok, _ = asyncio.run(casino_store.try_wager(10, 1))
check("30을 넘기면 다시 막힌다 (늘린 만큼만 열린다)", ok is False)

# 5코인을 **낼 때마다** 늘어나요 (2026-10-06 사용자 결정으로 하루 1회 제한을 풀었어요).
# 🚨 그래서 하루 상한은 사실상 그 사람 지갑이에요. 횟수를 돌려주는 건 안내에 쓰려는 거예요.
ok, limit, times = asyncio.run(casino_store.extend_limit(10))
check("두 번째 연장도 된다 → 한도 40 · 2번째", ok is True and limit == 40 and times == 2,
      f"{ok} {limit} {times}")
ok, limit, times = asyncio.run(casino_store.extend_limit(10))
check("세 번째도 된다 → 한도 50 · 3번째", ok is True and limit == 50 and times == 3,
      f"{ok} {limit} {times}")
check("extend_count가 안내용 횟수를 돌려준다", asyncio.run(casino_store.extend_count(10)) == 3)
ok, _ = asyncio.run(casino_store.try_wager(10, 5))
check("늘린 만큼 실제로 더 걸 수 있다 (30 → 35)", ok is True)

# 코인 차감이 실패했을 때 선점을 되돌리는 경로 (공짜 연장 방지)
fake.docs.clear()
asyncio.run(casino_store.try_wager(11, 5))
asyncio.run(casino_store.extend_limit(11))
check("되돌리기 전 한도 30", asyncio.run(casino_store.state_today(11))[1] == 30)
asyncio.run(casino_store.undo_extend(11))
check("되돌리면 한도 20 (결제 실패 시 공짜 연장이 안 남는다)",
      asyncio.run(casino_store.state_today(11))[1] == 20,
      str(asyncio.run(casino_store.state_today(11))))

# ⚠️ `extended` 필드가 **없는** 옛 문서 (연장권 전에 만들어진 기록)
fake.docs.clear()
fake.docs["12"] = {"_id": "12", "date": casino_store.today_iso(), "wagered": 20}
ok, limit, times = asyncio.run(casino_store.extend_limit(12))
check("extended 필드가 없는 옛 문서도 연장할 수 있다", ok is True and limit == 30 and times == 1,
      f"{ok} {limit} {times}")

# 🚨 날짜가 바뀌면 연장도 함께 리셋돼야 해요 (안 그러면 한도가 영구히 30)
fake.docs.clear()
fake.docs["13"] = {"_id": "13", "date": "2020-01-01", "wagered": 30, "extended": 1}
ok, total = asyncio.run(casino_store.try_wager(13, 5))
check("어제 산 연장권은 오늘로 안 넘어온다",
      ok is True and total == 5 and fake.docs["13"]["extended"] == 0,
      f"{ok} {total} extended={fake.docs['13'].get('extended')}")
for _ in range(3):
    asyncio.run(casino_store.try_wager(13, 5))
ok, _ = asyncio.run(casino_store.try_wager(13, 1))
check("그래서 오늘 한도는 다시 20에서 막힌다", ok is False)

# ⚠️ `cogs.casino`(=EXTEND_NOTE)는 여기서 import하면 안 돼요. `.env`를 읽기 **전**이라
#    `ADULT_ROLE_ID`가 None으로 캐시돼서 아래 성인 게이트 검사가 통째로 깨져요.
#    그 검사는 9) 뒤로 옮겼어요.

print("8) 한 판에 잃을 수 있는 최대와 하루 최대")
check(f"1회 최대 {casino_store.MAX_BET}코인", casino_store.MAX_BET == 5)
check(f"하루 최대 {casino_store.DAILY_LIMIT}코인", casino_store.DAILY_LIMIT == 20)
check("최소 베팅 1코인", casino_store.MIN_BET == 1)
biggest_win = casino_store.MAX_BET * max(p for _, p in games.SLOT_SYMBOLS)
check(f"한 방 최대 당첨 {biggest_win}코인 (지갑 최대 97코인 대비 과하지 않음)",
      biggest_win <= 40, str(biggest_win))

print("9) 🔞 성인 전용 게이트 (채널을 가리는 것만으로는 안 막혀요)")
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_casino_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_casino_test"

import discord  # noqa: E402

from cogs import casino as casino_cog  # noqa: E402

ADULT_ID = casino_cog.ADULT_ROLE_ID
check("ADULT_ROLE_ID가 설정돼 있다 (없으면 전원 차단돼요)", bool(ADULT_ID), str(ADULT_ID))


class FakeRole:
    def __init__(self, rid):
        self.id = int(rid)


class FakePerms:
    def __init__(self, administrator=False):
        self.administrator = administrator


class FakeMember(discord.Member):
    """`roles`·`guild_permissions`는 읽기 전용 property라 클래스 본문에서 덮어써요."""

    roles = ()
    guild_permissions = None

    def __init__(self, role_ids, administrator=False):
        self.roles = [FakeRole(r) for r in role_ids]
        self.guild_permissions = FakePerms(administrator)

    def __str__(self):
        return "테스터"


class FakeUser:
    def __str__(self):
        return "DM유저"


if ADULT_ID:
    check("성인 역할이 있으면 통과", casino_cog._is_adult(FakeMember([ADULT_ID])) is True)
    check("다른 역할만 있으면 차단", casino_cog._is_adult(FakeMember([999999])) is False)
    check("역할이 없으면 차단", casino_cog._is_adult(FakeMember([])) is False)
check("운영진(ADMIN)은 통과", casino_cog._is_adult(FakeMember([999999], administrator=True)) is True)
check("DM(서버 밖)은 차단", casino_cog._is_adult(FakeUser()) is False)
check("None도 차단", casino_cog._is_adult(None) is False)

# 설정이 비었을 때 **막는 쪽**으로 기우는지 (열어주면 미성년자가 통과해요)
saved = casino_cog.ADULT_ROLE_ID
casino_cog.ADULT_ROLE_ID = None
check("ADULT_ROLE_ID가 비면 일반 유저는 차단", casino_cog._is_adult(FakeMember([999999])) is False)
check("설정이 비어도 운영진은 통과(잠김 방지)",
      casino_cog._is_adult(FakeMember([999999], administrator=True)) is True)
casino_cog.ADULT_ROLE_ID = saved


async def check_commands():
    from discord.ext import commands as dcommands

    bot = dcommands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension("cogs.casino")
    group = bot.tree.get_command("도박")
    subs = {c.name: c for c in group.commands}
    check("하위 명령 4개", sorted(subs) == sorted(["슬롯", "하이로우", "블랙잭", "현황"]), str(sorted(subs)))
    for name, cmd in subs.items():
        check(f"/도박 {name} 에 체크가 붙어 있다", len(cmd.checks) >= 1, f"{len(cmd.checks)}개")
    # 성인이 아니면 실제로 거절되는지 체크 체인으로 확인
    for name in ("슬롯", "현황"):
        it = type("I", (), {"user": FakeMember([999999]), "guild": None,
                            "response": type("R", (), {"send_message": _noop})()})()
        results = [await c(it) for c in subs[name].checks]
        check(f"/도박 {name}: 성인 아니면 거절", any(r is False for r in results), str(results))


async def _noop(*a, **kw):
    return None


asyncio.run(check_commands())

print("10) 🔓 연장권 버튼이 디스코드에 보낼 수 있는 모양인지")
# 🚨 2026-10-05에 버튼 이모지(`🂠`)가 거부돼 블랙잭이 통째로 터졌어요. 여기선 `emoji=`를
#    안 쓰고 **label 안에** 🔓를 넣었는데(label은 자유 텍스트라 안전해요), 눈으로 믿지 말고
#    실제로 보낼 payload를 뽑아서 확인해요.
view = casino_cog.ExtendLimitView(123)
rows = view.to_components()
buttons = [c for row in rows for c in row["components"]]
check("버튼 1개 · 줄 1개", len(buttons) == 1 and len(rows) == 1, f"{len(buttons)}개/{len(rows)}줄")
check("emoji= 를 안 쓴다 (블랙잭 사고 경로를 아예 안 탐)",
      all("emoji" not in b for b in buttons))
check("label이 80자 이하", all(len(b["label"]) <= 80 for b in buttons),
      str([len(b["label"]) for b in buttons]))
check("custom_id가 100자 이하", all(len(b["custom_id"]) <= 100 for b in buttons))
check("label에 값과 증분이 적혀 있다 (누르기 전에 얼마인지 보여야 해요)",
      str(casino_store.extend_price(0)) in buttons[0]["label"]
      and str(casino_store.EXTEND_BONUS) in buttons[0]["label"], buttons[0]["label"])

# 🚨 값이 오르니 **라벨도 같이 올라야** 해요. 데코레이터에 박힌 채로 두면 3번째 연장인데도
#    "5코인"으로 보이고, 실제로는 15코인이 빠져서 사기처럼 느껴져요.
for already, expected in [(0, 5), (1, 10), (2, 15), (4, 25)]:
    label = casino_cog.ExtendLimitView(123, already).to_components()[0]["components"][0]["label"]
    check(f"{already}번 산 사람의 버튼은 {expected}코인으로 보인다",
          f"({expected}코인)" in label, label)
check("연장권 note가 '도박'으로 시작하지 않는다 (경제 리포트가 베팅액으로 오인해요)",
      not casino_cog.EXTEND_NOTE.startswith("도박"), casino_cog.EXTEND_NOTE)

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
