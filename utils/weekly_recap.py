"""🏆 주간 악귀력 순위에 "이번 주 무슨 일이 있었나" 한 문단을 붙여요.

## 왜 (2026-10-18)

`/주간랭킹`은 이름과 점수만 나열했어요. 그런데 `agwi_weekly`에는 **주차별로** 점수·등급과
`{kd, winRate, hs, matches}`가 쌓여 있어서, 지난주와 비교하면 "누가 치고 올라왔는지"를
말할 수 있어요. 순위표가 이야기가 되면 다음 주에 한 번 더 보고 싶어져요.

## 🚨 멘션은 모델에게 맡기지 않아요

모델에게 디스코드 ID를 주면 `<@...>`를 지어내다가 **엉뚱한 사람을 부를 수 있어요.**
그래서 모델에겐 **표시 이름만** 주고, 답변에도 이름만 쓰게 해요. 멘션이 들어간 순위표는
바로 위에 이미 있으니 중복될 이유도 없어요.

## 💰 비용

주 1회 수준이고, 캐시 키에 **순위 지문**이 들어가요. 순위가 그대로면 호출이 안 일어나요.
"""
from __future__ import annotations

import logging

from utils import ai

log = logging.getLogger(__name__)

FEATURE = "주간랭킹해설"

SYSTEM = """너는 디스코드 게임 서버의 주간 순위를 소개하는 사람이야. 한국어 존댓말로 써.

지킬 것:
- **받은 데이터 안에서만** 말해. 없는 경기·사건·이유를 지어내지 마.
  (왜 점수가 올랐는지 같은 건 KD·승률 변화로만 추측하고, 단정하지 마.)
- 2~4문장, 220자 안쪽. 자연스러운 문단 하나로.
- 이름은 **받은 표시 이름 그대로** 써. `<@숫자>` 같은 멘션 형식은 절대 만들지 마.
- 1등을 축하하고, **지난주보다 많이 오른 사람**이 있으면 그 사람을 꼭 짚어줘.
  순위 자체보다 '변화'가 재밌어.
- 지난주 데이터가 없으면 비교하지 말고 이번 주만 담백하게 소개해.
- 꼴찌나 점수 낮은 사람을 놀리지 마. 아무도 기록을 남기고 싶지 않게 돼."""


def _rows_text(rows: list[dict], names: dict[str, str], label: str) -> str:
    if not rows:
        return f"{label}: 기록 없음"
    lines = [f"{label}:"]
    for i, row in enumerate(rows, 1):
        uid = str(row.get("userId"))
        name = names.get(uid, "알 수 없음")
        stats = row.get("stats") or {}
        bits = [f"{i}위 {name} {row.get('score', 0):,.0f}점"]
        if row.get("grade"):
            bits.append(f"{row['grade']}등급")
        if stats.get("kd") is not None:
            bits.append(f"KD {stats['kd']}")
        if stats.get("winRate") is not None:
            bits.append(f"승률 {stats['winRate']}%")
        if stats.get("matches"):
            bits.append(f"{stats['matches']}경기")
        lines.append("  " + " · ".join(bits))
    return "\n".join(lines)


async def recap(
    this_week: list[dict],
    last_week: list[dict],
    names: dict[str, str],
    week_label: str,
) -> str | None:
    """순위 해설 한 문단. 못 만들면 None(그러면 순위표만 나가요)."""
    # 🚨 2명 이하면 "순위"라고 할 게 없어요. 억지로 해설하면 민망해져요.
    if len(this_week) < 3:
        return None

    key = "recap:" + ai.fingerprint(
        week_label,
        tuple((str(r.get("userId")), round(r.get("score") or 0)) for r in this_week),
        tuple((str(r.get("userId")), round(r.get("score") or 0)) for r in last_week),
    )

    body = (
        f"{_rows_text(this_week, names, '이번 주')}\n\n"
        f"{_rows_text(last_week, names, '지난주')}"
    )

    return await ai.ask(
        SYSTEM,
        f"{week_label} 악귀력 순위야. 소개해줘.\n\n{body}",
        feature=FEATURE,
        max_tokens=400,
        cache_key=key,
    )
