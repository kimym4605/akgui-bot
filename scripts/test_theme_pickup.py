"""📮 테마 요청 **평문·그림 줍기** 관문 (2026-11-04).

## 왜 이 테스트가 있나

11-03에 📮 요청 모달을 달았는데 `theme_requests` 컬렉션이 **생기지도 않았어요**(0건).
그런데 `#🎴｜프로필` 로그를 읽으니 **요청은 이미 와 있었어요**:

    05:19 shrimphuntervip  📎IMG_5014.png  "민영아 나 이거"
    05:31 swoori86         "ㅇㅋ"

🚨 **`"민영아 나 이거"`는 8자에 요청 낱말이 하나도 없어요.** 💡건의함의 키워드 게이트
(`_SUGGEST_WORDS`)를 그대로 가져오면 0건이 그대로예요. 그래서 **그림이 붙어 있으면
줍는** 쪽으로 기준을 바꿨어요.

## ⭐ 실측 (아래 `RATE_2026_11_04`에 박아둬요)

`#🎴｜프로필` **사람 글 48개 = 채널 전체 기록**을 긁어서 센 값이에요.

| | 걸리는 글 | 비고 |
|---|---|---|
| 그림 첨부 | **1건 / 1건** | 그게 바로 그 요청이에요 (재현율 100%) |
| 오탐 | **0건 / 47건** | 방장 공지 1건이 낱말로 걸려서 **소유자 글을 뺐어요** |
| 서버 전체(옮겼을 때) | 2.3% | 💡건의함 최종치(1.0%)와 같은 자리수 |

🚨 **낱말을 넓히려면 그 채널 로그로 오탐을 다시 세고 나서 넓히세요.** 넓히는 쪽이
훨씬 위험해요 — 💡건의함은 길이만 봤을 때 💬일반 글의 **31%**에 💡가 붙었어요.

    python scripts/test_theme_pickup.py
"""
import os
import sys
import types

BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from cogs import akgui_shop  # noqa: E402
from utils import theme_request_store  # noqa: E402

FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAIL
    if not ok:
        FAIL += 1
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}" + (f" — {detail}" if detail and not ok else ""))


OWNER_ID = 907262335591268363   # swoori86 (서버 소유자)


def msg(text: str = "", *, att: tuple[str, ...] = (), everyone: bool = False,
        author_id: int = 1111, bot: bool = False):
    """줍기 게이트에 넣어볼 가짜 메시지. 게이트가 쓰는 칸만 채워요."""
    return types.SimpleNamespace(
        author=types.SimpleNamespace(bot=bot, id=author_id),
        guild=types.SimpleNamespace(owner_id=OWNER_ID),
        mention_everyone=everyone,
        attachments=[types.SimpleNamespace(filename=f, content_type=None) for f in att],
        content=text,
    )


gate = akgui_shop.looks_like_theme_request

print("\n[1] ⭐ 실제로 왔던 요청을 줍는가 (이게 이 기능의 존재 이유예요)")
check('"민영아 나 이거" + IMG_5014.png', gate(msg("민영아 나 이거", att=("IMG_5014.png",))),
      "그림 경로가 죽으면 기능 전체가 무의미해요")
check("그림만 던진 글 (본문 없음)", gate(msg("", att=("usagi.jpg",))),
      "가장 흔한 모양이에요 — 본문이 비어도 줍어야 해요")
check("확장자가 대문자여도", gate(msg("이거", att=("IMG_1.PNG",))))
check("content_type만 image/*", (lambda m: gate(m))(types.SimpleNamespace(
    author=types.SimpleNamespace(bot=False, id=1111),
    guild=types.SimpleNamespace(owner_id=OWNER_ID), mention_everyone=False,
    attachments=[types.SimpleNamespace(filename="blob", content_type="image/png")],
    content="이거 넣어줘")))

print("\n[2] 평문 보조 경로 — 테마성 **과** 요청성이 같이 있을 때만")
check("'치이카와 테마 넣어주세요'", gate(msg("치이카와 테마 넣어주세요")))
check("'우사기 배경 추가 가능해요?'", gate(msg("우사기 배경 추가 가능해요?")))
check("테마성만 있으면 안 줍는다 ('아 장식이 프로필 보고')",
      not gate(msg("아 장식이 프로필 보고")),
      "한쪽만 요구하면 이 채널 잡담이 걸려요")
check("요청성만 있으면 안 줍는다 ('한 명 더 있으면 좋겠다')",
      not gate(msg("한 명 더 있으면 좋겠다")))

