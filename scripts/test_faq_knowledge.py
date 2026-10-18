"""❓ 봇 매니저 지식 베이스 검사 (API 키 없이 돌아요).

    python scripts/test_faq_knowledge.py

## 무엇을 막으려고 만들었나

1. 🚨 **안내문에 숫자를 손으로 적는 것.** 값은 바뀌는데 안내만 옛값으로 남는 사고가
   이 저장소에서 반복됐어요(`/악귀상점`이 4차 이후로도 "하루 1개"라고 거짓 안내를 했어요).
   그래서 주제 본문에 나오는 가격·한도·확률이 **진짜 상수와 일치하는지** 대조해요.
2. 🚨 **엉뚱한 주제를 자신 있게 답하는 것.** "모르겠다"보다 나빠요(못 잡으면 Claude가
   받아주니까요). 그래서 질문 표본으로 매칭을 돌려 오답이 없는지 봐요.
3. 봇과 무관한 질문을 규칙이 함부로 답하지 않는지(= Claude로 넘기는지)도 같이 봐요.
"""
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils import faq_knowledge as fk  # noqa: E402
from utils.achievement_data import TOTAL as ACHIEVEMENT_TOTAL  # noqa: E402
from utils.attend_remind import MIN_STREAK as ATTEND_REMIND_STREAK  # noqa: E402
from utils.notify_prefs import NOTIFY_KINDS  # noqa: E402
from utils.card_data import TOTAL as CARD_SPECIES  # noqa: E402
from utils.card_store import PITY_DRAWS, PULL_PRICE  # noqa: E402
from utils.casino_store import DAILY_LIMIT, MAX_BET  # noqa: E402
from utils.fish_data import GRADES, ROD_DURABILITY, ROD_PRICE, TOTAL_SPECIES  # noqa: E402
from utils.inventory_store import PROTECT_PRICE  # noqa: E402
from utils.mission_store import DAILY_MISSION_COUNT, REROLL_PRICE  # noqa: E402
from utils.title_store import TITLE_PLANS  # noqa: E402

failed: list[str] = []


# ------------------------------------------------------------------
# ⒜ 본문 안의 숫자가 상수와 맞나
# ------------------------------------------------------------------
print("⒜ 안내문 숫자 ↔ 실제 상수 대조")

CHECKS = [
    # (주제, 본문에 반드시 들어가야 하는 문구, 설명)
    ("fishing", f"{ROD_PRICE}코인", "낚시대 값"),
    ("fishing", f"{ROD_DURABILITY}번", "낚시대 내구도"),
    ("fishing", f"{TOTAL_SPECIES}종", "어종 수"),
    ("cards", f"{PULL_PRICE}코인", "뽑기 값"),
    ("cards", f"{CARD_SPECIES}종", "카드 종류 수"),
    ("cards", f"{PITY_DRAWS}장", "천장"),
    ("casino", f"{MAX_BET}코인", "1회 최대 베팅"),
    ("casino", f"{DAILY_LIMIT}코인", "하루 총 한도"),
    ("coin_spend", f"{REROLL_PRICE}코인", "리롤권 값"),
    ("coin_spend", f"{PROTECT_PRICE}코인", "보호권 값"),
    ("mission", f"{DAILY_MISSION_COUNT}개", "하루 미션 수"),
    ("title", f"{TITLE_PLANS[30]}코인", "칭호 30일 값"),
    # 🚨 규칙을 바꿨으면 안내문도 같이 바뀌어야 해요. 2026-10-18에 낚시를 "동시 한 판"으로
    #    제한했는데 안내문을 안 고쳐서, 매니저가 옛 규칙으로 자신 있게 답하고 있었어요.
    ("fishing", "한 번에 한 판", "동시 1판 제한 안내"),
    ("record", "한 줄 평", "AI 코칭 안내"),
    # 🚨 `/프로필` 안내가 "업적은 60개"라고 **거짓말을 하고 있었어요**(실제 50개).
    #    손으로 적은 숫자라 업적을 줄일 때 같이 안 바뀌었어요.
    ("profile", f"{ACHIEVEMENT_TOTAL}개", "업적 수"),
    ("notify", f"{len(NOTIFY_KINDS)}가지", "알림 종류 수"),
    ("attendance", f"연속 {ATTEND_REMIND_STREAK}일 이상", "출석 알림 최소 연속일"),
    # 🚨 낚시 대회에 **상금을 주면** 안 돼요(발행 1위 기능이라 경제가 기울어요).
    ("fishing_contest", "상금은 없어요", "상금 없음 명시"),
    ("fishing_contest", "등급이 먼저", "최대어는 등급 우선"),
]

# 🚨 알림이 새로 생겼는데 안내문이 모르는 경우. `/알림설정` 화면엔 뜨는데 매니저만
#    옛 목록을 들고 있으면, 유저가 "그런 알림 없다"는 답을 받아요.
notify_body = fk.TOPIC_BY_KEY["notify"].text()
for key, info in NOTIFY_KINDS.items():
    if info["title"] not in notify_body:
        failed.append(f"알림 '{key}'({info['title']})가 안내문에 없어요")
        print(f"  ❌ notify       {info['title']} 가 빠졌어요")
    else:
        print(f"  ✅ notify       {info['title']}")

