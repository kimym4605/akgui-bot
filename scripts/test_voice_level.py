"""🎙️ 음성 활동 레벨 검증. 실제 DB·디스코드 없이 돌아요.

    python scripts/test_voice_level.py

## 무엇을 막으려고 만들었나

1. 🚨 **레벨 곡선이 조용히 바뀌는 것.** 레벨은 누적 분에서 **매번 다시 계산**해요.
   `BASE_MINUTES`/`STEP_MINUTES`를 건드리면 **모두의 레벨이 한꺼번에 움직여요.**
   그래서 실제 활동량(10-18 실측: 최다 참여자 23일, 하루 30분~1시간)에 맞는지 못 박아요.
2. 🚨 **역할이 두 개 달리는 것.** 레벨이 오르면 아래 등급 역할을 떼야 해요.
3. 🚨 **코인을 주지 않는 것.** 낚시가 이미 발행의 70%라, 통화에까지 코인을 얹으면
   경제가 또 기울어요. 레벨은 명예 지표로만 둬요.
"""
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("MONGODB_DB_NAME", "agwi_voice_test")

from utils import voice_level as vl  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
print("⒜ 레벨 곡선")

check("0분이면 Lv.0", vl.level_of(0) == 0)
check(f"{vl.BASE_MINUTES}분이면 Lv.1", vl.level_of(vl.BASE_MINUTES) == 1,
      f"{vl.level_of(vl.BASE_MINUTES)}")
check("1분 모자라면 아직 Lv.0", vl.level_of(vl.BASE_MINUTES - 1) == 0)

# 레벨이 단조 증가하고, 건너뛰지 않아야 해요.
prev = 0
monotonic = True
for minutes in range(0, 20000, 7):
    lv = vl.level_of(minutes)
    if lv < prev or lv > prev + 1:
        monotonic = False
        break
    prev = lv
check("🚨 레벨이 역행하거나 건너뛰지 않는다", monotonic)

# 필요 시간이 갈수록 늘어야 해요(선형이면 금세 지루해져요).
gaps = [vl.minutes_for_level(n + 1) - vl.minutes_for_level(n) for n in range(1, 15)]
check("레벨이 오를수록 더 오래 걸린다", all(b > a for a, b in zip(gaps, gaps[1:])),
      f"{gaps[:5]}...")

print("\n⒝ 🚨 실제 활동량과 맞나 (10-18 실측 기준)")
# 하루 1시간씩 30일 = 1800분. 실측 최다 참여자가 23일이었어요.
for days, label in ((7, "일주일"), (30, "한 달")):
    minutes = 60 * days
    lv = vl.level_of(minutes)
    print(f"     하루 1시간 × {label}({minutes}분) → Lv.{lv}")
check("하루 1시간 일주일이면 Lv.3~7 사이", 3 <= vl.level_of(60 * 7) <= 7,
      f"Lv.{vl.level_of(60 * 7)}")
check("하루 1시간 한 달이면 Lv.10~18 사이", 10 <= vl.level_of(60 * 30) <= 18,
      f"Lv.{vl.level_of(60 * 30)}")
check("첫 레벨은 30분 안에 (처음 쓴 날 바로 체감)", vl.minutes_for_level(1) <= 30,
      f"{vl.minutes_for_level(1)}분")

print("\n⒞ 진행도 표시")
lv, done, need = vl.progress(vl.BASE_MINUTES + 10)
check("레벨이 맞다", lv == 1, f"Lv.{lv}")
check("이번 레벨 진행분이 맞다", done == 10, f"{done}분")
check("다음까지 필요한 분이 양수", need > 0, f"{need}분")
check("진행분이 필요분을 넘지 않는다", done < need, f"{done}/{need}")

print("\n⒟ 시간 표기")
check("90분 → 1시간 30분", vl.format_minutes(90) == "1시간 30분", vl.format_minutes(90))
check("120분 → 2시간", vl.format_minutes(120) == "2시간", vl.format_minutes(120))
check("45분 → 45분", vl.format_minutes(45) == "45분", vl.format_minutes(45))
check("0분도 깨지지 않는다", vl.format_minutes(0) == "0분", vl.format_minutes(0))

print("\n⒠ 🚨 역할은 한 등급만")
for level, expected in ((0, None), (4, None), (5, "말동무"), (12, "수다쟁이"),
                        (25, "단골"), (99, "터줏대감")):
    role = vl.role_for(level)
    ok = (role is None) if expected is None else (expected in (role or ""))
    check(f"Lv.{level} → {expected or '역할 없음'}", ok, f"{role}")

check("역할 구간이 높은 순으로 정렬돼 있다",
      [t[0] for t in vl.ROLE_TIERS] == sorted((t[0] for t in vl.ROLE_TIERS), reverse=True),
      f"{[t[0] for t in vl.ROLE_TIERS]}")
check("역할 이름이 전부 다르다",
      len(vl.ROLE_NAMES) == len(vl.ROLE_TIERS), f"{vl.ROLE_NAMES}")

print("\n⒡ 🚨 코인을 주지 않는다")
src = open(os.path.join(BOT_DIR, "utils", "voice_level.py"), encoding="utf-8").read()
src += open(os.path.join(BOT_DIR, "cogs", "voice_rank.py"), encoding="utf-8").read()
check("coin_wallet을 import하지 않는다", "coin_wallet" not in src)
check("코인을 더하는 코드가 없다", ".add(" not in src.replace("add_roles(", "").replace("add_minutes(", "").replace("add_field(", "").replace("add_item(", ""))

print("\n⒢ 주차 키")
check("주차 형식이 맞다", vl.week_key().startswith("20") and "-W" in vl.week_key(),
      vl.week_key())


print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
