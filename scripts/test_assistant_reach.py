"""❓ 봇 매니저가 **닿는지** 검증. 디스코드 없이 돌아요.

    python scripts/test_assistant_reach.py

## 무엇을 막으려고 만들었나 (2026-10-23)

매니저는 10-18에 켰고 **작동은 정상**이었어요(그날 "코인어떻게모아"에 제대로 답했어요).
그런데 닷새 뒤 `assistant_usage`가 **1건**이었어요. 기능이 아니라 **닿는 길**이 문제예요.
그래서 두 길을 넣었고, 여기서 그 길이 막히지 않았는지 봐요.

1. 🚨 **멘션하면 어디서든 답한다.** 멘션 판정이 틀리면 둘 중 하나가 나요 —
   아무 데서도 안 답하거나(지금과 같음), 반대로 **공지에 끼어들어요**(최악).
   특히 `@everyone`과 역할 멘션에 반응하면 안 돼요.
2. 🚨 **막히는 자리에 버튼이 붙어 있다.** `utils/channel_check.py`의 거절 메시지에
   ❓ 버튼이 같이 가야 해요. 상점을 진열만 해두면 0건이 된다는 걸 이미 봤어요.
3. 🚨 **"바라는 것"은 `/건의`로 보낸다.** 못 답한 자리에 다리가 없으면 바람이
   아무 데도 안 남아요(10-18에 실제로 그랬어요).
"""
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from cogs import assistant  # noqa: E402
from utils import ask_hint  # noqa: E402

failures = []

BOT_ID = 907262335591268363  # 실제 악귀봇 id (멘션 형태를 그대로 쓰려고요)


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
class _FakeUser:
    def __init__(self, uid, name="악귀봇", bot=False):
        self.id = uid
        self.display_name = name
        self.bot = bot

    def __eq__(self, other):
        return isinstance(other, _FakeUser) and other.id == self.id

    def __hash__(self):
        return hash(self.id)


class _FakeBot:
    def __init__(self):
        self.user = _FakeUser(BOT_ID, bot=True)


class _FakeMessage:
    def __init__(self, content, *, mentions=(), everyone=False):
        self.content = content
        self.mentions = list(mentions)
        self.mention_everyone = everyone


cog = assistant.Assistant(_FakeBot())
ME = _FakeUser(BOT_ID, bot=True)


# ------------------------------------------------------------------
print("⒜ 🚨 멘션 판정 — 불렀을 때만 답하고, 공지엔 끼어들지 않는다")

CASES = [
    # (글, 멘션 목록, @everyone, 기대값)
    (f"<@{BOT_ID}> 코인 어떻게 모아?", [ME], False, "코인 어떻게 모아?"),
    (f"<@!{BOT_ID}> 낚시대 어디서 사?", [ME], False, "낚시대 어디서 사?"),
    (f"낚시대 어디서 사? <@{BOT_ID}>", [ME], False, "낚시대 어디서 사?"),
    (f"<@{BOT_ID}>", [ME], False, ""),               # 부르기만 한 경우
    ("코인 어떻게 모아?", [], False, None),            # 멘션 없음 → 안 받음
    (f"<@{BOT_ID}> 봇 업데이트 있습니다", [ME], True, None),  # 🚨 @everyone 공지
    (f"<@{999}> 야 이것 좀 봐", [_FakeUser(999, "다른사람")], False, None),  # 남을 멘션
]

for content, mentions, everyone, expected in CASES:
    got = cog._question_from_mention(
        _FakeMessage(content, mentions=mentions, everyone=everyone))
    label = f"{content[:34]!r}" + (" + @everyone" if everyone else "")
    check(f"{label} → {expected!r}", got == expected, f"got={got!r}")

check("🚨 역할 멘션엔 안 반응한다 (mentions는 사용자 멘션만 담는다)",
      cog._question_from_mention(
          _FakeMessage("<@&55555> 이거 봐줘", mentions=[])) is None)


# ------------------------------------------------------------------
print("\n⒝ 🚨 막히는 자리에 ❓ 버튼이 붙어 있다")

with open(os.path.join(BOT_DIR, "utils", "channel_check.py"), encoding="utf-8") as f:
    channel_check_src = f.read()

check("채널 거절 메시지에 AskHintView를 같이 보낸다",
      "AskHintView()" in channel_check_src and "view=AskHintView()" in channel_check_src)
check("🚨 import가 함수 안에 있다 (모듈 맨 위면 순환 참조가 생긴다)",
      "    from utils.ask_hint import AskHintView" in channel_check_src
      or "        from utils.ask_hint import AskHintView" in channel_check_src)

view = ask_hint.AskHintView()
check("timeout=None (재시작 뒤에도 안 죽는다)", view.timeout is None, f"{view.timeout}")

ids = [c.custom_id for c in view.children if getattr(c, "custom_id", None)]
check("custom_id가 고정이다", ids == [ask_hint.ASK_CUSTOM_ID], f"{ids}")

# 🚨 영속 뷰는 봇 전체에 객체가 하나뿐이에요. 상태를 담으면 사용자끼리 섞여요.
#
# ⚠️ `ask`는 `@discord.ui.button`이 붙여준 **버튼 객체**고 `id`는 discord.py 내부
#    값이에요. 둘을 안 빼면 거짓 경보가 나요(`test_suggestion.py`와 같은 방식).
import discord  # noqa: E402

DISCORD_INTERNAL = {"id", "children", "timeout"}
own = {
    k: v for k, v in vars(view).items()
    if not k.startswith("_")
    and k not in DISCORD_INTERNAL
    and not isinstance(v, discord.ui.Item)
}
check("🚨 뷰가 상태를 들고 있지 않다", not own, f"{set(own) or '없음'}")

# 등록을 안 하면 재시작 뒤에 누른 사람이 "상호작용 실패"를 봐요.
with open(os.path.join(BOT_DIR, "cogs", "assistant.py"), encoding="utf-8") as f:
    assistant_src = f.read()
check("cog_load에서 영속 뷰를 등록한다",
      "add_view(AskHintView())" in assistant_src)


# ------------------------------------------------------------------
print("\n⒞ ⭐ \"바라는 것\"을 /건의로 보내는 다리가 있다")

hint = assistant.suggest_hint()
check("`/건의`를 가리킨다", "/건의" in hint, hint[:60])
check("💡 평문 줍기도 같이 알려준다", "💡" in hint)
check("매니저의 '못 답했어요' 화면에 그 다리가 붙어 있다",
      "suggest_hint()" in assistant_src)
# 🚨 못 답한 자리의 옛 문구. 이게 남아 있으면 바람이 또 아무 데도 안 남아요.
#    ⚠️ `AI_FOOTER`의 "이상하면 매니저에게 물어봐 주세요"는 **일부러 남겨뒀어요** —
#       그건 "AI 답이 틀렸을 때"라서 사람이 바로잡는 게 맞는 자리예요. 건의가 아니에요.
check("🚨 못 답한 자리를 '매니저에게 물어봐 주세요'로 끝내지 않는다",
      "찾아보시거나 매니저에게 물어봐 주세요" not in assistant_src)


# ------------------------------------------------------------------
print()
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for item in failures:
        print(f"   - {item}")
    sys.exit(1)
print("✅ 전부 통과")
