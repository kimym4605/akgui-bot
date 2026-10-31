# -*- coding: utf-8 -*-
"""🎪 도감에서 바로 팔기 테스트 (2026-11-01 신설).

## 왜

`/카드거래 상대:@ 카드:… 가격:…` 는 **인자 3개**를 손으로 채워야 해요. 13일간
거래가 **단 1건**이었어요. 🎣낚시·🪙상점과 같은 결론이에요 — 막은 건 기능이 아니라
**명령어 자체가 문턱**이었어요.

## 이 테스트가 지키는 것

1. 🚨 **도감이 열린다.** `CardSelect`가 한 줄을 통째로 먹는데 🎪팔기에 `row`를 박으면
   `add_item`이 ValueError로 터져서 **도감 화면 전체가 안 열려요.** 그래서 존재 검사가
   아니라 **뷰를 실제로 만들어** 봐요.
2. 🚨 **로직이 한 벌이다.** 에스크로·상대검사·상한을 복사하면 한쪽만 고쳐져 갈라져요.
3. 🚨 **가격 방어선.** 명령어는 `app_commands.Range`가 막아주지만 **모달은 아무 글자나
   들어와요.** `make_offer` 안의 범위 검사가 새 경로의 유일한 방어선이에요.
4. 🚨 **모달 앞에서 defer하지 않는다.** 이미 응답한 상호작용에는 모달을 못 띄워요.

실행: python scripts/test_card_market_sell.py   (종료코드 0 = 통과)
"""
import ast
import asyncio
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv            # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

import discord                            # noqa: E402

from cogs import card_gacha as cg          # noqa: E402
from cogs import card_market as cm         # noqa: E402
from utils import card_market as market    # noqa: E402
from utils import card_store               # noqa: E402
from utils.card_data import CARDS          # noqa: E402

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


# ---- 가짜 상호작용 ----------------------------------------------------------
class FakeUser:
    def __init__(self, uid, bot=False):
        self.id = uid
        self.bot = bot
        self.mention = f"<@{uid}>"
        self.display_name = f"유저{uid}"


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, *, embed=None, ephemeral=False, **kw):
        self.sent.append(content or (embed.title if embed else ""))


class FakeClient:
    def get_user(self, uid):
        return None

    async def fetch_user(self, uid):
        raise RuntimeError("DM 못 보냄 (일부러)")


class FakeInteraction:
    def __init__(self, uid):
        self.user = FakeUser(uid)
        self.followup = FakeFollowup()
        self.client = FakeClient()

    @property
    def text(self):
        return " | ".join(str(s) for s in self.followup.sent)


SELLER, BUYER = 777000001, 777000002
ANY_KEY = CARDS["일반"][0]["key"]


# ==========================================================================
print("\n[1] 🚨 **도감 카드 화면이 실제로 열린다** (row 충돌이면 여기서 터져요)")
# 일반 등급에서 3종을 가진 상태 — CardSelect가 뜨는 조건이에요
gen_keys = [c["key"] for c in CARDS["일반"][:3]]
counts = {gen_keys[0]: 4, gen_keys[1]: 1, gen_keys[2]: 2}
try:
    view = cg.CollectionView(SELLER, dict(counts), since_legend=0)
    view._build_card(gen_keys[0])
    rows = {}
    for it in view.children:
        rows.setdefault(it.row, []).append(type(it).__name__)
    check(True, f"카드 화면 구성 성공 — {len(view.children)}개 / {len(rows)}줄")
    sells = [it for it in view.children if isinstance(it, cg.SellButton)]
    check(len(sells) == 1, f"🎪팔기 버튼이 1개 붙었다 ({len(sells)}개)")
    check(len(rows) <= 5, f"5줄 한도 안 ({len(rows)}줄)", str(rows))
    sel = [it for it in view.children if isinstance(it, discord.ui.Select)]
    check(len(sel) == 1, "카드 선택 메뉴도 함께 남아있다 (다른 카드로 바로 이동)")
    # 🚨 `item.row`는 **안 박으면 None**이에요. 실제 배치는 직렬화할 때 계산되니
    #    거기서 봐야 해요 (`row`만 보고 "다른 줄"이라 믿으면 거짓 통과예요).
    comp = view.to_components()
    check(len(comp) >= 2, f"디스코드로 나갈 때 {len(comp)}줄로 배치된다")
    def _row_of(kind):
        for i, r in enumerate(comp):
            for c in r.get("components", []):
                if kind == "select" and c.get("type") == 3:
                    return i
                if kind == "sell" and c.get("label", "").startswith("팔기"):
                    return i
        return None
    r_sell, r_sel = _row_of("sell"), _row_of("select")
    check(r_sell is not None and r_sel is not None and r_sell != r_sel,
          f"🎪팔기가 선택 메뉴와 **다른 줄**에 배치된다 "
          f"(팔기={r_sell} 선택={r_sel})")
    check(all(len(r.get("components", [])) <= 5 for r in comp),
          "한 줄에 5개를 넘기지 않는다")
