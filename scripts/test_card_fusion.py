# -*- coding: utf-8 -*-
"""⚒️ 카드 합성 테스트 (2026-10-31).

DB를 안 건드려요 — `card_store`의 순수 함수(`fuse_materials`·`fuse_cards`)와
`cogs/card_gacha.py`의 패널 구조만 봐요.

실행: python scripts/test_card_fusion.py   (종료코드 0 = 전부 통과)
🚨 종료코드는 **파이프 없이** 재세요 — `python t.py | tail; echo $?`는 tail의 코드라
   테스트가 죽어도 0이 찍혀요(2026-10-28에 실제로 당했어요).
"""
import ast
import os
import random
import sys
from collections import Counter

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from utils import card_store as cs          # noqa: E402
from utils.card_data import CARDS           # noqa: E402

passed, failed = [], []


def ok(label):
    passed.append(label)
    print(f"  ✅ {label}")


def bad(label, detail=""):
    failed.append(f"{label}{(' — ' + detail) if detail else ''}")
    print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


def check(cond, label, detail=""):
    ok(label) if cond else bad(label, detail)


KEYS = {g: [c["key"] for c in lst] for g, lst in CARDS.items()}
N1, N2, N3 = KEYS["일반"][0], KEYS["일반"][1], KEYS["일반"][2]
R1 = KEYS["레어"][0]
E1 = KEYS["에픽"][0]
L1 = KEYS["레전드"][0]

print("\n[1] 재료 고르기 — 마지막 1장은 보호해요")
check(cs.fuse_materials({N1: 1, N2: 1, N3: 1}) is None,
      "각 1장만 있으면 재료가 안 돼요 (3장이지만 전부 마지막 장)")
check(cs.fuse_materials({N1: 4}) == {N1: 3},
      "4장이면 3장만 먹어요 (1장 남김)")
check(cs.fuse_materials({N1: 3}) is None,
      "3장이면 쓸 수 있는 중복은 2장이라 거절")
take = cs.fuse_materials({N1: 2, N2: 2, N3: 2})
check(take is not None and sum(take.values()) == 3 and all(v <= 1 for v in take.values()),
      "여러 종류에서 모아 3장을 맞춰요", str(take))

print("\n[2] 🚨 많이 쌓인 것부터 먹어요 (골고루 깎으면 체감이 안 줄어요)")
take = cs.fuse_materials({N1: 13, N2: 2})
check(take == {N1: 3}, "12장 쌓인 쪽에서만 3장", str(take))

print("\n[3] 🚨 에픽·레전드 중복은 재료가 아니에요 (장터 자산이라 태우면 안 돼요)")
check(cs.dup_count({E1: 5}) == 0, "에픽 5장 → 쓸 수 있는 중복 0장")
check(cs.dup_count({L1: 4}) == 0, "레전드 4장 → 쓸 수 있는 중복 0장")
check(cs.fuse_materials({E1: 9}) is None, "에픽만 9장이면 합성 거절")
check(cs.dup_count({N1: 5, R1: 3, E1: 4}) == 4 + 2,
      "일반·레어만 세요 (5→4 + 3→2 = 6)", str(cs.dup_count({N1: 5, R1: 3, E1: 4})))

print("\n[4] 합성 1회 — 재료 3장이 사라지고 카드 1장이 들어와요")
counts = {N1: 10}
res, used = cs.fuse_cards(counts, times=1, rng=random.Random(1))
check(len(res) == 1, "결과 1장", str(len(res)))
check(sum(used.values()) == cs.FUSE_N, f"먹은 재료 {cs.FUSE_N}장", str(used))
check(counts == {N1: 10}, "호출자의 dict를 안 건드려요", str(counts))

print("\n[5] 🚨 천장(since_legend)은 합성에 끼어들지 않아요")
# 천장 직전 상태를 만들어도 합성에선 레전드 확정이 되면 안 돼요.
res, _ = cs.fuse_cards({N1: 400}, times=0, rng=random.Random(3))
check(not any(d["pity"] for d in res),
      f"{len(res)}회 전부 pity=False",
      str([d["key"] for d in res if d["pity"]]))
src = ast.parse(open(os.path.join(BOT_DIR, "utils", "card_store.py"),
                     encoding="utf-8").read())
fuse_fn = next(n for n in ast.walk(src)
               if isinstance(n, ast.FunctionDef) and n.name == "fuse_cards")
draw_calls = [n for n in ast.walk(fuse_fn)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "draw_cards"]
check(len(draw_calls) == 1, "fuse_cards가 draw_cards를 한 번 불러요 (확률표 복붙 금지)",
      str(len(draw_calls)))