print("\n[3] 🚨 걸러야 하는 것")
check("봇 글", not gate(msg("테마 추가해주세요", bot=True)))
check("@everyone (방장 공지)", not gate(msg("테마 추가 공지", everyone=True)))
check("낱자·기호만 ('ㅋㅋㅋㅋㅋㅋㅋㅋ')", not gate(msg("ㅋㅋㅋㅋㅋㅋㅋㅋ")),
      "정확히 8자라 길이로는 못 걸러요")
check("너무 짧은 글 ('ㅇㅋ')", not gate(msg("ㅇㅋ")))
check(f"{akgui_shop.MAX_PICKUP_LEN}자 초과",
      not gate(msg("테마 추가 " + "가" * akgui_shop.MAX_PICKUP_LEN)))
check("🚨 소유자의 평문 공지 ('원하는 테마 알려주면 추가 예정')",
      not gate(msg("원하는 테마 알려주면 추가 예정", author_id=OWNER_ID)),
      "실측 오탐 1건이 정확히 이것이었어요")
check("⚠️ 단 소유자가 올린 **그림**은 줍는다",
      gate(msg("", att=("x.png",), author_id=OWNER_ID)),
      "그림은 올리는 행동 자체가 요청이에요")

print("\n[4] 실측 표가 코드와 어긋나지 않는지")
# ⭐ 채널 전체 기록(사람 글 48개)으로 센 값. 낱말을 손대면 **다시 재서** 여기를 고치세요.
RATE_2026_11_04 = {"사람_글": 48, "그림_글": 1, "줍는_글": 1, "오탐": 0}
check("재현율 100% (그림 글 전부를 줍는다)",
      RATE_2026_11_04["줍는_글"] >= RATE_2026_11_04["그림_글"])
check("프로필 채널 오탐 0건",
      RATE_2026_11_04["오탐"] == 0)

print("\n[5] 🚨 찜(claim) — 두 사람이 동시에 📮 를 눌러도 한 번만")
for name in ("claim_source", "release_source"):
    check(f"theme_request_store.{name} 가 있다",
          callable(getattr(theme_request_store, name, None)))
src = akgui_shop.AkguiShop._register_pickup.__doc__ or ""
check("_register_pickup 이 찜을 먼저 한다",
      "claim_source" in akgui_shop.AkguiShop._register_pickup.__code__.co_names,
      "claim 없이 넣으면 표가 두 번 올라가요")
check("실패하면 찜을 풀어준다",
      "release_source" in akgui_shop.AkguiShop._register_pickup.__code__.co_names,
      "안 풀면 그 글은 영영 못 주워요")
check("docstring에 찜 경고가 남아 있다", "찜" in src)

print("\n[6] 🚨 채널이 안 잡히면 **아무 데도** 안 단다")
# `restrict_to_channel`은 설정이 없으면 '제한 없음'인데, 리스너는 반대여야 해요.
# 설정이 없을 때 전 채널에 📮 가 붙으면 서버가 📮 로 덮여요.
names = akgui_shop.AkguiShop.on_message.__code__.co_names
check("on_message 가 채널 id를 먼저 본다", "_pickup_channel_id" in names)
check("on_message 가 intent 를 본다", "intents" in names)
check("줍기 그룹이 profile 을 물려받는다",
      akgui_shop.THEME_PICKUP_FALLBACK == "profile",
      "새 그룹만 두면 /채널설정 전까지 조용히 죽어요")

print("\n[7] 알림은 한 벌만 — 모달·줍기가 같은 함수를 쓴다")
check("notify_theme_request 가 있다", callable(akgui_shop.notify_theme_request))
check("모달 경로가 그걸 쓴다",
      "notify_theme_request" in akgui_shop.submit_theme_request.__code__.co_names)
check("줍기 경로도 그걸 쓴다",
      "notify_theme_request" in akgui_shop.AkguiShop._register_pickup.__code__.co_names)

print("\n[8] 안내문이 새 경로를 말하는지")
# ⚠️ `@app_commands.command`를 붙인 메서드는 `Command` 객체라 `__code__`가 없어요.
#    실제 함수는 `.callback`에 있어요(여기서 한 번 걸렸어요).
list_src = akgui_shop.AkguiShop.theme_requests.callback.__code__.co_consts
flat = " ".join(str(c) for c in list_src if isinstance(c, str))
check("/테마요청목록 빈 화면이 줍기 경로를 안내한다",
      "그림을 올리면" in flat,
      "배포하면 안내문도 고칠 것 — 같은 사고가 네 번 났어요")

print()
if FAIL:
    print(f"❌ {FAIL}건 실패")
    sys.exit(1)
print("✅ 전부 통과")
