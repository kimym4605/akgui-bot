"""🕘 한국어 시간 파싱 검증. DB·디스코드·네트워크 없이 돌아요.

    python scripts/test_when_parser.py

## 왜 이걸 따로 테스트하나

일정 기능에서 **제일 위험한 곳**이에요. 시간을 잘못 읽으면 엉뚱한 때 알림이 가는데,
그건 "알림이 안 오는 것"보다 나빠요. 특히:

🚨 **과거로 잡히는 것** — 리마인더 루프는 미래 일정만 보니까, 과거로 잡히면 알림이
   영영 안 가고 아무도 왜 안 왔는지 모르게 돼요.
🚨 **요일 계산** — "토요일"이 이번 주인지 다음 주인지. 오늘이 토요일이면 더 헷갈려요.
🚨 **연말** — 12월에 "1/3"을 잡으면 내년이어야 해요.
"""
import os
import sys
from datetime import datetime, timedelta

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from utils.when_parser import KST, ParseError, format_kst, parse  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


# 기준 '지금': 2026-10-18(일) 15:00
NOW = at(2026, 10, 18, 15, 0)
print(f"기준 지금: {format_kst(NOW)} (일요일)\n")


def expect(text, want, now=NOW):
    try:
        got = parse(text, now=now)
    except ParseError as exc:
        check(f"{text!r}", False, f"파싱 실패: {exc}")
        return
    check(f"{text!r} → {format_kst(want)}", got == want, f"got {format_kst(got)}")


# ------------------------------------------------------------------
print("⒜ 시각만 — 지났으면 내일")
expect("21시", at(2026, 10, 18, 21))
expect("21:00", at(2026, 10, 18, 21))
expect("9시", at(2026, 10, 19, 9))          # 오늘 9시는 지났으니 내일
expect("9시 30분", at(2026, 10, 19, 9, 30))
expect("23:45", at(2026, 10, 18, 23, 45))

print("\n⒝ 오전/오후")
expect("오후 9시", at(2026, 10, 18, 21))
expect("저녁 8시", at(2026, 10, 18, 20))
expect("밤 10시", at(2026, 10, 18, 22))
expect("오전 9시", at(2026, 10, 19, 9))
expect("오후 12시", at(2026, 10, 19, 12))   # 정오는 12시 그대로

print("\n⒞ 오늘/내일/모레")
expect("오늘 21시", at(2026, 10, 18, 21))
expect("내일 9시", at(2026, 10, 19, 9))
expect("모레 20시", at(2026, 10, 20, 20))

print("\n⒟ 🚨 요일 (오늘은 일요일)")
expect("월요일 21시", at(2026, 10, 19, 21))   # 내일
expect("토요일 21시", at(2026, 10, 24, 21))   # 이번 주 토요일
expect("토 21시", at(2026, 10, 24, 21))
expect("금 20시", at(2026, 10, 23, 20))
expect("다음주 토요일 21시", at(2026, 10, 31, 21))

print("\n⒠ 🚨 오늘이 그 요일일 때")
# 오늘(일요일) 21시는 아직 안 지났으니 오늘
expect("일요일 21시", at(2026, 10, 18, 21))
# 오늘 9시는 지났으니 **다음 주** 일요일
expect("일요일 9시", at(2026, 10, 25, 9))

print("\n⒡ 날짜 지정")
expect("10/25 21:00", at(2026, 10, 25, 21))
expect("10-25 21시", at(2026, 10, 25, 21))
expect("12월 3일 20시", at(2026, 12, 3, 20))
expect("11/1 9시", at(2026, 11, 1, 9))

print("\n⒢ 🚨 연말 — 지난 날짜는 내년")
DEC = at(2026, 12, 20, 15)
expect("1/3 21시", at(2027, 1, 3, 21), now=DEC)
expect("12/25 20시", at(2026, 12, 25, 20), now=DEC)

print("\n⒣ 🚨 모든 결과가 미래여야 한다")
SAMPLES = ["21시", "9시", "토요일 21시", "일요일 9시", "내일 8시", "10/25 21:00",
           "오후 3시", "새벽 2시", "월 9시"]
all_future = True
for text in SAMPLES:
    try:
        got = parse(text, now=NOW)
    except ParseError:
        continue
    if got <= NOW:
        all_future = False
        check(f"{text!r}가 과거로 잡혔다", False, format_kst(got))
check("🚨 표본 전부 미래로 잡힌다 (리마인더가 가야 하니까)", all_future)

# 자정 근처에서도 미래여야 해요.
LATE = at(2026, 10, 18, 23, 50)
for text in ("21시", "9시", "23:55"):
    got = parse(text, now=LATE)
    check(f"자정 직전 {text!r} → 미래", got > LATE, format_kst(got))

print("\n⒤ 잘못된 입력은 사유를 알려준다")
for bad in ("", "언젠가", "토요일", "25시", "99:99"):
    try:
        parse(bad, now=NOW)
        check(f"{bad!r}는 거절해야 한다", False, "통과해버렸어요")
    except ParseError as exc:
        check(f"{bad!r} 거절", True, str(exc)[:38])

try:
    parse("오늘 9시", now=NOW)
    check("'오늘 9시'(이미 지남)는 거절", False, "통과해버렸어요")
except ParseError as exc:
    check("'오늘 9시'(이미 지남) 거절", True, str(exc)[:38])

print("\n⒥ 표기")
check("요일이 붙는다", "(토)" in format_kst(at(2026, 10, 24, 21)),
      format_kst(at(2026, 10, 24, 21)))


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
