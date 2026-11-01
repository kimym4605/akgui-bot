# -*- coding: utf-8 -*-
"""🔁 /팀짜기 같은 팀 반복 피하기 테스트 (2026-11-01).

출발점은 2026-10-31 `#📣｜내전모집`의 불만이에요:

> 서아 → 방장 멘션: *"너무 밸런스만 보고 팀을 구성하니까 **맨날 똑같은 팀**이야"*
> *"나 지금 내전 하면서 **재호랑 한번도 같은팀 된적이 없어**"*

디스코드에 접속하지 않아요 — 편성 계산·쌍 이력 저장·화면 문구를 봐요.

🚨 **가장 중요한 검사 두 개**
  ⒜ **이력이 없으면 옛 동작과 완전히 같다** — 첫 사용·다른 서버에서 동작이 바뀌면 안 돼요.
  ⒝ **균형을 허용 폭 이상으로 양보하지 않는다** — 섞으려다 내전을 망치면 안 돼요.

실행: python scripts/test_team_rotation.py   (종료코드 0 = 통과)
🚨 종료코드는 파이프 없이 재세요. `| tail`을 붙이면 tail의 종료코드가 나와요.
"""
import ast
import os
import random
import sys
import tempfile
from itertools import combinations
from pathlib import Path

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                 # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

from utils import team_balance, team_history, team_store   # noqa: E402

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


# 실전에 가까운 명단 10명. 티어가 흩어져 있어야 "최적 편성이 하나뿐"인 상황이 나와요.
TIERS = [21, 19, 18, 18, 17, 16, 16, 15, 13, 12]


def roster() -> list[team_balance.Rated]:
    return [
        team_balance.Rated(key=100 + i, label=f"P{i}", rating=float(t), tier_index=t)
        for i, t in enumerate(TIERS)
    ]


def keys_of(team) -> frozenset:
    return frozenset(p.key for p in team)


def pairs_of(team) -> set:
    return {team_history.pair_key(a, b)
            for a, b in combinations(sorted(p.key for p in team), 2)}


def pick(players, weights=None):
    """한 편성만 골라 `(A팀, B팀, 차이, 최적 차이)`로 돌려줘요.

    `rotated_splits`는 `(편성 목록, 최적 차이)`를 주는데, 테스트마다 풀어쓰면
    `[0][0]`을 헷갈려서 엉뚱한 걸 비교하게 돼요(실제로 한 번 당했어요)."""
    splits, best = team_balance.rotated_splits(players, limit=1, pair_weights=weights)
    team_a, team_b, diff = splits[0]
    return team_a, team_b, diff, best


# 테스트가 운영 파일을 건드리면 안 돼요 — 이력 파일을 임시 폴더로 돌려놓아요.
_tmp = tempfile.TemporaryDirectory()
team_history.FILE_PATH = Path(_tmp.name) / "team_pairs.json"
team_history.DATA_DIR = Path(_tmp.name)

print("\n[1] 이력이 없으면 옛 동작과 같다 (가장 중요)")
random.seed(7)
base_splits, base_best = team_balance.rotated_splits(roster(), limit=1)
base_a = keys_of(base_splits[0][0])
base_diff = base_splits[0][2]
check(base_diff == base_best, "이력이 없으면 고른 편성이 곧 최적 편성이다",
      f"diff={base_diff!r} best={base_best!r}")
same = True
for seed in range(1, 12):
    random.seed(seed)
    got, _best = team_balance.rotated_splits(roster(), limit=1)
    if got[0][2] != base_best:
        same = False
check(same, "이력이 없으면 몇 번 돌려도 최적 차이가 그대로다")
check(team_balance.repeat_cost(base_splits[0][0], base_splits[0][1], None) == 0.0,
      "무게가 None이면 반복 비용이 0이다")
check(team_balance.repeat_cost(base_splits[0][0], base_splits[0][1], {}) == 0.0,
      "무게가 빈 dict면 반복 비용이 0이다")

