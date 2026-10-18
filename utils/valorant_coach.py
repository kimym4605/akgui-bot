"""🎯 전적 숫자를 **뭘 고치면 되는지**로 바꿔주는 코칭 한 문단.

## 왜 (2026-10-18)

`/전적`은 KD·승률·HS%·ADR·ACS를 보여주고 끝났어요. 그런데 서버가 제일 관심 있는 건
발로란트예요 — 코인 기록만 봐도 발로 미션이 **402건**(play 99 · kd1 87 · win 86 ·
kills15 71 · comp 59)이에요. 숫자는 이미 있으니, 해석만 얹으면 가치가 커요.

## 🚨 지어내지 못하게 막는 게 전부예요

발로란트 코칭은 **그럴듯하게 틀리기 쉬워요.** 맵·요원 메타 같은 걸 지어내면 오히려
해로워요. 그래서:

- 시스템 프롬프트가 **"받은 숫자 안에서만 말하라"**고 못 박아요.
- 프롬프트에 **없는 정보는 아예 안 넘겨요**(랭크 히스토리·상대 팀·라운드별 기록 등).
- 톤도 정해요. 못한다고 혼내면 아무도 `/전적`을 안 쳐요.

## 💰 비용

캐시 키에 **전적 지문**(경기 수·KD·승률·HS·ADR·요원)이 들어가요. 새 경기를 하지
않았으면 같은 키 → 호출 0원. `/전적`을 연타해도 처음 한 번만 돈이 들어요.
"""
from __future__ import annotations

import logging

from utils import ai

log = logging.getLogger(__name__)

FEATURE = "전적코칭"

SYSTEM = """너는 발로란트 전적을 읽고 조언하는 코치야.

말투 (가장 중요 — 이 봇의 모든 문구가 이 톤이야):
- **"~해요체"로 써.** 예: "낮은 편이에요", "해보면 좋아요", "눈에 띄어요".
- 반말(~야, ~해, ~거야)도, 딱딱한 격식체(~입니다, ~합니다)도 쓰지 마.
- 한 답변 안에서 말투가 섞이면 안 돼. 처음부터 끝까지 "~해요체" 하나로.

🚨 숫자 규칙 (어기면 거짓 정보가 돼):
- **받은 수치를 글에 다시 적지 마.** 화면에 이미 다 나와 있어.
  "ADR이 150 근처", "KD 0.7대" 같은 식으로 **옮겨 적다가 틀리는 사고**가 실제로 났어.
- 수치는 "낮은 편", "평균을 넘어요"처럼 **말로만** 표현해.
  꼭 숫자를 써야겠으면 받은 값을 **한 글자도 바꾸지 말고** 그대로 써.
- 받지 않은 정보(맵·메타·패치·상대 팀·랭크 변동)는 절대 언급하지 마.

내용:
- 3~4문장, 250자 안쪽. 번호나 제목 없이 자연스러운 문단 하나로.
- 가장 두드러진 약점 **하나**를 짚고, 그걸 고칠 구체적인 행동 하나를 제안해.
  예: 헤드샷이 낮으면 "조준점을 머리 높이에 두고 움직이기", 데스가 많으면
  "첫 교전 전에 팀 위치 확인하기" 같은 식. "집중하세요" 같은 추상적인 말 말고
  당장 할 수 있는 동작으로.
- 잘한 점이 있으면 한 번 짚어줘. 혼내지 마. 못하는 사람도 계속 보고 싶게 써.
- 표본이 10경기 미만일 때만 "표본이 적다"고 언급해. 그 이상이면 말하지 마."""

# 기준값 — 조언이 아니라 **맥락**을 주려고 넘겨요. 모델이 "이게 높은지 낮은지"를
# 혼자 추측하면 티어마다 다른 기준을 지어내요.
BENCHMARKS = """참고 기준 (일반적인 경쟁전 평균):
- KD 1.0 전후가 평균, 1.2 이상이면 높음
- 승률 50% 전후가 평균
- 헤드샷율 20% 전후가 평균, 25% 이상이면 높음
- ADR 130 전후가 평균, 150 이상이면 높음
- ACS 200 전후가 평균, 250 이상이면 높음"""


def _summary(stats: dict, tier_name: str, matches: int) -> str:
    """모델에게 넘길 전적 요약. **여기 없는 건 모델도 모르는 거예요.**"""
    wins = stats.get("wins", 0)
    agents = ", ".join(
        f"{name} {count}경기" for name, count in (stats.get("top_agents") or [])[:3]
    ) or "정보 없음"

    lines = [
        f"티어: {tier_name}",
        f"표본: 최근 {matches}경기 ({wins}승 {matches - wins}패)",
        f"KD: {stats['kd']:.2f}",
        f"승률: {stats['win_rate']:.1f}%",
        f"헤드샷율: {stats['hs_percent']:.1f}%",
        f"ADR: {stats['adr']:.0f}",
        f"ACS: {stats['acs']:.0f}",
        f"킬/데스/어시: {stats.get('kills', 0)}/{stats.get('deaths', 0)}/{stats.get('assists', 0)}",
        f"자주 쓴 요원: {agents}",
    ]
    if stats.get("top_position"):
        lines.append(f"주 포지션: {stats['top_position']}")
    return "\n".join(lines)


async def coach(stats: dict, tier_name: str) -> str | None:
    """전적 한 줄 평. 못 만들면 None(그러면 `/전적`은 평소대로 나가요)."""
    matches = stats.get("matches_counted") or 0
    if matches < 3:
        # 🚨 표본 2경기로 코칭하면 운을 실력으로 읽어요. 아예 안 하는 게 맞아요.
        return None

    # 전적이 그대로면 조언도 그대로예요 → 같은 키 → 호출 0원.
    key = "coach:" + ai.fingerprint(
        tier_name,
        matches,
        round(stats["kd"], 2),
        round(stats["win_rate"], 1),
        round(stats["hs_percent"], 1),
        round(stats["adr"]),
        round(stats["acs"]),
        tuple((n, c) for n, c in (stats.get("top_agents") or [])[:3]),
    )

    return await ai.ask(
        SYSTEM,
        f"{BENCHMARKS}\n\n이 사람의 전적이야:\n{_summary(stats, tier_name, matches)}",
        feature=FEATURE,
        max_tokens=400,
        cache_key=key,
    )