except Exception as exc:                                   # noqa: BLE001
    check(False, "카드 화면 구성 성공", f"{type(exc).__name__}: {exc}")

print("\n[2] 안 가진 카드에는 🎪팔기가 없다")
view2 = cg.CollectionView(SELLER, dict(counts), since_legend=0)
missing = next(c["key"] for c in CARDS["일반"] if c["key"] not in counts)
view2._build_card(missing)
check(not any(isinstance(it, cg.SellButton) for it in view2.children),
      "미보유 카드 화면엔 팔기 버튼이 없다")
check(any(isinstance(it, cg.BackButton) for it in view2.children),
      "그래도 📖 돌아가기는 있다")

print("\n[3] 마지막 1장은 **라벨로 경고**한다")
view3 = cg.CollectionView(SELLER, dict(counts), since_legend=0)
view3._build_card(gen_keys[1])          # 1장만 가진 카드
last = next(it for it in view3.children if isinstance(it, cg.SellButton))
check("마지막" in (last.label or ""), f"라벨에 경고가 있다: \"{last.label}\"")
view3._build_card(gen_keys[0])          # 4장
many = next(it for it in view3.children if isinstance(it, cg.SellButton))
check("마지막" not in (many.label or ""), f"여유분은 그냥 팔기: \"{many.label}\"")

print("\n[4] 🚨 제안이 들어가면 도감 숫자가 **줄어든다** (요약까지)")
v = cg.CollectionView(SELLER, dict(counts), since_legend=0)
before = v.summary["per_grade"]["일반"]["owned"]
v.on_card_sold(gen_keys[0])             # 4 → 3장
check(v.counts[gen_keys[0]] == 3, f"4장 → {v.counts[gen_keys[0]]}장")
check(v.summary["per_grade"]["일반"]["owned"] == before,
      "여유분이 빠져도 보유 **종수**는 그대로")
v.on_card_sold(gen_keys[1])             # 1 → 0장 (종수가 줄어야 해요)
check(gen_keys[1] not in v.counts, "마지막 1장은 목록에서 빠진다")
check(v.summary["per_grade"]["일반"]["owned"] == before - 1,
      f"보유 종수도 {before} → {v.summary['per_grade']['일반']['owned']}",
      "summarize를 다시 안 하면 등급 버튼이 거짓말을 해요")

print("\n[5] 🚨 로직이 **한 벌**이다 (`/카드거래`가 복사하지 않았다)")
src = open(os.path.join(BOT_DIR, "cogs", "card_market.py"), encoding="utf-8").read()
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree)
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "card_trade")
body = ast.unparse(fn)
check("make_offer" in body, "`/카드거래`가 `make_offer`를 부른다")
for dup in ("take_card", "open_count", "card_market.offer", "give_card"):
    check(dup not in body, f"`/카드거래` 본문에 `{dup}` 복사본이 없다")
mo = next(n for n in ast.walk(tree)
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "make_offer")
mob = ast.unparse(mo)
check("take_card" in mob and "open_count" in mob, "로직이 `make_offer`에 모여 있다")
# 🚨 상대 검사가 카드 회수보다 **앞**이어야 해요 (뒤면 왕복이 생겨 카드가 떠요)
i_self = mob.find("buyer.id == me")
i_take = mob.find("take_card")
check(0 <= i_self < i_take, "상대 검사가 카드 회수보다 앞에 있다",
      f"{i_self} vs {i_take}")

print("\n[6] 🚨 모달 앞에서 **defer하지 않는다**")
gsrc = open(os.path.join(BOT_DIR, "cogs", "card_gacha.py"), encoding="utf-8").read()
gtree = ast.parse(gsrc)
sel_cls = next(n for n in ast.walk(gtree)
               if isinstance(n, ast.ClassDef) and n.name == "_SellBuyerSelect")
cb = next(ast.unparse(n) for n in ast.walk(sel_cls)
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "callback")
check("send_modal" in cb, "상대를 고르면 가격 모달을 띄운다")
check("defer" not in cb, "defer가 없다 (있으면 모달이 거부돼요)")
# 반대로 모달 제출에서는 defer가 **있어야** 해요 (make_offer가 followup만 써요)
modal = next(n for n in ast.walk(gtree)
             if isinstance(n, ast.ClassDef) and n.name == "_PriceModal")
