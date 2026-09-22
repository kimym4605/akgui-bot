"""
`/팀짜기`의 실력 균형 계산이에요. 디스코드에 의존하지 않는 순수 계산만 모아둬서
따로 테스트할 수 있게 했어요. (cogs/team.py가 멤버 -> Rated 변환만 해서 넘겨줘요)

점수 축은 **티어 단계 번호**예요 (아이언1=1 … 실버3=9 … 레디언트=25).
이 축을 고른 이유:
  - 티어 역할은 `/전적`을 돌린 사람에게 자동으로 붙어 있어서 확보율이 가장 높아요.
  - 악귀 스코어(0~2000)는 조회해본 사람만 있어서, 단독 축으로 쓰면 절반이 빈칸이 돼요.
그래서 티어를 뼈대로 쓰고, 악귀 스코어가 있으면 같은 티어 안에서 세부 보정만 해요.
"""
import random
from dataclasses import dataclass
from itertools import combinations
from typing import Optional

# 아래 세 값은 cogs/rank.py의 악귀 스코어 공식과 반드시 같아야 해요. 거기서 바꾸면 여기도 바꿔주세요.
#   악귀 스코어 = 500 + (성적 편차) × 1.08^(N - 9 + RR/100)
AGWI_BASELINE = 500.0
TIER_MULT_BASE = 1.08
TIER_MULT_N_BASELINE = 9  # 실버 3 = 배수 1.00배

# ⚠️ 악귀 스코어에는 **티어 배수가 이미 곱해져 있어요.** 그래서 스코어를 그대로 보정에 쓰면
#    티어를 두 번 세게 돼요(초월자가 불멸 위로 올라가는 식으로 과대평가됐어요).
#    그래서 배수를 먼저 나눠서 '티어와 무관한 순수 성적 편차'로 되돌린 뒤에 씁니다.
# 성적 편차가 이만큼이면 티어 한 단계 값으로 봐요. (KD +0.75 정도가 한 단계)
DELTA_PER_TIER = 150.0
# 성적 보정이 티어를 완전히 뒤집지는 못하게 막아요(조회 한 번의 표본에 휘둘리면 안 돼요).
# 2단계 = 같은 티어 안에서 움직이는 정도예요(티어 하나는 3단계).
AGWI_ADJUST_LIMIT = 2.0
# 티어도 스코어도 없는 사람을 놓을 자리(실버 3). 참가자 평균을 알면 그걸 먼저 써요.
FALLBACK_TIER_INDEX = 9

# 이 인원까지는 모든 조합을 다 따져서 최적해를 보장해요. C(14,7)=3432개라 순식간이에요.
EXHAUSTIVE_LIMIT = 14


@dataclass
class Rated:
    """점수가 매겨진 참가자 한 명."""

    key: int  # 디스코드 유저 id
    label: str  # 화면에 보일 이름
    rating: float  # 티어 단계 축의 실력 점수
    tier_index: Optional[int] = None  # 티어 역할에서 읽은 단계(없으면 None)
    agwi_score: Optional[float] = None  # 마지막 /전적의 악귀 스코어(없으면 None)
    estimated: bool = False  # 근거가 없어서 평균값으로 때운 경우 True


def performance_delta(
    agwi_score: Optional[float], tier_index: Optional[int]
) -> Optional[float]:
    """악귀 스코어에서 티어 배수를 되돌려 '티어와 무관한 순수 성적 편차'를 복원해요.

    0이면 그 티어에서 평균적인 성적, 양수면 티어 대비 잘하고 있다는 뜻이에요.
    RR은 저장해두지 않아서 0으로 봐요(배수 오차 최대 8%라 순위를 뒤집지 않아요)."""
    if agwi_score is None:
        return None
    base = tier_index if tier_index is not None else FALLBACK_TIER_INDEX
    multiplier = TIER_MULT_BASE ** (base - TIER_MULT_N_BASELINE)
    return (agwi_score - AGWI_BASELINE) / multiplier


def agwi_adjustment(
    agwi_score: Optional[float], tier_index: Optional[int] = None
) -> float:
    """성적이 티어 대비 얼마나 좋은지를 티어 단계 보정값으로 바꿔요. 스코어가 없으면 0."""
    delta = performance_delta(agwi_score, tier_index)
    if delta is None:
        return 0.0
    raw = delta / DELTA_PER_TIER
    return max(-AGWI_ADJUST_LIMIT, min(AGWI_ADJUST_LIMIT, raw))


def rate_one(
    tier_index: Optional[int], agwi_score: Optional[float]
) -> Optional[float]:
    """한 사람의 실력 점수. 티어도 스코어도 없으면 None(부를 쪽에서 평균으로 채워요)."""
    if tier_index is None and agwi_score is None:
        return None
    base = float(tier_index) if tier_index is not None else float(FALLBACK_TIER_INDEX)
    return base + agwi_adjustment(agwi_score, tier_index)


def fill_missing(players: list[Rated]) -> list[Rated]:
    """점수를 못 매긴 사람을 나머지 참가자의 평균으로 채워요.

    0점으로 두면 그 사람들이 한 팀에 몰려버려요. 전원 정보가 없으면 다 같은 값이 돼서
    결과적으로 랜덤 분배와 같아지는데, 그게 맞는 동작이에요(근거가 없으니까)."""
    known = [p.rating for p in players if not p.estimated and p.rating is not None]
    average = sum(known) / len(known) if known else float(FALLBACK_TIER_INDEX)
    for player in players:
        if player.rating is None:
            player.rating = average
            player.estimated = True
    return players


