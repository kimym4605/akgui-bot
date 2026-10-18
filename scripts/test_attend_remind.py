"""⏰ 출석 끊기기 전 알림 검증. 가짜 데이터로 돌려서 **실제 DM은 안 보내요.**

    python scripts/test_attend_remind.py

## 무엇을 막으려고 만들었나

🚨 **스팸.** 알림은 금방 미움받아요. 잘못 보내면 기능 하나가 아니라 봇 전체가 미움받아요.
   - 이미 출석한 사람에게 보내면 안 돼요.
   - **떠난 사람**(한 달째 안 오는)에게 보내면 안 돼요. 그건 쫓아다니는 거예요.
   - 연속이 짧아서 **잃을 게 없는 사람**에게도 보낼 이유가 없어요.
   - 🚨 끈 사람에게 보내면 그건 그냥 고장이에요.

🚨 **문자열 날짜 비교.** `lastAttendanceDate`가 ISO(YYYY-MM-DD) 문자열이라 사전순 비교로
   시간순을 흉내내요. 형식이 깨지면 조용히 틀린 사람이 뽑혀요.
"""
import os
import sys
from datetime import datetime, timedelta

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("MONGODB_DB_NAME", "agwi_remind_test")

from utils import attend_remind  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


KST = attend_remind.KST
TODAY = datetime.now(KST).date()


def iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


# ------------------------------------------------------------------
print("⒜ 🚨 누구를 고르나 (쿼리 조건 그대로 흉내내서 확인)")

# `_candidates_sync`의 조건을 그대로 적용해보는 작은 흉내예요.
# (DB를 안 쓰고도 '어떤 사람이 뽑히는지'를 못 박을 수 있어요)
def would_send(streak: int, last_days_ago: int) -> bool:
    last = iso(last_days_ago)
    today = TODAY.isoformat()
    cutoff = iso(attend_remind.ACTIVE_WITHIN_DAYS)
    return (streak >= attend_remind.MIN_STREAK
            and last < today
            and last >= cutoff)


CASES = [
    # (연속, 마지막 출석 n일 전, 보내야 하나?, 설명)
    (46, 1, True, "어제까지 46일 연속 — 오늘 놓치면 끊긴다"),
    (3, 1, True, f"연속 {attend_remind.MIN_STREAK}일 — 경계값"),
    (2, 1, False, "연속이 짧아 잃을 게 적다"),
    (46, 0, False, "🚨 오늘 이미 출석했다"),
    (41, 14, False, "🚨 2주째 안 온다 — 떠난 사람을 쫓아다니지 않는다"),
    (12, 42, False, "🚨 한 달 넘게 안 온다"),
    (55, 2, True, "이틀 전까지 왔다 — 아직 살아있는 연속"),
    (0, 1, False, "연속이 0이면 끊길 게 없다"),
]
for streak, ago, want, why in CASES:
    got = would_send(streak, ago)
    check(f"연속{streak:3}일 · {ago}일 전 출석 → {'보냄' if want else '안 보냄'}",
          got == want, why)


# ------------------------------------------------------------------
print("\n⒝ 문구")

plain = attend_remind.message_for(46, 0)
check("연속 일수가 들어간다", "46" in plain, plain.splitlines()[0])
check("출석 명령어를 알려준다", "/출석" in plain)
check("보호권이 없으면 상점을 안내한다", "악귀상점" in plain and "보호권" in plain)
check("끄는 법을 알려준다", "알림설정" in plain)

with_protect = attend_remind.message_for(46, 2)
check("보호권이 있으면 그걸 알려준다", "2장" in with_protect, with_protect.splitlines()[1])
check("🚨 보호권이 있어도 출석을 권한다 (사둔 보람이 있게)",
      "이득" in with_protect or "하는 게" in with_protect)
check("보호권이 있으면 상점 안내는 안 한다 (이미 샀으니까)",
      "악귀상점" not in with_protect)


# ------------------------------------------------------------------
print("\n⒞ 🚨 조건이 과하게 넓어지지 않았나")

check(f"최소 연속이 2일 이상이다 (지금 {attend_remind.MIN_STREAK}일)",
      attend_remind.MIN_STREAK >= 2)
check(f"활동 판정이 7일 이내다 (지금 {attend_remind.ACTIVE_WITHIN_DAYS}일)",
      attend_remind.ACTIVE_WITHIN_DAYS <= 7,
      "이보다 넓으면 떠난 사람에게도 가요")

# 🚨 알림 설정에 등록돼 있어야 끌 수 있어요.
from utils import notify_prefs  # noqa: E402

check("🚨 /알림설정에서 끌 수 있다", "attend_remind" in notify_prefs.NOTIFY_KINDS,
      str(list(notify_prefs.NOTIFY_KINDS)))


# ------------------------------------------------------------------
print("\n⒟ 보내는 시각")
from cogs import attend_remind as cog  # noqa: E402

hour = cog.SEND_AT.hour
check("밤에 보낸다 (자정 전 여유 · 자는 시간은 피함)", 20 <= hour <= 23, f"{hour}시")
check("DM 사이에 간격을 둔다 (레이트리밋)", cog.SEND_GAP_SECONDS > 0,
      f"{cog.SEND_GAP_SECONDS}초")


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
