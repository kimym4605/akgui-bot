# -*- coding: utf-8 -*-
"""💡 평문 줍기 게이트 테스트 (2026-11-01 신설).

## 왜

💡건의함을 `💡｜기능-추천방`에서 **사람이 있는 채널로 옮기면서** 생겼어요(추천방은
10-16 이후 사람 글 0건으로 죽어 정리했어요).

🚨 **길이만으로는 못 옮겨요.** 전용 채널에선 8자 기준이 통했지만 💬일반 같은 곳은
   잡담도 8자를 쉽게 넘어요 — 실측으로 **31%의 글에 💡 가 붙었어요.**
   건의성 문구 게이트를 넣어 **0%**로 내렸어요(아래 [3] 참고).

실행: python scripts/test_suggest_gate.py   (종료코드 0 = 통과)
"""
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv            # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

from cogs import suggestion as sg         # noqa: E402

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


print("\n[1] ⭐ 실제 채널에 있던 **진짜 건의**는 통과한다")
REAL = [
    # 전부 실제 로그에서 가져온 문장이에요
    "일반카드 합성 기능 만들어주면 안돼냐?",          # 10-30 뽑기방 → 오늘 만든 기능
    "낚시 더할수있게해줘",                            # → 🎣 몰아 던지기의 근거
    "미션 내용 추천점",                               # 추천방
    "기술머신 상점에 추가해주세요",                   # 추천방
    "이거 기준으로 롤체봇 같은거도 만들어줘",         # 추천방
    "미션깨면 낚시권 주는걸로 바꿔야 겠다",           # 낚시터
    "이거 미션 같은거 추가 언제 돼?",                 # 추천방
]
for t in REAL:
    check(sg._has_suggest_word(t), f"통과: \"{t[:34]}\"")

print("\n[2] 🚨 **잡담은 걸러진다**")
CHATTER = [
    "오늘 롤체 할사람?",            # 11자 — 길이만으로는 통과해버려요
    "통방 ㄱ 지금 들어와",
    "나 지금 피방왔는데 자리 없음",
    "오늘 진짜 개못하네 ㅋㅋㅋㅋ",
    "밥먹고 올게 조금만 기다려줘",   # '기다려줘'는 건의가 아니에요
]
for t in CHATTER:
    check(not sg._has_suggest_word(t), f"걸러짐: \"{t[:34]}\"")

print("\n[3] 🚨 실측으로 뺀 키워드가 다시 들어오지 않았다")
# ⒜ "해달" — 서버에 **닉네임 `해다리🍀`**가 있어 `김해달`·`찐해달`이 전부 걸렸어요
check("해달" not in sg._SUGGEST_WORDS,
      "`해달`이 없다 (닉네임 `해다리`와 충돌 — 실측 오탐 3건)")
check("해달라" in sg._SUGGEST_WORDS, "대신 `해달라`로 좁혔다")
for nick in ("김해달은 골드임", "해달이 누나가 형 잡아갓엉", "내가 찐해달임"):
    check(not sg._has_suggest_word(nick), f"닉네임 오탐 없음: \"{nick[:26]}\"")
# ⒝ "필요" — 구인글에 흔해요
check("필요" not in sg._SUGGEST_WORDS,
      "`필요`가 없다 (구인글 `한 명 필요해`가 걸렸다)")
check(not sg._has_suggest_word("잇었는데 없어서 한 명ㅇ리 필요해"),
      "구인글 오탐 없음")

print("\n[4] 🚨 게이트가 `_looks_like_suggestion`의 **마지막 관문**에 꽂혀 있다")
import ast                                            # noqa: E402
src = open(os.path.join(BOT_DIR, "cogs", "suggestion.py"), encoding="utf-8").read()
fn = next(n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "_looks_like_suggestion")
body = ast.unparse(fn)
check("_has_suggest_word" in body, "줍기 판정이 게이트를 부른다")
# 길이 검사보다 뒤에 있어야 해요(짧은 글을 굳이 키워드까지 훑을 필요가 없어요)
i_len = body.find("MIN_PICKUP_LEN")
i_gate = body.find("_has_suggest_word")
check(0 <= i_len < i_gate, "길이·필러 검사 뒤에 온다", f"{i_len} vs {i_gate}")
check("not _has_suggest_word" in body, "없으면 False를 돌려준다")

print("\n[5] 길이·필러 조건은 그대로다 (옛 판정이 안 느슨해졌나)")
check(sg.MIN_PICKUP_LEN == 8, f"MIN_PICKUP_LEN={sg.MIN_PICKUP_LEN}")
check(bool(sg._FILLER_ONLY.match("ㅋㅋㅋㅋㅋㅋㅋㅋ")), "필러(ㅋㅋㅋ)는 필러로 잡힌다")
check(not sg._FILLER_ONLY.match("미션 내용 추천점"), "내용 있는 글은 필러가 아니다")

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("✅ 줍기 게이트 정상")