check(bool(draw_calls) and any(
          isinstance(a, ast.Constant) and a.value == 0 for a in draw_calls[0].args),
      "🚨 since_legend에 0을 넘겨 천장을 막아요",
      ast.dump(draw_calls[0]) if draw_calls else "호출 없음")

print("\n[6] 몰아 합성 — 중복이 바닥날 때까지 돌고 멈춰요")
start = {N1: 31}                      # 중복 30장
res, used = cs.fuse_cards(start, times=0, rng=random.Random(5))
left = dict(start)
for k, v in used.items():
    left[k] -= v
for d in res:
    left[d["key"]] = left.get(d["key"], 0) + 1
check(cs.dup_count(left) < cs.FUSE_N,
      f"{len(res)}회 돌린 뒤 남은 중복 {cs.dup_count(left)}장 < {cs.FUSE_N}",
      str(cs.dup_count(left)))
check(sum(used.values()) == len(res) * cs.FUSE_N,
      "먹은 재료 = 합성 횟수 x 3", f"{sum(used.values())} vs {len(res) * cs.FUSE_N}")
check(len(res) <= cs.MAX_FUSES, f"안전 상한 {cs.MAX_FUSES} 안", str(len(res)))

print("\n[7] 🚨 장수 보존 — 합성해도 카드가 공짜로 늘거나 사라지지 않아요")
start = {N1: 20, N2: 7, R1: 4}
total_before = sum(start.values())
res, used = cs.fuse_cards(start, times=0, rng=random.Random(11))
expect = total_before - sum(used.values()) + len(res)
after = dict(start)
for k, v in used.items():
    after[k] -= v
for d in res:
    after[d["key"]] = after.get(d["key"], 0) + 1
check(sum(after.values()) == expect,
      f"{total_before}장 - {sum(used.values())} + {len(res)} = {expect}",
      str(sum(after.values())))
check(all(v >= 0 for v in after.values()), "음수가 된 카드 없음",
      str({k: v for k, v in after.items() if v < 0}))
check(all(v >= 1 for k, v in after.items() if start.get(k)),
      "원래 갖고 있던 카드는 전부 1장 이상 남아요 (도감이 안 비어요)",
      str({k: v for k, v in after.items() if start.get(k) and v < 1}))

print("\n[8] 확률이 뽑기와 같아요 (사용자 결정 2026-10-31)")
res, _ = cs.fuse_cards({N1: 3001}, times=0, rng=random.Random(99))
tally = Counter(d["grade"] for d in res)
n = len(res)
want = cs.GRADE_WEIGHTS["일반"] / sum(cs.GRADE_WEIGHTS.values()) * 100
got = tally["일반"] / n * 100
check(abs(got - want) < 4,
      f"{n}회 중 일반 {got:.1f}% (뽑기 {want:.1f}%와 오차 4%p 안)",
      f"{got:.1f}% vs {want:.1f}%")
check(tally["레어"] > 0 and (tally["에픽"] > 0 or tally["레전드"] > 0),
      f"레어 이상도 나와요 (레어 {tally['레어']} · 에픽 {tally['에픽']} · 레전드 {tally['레전드']})")

print("\n[9] 🚨 에픽·레전드는 '안 가진 것만' 나와요 (중복 불가)")
# 에픽 1종만 빼고 다 가진 상태 + 레전드 전종 보유 → 에픽은 그 1종만 나와야 해요.
have = {k: 1 for k in KEYS["에픽"][1:]}
have.update({k: 1 for k in KEYS["레전드"]})
have[N1] = 200
res, _ = cs.fuse_cards(have, times=0, rng=random.Random(21))
eps = [d["key"] for d in res if d["grade"] == "에픽"]
check(all(k == KEYS["에픽"][0] for k in eps),
      f"나온 에픽이 전부 미보유 1종 ({len(eps)}장)", str(set(eps)))
check(all(d["is_new"] for d in res if d["grade"] in ("에픽", "레전드")),
      "에픽·레전드는 전부 신규예요")

print("\n[10] 🚨 줄 카드가 없으면 재료를 안 먹어요 (빈손으로 태우면 안 돼요)")
# 도감을 전부 모으고 중복만 남긴 상태에선 일반·레어가 중복을 허용하니 늘 뭔가 나와요.
# 그래서 '줄 게 없다'를 억지로 만들려면 가중치를 비워야 해요 — 되돌림 분기만 직접 봐요.
real = cs.GRADE_WEIGHTS.copy()
try:
    for g in list(cs.GRADE_WEIGHTS):
        cs.GRADE_WEIGHTS[g] = 0.0
    res, used = cs.fuse_cards({N1: 10}, times=1, rng=random.Random(2))
    check(res == [] and used == {},
          "줄 카드가 없으면 결과도 없고 재료도 안 먹어요", f"res={res} used={used}")