def _imbalance(team_a: list[Rated], team_b: list[Rated]) -> float:
    """두 팀의 평균 실력 차이(절댓값).

    합계가 아니라 평균으로 재요. 홀수 인원이면 한 팀이 한 명 많은데, 합계로 재면
    인원이 많은 쪽이 무조건 강해 보여서 엉뚱한 조합이 뽑혀요."""
    if not team_a or not team_b:
        return float("inf")
    mean_a = sum(p.rating for p in team_a) / len(team_a)
    mean_b = sum(p.rating for p in team_b) / len(team_b)
    return abs(mean_a - mean_b)


def _exhaustive_candidates(players: list[Rated]) -> list[tuple[float, list[int], list[int]]]:
    """모든 편성을 다 따져서 (차이, A인덱스, B인덱스) 목록을 만들어요.

    0번 참가자는 항상 A팀에 고정해요. 안 그러면 A/B만 바꾼 같은 편성이 두 번 나와요."""
    count = len(players)
    size_a = count // 2  # 홀수면 A팀이 한 명 적어요
    rest = list(range(1, count))
    results = []
    for chosen in combinations(rest, size_a - 1):
        a_index = [0, *chosen]
        b_index = [i for i in rest if i not in chosen]
        team_a = [players[i] for i in a_index]
        team_b = [players[i] for i in b_index]
        results.append((_imbalance(team_a, team_b), a_index, b_index))
    results.sort(key=lambda row: row[0])
    return results


def _greedy_candidates(
    players: list[Rated], rounds: int = 60
) -> list[tuple[float, list[int], list[int]]]:
    """인원이 많을 때 쓰는 방법이에요. 센 사람부터 번갈아 담고(스네이크), 그 뒤에
    두 명씩 맞바꿔 보면서 차이가 줄면 채택해요. 시작 순서를 조금씩 흔들어 여러 후보를 만들어요."""
    count = len(players)
    size_a = count // 2
    size_b = count - size_a  # 홀수면 B팀이 한 명 많아요
    order = sorted(range(count), key=lambda i: players[i].rating, reverse=True)
    results = []
    for attempt in range(rounds):
        shuffled = order[:]
        if attempt:
            # 비슷한 점수끼리 앞뒤를 살짝 섞어서 다른 출발점을 만들어요.
            for i in range(0, count - 1, 2):
                if random.random() < 0.5:
                    shuffled[i], shuffled[i + 1] = shuffled[i + 1], shuffled[i]
        a_index, b_index = [], []
        for position, index in enumerate(shuffled):
            # 스네이크 드래프트: A B / B A / A B / B A … 순으로 담아요.
            pair_is_even = (position // 2) % 2 == 0
            prefer_a = (position % 2 == 0) == pair_is_even
            if prefer_a and len(a_index) < size_a:
                a_index.append(index)
            elif not prefer_a and len(b_index) < size_b:
                b_index.append(index)
            elif len(a_index) < size_a:  # 원하던 팀이 꽉 찼으면 남은 자리로
                a_index.append(index)
            else:
                b_index.append(index)
        # 스왑 개선
        improved = True
        while improved:
            improved = False
            best = _imbalance([players[i] for i in a_index], [players[i] for i in b_index])
            for ai in range(len(a_index)):
                for bi in range(len(b_index)):
                    a_try, b_try = a_index[:], b_index[:]
                    a_try[ai], b_try[bi] = b_try[bi], a_try[ai]
                    diff = _imbalance([players[i] for i in a_try], [players[i] for i in b_try])
                    if diff < best - 1e-9:
                        a_index, b_index, best, improved = a_try, b_try, diff, True
                        break
                if improved:
                    break
        results.append((
            _imbalance([players[i] for i in a_index], [players[i] for i in b_index]),
            sorted(a_index), sorted(b_index),
        ))
    # 같은 편성이 여러 번 나오니 중복을 걷어내요.
    seen, unique = set(), []
    for diff, a_index, b_index in sorted(results, key=lambda row: row[0]):
        signature = (tuple(a_index), tuple(b_index))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append((diff, a_index, b_index))
    return unique


def balanced_splits(
    players: list[Rated], limit: int = 10
) -> list[tuple[list[Rated], list[Rated], float]]:
    """실력 차이가 작은 편성을 좋은 순서대로 최대 `limit`개 돌려줘요.

    맨 앞이 가장 균형 잡힌 편성이고, 뒤쪽은 '다시 섞기'에 쓸 차선책이에요.
    차이가 완전히 같은 편성들은 매번 다른 게 먼저 나오도록 섞어줘요."""
    if len(players) < 2:
        return []
    candidates = (
        _exhaustive_candidates(players)
        if len(players) <= EXHAUSTIVE_LIMIT
        else _greedy_candidates(players)
    )
    # 차이가 동률인 묶음 안에서만 순서를 섞어요(더 균형 잡힌 편성이 뒤로 밀리지 않게).
    grouped: dict[float, list[tuple[list[int], list[int]]]] = {}
    for diff, a_index, b_index in candidates:
        grouped.setdefault(round(diff, 6), []).append((a_index, b_index))
    output = []
    for diff in sorted(grouped):
        bucket = grouped[diff]
        random.shuffle(bucket)
        for a_index, b_index in bucket:
            output.append((
                [players[i] for i in a_index],
                [players[i] for i in b_index],
                diff,
            ))
            if len(output) >= limit:
                return output
    return output


def random_split(players: list[Rated]) -> tuple[list[Rated], list[Rated], float]:
    """실력을 무시하고 그냥 섞어요. 예전 `/팀짜기`와 같은 동작이에요."""
    shuffled = players[:]
    random.shuffle(shuffled)
    half = len(shuffled) // 2
    team_a, team_b = shuffled[:half], shuffled[half:]
    return team_a, team_b, _imbalance(team_a, team_b)
