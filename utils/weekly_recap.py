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

SYSTEM = """너는 디스코드 게임 서버의 주간 순위를 소개하는 사람이야.

말투 (가장 중요 — 이 봇의 모든 문구가 이 톤이야):
- **"~해요체"로 써.** 예: "1위예요", "올라왔어요", "눈에 띄어요".
- 반말도, 딱딱한 격식체(~입니다, ~합니다)도 쓰지 마. 한 답변 안에서 섞이면 안 돼.

🚨 지켜야 할 것:
- **받은 데이터 안에서만** 말해. 없는 경기·사건·이유를 지어내지 마.
- **순위 변화는 이미 계산해서 줬어.** 그걸 그대로 쓰고, 직접 비교하거나 추측하지 마.
- 숫자를 옮겨 적다가 틀리는 사고가 나. 점수는 **받은 값 그대로** 쓰거나,
  아예 말로만("크게 올랐어요") 표현해.
- 이름은 **받은 표시 이름 그대로** 써. `<@숫자>` 같은 멘션 형식은 절대 만들지 마.
- 🚨 **왜 그렇게 됐는지 추측하지 마.** "조절 기간을 거친 것 같네요", "전반적으로 조정된
  모습" 같은 말은 아무 뜻도 없고 근거도 없어. 그런 문장은 한 개도 쓰지 마.
  할 말이 없으면 **짧게 끝내.** 짧은 게 지어낸 것보다 훨씬 나아.

형식:
- 🚨 **제목·헤더·굵은 제목 줄을 넣지 마.** 순위표는 바로 위에 이미 있어.
  첫 글자부터 바로 본문으로 시작해.
- 2~4문장, 220자 안쪽. 문단 하나로.

내용:
- 1등을 축하하고, **순위가 오른 사람이나 새로 들어온 사람**이 있으면 꼭 짚어줘.
  순위 자체보다 '변화'가 재밌어.
- 지난주 기록이 없다고 나오면 비교하지 말고 이번 주만 담백하게 소개해.
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


def _changes_text(
    this_week: list[dict], last_week: list[dict], names: dict[str, str]
) -> str:
    """🚨 **비교는 코드가 해요.**

    모델에게 두 주의 표만 주고 "비교해줘"라고 했더니 "전반적으로 조정된 모습",
    "조절 기간을 거친 것 같네요" 같은 **뜻 없는 추측**을 지어냈어요(2026-10-18 실측).
    순위 변동·신규 진입은 계산이지 해석이 아니에요. 계산은 여기서 끝내고, 모델에게는
    **이미 나온 결론**만 줘요. 그러면 지어낼 여지가 없어요.
    """
    last_rank = {str(r.get("userId")): i for i, r in enumerate(last_week, 1)}
    last_score = {str(r.get("userId")): (r.get("score") or 0) for r in last_week}

    if not last_week:
        return "지난주 기록이 없어서 비교할 수 없어요. 이번 주만 소개하세요."

    lines = []
    for i, row in enumerate(this_week, 1):
        uid = str(row.get("userId"))
        name = names.get(uid, "알 수 없음")
        if uid not in last_rank:
            lines.append(f"  {name}: 이번 주에 새로 들어왔어요 (지난주 기록 없음)")
            continue
        rank_diff = last_rank[uid] - i          # +면 순위가 올라감
        score_diff = (row.get("score") or 0) - last_score[uid]
        bits = []
        if rank_diff > 0:
            bits.append(f"{last_rank[uid]}위 → {i}위 ({rank_diff}계단 상승)")
        elif rank_diff < 0:
            bits.append(f"{last_rank[uid]}위 → {i}위 ({-rank_diff}계단 하락)")
        else:
            bits.append(f"{i}위 유지")
        bits.append(f"점수 {score_diff:+,.0f}")
        lines.append(f"  {name}: " + " · ".join(bits))

    gone = [names.get(u, "알 수 없음") for u in last_rank if
            u not in {str(r.get("userId")) for r in this_week}]
    if gone:
        lines.append(f"  이번 주에 기록이 없는 사람: {', '.join(gone)}")

    return "지난주 대비 변화 (이미 계산됐어요 — 그대로 쓰세요):\n" + "\n".join(lines)


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
        f"{_changes_text(this_week, last_week, names)}"
    )

    return await ai.ask(
        SYSTEM,
        f"{week_label} 악귀력 순위야. 소개해줘.\n\n{body}",
        feature=FEATURE,
        max_tokens=400,
        cache_key=key,
    )