for key, needle, label in CHECKS:
    body = fk.TOPIC_BY_KEY[key].text()
    if needle in body:
        print(f"  ✅ {key:12} {label}: {needle}")
    else:
        failed.append(f"[{key}] {label} 안내가 상수({needle})와 달라요")
        print(f"  ❌ {key:12} {label}: 본문에 {needle!r}가 없어요")

# 🚨 낚시 등급의 `weight`는 퍼센트가 **아니라** 가중치예요(합이 100이 아니에요).
#    그대로 적으면 "일반 135%"라는 거짓말이 나와요. 과거에 실제로 그렇게 썼다가 고쳤어요.
fishing_body = fk.TOPIC_BY_KEY["fishing"].text()
for grade, info in GRADES.items():
    raw = f"{grade} {info['weight']}%"
    if raw in fishing_body:
        failed.append(f"낚시 등급 '{grade}'을 가중치 그대로 %로 적었어요 ({raw})")
        print(f"  ❌ {raw!r} — 가중치를 합으로 나눠 환산해야 해요")
if "%" in fishing_body:
    print("  ✅ fishing      등급 확률은 환산된 값으로 들어가 있어요")


# ------------------------------------------------------------------
# ⒝ 모든 주제가 본문을 만들 수 있나 (상수 이름이 바뀌면 여기서 터져요)
# ------------------------------------------------------------------
print("\n⒝ 주제 본문 생성")
for topic in fk.TOPICS:
    try:
        body = topic.text()
    except Exception as exc:  # noqa: BLE001
        failed.append(f"[{topic.key}] 본문 생성 실패: {type(exc).__name__}: {exc}")
        print(f"  ❌ {topic.key}: {type(exc).__name__}: {exc}")
        continue
    if len(body) < 30:
        failed.append(f"[{topic.key}] 본문이 너무 짧아요")
        print(f"  ❌ {topic.key}: 너무 짧아요")
    elif len(body) > 4000:  # 디스코드 임베드 description 한도가 4096자예요
        failed.append(f"[{topic.key}] 본문이 임베드 한도(4096자)에 가까워요: {len(body)}자")
        print(f"  ❌ {topic.key}: {len(body)}자 — 임베드 한도에 걸려요")
    else:
        print(f"  ✅ {topic.key:12} {len(body)}자")


# ------------------------------------------------------------------
# ⒞ 질문 → 주제 매칭
# ------------------------------------------------------------------
print("\n⒞ 질문 표본 매칭")

# 규칙이 **반드시 이 주제로** 답해야 하는 질문들 (자주 들어올 말)
MUST_HIT = [
    ("코인 어떻게 모아?", "coin_earn"),
    ("돈 벌고 싶어", "coin_earn"),
    ("코인 어디에 써?", "coin_spend"),
    ("낚시 어떻게 해?", "fishing"),
    ("낚시대 어디서 사?", "fishing"),
    ("물고기 팔고 싶어", "fishing"),
    ("출석 보상이 뭐야", "attendance"),
    ("연속 출석 끊겼는데", "attendance"),
    ("미션이 안 깨지는데", "mission"),
    ("미션 바꾸고 싶어", "mission"),
    ("카드 천장 몇 장이야", "cards"),
    ("카드 뽑기 얼마야", "cards"),
    ("도박 하루 한도 얼마", "casino"),
    ("블랙잭 어떻게 해", "casino"),
    ("칭호 사려면 얼마 필요해", "title"),
    ("내전 전적은 어디서 봐", "scrim"),
    ("팀짜기 어떻게 써", "scrim"),
    ("통화방 어떻게 만들어", "rooms"),
    ("오상 쓰려면 뭐 해야 해", "myshop"),
    ("전적 등록 어떻게", "record"),
    ("노래 틀고 싶어", "karaoke"),
    ("알림 끄고 싶어", "notify"),
    ("프로필 카드 어떻게 봐", "profile"),
    ("생일 등록", "birthday"),
    ("성인인증 어떻게", "adult"),
    # 🚨 기능을 바꾸면 여기도 같이 늘려주세요. 매니저가 **옛 규칙을 자신 있게 답하는** 게
    #    제일 나쁜 경우예요(못 잡으면 Claude가 받아주지만, 틀린 확신은 안 받아줘요).
    ("봇한테 어떻게 물어봐?", "ask_bot"),
    ("도움말 어떻게 써?", "ask_bot"),
    ("낚시 왜 한 번만 돼?", "fishing"),
    # 2026-10-18 신기능 5종. 기능을 더하면 여기도 같이 늘려주세요.
    ("음성 레벨 어떻게 올려?", "voice_level"),
    ("통화방 레벨이 뭐야", "voice_level"),
    ("일정 어떻게 잡아?", "event"),
    ("내전 약속 잡고 싶어", "event"),
    ("건의하고 싶어", "suggestion"),
    ("전적이 자동으로 올라오던데", "match_feed"),
    # 🚨 이게 /오상으로 갔었어요 — myshop의 strong에 "vp"가 있어서 **"m-vp"에 걸렸어요.**
    ("mvp 어떻게 뽑아?", "weekly_mvp"),
    # 그래서 /오상 쪽도 같이 지켜요(구체적인 말로 바꾼 뒤에도 잘 잡히는지).
    ("vp 충전 얼마나 해야 해?", "myshop"),
    # 2026-10-18 v140 3종.
    ("낚시대회 뭐야", "fishing_contest"),
    ("주간 낚시 대회 어떻게 참여해", "fishing_contest"),
    ("최대어 누가 1등이야", "fishing_contest"),
    ("낚시대회 상금 있어?", "fishing_contest"),
    # 🚨 "낚시대"가 **"낚시대회"에 걸렸어요**("vp"가 "mvp"에 걸린 것과 같은 사고예요).
    #    그래서 낚시 쪽도 같이 지켜요 — 둘이 서로를 가져가면 안 돼요.
    ("낚시대 얼마야", "fishing"),
    ("낚시왕 뭐야", "fishing"),          # 누적 랭킹. 주간 대회가 아니에요
    # 🚨 "알림"이 /알림설정으로 가져가 버려서 동점(무응답)이 됐어요. 붙은 말로 잡아요.
    ("출석 끊겼는데 알림 안 와?", "attendance"),
    ("출석 알림 꺼줘", "attendance"),
    ("업적 몇 개야", "profile"),
    ("다음에 깰 업적 알려줘", "profile"),
]

