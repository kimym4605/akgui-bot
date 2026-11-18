"""🛡️ 스팸 판정 오탐/미탐 검사 (디스코드 접속 없음).

    python scripts/test_spam_guard.py

새 수법을 보면 SPAM에, 억울하게 걸린 평범한 글을 보면 HAM에 한 줄씩 추가해 주세요.
"""
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from utils import spam_guard
from utils.spam_guard import Post, PostTracker

failed = []

# 메시지 한 개만 봐도 걸려야 하는 것
SPAM = [
    "MrBeast is giving away $2500 to the first 1000 people! https://mrbeast-gift.xyz/claim",
    "미스터 비스트가 선착순으로 상품권 뿌림 ㄷㄷ https://bit.ly/3xYz",
    "Free Nitro for everyone 🎁 discord.gg/freenitro2026",
    "steam gift 50$ → steamcommunlty.com/gift/activation",
    "@everyone 새 서버 오픈 https://discord.gg/abcd",
    "Ｍｒ​Ｂｅａｓｔ ｃａｓｉｎｏ bonus code → https://win-bet.top",   # 전각 + 제로폭 공백
    "[https://discord.com/gifts/abc](https://dlscord-gift.ru/abc)",      # 위장 링크
    "I'm leaving CS2, giving my skins away. withdraw here https://csgo-free.site",
]
# 평범한 글 — 절대 걸리면 안 됨
HAM = [
    "이 영상 봐봐 https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "전적 https://tracker.gg/valorant/profile/riot/abc%23kr1/overview",
    "오늘 카지노에서 블랙잭 100코인 땄다 ㅋㅋ",
    "이번 이벤트 당첨자 누구임?",
    "내전 9시에 함 @here 아님 그냥 오셈",
    "패치노트 링크 playvalorant.com/ko-kr/news",
    "[공식 패치노트](https://playvalorant.com/ko-kr/news/game-updates/)",
    "$50 짜리 번들 살까 말까",
    "ㅋㅋㅋㅋㅋ",
    "",
]

print("메시지 단독 판정:")
for text in SPAM:
    v = spam_guard.judge_content(text)
    print(f"  {'✅' if v else '❌'} 잡음  | {v.reason if v else '-'} | {text[:50]}")
    if not v:
        failed.append(f"미탐: {text[:40]}")
for text in HAM:
    v = spam_guard.judge_content(text)
    print(f"  {'❌' if v else '✅'} 통과  | {v.reason if v else '-'} | {text[:50]}")
    if v:
        failed.append(f"오탐: {text[:40]} ({v.reason})")

# 위장 링크는 운영진도 잡아야 하니 strong
v = spam_guard.judge_content("[discord.com/nitro](https://disc0rd-nitro.com)")
if not (v and v.strong):
    failed.append("위장 링크가 strong이 아니에요")

print("\n여러 채널 도배:")
t = PostTracker()
msg = "check this out lol"   # 링크도 미끼 단어도 없는 글이라도 3개 채널이면 걸려요
fp = PostTracker.fingerprint(msg, [])
r1 = t.add(1, Post(0.0, 101, 1, fp, False))
r2 = t.add(1, Post(2.0, 102, 2, fp, False))
r3 = t.add(1, Post(4.0, 103, 3, fp, False))
print(f"  1·2번째: {r1}, {r2} / 3번째: {r3}")
if r1 or r2:
    failed.append("2개 채널에서 벌써 걸림")
if not (r3 and r3.strong):
    failed.append("같은 내용 3개 채널을 못 잡음")

# 같은 채널에 3번은 도배가 아니에요(채팅 연타)
t2 = PostTracker()
for i in range(5):
    if t2.add(2, Post(float(i), 200, i, fp, False)):
        failed.append("같은 채널 반복을 도배로 봄")
        break

# 시간이 지나면 잊어요
t3 = PostTracker()
t3.add(3, Post(0.0, 1, 1, fp, False))
t3.add(3, Post(1.0, 2, 2, fp, False))
if t3.add(3, Post(spam_guard.WINDOW_SECONDS + 5, 3, 3, fp, False)):
    failed.append("90초 지난 게시물까지 세고 있음")

# 내용이 달라도 이미지 첨부를 4개 채널에 → 잡음
t4 = PostTracker()
hits = [t4.add(4, Post(float(i), 300 + i, i,
                       PostTracker.fingerprint(f"hey {i}", [(f"img{i}.png", 1000 + i)]), True))
        for i in range(4)]
print(f"  첨부 4채널: {[bool(h) for h in hits]}")
if any(hits[:3]) or not hits[3]:
    failed.append("첨부 4채널 도배 판정이 틀림")

print("\n링크 무력화:")
d = spam_guard.defang("@everyone https://mrbeast.xyz discord.gg/abc")
print(f"  {d}")
if "https://" in d or "@everyone" in d:
    failed.append("defang이 링크/멘션을 남김")

print("\n" + "=" * 50)
if failed:
    print("❌ 실패:\n  - " + "\n  - ".join(failed))
    sys.exit(1)
print("✅ 스팸 판정 전부 정상")