print("\n[2] 🚨 쌍 키 규칙이 두 모듈에서 같다 (어긋나면 비용이 조용히 전부 0)")
check(team_history.pair_key(222, 111) == "111|222", "pair_key는 정렬해서 이어 붙인다",
      team_history.pair_key(222, 111))
check(team_history.pair_key(111, 222) == team_history.pair_key(222, 111),
      "순서를 바꿔도 같은 키다")
# team_balance가 직접 만드는 키로 비용을 재서, 실제로 **잡히는지** 확인해요.
one = roster()
probe = {team_history.pair_key(one[0].key, one[1].key): 3.0}
check(team_balance.repeat_cost([one[0], one[1]], one[2:], probe) == 3.0,
      "team_history가 만든 키를 team_balance가 알아본다")
check(team_balance.repeat_cost([one[0], one[2]], [one[1], *one[3:]], probe) == 0.0,
      "두 사람이 갈라지면 그 쌍의 비용은 안 센다")

print("\n[3] 최근에 같은 팀이던 조합을 실제로 피한다 (서아의 불만)")
random.seed(11)
players = roster()
first_a, first_b, _d, _b = pick(players)
team_history.remember(9001, 42, first_a, first_b)
weights = team_history.pair_weights(42)
check(len(weights) == len(pairs_of(first_a)) + len(pairs_of(first_b)),
      "편성 한 건에서 같은 팀 쌍이 모두 기록된다",
      f"{len(weights)}개")
random.seed(11)
second, _sb, _sd, _s = pick(players, weights)
check(keys_of(second) != keys_of(first_a) and keys_of(second) != keys_of(first_b),
      "🥇 같은 명단인데 **다른 편성**이 나온다",
      f"{sorted(p.label for p in first_a)} → {sorted(p.label for p in second)}")
before = team_balance.repeat_cost(first_a, first_b, weights)
after_a, after_b, _ad, _ab = pick(players, weights)
after = team_balance.repeat_cost(after_a, after_b, weights)
check(after < before, "반복 비용이 줄어든 편성을 고른다", f"{before:.2f} → {after:.2f}")

print("\n[4] 한 번도 같은 팀이 아니던 두 사람이 언젠가 붙는다")
# 서아·재호에 해당하는 검사예요. 이력을 쌓아가며 10번 짜서, 모든 쌍이 한 번은 같은 팀이
# 되는지 봐요. (이력 없이 최적 편성만 쓰면 **영원히** 안 붙어요)
random.seed(3)
seen_pairs, msg = set(), 9100
team_history.FILE_PATH = Path(_tmp.name) / "run4.json"
for round_no in range(10):
    w = team_history.pair_weights(42)
    a, b, _d, _bd = pick(roster(), w)
    seen_pairs |= pairs_of(a) | pairs_of(b)
    team_history.remember(msg + round_no, 42, a, b)
all_pairs = {team_history.pair_key(x.key, y.key)
             for x, y in combinations(roster(), 2)}
coverage = len(seen_pairs) / len(all_pairs)
check(coverage > 0.60, "10번 짜면 가능한 쌍의 60% 넘게 한 팀이 된다",
      f"{len(seen_pairs)}/{len(all_pairs)} = {coverage:.0%}")
# 옛 동작과 비교 — 이력을 안 쓰면 같은 10번이 같은 쌍만 반복해요.
random.seed(3)
old_pairs = set()
for _ in range(10):
    a, b, _d, _bd = pick(roster())
    old_pairs |= pairs_of(a) | pairs_of(b)
check(len(seen_pairs) > len(old_pairs),
      "🥇 회전 쪽이 옛 동작보다 더 많은 쌍을 붙여준다",
      f"회전 {len(seen_pairs)}쌍 vs 옛 동작 {len(old_pairs)}쌍")

print("\n[5] 🚨 균형을 허용 폭 이상으로 양보하지 않는다")
random.seed(5)
_sa, _sb, _sd, best = pick(roster())
cut = team_balance.rotation_cutoff(best)
worst = 0.0
for round_no in range(12):
    w = team_history.pair_weights(42)
    a, b, diff, _bd = pick(roster(), w)
    worst = max(worst, diff)
    team_history.remember(9200 + round_no, 42, a, b)
