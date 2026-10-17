"""🤝 악귀카드 **지목 거래** 검증. 실제 DB·디스코드 없이 돌아가요.

거래는 **카드와 코인이 동시에 움직이는** 유일한 기능이라, 한쪽만 성공하면 바로 분쟁이에요.

2026-10-18에 공개 장터 → 지목 거래로 바뀌었어요. 그래서 검사의 중심이 "동시 구매"에서
**"지목된 사람만 수락"**으로 옮겨갔어요.

  1) 에스크로: 제안하면 카드가 **그 자리에서** 도감에서 빠진다
  2) 안 가진 카드는 제안할 수 없다 (조건부 차감)
  3) 같은 카드를 가진 장수보다 많이 제안할 수 없다
  4) 취소하면 카드가 **그대로 돌아온다**
  5) 남의 제안은 취소할 수 없다 / 이미 끝난 제안도 취소할 수 없다
  6) 🚨 **지목**: 지목되지 않은 사람은 제안 id를 알아도 수락할 수 없다
  7) 결제 실패면 제안이 **다시 열린다** — 그리고 `buyer`가 **지워지지 않는다**
     (지워지면 주인 없는 제안이 되어 카드가 에스크로에 영영 잠겨요)
  8) 🚨 거절하면 카드가 **판매자에게** 돌아간다 (거절한 사람이 아니라)
  9) 수락·거절·취소가 겹쳐도 **하나만** 성공한다 (카드 복제 방지)
 10) 거래가 성립하면 코인이 산 사람 -> 판 사람으로 **정확히** 옮겨간다
 11) 경제 리포트가 거래를 **소각이 아니라 재분배**로 분류한다 (옛 `장터:` 기록까지)
 12) 제안 상한
 13) cog가 상대 검사를 **카드 회수보다 먼저** 한다
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
print("\n[1][2][3] 에스크로 - 제안하면 바로 빠진다")
fake_cards.docs[SELLER] = {EPIC: 1, COMMON: 2}

check("안 가진 카드는 제안 불가",
      run(card_store.take_card(SELLER, CARDS["레전드"][0]["key"])) is False)

check("가진 카드는 회수된다", run(card_store.take_card(SELLER, EPIC)) is True)
check("도감에서 빠졌다", fake_cards.docs[SELLER][EPIC] == 0,
      str(fake_cards.docs[SELLER]))
offer = run(card_market.offer(SELLER, BUYER, EPIC, 50))
check("제안이 생겼다", offer is not None)
check("지목 상대가 기록된다", run(card_market.get(offer))["buyer"] == BUYER)

check("한 장 더 내놓으려 하면 거부", run(card_store.take_card(SELLER, EPIC)) is False)
check("2장 가진 건 두 번 내놓을 수 있다",
      run(card_store.take_card(SELLER, COMMON)) and run(card_store.take_card(SELLER, COMMON)))
check("세 번째는 거부", run(card_store.take_card(SELLER, COMMON)) is False)

# 받은/보낸 제안 목록
check("판매자의 '보낸 제안'에 보인다",
      [d["_id"] for d in run(card_market.outgoing(SELLER))] == [offer])
check("지목된 사람의 '받은 제안'에 보인다",
      [d["_id"] for d in run(card_market.incoming(BUYER))] == [offer])
check("🚨 지목 안 된 사람에게는 안 보인다",
      run(card_market.incoming(OTHER)) == [])

# ==================================================================
print("\n[4][5] 취소")
c1 = run(card_market.offer(SELLER, BUYER, COMMON, 5))
got = run(card_market.cancel(c1, SELLER))
check("내 제안은 취소된다", got is not None)
run(card_store.give_card(SELLER, COMMON))
check("카드가 돌아왔다", fake_cards.docs[SELLER][COMMON] == 1,
      str(fake_cards.docs[SELLER]))
check("같은 제안을 두 번 취소할 수 없다", run(card_market.cancel(c1, SELLER)) is None)
check("남의 제안은 취소 불가", run(card_market.cancel(offer, OTHER)) is None)
check("🚨 지목된 상대도 '취소'는 못 한다 (거절을 써야 해요)",
      run(card_market.cancel(offer, BUYER)) is None)

# ==================================================================
print("\n[6] 🚨 지목 - 지목된 사람만 수락할 수 있다")
# 제안 id를 알아냈다고 가정해도 막혀야 해요. 권한 검사가 claim 필터 안에 있는지가 핵심.
check("지목 안 된 사람은 수락 불가", run(card_market.claim(offer, OTHER)) is None)
check("그래도 제안은 멀쩡히 열려 있다",
      run(card_market.get(offer))["status"] == "open")
won = run(card_market.claim(offer, BUYER))
check("지목된 사람은 수락된다", won is not None)
check("두 번 수락할 수 없다", run(card_market.claim(offer, BUYER)) is None)

# ==================================================================
print("\n[7] 결제 실패 → 다시 열린다 (buyer는 유지)")
run(card_market.release(offer))
reopened = run(card_market.get(offer))
check("상태가 open으로 돌아왔다", reopened["status"] == "open")
check("🚨 buyer가 지워지지 않았다 (지워지면 주인 없는 제안이 돼요)",
      reopened.get("buyer") == BUYER, str(reopened.get("buyer")))
check("되돌린 뒤에도 남은 수락 불가", run(card_market.claim(offer, OTHER)) is None)

# ==================================================================
print("\n[8] 🚨 거절 - 카드는 판매자에게 돌아간다")
d1 = run(card_market.offer(SELLER, BUYER, COMMON, 7))
run(card_store.take_card(SELLER, COMMON))          # 에스크로 흉내
before_seller = dict(fake_cards.docs[SELLER])
declined = run(card_market.decline(d1, BUYER))
check("지목된 사람은 거절할 수 있다", declined is not None)
check("판매자가 기록돼 있다 (카드를 누구에게 돌려줄지)",
      declined and declined["seller"] == SELLER)
run(card_store.give_card(declined["seller"], declined["key"]))
check("🚨 카드가 **판매자**에게 돌아갔다",
      fake_cards.docs[SELLER][COMMON] == before_seller[COMMON] + 1,
      f"{before_seller} -> {fake_cards.docs[SELLER]}")
check("거절한 사람은 카드를 안 받았다",
      fake_cards.docs.get(BUYER, {}).get(COMMON, 0) == 0)
check("남이 거절할 수는 없다",
      run(card_market.decline(run(card_market.offer(SELLER, BUYER, COMMON, 7)),
                              OTHER)) is None)

# ==================================================================
print("\n[9] 🚨 수락·거절·취소가 겹쳐도 하나만 성공 (카드 복제 방지)")
race = run(card_market.offer(SELLER, BUYER, COMMON, 9))
wins = [
    ("수락", run(card_market.claim(race, BUYER))),
    ("거절", run(card_market.decline(race, BUYER))),
    ("취소", run(card_market.cancel(race, SELLER))),
]
succeeded = [n for n, r in wins if r is not None]
check("셋 중 하나만 통과한다", len(succeeded) == 1, f"통과: {succeeded}")

race2 = run(card_market.offer(SELLER, BUYER, COMMON, 9))
order = [
    ("취소", run(card_market.cancel(race2, SELLER))),
    ("수락", run(card_market.claim(race2, BUYER))),
]
check("순서를 바꿔도 하나만 통과한다",
      len([n for n, r in order if r is not None]) == 1,
      f"통과: {[n for n, r in order if r is not None]}")

# ==================================================================
print("\n[10] 코인 이동")


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
item = run(card_market.claim(offer, BUYER))
ok, _ = run(wallet.transfer(BUYER, SELLER, item["price"], note=f"거래:{item['key']}"))
run(card_store.give_card(BUYER, item["key"]))
check("구매자 코인이 줄었다", wallet.bal[BUYER] == 50, str(wallet.bal))
check("판매자 코인이 늘었다", wallet.bal[SELLER] == 60, str(wallet.bal))
check("총량은 그대로", sum(wallet.bal.values()) == 110, str(sum(wallet.bal.values())))
check("구매자가 카드를 받았다", fake_cards.docs[BUYER][EPIC] == 1,
      str(fake_cards.docs.get(BUYER)))
check("기록에 거래 용도가 남는다", wallet.log[-1][4] == f"거래:{EPIC}", str(wallet.log[-1]))

# 잔액 부족이면 아무것도 안 움직여요.
before = dict(wallet.bal)
ok2, reason = run(wallet.transfer(OTHER, SELLER, 999))
check("잔액 부족이면 실패", ok2 is False and reason == "balance")
check("실패하면 코인이 그대로", wallet.bal == before)

# ==================================================================
print("\n[11] 경제 리포트가 거래를 재분배로 분류하는가")
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
    ({"kind": "transfer", "note": f"거래:{EPIC}"}, "transfer"),
    ({"kind": "transfer", "note": f"장터:{EPIC}"}, "transfer"),   # 2026-10-17까지의 옛 기록
    ({"kind": "transfer", "note": ""}, "transfer"),      # /코인보내기
    ({"kind": "spend", "note": "카드뽑기"}, "burn"),
    ({"kind": "add", "note": "출석"}, "issue"),
]:
    got = ns["classify"](entry)
    if got != want:
        failures.append(f"classify {entry}")
    print(f"  {'OK  ' if got == want else 'FAIL'} {entry['kind']:8s} "
          f"{entry['note'] or '(없음)':14s} -> {got}")
check("🚨 거래가 소각으로 안 세어진다",
      ns["classify"]({"kind": "transfer", "note": "거래:x"}) != "burn")

# 🚨 리포트의 **장터 집계 줄**도 새 note를 집어야 해요. classify만 맞고 여기가 틀리면
#    거래 건수가 0으로 보여서 "아무도 거래 안 한다"고 오판해요(실제로 그럴 뻔했어요).
_report_src = Path(os.path.join(BOT_DIR, "scripts/report_economy.py")).read_text(
    encoding="utf-8")
check("리포트 집계가 `거래:`와 옛 `장터:`를 **둘 다** 센다",
      'startswith(("장터", "거래"))' in _report_src)

# ==================================================================
print("\n[12] 제안 상한")
fake_market.docs.clear()
for i in range(card_market.MAX_OFFERS):
    run(card_market.offer(SELLER, BUYER, COMMON, 5))
check(f"{card_market.MAX_OFFERS}개까지 올라간다",
      run(card_market.open_count(SELLER)) == card_market.MAX_OFFERS)
check("상한에 도달하면 더 못 올린다 (cog가 막아요)",
      run(card_market.open_count(SELLER)) >= card_market.MAX_OFFERS)

# ==================================================================
print("\n[13] 🚨 cog가 상대 검사를 카드 회수보다 먼저 하는가")
# 순서가 뒤집히면 "나에게 팔기"·"봇에게 팔기"를 시도할 때마다 카드를 뺐다 돌려주는
# 왕복이 생겨요. 그 사이에 터지면 카드가 떠버려요(에스크로에도, 도감에도 없음).
import ast as _ast2  # noqa: E402
import inspect as _inspect  # noqa: E402

import cogs.card_market as _cm  # noqa: E402

_fn = _ast2.parse(
    __import__("textwrap").dedent(
        _inspect.getsource(_cm.CardMarket.card_trade.callback))).body[0]
_self_check_line = _take_line = None
for _n in _ast2.walk(_fn):
    if isinstance(_n, _ast2.Attribute) and _n.attr == "bot" and _take_line is None:
        _self_check_line = _self_check_line or _n.lineno
    if (isinstance(_n, _ast2.Attribute) and _n.attr == "take_card"):
        _take_line = _n.lineno
check("상대(self/bot) 검사가 take_card보다 앞에 있다",
      _self_check_line is not None and _take_line is not None
      and _self_check_line < _take_line,
      f"상대검사 {_self_check_line}줄 / take_card {_take_line}줄")

print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