for question, expected in MUST_HIT:
    topic, _related = fk.search(question)
    if topic is None:
        # Claude가 받아주니 치명적이진 않지만, 흔한 질문은 공짜로 답해야 해요.
        failed.append(f"흔한 질문을 규칙이 못 잡아요: {question!r} (기대: {expected})")
        print(f"  ❌ {question!r:28} → 규칙 미스 (Claude로 넘어가요)")
    elif topic.key != expected:
        failed.append(f"엉뚱한 주제로 답해요: {question!r} → {topic.key} (기대: {expected})")
        print(f"  ❌ {question!r:28} → {topic.key} (기대 {expected})")
    else:
        print(f"  ✅ {question!r:28} → {topic.key}")

# 봇과 무관한 질문은 규칙이 **답하지 않아야** 해요(Claude가 "범위 밖"이라고 답해요).
MUST_MISS = [
    "제트 스킨 언제 나와",
    "발로 티어 올리는 법 알려줘",
    "안녕",
    "오늘 날씨 어때",
    "에임 좋아지는 법",
]
print()
for question in MUST_MISS:
    topic, _related = fk.search(question)
    if topic is not None:
        failed.append(f"봇과 무관한 질문에 규칙이 답해버려요: {question!r} → {topic.key}")
        print(f"  ❌ {question!r:28} → {topic.key} (답하지 말아야 해요)")
    else:
        print(f"  ✅ {question!r:28} → Claude로 넘겨요")


# ------------------------------------------------------------------
# ⒟ Claude 시스템 프롬프트
# ------------------------------------------------------------------
print("\n⒟ Claude 시스템 프롬프트")


class _FakeTree:
    def get_commands(self):
        return []


class _FakeBot:
    tree = _FakeTree()


prompt = fk.build_system_prompt(_FakeBot())
print(f"  📏 {len(prompt)}자 (명령어 목록 없이 — 실제로는 더 길어요)")

for topic in fk.TOPICS:
    if topic.title not in prompt:
        failed.append(f"시스템 프롬프트에 '{topic.title}'이 빠졌어요")

# 🚨 Haiku 4.5는 프롬프트 캐시가 붙는 최소 길이가 **4096 토큰**이에요. 그보다 짧으면
#    에러 없이 조용히 캐시가 안 걸려요(동작은 정상, 값만 못 깎음). 한글은 글자당
#    대략 1~1.5토큰이라 넉넉히 잡아 3000자 미만이면 경고해요.
if len(prompt) < 3000:
    print(f"  ⚠️ 프롬프트가 짧아요({len(prompt)}자) — 캐시가 안 걸릴 수 있어요(동작은 정상)")
else:
    print("  ✅ 프롬프트 캐시가 걸릴 만한 길이예요")

if "지어내지 마" in prompt and "모른다고" in prompt:
    print("  ✅ '자료에 없으면 모른다고 답하라' 지시가 들어 있어요")
else:
    failed.append("시스템 프롬프트에 환각 방지 지시가 없어요")


# ------------------------------------------------------------------
print()
if failed:
    print(f"❌ 실패 {len(failed)}건")
    for item in failed:
        print(f"  · {item}")
    sys.exit(1)
print("✅ 전부 통과")