check(worst <= cut + 1e-9, "고른 편성이 전부 허용 상한 안이다",
      f"최대 {worst:.3f} · 상한 {cut:.3f}")
check(cut <= max(team_balance.GOOD_BALANCE, best) + 1e-9,
      "허용 상한이 '균형이 잘 맞아요' 범위를 안 넘는다",
      f"cut={cut:.3f} good={team_balance.GOOD_BALANCE}")
# 이미 기울어진 명단은 회전을 꺼야 해요.
# ⚠️ 첫 시도는 8명 [25,24,23,22,6,5,4,3]이었는데 **완벽히 반으로 갈라져서**(best=0.00)
#    전제가 틀렸어요. 홀수 인원 + 큰 격차여야 균형을 못 맞춰요.
lopsided = [
    team_balance.Rated(key=200 + i, label=f"Q{i}", rating=float(t), tier_index=t)
    for i, t in enumerate([20, 20, 19, 10, 10])
]
_s2, best2 = team_balance.rotated_splits(lopsided, limit=1)
check(best2 >= team_balance.GOOD_BALANCE,
      "기울어진 명단은 최적 편성도 균형 범위를 벗어난다", f"best={best2:.2f}")
check(abs(team_balance.rotation_cutoff(best2) - best2) < 1e-9,
      "🚨 그 경우 허용 폭이 0이 되어 회전이 꺼진다",
      f"cutoff={team_balance.rotation_cutoff(best2):.3f} best={best2:.3f}")

print("\n[6] 이력 저장 규칙")
team_history.FILE_PATH = Path(_tmp.name) / "run6.json"
a, b, _d, _bd = pick(roster())
team_history.remember(7001, 42, a, b)
first_len = len(team_history.recent_sessions(42))
team_history.remember(7001, 42, a, b)
check(team_history.recent_sessions(42) and first_len == 1,
      "같은 세션을 두 번 저장해도 한 줄이다", f"{len(team_history.recent_sessions(42))}줄")
seq_before = team_history.recent_sessions(42)[0]["seq"]
team_history.remember(7002, 42, b, a)        # 다른 세션
team_history.remember(7001, 42, b, a)        # 7001의 편성을 바꿔 저장
rows = {r["seq"]: r for r in team_history.recent_sessions(42)}
check(seq_before in rows, "🚨 덮어쓸 때 순번이 유지된다(옛 내전이 최신으로 끼어들면 안 됨)",
      str(sorted(rows)))
check(team_history.recent_sessions(99) == [], "다른 서버의 이력은 안 섞인다")
check(team_history.pair_weights(42, exclude_message_id=7001)
      != team_history.pair_weights(42),
      "🚨 exclude_message_id가 그 세션을 실제로 뺀다")
team_history.FILE_PATH = Path(_tmp.name) / "run6b.json"
two = roster()[:2]
team_history.remember(7100, 42, two[:1], two[1:])
check(team_history.recent_sessions(42) == [],
      "2명짜리는 쌍이 하나뿐이라 저장하지 않는다")
# 가중치가 최근일수록 커야 해요.
team_history.FILE_PATH = Path(_tmp.name) / "run6c.json"
r = roster()
team_history.remember(7200, 42, r[:5], r[5:])          # 오래된 것
team_history.remember(7201, 42, r[::2], r[1::2])       # 최근 것
w = team_history.pair_weights(42)
# ⚠️ **두 편성에 모두 있는 쌍을 골라선 안 돼요** — 처음에 (0,2)를 썼다가 양쪽에 다
#    들어 있어서 무게가 1.7로 나왔어요(전제가 틀린 것이지 코드가 틀린 게 아니었어요).
old_pair = team_history.pair_key(r[0].key, r[1].key)   # 7200에서만 같은 팀
new_pair = team_history.pair_key(r[0].key, r[6].key)   # 7201에서만 같은 팀
check(w.get(new_pair, 0) > w.get(old_pair, 0),
      "최근 편성의 쌍이 더 무겁다",
      f"최근 {w.get(new_pair, 0):.2f} vs 오래된 {w.get(old_pair, 0):.2f}")
