"""🎪 악귀카드 장터 검증. 실제 DB·디스코드 없이 돌아가요.

장터는 **카드와 코인이 동시에 움직이는** 유일한 기능이라, 한쪽만 성공하면 바로 분쟁이에요.
여기서 확인하는 것:

  1) 에스크로: 등록하면 카드가 **그 자리에서** 도감에서 빠진다
  2) 안 가진 카드는 등록할 수 없다 (조건부 차감)
  3) 같은 카드를 가진 장수보다 많이 등록할 수 없다
  4) 취소하면 카드가 **그대로 돌아온다**
  5) 남의 매물은 취소할 수 없다 / 이미 팔린 매물도 취소할 수 없다
  6) 🚨 **동시 구매**: 둘이 같은 매물을 사면 한 명만 성공한다
  7) 결제 실패(잔액 부족)면 매물이 **다시 열린다** (영영 잠기면 안 돼요)
  8) 내 매물은 내가 못 산다
  9) 거래가 성립하면 코인이 산 사람 -> 판 사람으로 **정확히** 옮겨간다
 10) 경제 리포트가 장터 거래를 **소각이 아니라 재분배**로 분류한다
 11) 매물 등록 상한
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_market_test"

from utils import card_market, card_store  # noqa: E402
from utils.card_data import CARDS  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------
# 가짜 컬렉션 (cards / card_market)
# ------------------------------------------------------------------
class FakeCards:
    """{uid: {key: n}} 를 들고 조건부 차감·증가를 흉내내요."""

    def __init__(self):
        self.docs = {}

    def update_one(self, flt, update, upsert=False):
        class Res:
            def __init__(self, m=0, u=None):
                self.modified_count, self.upserted_id = m, u

        uid = flt["_id"]
        doc = self.docs.get(uid)
        # 조건부 필터: counts.<key> >= 1
        for field, cond in flt.items():
            if field == "_id":
                continue
            if isinstance(cond, dict) and "$gte" in cond:
                key = field.split(".", 1)[1]
                if not doc or doc.get(key, 0) < cond["$gte"]:
                    return Res()
        if doc is None:
            if not upsert:
                return Res()
            doc = self.docs[uid] = {}
        for field, delta in (update.get("$inc") or {}).items():
            key = field.split(".", 1)[1] if "." in field else field
            doc[key] = doc.get(key, 0) + delta
        return Res(m=1)

    def find_one(self, flt, projection=None):
        uid = flt["_id"]
        if uid not in self.docs:
            return None
        return {"_id": uid, "counts": dict(self.docs[uid])}


class FakeMarket:
    """매물 저장소. find_one_and_update의 **원자성**을 흉내내는 게 핵심이에요."""

    def __init__(self):
        self.docs = {}
        self.seq = 0
        self.before_claim = None     # 동시 구매 재현용 훅

    def insert_one(self, doc):
        self.seq += 1
        oid = f"id{self.seq}"
        self.docs[oid] = {**doc, "_id": oid}

        class R:
            inserted_id = oid
        return R()

    def _match(self, doc, flt):
        for k, v in flt.items():
            if k == "_id":
                if doc["_id"] != v:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    def find_one(self, flt, projection=None):
        return next((dict(d) for d in self.docs.values() if self._match(d, flt)), None)

    def find_one_and_update(self, flt, update, return_document=None):
        if self.before_claim is not None:
            cb, self.before_claim = self.before_claim, None
            cb()
        doc = next((d for d in self.docs.values() if self._match(d, flt)), None)
        if doc is None:
            return None
        for k, v in (update.get("$set") or {}).items():
            doc[k] = v
        return dict(doc)

    def update_one(self, flt, update):
        class Res:
            modified_count = 0
        doc = next((d for d in self.docs.values() if self._match(d, flt)), None)
        if doc is None:
            return Res()
        for k, v in (update.get("$set") or {}).items():
            doc[k] = v
        for k in (update.get("$unset") or {}):
            doc.pop(k, None)
        Res.modified_count = 1
        return Res()

    def count_documents(self, flt):
        return sum(1 for d in self.docs.values() if self._match(d, flt))

    def find(self, flt, projection=None):
        rows = [dict(d) for d in self.docs.values() if self._match(d, flt)]

        class Cur:
            def __init__(self, rows): self.rows = rows
            def sort(self, *a, **k):
                key = a[0]
                if isinstance(key, list):
                    self.rows.sort(key=lambda r: tuple(r.get(f, 0) for f, _ in key))
                return self
            def skip(self, n): self.rows = self.rows[n:]; return self
            def limit(self, n): self.rows = self.rows[:n]; return self
            def __iter__(self): return iter(self.rows)
        return Cur(rows)


fake_cards = FakeCards()
fake_market = FakeMarket()
card_store._cards = fake_cards
card_market._market = fake_market

# card_market._oid는 ObjectId를 만들려 해서 가짜 id("id1")에선 None이 돼요.
# 테스트에서는 id를 그대로 쓰게 바꿔요.
card_market._oid = lambda x: x

SELLER, BUYER, OTHER = "1001", "1002", "1003"
EPIC = CARDS["에픽"][0]["key"]
COMMON = CARDS["일반"][0]["key"]

# ==================================================================
print("\n[1][2][3] 에스크로 - 등록하면 바로 빠진다")
fake_cards.docs[SELLER] = {EPIC: 1, COMMON: 2}

check("안 가진 카드는 등록 불가",
      run(card_store.take_card(SELLER, CARDS["레전드"][0]["key"])) is False)

check("가진 카드는 회수된다", run(card_store.take_card(SELLER, EPIC)) is True)
check("도감에서 빠졌다", fake_cards.docs[SELLER][EPIC] == 0,
      str(fake_cards.docs[SELLER]))
listing = run(card_market.create(SELLER, EPIC, 50))
check("매물이 생겼다", listing is not None)

check("한 장 더 내놓으려 하면 거부", run(card_store.take_card(SELLER, EPIC)) is False)
check("2장 가진 건 두 번 내놓을 수 있다",
      run(card_store.take_card(SELLER, COMMON)) and run(card_store.take_card(SELLER, COMMON)))
check("세 번째는 거부", run(card_store.take_card(SELLER, COMMON)) is False)

# ==================================================================
print("\n[4][5] 취소")
c1 = run(card_market.create(SELLER, COMMON, 5))
got = run(card_market.cancel(c1, SELLER))
check("내 매물은 취소된다", got is not None)
run(card_store.give_card(SELLER, COMMON))
check("카드가 돌아왔다", fake_cards.docs[SELLER][COMMON] == 1,
      str(fake_cards.docs[SELLER]))
check("같은 매물을 두 번 취소할 수 없다", run(card_market.cancel(c1, SELLER)) is None)
check("남의 매물은 취소 불가", run(card_market.cancel(listing, OTHER)) is None)

# ==================================================================
print("\n[6] 🚨 동시 구매 - 한 명만 성공해야 한다")
first = run(card_market.claim(listing, BUYER))
second = run(card_market.claim(listing, OTHER))
check("먼저 누른 사람만 선점한다", first is not None and second is None,
      f"first={bool(first)} second={bool(second)}")
check("선점자가 기록된다", first and first["buyer"] == BUYER)

# 결제 실패를 가정하고 되돌리면 다시 살 수 있어야 해요.
run(card_market.release(listing))
again = run(card_market.claim(listing, OTHER))
check("[7] 되돌리면 다른 사람이 살 수 있다", again is not None)
check("매물이 영영 잠기지 않는다", again and again["status"] == "sold")
run(card_market.release(listing))

# ==================================================================
print("\n[8][9] 코인 이동")


class FakeWallet:
    def __init__(self):
        self.bal = {BUYER: 100, SELLER: 10, OTHER: 0}
        self.log = []

    async def transfer(self, a, b, amount, *, note=""):
        if self.bal.get(str(a), 0) < amount:
            return False, "balance"
        self.bal[str(a)] -= amount
        self.bal[str(b)] = self.bal.get(str(b), 0) + amount
        self.log.append(("transfer", str(a), str(b), amount, note))
        return True, "ok"

    async def get_balance(self, u):
        return self.bal.get(str(u), 0)


wallet = FakeWallet()
item = run(card_market.claim(listing, BUYER))
ok, _ = run(wallet.transfer(BUYER, SELLER, item["price"], note=f"장터:{item['key']}"))
run(card_store.give_card(BUYER, item["key"]))
check("구매자 코인이 줄었다", wallet.bal[BUYER] == 50, str(wallet.bal))
check("판매자 코인이 늘었다", wallet.bal[SELLER] == 60, str(wallet.bal))
check("총량은 그대로", sum(wallet.bal.values()) == 110, str(sum(wallet.bal.values())))
check("구매자가 카드를 받았다", fake_cards.docs[BUYER][EPIC] == 1,
      str(fake_cards.docs.get(BUYER)))
check("기록에 장터 용도가 남는다", wallet.log[-1][4] == f"장터:{EPIC}", str(wallet.log[-1]))

# 잔액 부족이면 아무것도 안 움직여요.
before = dict(wallet.bal)
ok2, reason = run(wallet.transfer(OTHER, SELLER, 999))
check("잔액 부족이면 실패", ok2 is False and reason == "balance")
check("실패하면 코인이 그대로", wallet.bal == before)

# ==================================================================
print("\n[10] 경제 리포트가 장터를 재분배로 분류하는가")
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

for entry, want in [
    ({"kind": "transfer", "note": f"장터:{EPIC}"}, "transfer"),
    ({"kind": "transfer", "note": ""}, "transfer"),      # /코인보내기
    ({"kind": "spend", "note": "카드뽑기"}, "burn"),
    ({"kind": "add", "note": "출석"}, "issue"),
]:
    got = ns["classify"](entry)
    if got != want:
        failures.append(f"classify {entry}")
    print(f"  {'OK  ' if got == want else 'FAIL'} {entry['kind']:8s} "
          f"{entry['note'] or '(없음)':14s} -> {got}")
check("🚨 장터 거래가 소각으로 안 세어진다",
      ns["classify"]({"kind": "transfer", "note": "장터:x"}) != "burn")

# ==================================================================
print("\n[11] 매물 상한")
fake_market.docs.clear()
for i in range(card_market.MAX_LISTINGS):
    run(card_market.create(SELLER, COMMON, 5))
check(f"{card_market.MAX_LISTINGS}개까지 올라간다",
      run(card_market.open_count(SELLER)) == card_market.MAX_LISTINGS)
check("상한에 도달하면 더 못 올린다 (cog가 막아요)",
      run(card_market.open_count(SELLER)) >= card_market.MAX_LISTINGS)

print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