finally:
    cs.GRADE_WEIGHTS.clear()
    cs.GRADE_WEIGHTS.update(real)
check(sum(cs.GRADE_WEIGHTS.values()) == 100, "가중치를 원래대로 돌려놨어요",
      str(sum(cs.GRADE_WEIGHTS.values())))

print("\n[11] 🚨 draws를 올리지 않아요 (뽑기 횟수 통계가 거짓이 돼요)")
store_src = open(os.path.join(BOT_DIR, "utils", "card_store.py"), encoding="utf-8").read()
fsync = next(n for n in ast.walk(ast.parse(store_src))
             if isinstance(n, ast.FunctionDef) and n.name == "_fuse_sync")
body = ast.unparse(fsync)
check('"draws"' not in body and "'draws'" not in body.replace("state['draws']", ""),
      "_fuse_sync가 draws를 안 건드려요")
check('"$gte"' in body or "'$gte'" in body,
      "🚨 낙관적 동시성을 $gte로 걸어요 (안 걸면 장수가 음수가 돼요)")

print("\n[12] 🎴 패널 — 영속 뷰 3요소 + edit 사고 방지")
gacha_src = open(os.path.join(BOT_DIR, "cogs", "card_gacha.py"), encoding="utf-8").read()
tree = ast.parse(gacha_src)
panel = next((n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == "CardPanelView"), None)
check(panel is not None, "CardPanelView가 있어요")
if panel:
    ptxt = ast.unparse(panel)
    check("timeout=None" in ptxt, "① timeout=None")
    ids = [kw.value.value for n in ast.walk(panel)
           if isinstance(n, ast.Call)
           for kw in n.keywords
           if kw.arg == "custom_id" and isinstance(kw.value, ast.Constant)]
    btns = [n for n in panel.body
            if isinstance(n, ast.AsyncFunctionDef) and n.decorator_list]
    check(len(ids) == len(btns) and len(set(ids)) == len(ids),
          f"② 버튼 {len(btns)}개가 전부 고유 custom_id ({len(ids)}개)", str(ids))
    check(all(i.startswith("akgui:card:") for i in ids),
          "custom_id가 akgui:card: 로 시작해요", str(ids))
    check("self" not in ptxt.split("def __init__")[-1].split("@discord")[0]
          or "interaction.user" in ptxt,
          "③ 누른 사람은 interaction.user로만 알아내요")
    # 🚨 패널 버튼이 ephemeral로 응답해야 패널이 결과로 덮이지 않아요.
    for fn in btns:
        ftxt = ast.unparse(fn)
        if fn.name.startswith("fuse") or fn.name == "dex":
            check("ephemeral=True" in ftxt, f"{fn.name}: ephemeral=True로 응답")
        check("defer" in ftxt, f"{fn.name}: defer가 먼저 (3초 토큰)")

check("self.bot.add_view(CardPanelView())" in gacha_src,
      "③ cog_load에서 add_view (없으면 재시작 뒤 버튼이 조용히 죽어요)")

print("\n[13] 🚨 패널·안내 글에 숫자를 손으로 적지 않아요")
panel_fn = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_card_panel_embed"), None)
check(panel_fn is not None, "_card_panel_embed가 있어요")
if panel_fn:
    txt = ast.unparse(panel_fn)
    check("PULL_PRICE" in txt and "CARDS_PER_PULL" in txt and "FUSE_N" in txt,
          "가격·장수·재료 수를 상수에서 읽어요")
    check("GRADE_WEIGHTS" in txt, "확률도 상수에서 만들어요")
    # 상수가 아닌 생짜 숫자가 문구에 박혀 있으면 잡아요(10코인·3장 같은 것).
    lits = [f"{cs.PULL_PRICE}코인", f"{cs.CARDS_PER_PULL}장", f"{cs.FUSE_N}장"]
    hard = [s for s in lits if f'"{s}' in txt or f"'{s}" in txt or f" {s}" in txt]
    check(not hard, "문구에 숫자를 직접 박지 않았어요", str(hard))

print("\n[14] 합성이 명령어·버튼 양쪽에서 같은 함수를 써요")
check("await do_fuse(" in gacha_src, "do_fuse를 위임해서 써요")
check(gacha_src.count("async def do_fuse") == 1, "do_fuse 정의는 하나뿐")
check("async def show_collection" in gacha_src
      and gacha_src.count("async def show_collection") == 1,
      "도감 본체도 모듈 함수 하나 (📖 버튼이 복붙 아님)")

print("\n" + "=" * 50)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 합성 전부 정상")