check(abs(w.get(new_pair, 0) - 1.0) < 1e-9, "가장 최근 편성의 무게는 1.0이다",
      f"{w.get(new_pair, 0):.3f}")
check(abs(w.get(old_pair, 0) - team_history.RECENCY_DECAY) < 1e-9,
      "한 칸 오래된 편성의 무게는 RECENCY_DECAY다",
      f"{w.get(old_pair, 0):.3f} vs {team_history.RECENCY_DECAY}")
both_pair = team_history.pair_key(r[0].key, r[2].key)  # 두 편성에 모두 있는 쌍
check(abs(w.get(both_pair, 0) - (1.0 + team_history.RECENCY_DECAY)) < 1e-9,
      "두 번 같은 팀이던 쌍은 무게가 더해진다", f"{w.get(both_pair, 0):.3f}")

print("\n[7] 저장소가 rotated를 싣고, 이력 훅이 안쪽에 있다")
store_src = open(os.path.join(BOT_DIR, "utils", "team_store.py"), encoding="utf-8").read()
check('"rotated"' in store_src, "save_session이 rotated를 저장한다")
sig = next(n for n in ast.walk(ast.parse(store_src))
           if isinstance(n, ast.FunctionDef) and n.name == "save_session")
kwonly = [x.arg for x in sig.args.kwonlyargs]
check("rotated" in kwonly, "save_session에 rotated 인자가 있다", str(kwonly))
body = ast.unparse(sig)
check("team_history.remember" in body,
      "🚨 쌍 이력 훅이 save_session **안**에 있다(호출부마다 붙이면 빼먹는다)")
i_save = body.find("_save_all(_pruned(data))")
i_hook = body.find("team_history.remember")
check(0 <= i_save < i_hook,
      "🚨 이력 저장이 세션 저장 **뒤**다(이력이 터져도 버튼은 살아야 한다)",
      f"{i_save} vs {i_hook}")
check("except Exception" in body, "이력 실패를 삼켜서 세션 저장을 막지 않는다")

print("\n[8] 화면 문구가 거짓말하지 않는다")
cog_src = open(os.path.join(BOT_DIR, "cogs", "team.py"), encoding="utf-8").read()
check("GOOD_BALANCE = team_balance.GOOD_BALANCE" in cog_src,
      "🚨 GOOD_BALANCE 숫자가 한 곳에만 있다(두 곳이면 조용히 어긋난다)")
tree = ast.parse(cog_src)
embed_fn = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_build_embed")
etxt = ast.unparse(embed_fn)
check("rotated" in [x.arg for x in embed_fn.args.kwonlyargs],
      "_build_embed가 rotated를 받는다")
i_rot = etxt.find("최근에 같은 팀이던 조합을 피해 섞었어요")
i_best = etxt.find("이 인원에선 이게 가장 균형 잡힌 편성이에요")
check(i_rot >= 0, "회전했을 때의 문구가 있다")
check(0 <= i_rot < i_best,
      "🚨 회전 문구가 '가장 균형 잡힌' 문구보다 **먼저** 걸린다", f"{i_rot} vs {i_best}")
check("rotated and (not manual)" in etxt,          # ast.unparse가 괄호를 붙여요
      "직접 조정한 편성엔 회전 문구를 안 띄운다", etxt[etxt.find("rotated and"):][:40])

print("\n[9] 세션이 rotated를 들고 다니고, 버튼이 제대로 갱신한다")
check("self.rotated = bool(record.get('rotated'))" in ast.unparse(tree)
      or "record.get(\"rotated\")" in cog_src,
      "Session이 rotated를 읽는다(옛 기록은 기본 False)")
for name, must in (
    ("reshuffle", "_is_rotated"),
    ("pure_random", "session.rotated = False"),
):
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == name), None)
    check(fn is not None and must in ast.unparse(fn), f"{name}가 rotated를 제대로 둔다")
