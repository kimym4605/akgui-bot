"""`/팀짜기`의 🔀 직접 조정(맞교환/이동) 회귀 테스트.

    python scripts/test_team_manual_swap.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.team import _pick, swap_players  # noqa: E402
from utils import team_balance  # noqa: E402

passed = failed = 0


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


def player(key, rating):
    return team_balance.Rated(key=key, label=f"P{key}", rating=rating, tier_index=int(rating))


def names(team):
    return [p.label for p in team]


A = [player(1, 10), player(2, 9), player(3, 8)]
B = [player(4, 7), player(5, 6), player(6, 5)]

print("맞교환 (양쪽에서 한 명씩)")
new_a, new_b = swap_players(A, B, A[0], B[0])
check("A에서 뺀 사람이 B로", "P1" in names(new_b), True)
check("B에서 뺀 사람이 A로", "P4" in names(new_a), True)
check("A에 더 이상 없음", "P1" not in names(new_a), True)
check("B에 더 이상 없음", "P4" not in names(new_b), True)
check("인원이 유지됨", (len(new_a), len(new_b)), (3, 3))
check("남은 사람 순서는 그대로", names(new_a), ["P2", "P3", "P4"])

print("\n한 명만 이동 (한쪽만 고름)")
new_a, new_b = swap_players(A, B, A[1], None)
check("A→B 이동", (names(new_a), names(new_b)), (["P1", "P3"], ["P4", "P5", "P6", "P2"]))
check("인원이 한 명씩 어긋남", (len(new_a), len(new_b)), (2, 4))
new_a, new_b = swap_players(A, B, None, B[2])
check("B→A 이동", (names(new_a), names(new_b)), (["P1", "P2", "P3", "P6"], ["P4", "P5"]))

print("\n아무도 안 고름")
new_a, new_b = swap_players(A, B, None, None)
check("그대로 복사됨", (names(new_a), names(new_b)), (names(A), names(B)))
check("새 리스트를 돌려줌", new_a is not A, True)

print("\n원본 불변 (⚠️ _candidates와 리스트를 공유해서 중요해요)")
before_a, before_b = names(A), names(B)
swap_players(A, B, A[0], B[0])
swap_players(A, B, A[1], None)
check("A 원본 그대로", names(A), before_a)
check("B 원본 그대로", names(B), before_b)

print("\n연속 조정 (교환 결과를 다시 교환)")
mid_a, mid_b = swap_players(A, B, A[0], B[0])          # P1 ↔ P4
fin_a, fin_b = swap_players(mid_a, mid_b, mid_a[0], mid_b[0])  # P2 ↔ P5
check("두 번 교환이 누적됨", sorted(names(fin_a)), ["P3", "P4", "P5"])
check("반대편도 누적됨", sorted(names(fin_b)), ["P1", "P2", "P6"])
check("아무도 사라지지 않음", sorted(names(fin_a) + names(fin_b)),
      ["P1", "P2", "P3", "P4", "P5", "P6"])

print("\n한쪽 팀이 비는 경우 (호출하는 쪽에서 막지만, 함수는 그대로 돌려줘요)")
solo_a, solo_b = [player(1, 10)], [player(2, 5)]
new_a, new_b = swap_players(solo_a, solo_b, solo_a[0], None)
check("A가 비어버림", (len(new_a), len(new_b)), (0, 2))

print("\n실력 차이 재계산")
diff_same = team_balance.imbalance(A, B)
check("imbalance가 양수", diff_same > 0, True)
check("평균 차이와 일치", round(diff_same, 6), round(abs(9 - 6), 6))
check("팀을 맞바꿔도 같은 값", round(team_balance.imbalance(B, A), 6), round(diff_same, 6))
# 균형 탐색이 내는 diff와 같은 척도인지 (조정 전후를 나란히 비교하려면 같아야 해요)
cand_a, cand_b, cand_diff = team_balance.balanced_splits(A + B, limit=1)[0]
check("balanced_splits의 diff와 같은 척도",
      round(team_balance.imbalance(cand_a, cand_b), 6), round(cand_diff, 6))
check("빈 팀이면 inf", team_balance.imbalance([], B), float("inf"))

print("\n드롭다운 값 → 참가자 찾기 (_pick)")
check("고른 id의 사람을 찾음", _pick(A, ["2"]).label, "P2")
check("안 고르면 None", _pick(A, []), None)
check("그 팀에 없는 id면 None", _pick(A, ["4"]), None)

print(f"\n{passed}개 통과, {failed}개 실패")
sys.exit(1 if failed else 0)
