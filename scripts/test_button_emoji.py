"""봇의 **모든 버튼·드롭다운 이모지가 진짜 디스코드 이모지인지** 검사해요.

2026-10-05 사고에서 나왔어요. 블랙잭 '히트' 버튼에 `🂠`(U+1F0A0 카드 뒷면)을 썼는데,
유니코드 '카드' 블록 문자는 생긴 건 이모지 같아도 디스코드가 안 받아줘요:

    400 Bad Request (50035): In components.0.components.0.emoji.name: Invalid emoji

그래서 **버튼이 필요한 블랙잭 판이 전부 실패**했어요. 코인은 이미 빠진 뒤라 유저가
하지도 않은 판에 돈을 냈고, 버튼 없이 끝나는 '처음부터 21' 판만 성공해서 더 늦게 들켰어요.

눈으로는 구분이 안 되니(🂠 vs 🃏) 기계가 잡아야 해요. 소스에서 `emoji=` 를 전부 긁어
위험한 유니코드 블록에 걸리는지 봐요.
"""
import os
import re
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# 디스코드가 이모지로 인정하지 않는 '그림문자' 블록들.
# ⚠️ 이 블록 안에도 진짜 이모지가 몇 개 섞여 있어요(🀄 U+1F004, 🃏 U+1F0CF). 그래서 예외를 둬요.
BAD_RANGES = [
    (0x1F000, 0x1F02F, "마작패"),
    (0x1F030, 0x1F09F, "도미노"),
    (0x1F0A0, 0x1F0FF, "카드"),
]
ALLOWED_IN_BAD = {0x1F004, 0x1F0CF}   # 🀄 홍중, 🃏 조커 — 이 둘만 진짜 이모지예요

# 글자·숫자·일반 기호는 이모지가 아니에요(버튼 emoji= 에 넣으면 거부돼요).
PLAIN_ASCII = re.compile(r"^[\x00-\x7F]+$")


def bad_reason(text: str) -> str | None:
    if not text:
        return None
    if PLAIN_ASCII.match(text):
        return "ASCII 문자는 이모지가 아니에요"
    for ch in text:
        code = ord(ch)
        if code in ALLOWED_IN_BAD:
            continue
        for lo, hi, name in BAD_RANGES:
            if lo <= code <= hi:
                return f"{name} 블록(U+{code:04X})은 디스코드가 이모지로 안 받아요"
    return None


print("1) 알려진 함정 문자를 실제로 잡아내는지 (검사기 자체 검증)")
check("🂠 (카드 뒷면) 을 잡는다", bad_reason("🂠") is not None, str(bad_reason("🂠")))
check("🂥 (카드) 을 잡는다", bad_reason("🂥") is not None)
check("🀰 (도미노) 를 잡는다", bad_reason("🀰") is not None)
check("🃏 (조커) 는 통과시킨다", bad_reason("🃏") is None, str(bad_reason("🃏")))
check("🀄 (홍중) 은 통과시킨다", bad_reason("🀄") is None)
for ok_emoji in ("🎰", "🎲", "🃏", "➕", "✋", "🧊", "🎨", "🏷️", "💣", "🔫", "🛡️", "💎", "👑", "🔀"):
    if bad_reason(ok_emoji) is not None:
        check(f"{ok_emoji} 는 통과해야 한다", False, str(bad_reason(ok_emoji)))
check("정상 이모지들은 전부 통과", all(bad_reason(e) is None
      for e in ("🎰", "🎲", "🃏", "➕", "✋", "🧊", "🎨", "💣", "🔫", "🛡️", "💎")))

print("\n2) 봇 소스 전체의 emoji= 값 검사")
pattern = re.compile(r'emoji\s*=\s*["\']([^"\']+)["\']')
found = 0
for path in sorted(list((BOT_DIR / "cogs").glob("*.py")) + list((BOT_DIR / "utils").glob("*.py"))):
    source = path.read_text(encoding="utf-8")
    for match in pattern.finditer(source):
        value = match.group(1)
        found += 1
        line_no = source[: match.start()].count("\n") + 1
        reason = bad_reason(value)
        if reason:
            check(f"{path.name}:{line_no} emoji={value!r}", False, reason)
if found:
    check(f"소스에서 찾은 emoji= {found}개가 전부 정상", not failures, f"{found}개 검사")
else:
    check("emoji= 를 하나도 못 찾았어요 (정규식이 깨졌을 수 있어요)", False)

print("\n3) 슬롯 심볼·테마 이모지도 같이 검사")
from utils.casino_games import SLOT_SYMBOLS  # noqa: E402
from utils.profile_card import THEMES  # noqa: E402

for symbol, _ in SLOT_SYMBOLS:
    check(f"슬롯 심볼 {symbol}", bad_reason(symbol) is None, str(bad_reason(symbol)))
for name, info in THEMES.items():
    check(f"테마 {name} {info['emoji']}", bad_reason(info["emoji"]) is None,
          str(bad_reason(info["emoji"])))

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