reshuffle = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "reshuffle")
rtxt = ast.unparse(reshuffle)
check("exclude_message_id=session.message_id" in rtxt,
      "🚨 다시 섞기가 **자기 세션을 이력에서 뺀다**(안 빼면 자길 피하느라 망가진다)")

print("\n[10] 옛 호출 방식이 그대로 돈다 (회귀 방어)")
legacy = team_balance.balanced_splits(roster(), limit=3)
check(len(legacy) == 3 and len(legacy[0]) == 3,
      "balanced_splits가 여전히 3칸 튜플 목록을 준다", str(len(legacy[0])))
check(legacy[0][2] <= legacy[-1][2] + team_balance.PAIR_TOLERANCE + 1e-9,
      "후보 목록이 대체로 좋은 순서다")
check(team_balance.balanced_splits([], limit=1) == [], "0명이면 빈 목록이다")
one_player = roster()[:1]
check(team_balance.balanced_splits(one_player, limit=1) == [], "1명이면 빈 목록이다")
check(team_balance.rotated_splits([], limit=1) == ([], None),
      "rotated_splits도 0명이면 (빈 목록, None)이다")
sig2 = next(n for n in ast.walk(ast.parse(
    open(os.path.join(BOT_DIR, "utils", "team_balance.py"), encoding="utf-8").read()))
    if isinstance(n, ast.FunctionDef) and n.name == "balanced_splits")
check([a.arg for a in sig2.args.args][:2] == ["players", "limit"],
      "balanced_splits의 앞 두 인자가 그대로다(위치 인자로 부르는 곳이 있다)")

print("\n[11] 🥇 불만 그대로 재현 — '맨날 똑같은 팀'")
# 🚨 정수 티어만 쓰면 동률 편성이 수없이 생겨서 **옛 동작도 섞인 것처럼 보여요.**
#    실제로는 악귀 스코어 보정이 더해져 실수가 되고, 그래서 동률이 사라져요.
#    이 검사가 통째로 무효가 되는 지점이라 보정값을 꼭 섞어요.
ADJUST = [0.63, -0.41, 1.12, -0.85, 0.27, 1.44, -1.03, 0.09, -0.56, 0.78]


def real_roster():
    return [
        team_balance.Rated(key=300 + i, label=f"R{i}", rating=float(t) + adj, tier_index=t)
        for i, (t, adj) in enumerate(zip(TIERS, ADJUST))
    ]


team_history.FILE_PATH = Path(_tmp.name) / "run11.json"
random.seed(42)
old_shapes = set()
for _ in range(8):
    a, b, _d, _bd = pick(real_roster())
    old_shapes.add(keys_of(a))
check(len(old_shapes) == 1,
      "🔴 옛 동작은 8번을 돌려도 **편성이 한 가지뿐**이다(= 불만의 원인)",
      f"{len(old_shapes)}가지")

random.seed(42)
new_shapes, worst11, best11 = set(), 0.0, None
for round_no in range(8):
    w = team_history.pair_weights(42)
    a, b, diff, bd = pick(real_roster(), w)
    best11 = bd if best11 is None else best11
    new_shapes.add(keys_of(a))
    worst11 = max(worst11, diff)
    team_history.remember(9400 + round_no, 42, a, b)
check(len(new_shapes) == 8, "✅ 고친 뒤엔 8번이 **전부 다른 편성**이다",
      f"{len(new_shapes)}가지")
check(worst11 <= team_balance.rotation_cutoff(best11) + 1e-9,
      "🚨 그래도 균형은 허용 상한 안이다",
      f"최대 {worst11:.3f} · 상한 {team_balance.rotation_cutoff(best11):.3f}")
check(worst11 < team_balance.GOOD_BALANCE,
      "그 8번 모두 '균형이 잘 맞아요' 범위 안이다", f"최대 {worst11:.3f}")

_tmp.cleanup()

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("✅ 같은 팀 반복 피하기 전부 정상")