sub = next(ast.unparse(n) for n in ast.walk(modal)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_submit")
check("defer" in sub, "모달 제출에서는 defer를 한다")
check("make_offer" in sub, "모달 제출이 `make_offer`로 넘긴다")
check("on_card_sold" in sub, "성공하면 도감 숫자를 줄인다")


# ==========================================================================
# 실제로 돌려보는 부분 — DB는 안 건드리고 저장소 함수만 가짜로 바꿔요
# ==========================================================================
async def run_live():
    calls = {"take": [], "give": [], "offer": [], "open": 0}

    async def fake_take(uid, key):
        calls["take"].append((uid, key))
        return key in counts

    async def fake_give(uid, key):
        calls["give"].append((uid, key))

    async def fake_offer(sid, bid, key, price):
        calls["offer"].append((sid, bid, key, price))
        return "fake-id"

    async def fake_open_count(uid):
        return calls["open"]

    orig = (card_store.take_card, card_store.give_card,
            market.offer, market.open_count)
    card_store.take_card = fake_take
    card_store.give_card = fake_give
    market.offer = fake_offer
    market.open_count = fake_open_count
    try:
        print("\n[7] 🚨 **가격 방어선** — 모달에는 아무 숫자나 들어와요")
        for bad, why in ((0, "0코인"), (market.MAX_PRICE + 1, "상한 초과"),
                         (-5, "음수")):
            it = FakeInteraction(SELLER)
            ok = await cm.make_offer(it, FakeUser(BUYER), ANY_KEY, bad)
            check(not ok and not calls["offer"], f"{why}({bad})는 거절된다")
            check("코인" in it.text, f"{why} 안내가 간다", it.text[:60])
        check(not calls["take"], "거절된 제안은 카드를 **건드리지 않았다**",
              f"take={calls['take']}")

        print("\n[8] 경계값은 통과한다 (느슨한 검사였는지 확인)")
        for good in (market.MIN_PRICE, market.MAX_PRICE):
            calls["offer"].clear()
            it = FakeInteraction(SELLER)
            ok = await cm.make_offer(it, FakeUser(BUYER), ANY_KEY, good)
            check(ok and len(calls["offer"]) == 1, f"{good}코인은 통과")

        print("\n[9] 나 자신·봇·제안 상한")
        calls["take"].clear(); calls["offer"].clear()
        it = FakeInteraction(SELLER)
        ok = await cm.make_offer(it, FakeUser(SELLER), ANY_KEY, 30)
        check(not ok and not calls["take"], "나에게는 못 판다 (카드도 안 건드림)")
        it = FakeInteraction(SELLER)
        ok = await cm.make_offer(it, FakeUser(BUYER, bot=True), ANY_KEY, 30)
        check(not ok and not calls["take"], "봇에게는 못 판다")
        calls["open"] = market.MAX_OFFERS
        it = FakeInteraction(SELLER)
        ok = await cm.make_offer(it, FakeUser(BUYER), ANY_KEY, 30)
        check(not ok and not calls["take"],
              f"제안 {market.MAX_OFFERS}개를 넘기면 막힌다")
        calls["open"] = 0

        print("\n[10] 🚨 제안이 실패하면 카드를 **돌려준다**")
        async def boom(sid, bid, key, price):
            raise RuntimeError("일부러 터뜨림")
        market.offer = boom
        calls["take"].clear(); calls["give"].clear()
        it = FakeInteraction(SELLER)
        ok = await cm.make_offer(it, FakeUser(BUYER), ANY_KEY, 30)
        check(not ok, "실패를 False로 알린다")
        check(len(calls["take"]) == 1 and len(calls["give"]) == 1,
              "회수한 카드를 되돌렸다", f"take={calls['take']} give={calls['give']}")
        check("그대로" in it.text, "카드가 그대로라고 안내한다", it.text[:60])
        market.offer = fake_offer

        print("\n[11] 안 가진 카드는 회수 단계에서 막힌다")
        calls["offer"].clear()
        it = FakeInteraction(SELLER)
        ok = await cm.make_offer(it, FakeUser(BUYER), "그런키없음", 30)
        check(not ok and not calls["offer"], "없는 키는 거절")
    finally:
        (card_store.take_card, card_store.give_card,
         market.offer, market.open_count) = orig


asyncio.run(run_live())

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("✅ 🎪 도감 팔기 정상")
