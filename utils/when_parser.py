"""🕘 "토요일 9시" 같은 한국어 시간 표현을 실제 시각으로 바꿔요.

## 왜 규칙 기반인가 (AI를 안 쓰는 이유)

봇에 Claude가 붙어 있지만 **시간 파싱은 결정적이어야** 해요. 모델이 가끔 다르게 읽으면
엉뚱한 때 알림이 가고, 그건 "알림이 안 오는 것"보다 나빠요. 게다가 일정을 잡을 때마다
돈이 들고 2초씩 기다려야 해요. 패턴은 몇 개 안 되니 규칙으로 충분해요.

## 🚨 항상 '앞으로'를 가리켜요

"9시"라고 했는데 지금이 10시면 **내일 9시**예요. 과거로 잡히면 리마인더가 영영 안 가요.
요일도 마찬가지로 **다음에 오는 그 요일**이에요(오늘이 그 요일이고 시간이 남았으면 오늘).

## 받아들이는 형식

    21:00 / 21시 / 9시 30분          → 오늘(지났으면 내일)
    오늘 21시 / 내일 9시 / 모레 20시
    토요일 21시 / 토 9시 / 이번주 금요일 20시 / 다음주 토요일 21시
    10/25 21:00 / 10-25 21시 / 12월 3일 20시

⚠️ "오후 9시"처럼 오전/오후를 붙이면 12시간제로 읽어요. 안 붙이면 **24시간제**예요
   (9시 = 오전 9시). 밤 약속이 많아서 헷갈릴 수 있지만, 추측하는 것보다 명시가 안전해요.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

WEEKDAYS = {
    "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6,
    "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3,
    "금요일": 4, "토요일": 5, "일요일": 6,
}

_TIME_RE = re.compile(
    r"(?P<ampm>오전|오후|아침|저녁|밤|새벽)?\s*"
    r"(?P<hour>\d{1,2})\s*(?::|시)\s*(?P<minute>\d{1,2})?\s*분?"
)
_DATE_SLASH_RE = re.compile(r"(?P<month>\d{1,2})\s*[/\-.]\s*(?P<day>\d{1,2})")
_DATE_KO_RE = re.compile(r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일")


class ParseError(ValueError):
    """사람이 읽을 수 있는 사유를 담아요(그대로 유저에게 보여줘요)."""


def _apply_ampm(hour: int, ampm: str | None) -> int:
    """오전/오후를 반영해요. 없으면 24시간제로 그대로 둬요."""
    if ampm in ("오후", "저녁", "밤") and hour < 12:
        return hour + 12
    if ampm in ("오전", "아침") and hour == 12:
        return 0
    if ampm == "새벽" and hour == 12:
        return 0
    return hour


def parse(text: str, *, now: datetime | None = None) -> datetime:
    """한국어 시간 표현 → KST 기준 `datetime`. 못 읽으면 `ParseError`.

    `now`는 테스트에서 '지금'을 고정하려고 받아요."""
    now = (now or datetime.now(KST)).astimezone(KST)
    raw = (text or "").strip()
    if not raw:
        raise ParseError("언제인지 적어주세요. 예: `토요일 21시`, `10/25 21:00`")

    time_match = _TIME_RE.search(raw)
    if time_match is None:
        raise ParseError(
            "시간을 못 읽었어요. 예: `21시`, `21:00`, `오후 9시`처럼 적어주세요."
        )

    hour = int(time_match.group("hour"))
    minute = int(time_match.group("minute") or 0)
    hour = _apply_ampm(hour, time_match.group("ampm"))

    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise ParseError(f"{hour}시 {minute}분은 없는 시각이에요.")

    before_time = raw[: time_match.start()]

    # ── 날짜 ────────────────────────────────────────────────────────
    date_match = _DATE_KO_RE.search(raw) or _DATE_SLASH_RE.search(raw)
    if date_match:
        month, day = int(date_match.group("month")), int(date_match.group("day"))
        year = now.year
        try:
            target = now.replace(year=year, month=month, day=day,
                                 hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            raise ParseError(f"{month}월 {day}일은 없는 날짜예요.") from None
        # 🚨 이미 지난 날짜면 **내년**이에요(12월에 1월 일정을 잡는 경우).
        if target <= now:
            try:
                target = target.replace(year=year + 1)
            except ValueError:
                raise ParseError(f"{month}월 {day}일은 없는 날짜예요.") from None
        return target

    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # 🚨 **"지금"은 미래가 아니에요.** 같은 시각으로 잡히면 리마인더(시작 30분 전)가 이미
    #    지난 상태라 알림이 영영 안 가고, 예약이라는 말 자체가 무의미해져요.
    #    그래서 비교는 전부 `<=`로 해요(2026-10-18에 테스트가 이걸 잡았어요).
    if "모레" in before_time:
        return base + timedelta(days=2)
    if "내일" in before_time:
        return base + timedelta(days=1)
    if "오늘" in before_time:
        # 🚨 "오늘 9시"인데 이미 지났으면 잡을 수 없어요. 추측해서 내일로 미루면
        #    사용자가 의도한 것과 달라져요.
        if base <= now:
            raise ParseError("그 시각은 이미 지났어요. `내일`이나 날짜를 적어주세요.")
        return base

    # 요일 — 긴 이름부터 봐야 "토요일"이 "토"로 먼저 안 잡혀요.
    for name in sorted(WEEKDAYS, key=len, reverse=True):
        if name not in before_time:
            continue
        target_wd = WEEKDAYS[name]
        ahead = (target_wd - now.weekday()) % 7
        candidate = base + timedelta(days=ahead)
        # 오늘이 그 요일인데 시간이 지났으면 다음 주예요. (`<=` — 위 주석 참고)
        if ahead == 0 and candidate <= now:
            candidate += timedelta(days=7)
        # "다음주 토요일"이면 한 주 더.
        if "다음주" in before_time or "담주" in before_time:
            candidate += timedelta(days=7)
        return candidate

    # 날짜 단서가 없으면 오늘, 지났으면 내일. (`>` — 지금과 같은 시각은 내일로)
    return base if base > now else base + timedelta(days=1)


def format_kst(when: datetime) -> str:
    """사람이 읽는 표기. 요일까지 붙여줘요."""
    kst = when.astimezone(KST)
    names = "월화수목금토일"
    return f"{kst:%m/%d}({names[kst.weekday()]}) {kst:%H:%M}"


def discord_timestamp(when: datetime, style: str = "F") -> str:
    """디스코드가 **보는 사람 시간대로** 바꿔주는 표기예요.

    서버원이 다른 나라에 있어도 각자 자기 시간으로 보여요. `R`은 "3시간 뒤" 같은 상대 표기."""
    return f"<t:{int(when.timestamp())}:{style}>"
