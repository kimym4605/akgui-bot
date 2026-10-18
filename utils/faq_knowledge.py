"""❓ 봇 매니저가 쓰는 지식 베이스예요. 질문 → 주제 매칭(공짜)과 Claude용 시스템 프롬프트를 둘 다 여기서 만들어요.

## 왜 만들었나 (2026-10-18)

기능은 쌓였는데 **사람들이 못 쓰고 있었어요.** 실측으로 `/악귀상점` 구매 0건(열흘),
카드 거래 1건, 낚시 수혜자 12명. 구매력 문제가 아니라 **"있는 줄 몰랐다 / 쓰는 법을 모른다"**
쪽이에요. 그래서 물어보면 답하는 창구를 하나 만들어요.

## 🚨 숫자를 여기에 적지 말 것

낚시대 값·뽑기 값·도박 한도 같은 수치는 **전부 각 모듈 상수에서 import해서** 문장에 끼워요.
`/악귀상점`이 "하루 1개"라고 거짓 안내를 하던 게 딱 이걸 안 지켜서 생긴 일이에요
(값은 바뀌었는데 안내 문구는 안 바뀜). `scripts/test_faq_knowledge.py`가 하드코딩을 막아요.

## 두 갈래로 답해요

1. **규칙 매칭** (`search()`) — 키워드가 또렷하면 바로 답해요. 돈이 안 들고 즉시 답해요.
2. **Claude** (`build_system_prompt()`) — 위에서 못 잡은 자연어 질문만 넘겨요.
   그때도 여기서 만든 지식 베이스를 그대로 먹여요. 두 갈래가 같은 사실을 보게 하려고요.

## 명령어 목록은 코드에서 긁어요

`build_command_catalog(bot)`은 `bot.tree`를 그대로 훑어요. 명령어를 새로 만들면
여기 손 안 대도 매니저가 알게 돼요(목록을 따로 적어두면 또 썩어요).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import discord

from utils import fish_data
from utils.attend_service import STREAK_BONUS_TIERS, WEEKLY_BONUS_COIN, WEEKLY_BONUS_EVERY
from utils.card_data import TOTAL as CARD_SPECIES
from utils.card_store import (
    CARDS_PER_PULL,
    GRADE_ORDER as CARD_GRADES,
    GRADE_WEIGHTS as CARD_WEIGHTS,
    MAX_PULLS,
    PITY_DRAWS,
    PULL_PRICE,
)
from utils.casino_store import (
    BET_EXTEND_BASE_PRICE,
    BET_EXTEND_BONUS,
    BET_EXTEND_MAX,
    DAILY_LIMIT,
    EXTEND_BASE_PRICE,
    EXTEND_BONUS,
    MAX_BET,
    MIN_BET,
)
from utils.fish_data import (
    COIN_PIECES,
    GRADE_ORDER as FISH_GRADES,
    GRADES as FISH_GRADE_INFO,
    ROD_DURABILITY,
    ROD_PRICE,
    SMALL_ROD_DURABILITY,
    SMALL_ROD_PRICE,
    TOTAL_SPECIES as FISH_SPECIES,
)
from utils.achievement_data import TOTAL as ACHIEVEMENT_TOTAL
from utils.attend_remind import MIN_STREAK as ATTEND_REMIND_STREAK
from utils.inventory_store import PROTECT_MAX, PROTECT_PRICE
from utils.mission_store import (
    DAILY_MISSION_COUNT,
    REROLL_LIMIT_PER_DAY,
    REROLL_PRICE,
    REWARD_PER_MISSION,
)
from utils.event_store import REMIND_BEFORE_MINUTES as EVENT_REMIND_MINUTES
from utils.notify_prefs import NOTIFY_KINDS
from utils.pokemon_store import COIN_PER_ATTENDANCE
from utils.profile_card import THEME_PRICE
from utils.title_store import TITLE_DAYS, TITLE_PLANS
from utils.voice_level import (
    ROLE_TIERS as VOICE_ROLE_TIERS,
    minutes_for_level as _voice_minutes_for_level,
)

# 🚨 숫자를 여기에 적지 말 것 — 전부 상수에서 끌어와요(이 파일 맨 위 설명 참고).
VOICE_FIRST_LEVEL_MINUTES = _voice_minutes_for_level(1)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 상수에서 뽑아낸 사실들 — 문장에 끼워 쓰는 재료
# ------------------------------------------------------------------
def _fish_grade_line() -> str:
    """등급별 확률·값 한 줄. `fish_data.GRADES`가 바뀌면 같이 바뀌어요.

    🚨 `GRADES[*]["weight"]`는 **퍼센트가 아니라 가중치**예요(합이 149.2). 그대로 적으면
    "일반 135%"라는 거짓말이 나와요. `/낚시확률`과 똑같이 합으로 나눠서 환산해요."""
    total = sum(info["weight"] for info in FISH_GRADE_INFO.values())
    if total <= 0:
        return ""
    parts = []
    for grade in FISH_GRADES:
        info = FISH_GRADE_INFO.get(grade)
        if not info:
            continue
        lo, hi = info["pieces"]
        parts.append(
            f"{info['emoji']} {grade} {info['weight'] / total * 100:.1f}% "
            f"({lo / COIN_PIECES:.1f}~{hi / COIN_PIECES:.1f}코인)"
        )
    return "\n".join(parts)


def _card_grade_line() -> str:
    parts = []
    for grade in CARD_GRADES:
        weight = CARD_WEIGHTS.get(grade)
        if weight is None:
            continue
        parts.append(f"{grade} {weight}%")
    return " · ".join(parts)


def _title_plan_line() -> str:
    """칭호 요금제. `TITLE_PLANS`에 요금제를 더하면 저절로 따라와요."""
    return " · ".join(
        f"{days}일 {price}코인" for days, price in sorted(TITLE_PLANS.items())
    )


def _streak_bonus_line() -> str:
    tiers = sorted(STREAK_BONUS_TIERS, key=lambda t: t[0])
    return " · ".join(f"{days}일 이상 +{bonus}" for days, bonus in tiers)


# ------------------------------------------------------------------
# 주제
# ------------------------------------------------------------------
@dataclass(frozen=True)
class Topic:
    """하나의 안내 주제.

    키워드를 **두 단계로** 나눠요. 한국어는 어미가 변해서("모아/모으는/벌고") 긴 구절
    매칭이 잘 빗나가요. 그래서:

    · `strong` — 이 말이 나오면 주제가 거의 확정되는 것. 하나만 맞아도 답해요.
    · `weak`   — 여러 주제에 걸치는 보조어("코인", "사", "확률"). 모아야 의미가 생겨요.

    🚨 `weak`만 쌓여서 답하면 **엉뚱한 주제를 자신 있게 답하는** 쪽으로 틀려요. 그게
    "모르겠다"보다 나빠요(못 잡으면 Claude가 받아주니까요). 그래서 weak 점수는 낮게 둬요.
    """

    key: str
    title: str
    strong: tuple[str, ...]
    body: Callable[[], str]
    weak: tuple[str, ...] = field(default=())
    commands: tuple[str, ...] = field(default=())

    def text(self) -> str:
        return self.body().strip()

    @property
    def keywords(self) -> tuple[str, ...]:
        return self.strong + self.weak


def _coin_earn() -> str:
    return f"""악귀코인을 버는 길은 **네 개**예요.

· 📅 `/출석` — 하루 1번 {COIN_PER_ATTENDANCE}코인. 연속으로 오면 더 줘요({_streak_bonus_line()}),
  연속 {WEEKLY_BONUS_EVERY}일마다 보너스 {WEEKLY_BONUS_COIN}코인이 또 붙어요.
· 🎯 `/미션` — 하루 {DAILY_MISSION_COUNT}개 배정, 깰 때마다 {REWARD_PER_MISSION}코인
  (하루 최대 {DAILY_MISSION_COUNT * REWARD_PER_MISSION}코인). 발로란트 미션은 봇이 전적을 보고 **자동으로** 체크해요.
· 🎣 `/낚시` — 지금 **가장 많이 벌리는 쪽**이에요. 낚시대({ROD_PRICE}코인)를 사서 {ROD_DURABILITY}번 던지고,
  잡은 걸 `/물고기판매`로 팔아요. 등급이 높으면 본전을 크게 넘겨요.
· 🏅 업적 — `/업적`을 달성하면 그때그때 코인이 들어와요.

지금 얼마 있는지는 `/코인`으로 봐요."""


def _coin_spend() -> str:
    return f"""코인 쓰는 곳이에요.

· 🛒 `/악귀상점` — 🎣 낚시대 {ROD_PRICE}코인(🪝 소형 {SMALL_ROD_PRICE}코인) · 🎲 미션 리롤권 {REROLL_PRICE}코인 ·
  🧊 출석 보호권 {PROTECT_PRICE}코인 · 🎨 프로필 카드 테마 {THEME_PRICE}코인
· 🎴 `/카드뽑기` — {PULL_PRICE}코인에 {CARDS_PER_PULL}장
· 🎰 `/도박` — 슬롯 · 하이로우 · 블랙잭
· 🏷️ `/칭호구매` — {_title_plan_line()}
· 🤝 `/코인보내기` — 사람한테 직접 줄 수도 있어요"""


def _attendance() -> str:
    return f"""📅 `/출석`은 하루에 한 번이에요(한국 시간 자정에 넘어가요).

· 기본 {COIN_PER_ATTENDANCE}코인 + 연속 보너스({_streak_bonus_line()})
· 연속 {WEEKLY_BONUS_EVERY}일마다 {WEEKLY_BONUS_COIN}코인이 더 붙어요. **{WEEKLY_BONUS_EVERY}일마다 계속** 돌아와요.
· 하루 빠지면 연속이 0으로 돌아가요. 🧊 **출석 보호권**({PROTECT_PRICE}코인 · `/악귀상점`)이 있으면
  하루치를 살려줘요(최대 {PROTECT_MAX}장까지 들고 있을 수 있어요 · 이틀 이상은 못 살려요).
· ⏰ **끊기기 전에 알려드려요.** 연속 {ATTEND_REMIND_STREAK}일 이상 이어오셨는데 그날 아직
  `/출석`을 안 하셨으면 밤에 DM이 한 번 가요(🧊 보호권이 있으면 그것도 같이 알려드려요).
  번거로우면 `/알림설정`에서 꺼요.
· 누가 제일 오래 왔는지는 `/출석순위`로 봐요."""


def _mission() -> str:
    return f"""🎯 `/미션`은 하루 {DAILY_MISSION_COUNT}개가 배정되고, 하나 깰 때마다 {REWARD_PER_MISSION}코인이에요.

· **발로란트 미션은 자동 판정이에요.** 봇이 30분마다 전적을 확인해요
  (그래서 깬 직후 바로는 안 뜰 수 있어요. 조금 기다려 주세요).
  단, `/전적`에 계정이 등록돼 있어야 봇이 찾을 수 있어요.
· 서버 미션(통화방 참여 등)은 조건을 채우면 반영돼요.
· 마음에 안 드는 미션은 🎲 **리롤권**({REROLL_PRICE}코인 · `/악귀상점`)으로 바꿔요.
  하루 {REROLL_LIMIT_PER_DAY}번까지예요.
· 미션을 깼다는 알림이 시끄러우면 `/알림설정`에서 꺼요."""


def _fishing() -> str:
    return f"""🎣 낚시는 이렇게 해요.

1. `/악귀상점`에서 **낚시대**를 사요({ROD_PRICE}코인 · {ROD_DURABILITY}번 던질 수 있어요). 개수 제한은 없어요.
   코인이 적으면 🪝 **소형 낚시대**({SMALL_ROD_PRICE}코인 · {SMALL_ROD_DURABILITY}번)로 시작해도 돼요.
   **횟수당 값이 똑같아서** 손해가 아니에요 — 작게 사서 번 걸로 다시 사면 돼요.
2. `/낚시`로 찌를 던지고, **입질이 오면 버튼을 눌러** 챔질해요.
3. 잡은 건 `/어항`에서 보고, `/물고기판매`로 한꺼번에 팔아요.

⚠️ **한 번에 한 판만** 할 수 있어요. 던지는 중에 또 `/낚시`를 치면 "그 판을 먼저
끝내주세요"라고 나와요(이때 **낚시대는 안 줄어요**). 결과 화면의 **🎣 다시 던지기**
버튼을 쓰면 바로 다음 판이라 제일 편해요.

어종은 {FISH_SPECIES}종이고 등급은 네 개예요.
{_fish_grade_line()}

· 한 번 던지면 평균 **{fish_data.expected_coin_per_cast():.1f}코인**,
  낚시대 하나(={ROD_DURABILITY}번)로 약 **{fish_data.expected_coin_per_day():.0f}코인**이에요.
  낚시대값을 빼면 **{fish_data.net_issue_per_rod():+.0f}코인**쯤 남아요.
· **꽝은 없어요.** 타이밍만 맞히면 뭔가 나오고, 챔질을 놓치면 횟수를 돌려줘요.
· 치수(cm)는 어종별 실제 크기에서 굴려요. 같은 어종도 치수가 값을 갈라요.
· 더 자세한 건 `/낚시확률`에 전부 공개돼 있어요.
· 누가 제일 많이 벌었는지는 `/낚시왕`으로 봐요(**누적** 기준이에요).
· 주마다 따로 겨루는 🎣 **주간 낚시 대회**도 있어요(`/낚시대회`)."""


def _fishing_contest() -> str:
    return """🎣 주간 낚시 대회는 **매주 월요일 낮**에 지난주 기록을 결산해요.
결과는 🏆 **주간결산** 채널에 올라와요(🏅 주간 MVP도 같은 곳이에요).

종목이 **둘**이에요. 둘의 1등이 서로 다를 수 있어요.
🏆 **최대어** — 그 주에 낚은 제일 대단한 물고기. 운이 섞여서 누구나 하루아침에 1등이 돼요.
💰 **최다 수익** — 그 주에 `/물고기판매`로 번 코인. 꾸준히 하신 분 쪽이에요.

· 🚨 최대어는 **등급이 먼저**예요. 전설 30cm가 일반 40cm보다 위예요.
  같은 등급 안에서만 치수로 가려요.
· 중간 순위는 `/낚시대회`로 아무 때나 봐요. 지난주 것이 아니라 **이번 주** 진행 상황이에요.
· 최대어 1등에게 🎣 **이주의 낚시왕** 역할이 가요. 다음 주 우승자가 나오면 넘어가요.
· **상금은 없어요.** 낚시가 이미 코인이 제일 많이 나오는 곳이라, 상은 역할(명예)로만 둬요.
· `/낚시왕`은 누적 랭킹이라 이것과 달라요."""


def _cards() -> str:
    return f"""🎴 악귀카드는 **{CARD_SPECIES}종**이에요.

· `/카드뽑기` — {PULL_PRICE}코인에 {CARDS_PER_PULL}장. 한 번에 {MAX_PULLS}뽑기까지 이어서 돌릴 수 있어요.
· 등급 확률은 {_card_grade_line()} (`/카드확률`에서 봐요)
· **천장이 있어요.** 레전드 없이 {PITY_DRAWS}장을 뽑으면 다음에 레전드가 확정이에요.
· 모은 건 `/도감`에서 번호순으로 봐요.
· `/카드거래`로 **상대를 지목해서** 카드를 팔아요. 받는 사람은 `/거래함`에서 수락/거절해요.
  (예전처럼 아무나 집어가는 공개 장터가 아니에요)"""


def _casino() -> str:
    return f"""🎰 `/도박`에는 슬롯 · 하이로우 · 블랙잭이 있어요.

· 한 번에 {MIN_BET}~{MAX_BET}코인, **하루 총 {DAILY_LIMIT}코인**까지 걸 수 있어요.
· 🔓 하루 한도는 연장권으로 늘려요({EXTEND_BASE_PRICE}코인부터 시작해 살수록 비싸져요 · 한 번에 +{EXTEND_BONUS}).
· 🎲 1회 한도도 따로 늘릴 수 있어요({BET_EXTEND_BASE_PRICE}코인부터 · 한 번에 +{BET_EXTEND_BONUS} · 통산 {BET_EXTEND_MAX}번까지).
  이쪽은 **하루 총액은 안 건드려요.**
· 한도 확인·연장은 `/도박 한도늘리기`예요."""


def _title() -> str:
    return f"""🏷️ `/칭호구매`로 **나만의 역할 이름과 색**을 달아요.

· 요금제: {_title_plan_line()} (하루 단가는 {TITLE_DAYS}일권이 더 싸요)
· 기간이 남아 있을 때 또 사면 **이어붙어요.**
· 지금 뭘 달고 있는지는 `/칭호`, 떼려면 `/칭호해제`예요.
· 이름은 최대 20자예요."""


def _scrim() -> str:
    return """🤝 내전은 이렇게 돌아가요.

· `/내전모집` — 사람을 모아요.
· `/팀짜기` — 실력을 맞춰 두 팀으로 나눠요. 수동 명단·팀장 지정·맵 지정도 돼요.
· 경기가 끝나면 **승리 보고 버튼**을 눌러주세요. 그래야 전적이 쌓여요
  (KDA는 봇이 라이엇 쪽에서 자동으로 가져와요).
· 쌓인 건 `/내전전적` · `/주간랭킹` · `/내전시즌`에서 봐요.
· `/베팅개설`로 승부에 코인을 걸 수도 있어요(딴 사람끼리 나눠 갖는 방식이에요)."""


def _rooms() -> str:
    return """🔊 통화방은 `/방만들기` 하나로 만들어요.

· 랭크방 · 폐관수련방 · 프리미어방 · 내전방을 고를 수 있어요.
· 만든 사람이 방장이에요. `/방장넘기기`로 넘길 수 있어요.
· `/방초대` · `/방신청` · `/방닫기`가 같이 있어요.
· 들어올 때 자동으로 음소거되는 방도 있어요(놀라지 마세요)."""


def _myshop() -> str:
    return """🛒 `/오상`은 **내 발로란트 개인 상점**을 보여줘요.

· 처음 쓸 때 라이엇 로그인이 필요해요. 봇이 알려주는 절차대로 **쿠키**를 넣어요.
· 계정은 3개까지 등록할 수 있어요.
· 야시장 · VP 잔액 · 위시리스트 알림도 같이 돼요.
· 로그인 창 자체가 안 뜨면 그건 봇이 아니라 브라우저 쪽 문제일 수 있어요.
· 쿠키를 지우려면 `/오상쿠키삭제`예요.
· 오늘 서버 전체가 공통으로 보는 번들은 `/오늘의번들`이에요(로그인 필요 없어요)."""


def _record() -> str:
    return """🎯 `/전적`으로 발로란트 전적을 봐요.

· 처음엔 라이엇 아이디(닉네임#태그)를 넣어 등록해요. 한 번 등록하면 다음부터는 그냥 `/전적`이에요.
· **미션 자동 판정도 이 등록을 써요.** 등록이 안 되어 있으면 발로 미션이 자동으로 안 깨져요.
· 등록을 지우려면 `/계정삭제`예요.
· 티어 역할은 자동으로 붙어요.
· 🎯 맨 아래 **한 줄 평**은 봇이 KD·승률·헤드샷율·자주 쓴 요원을 읽고 써주는 조언이에요.
  최근 3경기 미만이면 표본이 적어서 안 나와요. 새 경기를 하면 새로 써줘요."""


def _karaoke() -> str:
    return """🎤 노래방은 음성채널에 들어간 뒤에 써요.

· `/재생 <유튜브 주소 또는 검색어>` — 틀어요.
· `/대기열` · `/스킵` · `/일시정지` · `/재개` · `/정지` · `/음량` · `/반복`
· `/대기열섞기` · `/대기열삭제` · `/비우기`도 있어요.
· 지정된 노래방 음성채널에서만 돼요."""


def _profile() -> str:
    return f"""🪪 `/프로필`은 내 정보를 그림 카드 한 장으로 보여줘요.

· 출석·코인·업적·내전 전적이 다 올라가요.
· 업적은 {ACHIEVEMENT_TOTAL}개가 있어요(`/업적`).
· 🎯 `/업적` 맨 위에 **조금만 더 하면 깨는 업적**이 떠요. 뭘 해야 할지 모를 때 거기부터 보세요.
· 카드 모양은 🎨 **테마**를 사면 바꿀 수 있어요(`/악귀상점` · 영구)."""


def _notify() -> str:
    # 🚨 종류를 여기에 적지 말 것 — 알림이 새로 생길 때마다 이 안내문이 썩어요.
    kinds = "\n".join(
        f"  {info['emoji']} {info['title']}" for info in NOTIFY_KINDS.values()
    )
    return f"""🔔 `/알림설정`으로 봇이 보내는 알림을 하나씩 끄고 켜요.

지금 조절할 수 있는 건 **{len(NOTIFY_KINDS)}가지**예요.
{kinds}

· 기본은 다 켜져 있어요. 시끄러운 것만 골라서 꺼요.
· 끈 건 계속 꺼진 채로 있어요. 나중에 새 알림이 생기면 그건 켜진 상태로 시작해요."""


def _adult() -> str:
    return """🔞 `/성인인증`은 생년월일을 넣으면 봇이 먼저 확인하고, 그다음 매니저가 승인해요.

· 승인되면 성인 역할이 붙어요.
· 바로 안 될 수 있어요(사람이 한 번 보는 단계가 있어서요)."""


def _voice_level_topic() -> str:
    tiers = "\n".join(
        f"· **Lv.{lv}** 이상 → {name}" for lv, name in reversed(VOICE_ROLE_TIERS)
    )
    return f"""🎙️ 통화방에 머문 시간이 쌓여서 **레벨**이 올라가요.

· `/음성레벨` — 내 레벨과 누적 시간을 봐요 (`유저:@이름`으로 남의 것도 볼 수 있어요)
· `/음성랭킹` — 이번 주 / 누적 순위를 봐요
· 혼자 있는 시간은 **안 세요.** 2명 이상일 때만 쌓여요.
· 5분마다 정산돼요. 통화를 길게 켜놔도 중간중간 반영돼요.
· 첫 레벨은 **{VOICE_FIRST_LEVEL_MINUTES}분**이면 올라가요.

받을 수 있는 역할이에요.
{tiers}

⚠️ **코인은 안 줘요.** 레벨은 명예 지표라서, 코인은 출석·미션·낚시로 모으는 거예요."""


def _event_topic() -> str:
    return f"""📅 `/일정`으로 약속을 미리 잡아요. ("토요일 9시 내전" 같은 것)

· `/일정 제목:내전 언제:토요일 21시` — 이렇게 적으면 돼요
  └ `내일 9시` · `10/25 21:00` · `다음주 토요일 20시` 다 알아들어요
  └ `인원`을 적으면 정원이 생겨요(비우면 제한 없음)
· **✅ 간다 / ❌ 못 감** 버튼으로 참가를 알려요. 마음이 바뀌면 다시 눌러 취소해요.
· 시작 **{EVENT_REMIND_MINUTES}분 전**에 참가한 사람들을 멘션해서 알려줘요.
· 🚫 취소는 **만든 사람만** 할 수 있어요.
· `/일정목록` — 앞으로 잡힌 일정을 모아 봐요."""


def _suggestion_topic() -> str:
    return """💡 `/건의`로 봇이나 서버에 바라는 점을 올려요.

· 올리면 다른 사람이 **👍 👎 투표**할 수 있어요.
· 운영진이 **✅ 채택 / 🎉 반영 완료 / 🙏 보류** 중 하나를 붙여줘요.
· `/건의목록` — 지금까지 올라온 건의를 모아 봐요.
· 무슨 말이든 괜찮아요. 작은 불편도 적어주시면 고칠 거리가 돼요."""


def _match_feed_topic() -> str:
    return """🔔 발로란트 경기가 끝나면 **전적 카드가 자동으로 올라와요.**

· `/전적`을 치지 않아도 돼요. 봇이 알아서 올려줘요.
· 맵 · 스코어 · KDA · ACS · ADR · 요원이 같이 나와요.
· 🚨 **공개가 싫으면** `/알림설정`에서 **경기 결과 자동 공개**를 꺼주세요.
· `/전적`에 계정이 등록돼 있어야 올라와요."""


def _mvp_topic() -> str:
    # ⚠️ 지연 import예요. `utils`가 `cogs`를 **모듈 최상단에서** 참조하면 순환 import가 나요
    #    (cogs 쪽이 utils를 먼저 부르거든요). 숫자를 손으로 적지 않으려고 이렇게 끌어와요.
    from cogs.weekly_mvp import MIN_MATCHES

    return f"""🏅 매주 월요일, 지난주 **악귀력 1위**를 발표하고 역할을 드려요.

· 그 주에 `/전적`을 돌린 사람 중에서 뽑아요.
· 최소 **{MIN_MATCHES}경기**는 해야 후보가 돼요(한 판 운으로 뽑히지 않게요).
· 역할은 다음 주 MVP가 나올 때까지 유지돼요.
· 순위는 `/주간랭킹`에서 미리 볼 수 있어요."""


def _ask_bot() -> str:
    """🚨 매니저가 **자기 자신**을 설명하는 주제예요.

    없으면 "봇한테 어떻게 물어봐?" 같은 질문이 전부 Claude로 넘어가요(돈이 들고,
    정작 제일 자주 나올 질문이에요)."""
    return """❓ 봇 쓰는 법이 궁금하면 **그냥 한국어로 물어보세요.**

· ❓봇에게-질문 채널에 **명령어 없이 그냥 적으면** 돼요.
· 다른 채널에서는 `/도움` 을 쓰면 똑같이 답해줘요.
· 명령어 이름을 몰라도 돼요 — "코인 어떻게 모아?"처럼 하고 싶은 걸 적으면 알려줘요.
· 못 알아들으면 비슷한 주제를 보여줘요. 그래도 모르겠으면 매니저에게 물어봐 주세요."""


def _birthday() -> str:
    return """🎂 생일은 `/생일등록`으로 넣어요.

· 그날이 오면 봇이 축하해줘요.
· `/생일확인` · `/다가오는생일` · `/생일삭제`가 같이 있어요."""


def _coin_basic() -> str:
    return f"""🪙 악귀코인은 서버 안에서만 쓰는 돈이에요.

· 내 잔액은 `/코인`
· 남한테 주려면 `/코인보내기`
· 버는 법은 출석 · 미션 · 낚시 · 업적 네 가지예요(자세히는 "코인 어떻게 모아?"라고 물어보세요).
· 하루에 그냥 들어오는 건 출석 {COIN_PER_ATTENDANCE}코인 + 미션 최대 {DAILY_MISSION_COUNT}코인이에요."""


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="coin_earn",
        title="🪙 악귀코인 모으는 법",
        strong=(
            "모아", "모으", "모을", "모지", "모나", "모음",
            "버는", "벌어", "벌고", "벌려", "벌 수", "벌면", "버나", "버냐",
            "얻어", "얻는", "얻나", "획득", "수입", "벌이", "부자", "개같이 벌",
        ),
        weak=("코인", "돈", "어떻게", "많이"),
        body=_coin_earn,
        commands=("/출석", "/미션", "/낚시", "/업적"),
    ),
    Topic(
        key="coin_spend",
        title="🛍️ 악귀코인 쓰는 곳",
        strong=(
            "어디에 써", "어디 써", "어디에 쓰", "어디 쓰", "쓰는 곳", "쓸 곳", "쓸데",
            "쓸 데", "소비", "악귀상점", "살 수", "뭐 살", "뭐 사", "사는 법", "구매",
        ),
        weak=("코인", "상점", "써", "쓰", "사"),
        body=_coin_spend,
        commands=("/악귀상점", "/카드뽑기", "/도박", "/칭호구매"),
    ),
    Topic(
        key="coin_basic",
        title="🪙 악귀코인이 뭔가요",
        strong=("악귀코인", "코인이 뭐", "코인 확인", "잔액", "코인 보내", "송금", "코인 줘"),
        weak=("코인", "돈"),
        body=_coin_basic,
        commands=("/코인", "/코인보내기"),
    ),
    Topic(
        key="attendance",
        title="📅 출석",
        # 🚨 "끊"만 strong으로 넣으면 "노래가 끊겨요"(🎤)를 가져가요. 붙은 말로만 잡아요.
        strong=("출석", "개근", "보호권", "스트릭", "연속",
                "출석끊", "연속끊", "출석알림"),
        weak=("매일", "하루", "빠지", "끊기", "끊겨"),
        body=_attendance,
        commands=("/출석", "/출석순위"),
    ),
    Topic(
        key="mission",
        title="🎯 미션",
        strong=("미션", "리롤", "퀘스트", "일일 숙제"),
        weak=("자동", "판정", "안 깨", "안깨", "하루"),
        body=_mission,
        commands=("/미션", "/악귀상점"),
    ),
    Topic(
        key="fishing",
        title="🎣 낚시",
        strong=(
            # 🚨 "낚시대"를 넣지 말 것 — **"낚시대회"에 걸려요**(`"vp"`가 `"mvp"`에 걸렸던 것과
            #    같은 사고예요). "낚시" 하나로 이미 잡히니 없어도 돼요.
            "낚시", "물고기", "어항", "낚아", "낚는", "입질", "챔질", "어종",
        ),
        weak=("찌", "치수", "판매", "팔아", "팔기", "등급"),
        body=_fishing,
        commands=("/낚시", "/어항", "/물고기판매", "/낚시확률", "/낚시왕"),
    ),
    Topic(
        key="fishing_contest",
        title="🎣 주간 낚시 대회",
        strong=(
            "낚시대회", "대회", "최대어", "주간낚시", "이주의낚시왕",
        ),
        weak=("최다", "수익", "주간", "우승", "월요일"),
        body=_fishing_contest,
        commands=("/낚시대회",),
    ),
    Topic(
        key="cards",
        title="🎴 악귀카드",
        strong=(
            "악귀카드", "카드", "뽑기", "가챠", "가차", "천장", "도감", "레전드", "에픽",
        ),
        weak=("중복", "컬렉션", "수집", "확률", "거래", "모으"),
        body=_cards,
        commands=("/카드뽑기", "/카드확률", "/도감", "/카드거래", "/거래함"),
    ),
    Topic(
        key="casino",
        title="🎰 도박",
        strong=(
            "도박", "슬롯", "하이로우", "블랙잭", "카지노", "겜블", "연장권", "한도늘리기",
        ),
        weak=("한도", "베팅", "걸", "배팅"),
        body=_casino,
        commands=("/도박",),
    ),
    Topic(
        key="title",
        title="🏷️ 칭호",
        strong=("칭호", "역할 이름", "닉네임 색", "역할 색", "내 색깔"),
        weak=("역할", "색", "기간"),
        body=_title,
        commands=("/칭호구매", "/칭호", "/칭호해제"),
    ),
    Topic(
        key="scrim",
        title="🤝 내전",
        strong=(
            "내전", "내전 전적", "팀짜기", "팀 짜", "팀 나누", "승리 보고", "베팅개설",
            "주간랭킹", "내전시즌", "kda",
        ),
        weak=("베팅", "전적", "밸런스", "팀", "맵"),
        body=_scrim,
        commands=("/내전모집", "/팀짜기", "/내전전적", "/주간랭킹", "/베팅개설"),
    ),
    Topic(
        key="rooms",
        title="🔊 통화방",
        strong=(
            "방만들기", "통화방", "방 만들", "방장", "랭크방", "폐관수련", "프리미어방",
            "방 파", "방 열", "음성 채널 만",
        ),
        weak=("방", "초대", "신청", "음성"),
        body=_rooms,
        commands=("/방만들기", "/방장넘기기", "/방초대", "/방닫기"),
    ),
    Topic(
        key="myshop",
        title="🛒 /오상 (개인 상점)",
        strong=(
            "오상", "개인 상점", "내 상점", "오늘의 상점", "쿠키", "라이엇 로그인",
            "야시장", "위시리스트", "번들",
            # 🚨 그냥 "vp"로 두면 **"mvp"가 걸려요**(2026-10-18에 실제로 /주간mvp 질문이
            #    /오상으로 갔어요). 앞뒤를 붙여 구체적으로 둬요.
            "vp계산", "vp 계산", "vp 충전", "vp 가격", "vp 얼마", "vp가",
        ),
        weak=("상점", "로그인", "계정", "스킨"),
        body=_myshop,
        commands=("/오상", "/오늘의번들", "/오상쿠키삭제", "/vp계산"),
    ),
    Topic(
        key="record",
        title="🎯 전적 조회",
        strong=("전적", "라이엇 아이디", "계정 등록", "계정삭제", "티어 역할"),
        weak=("티어", "랭크", "등록", "계정", "닉네임"),
        body=_record,
        commands=("/전적", "/계정삭제"),
    ),
    Topic(
        key="skin",
        title="🔎 스킨 검색",
        strong=("스킨검색", "스킨 검색", "스킨 정보", "스킨 찾", "스킨 가격", "스킨이 얼마"),
        weak=("스킨", "검색", "가격"),
        body=lambda: """🔎 `/스킨검색 <스킨 이름>`으로 발로란트 스킨 정보를 봐요.

· 가격·등급·컬렉션을 보여줘요.
· **내 상점에 지금 떴는지**는 `/오상`, 서버 공통 번들은 `/오늘의번들`이에요.
· VP를 얼마 충전해야 하는지는 `/vp계산`이 계산해줘요.""",
        commands=("/스킨검색", "/vp계산"),
    ),
    Topic(
        key="karaoke",
        title="🎤 노래방",
        strong=("노래방", "노래", "음악", "유튜브", "대기열", "틀어", "틀고", "재생"),
        weak=("스킵", "음량", "볼륨", "플레이리스트", "곡"),
        body=_karaoke,
        commands=("/재생", "/대기열", "/스킵", "/음량"),
    ),
    Topic(
        key="profile",
        title="🪪 프로필 · 업적",
        strong=("프로필", "업적", "카드 테마", "프로필 카드"),
        weak=("테마", "카드", "내 정보"),
        body=_profile,
        commands=("/프로필", "/업적"),
    ),
    Topic(
        key="notify",
        title="🔔 알림 설정",
        strong=("알림", "알림설정", "dm", "디엠", "시끄러"),
        weak=("꺼", "끄", "켜", "안 받"),
        body=_notify,
        commands=("/알림설정",),
    ),
    Topic(
        key="adult",
        title="🔞 성인 인증",
        strong=("성인", "성인인증", "19금", "미성년"),
        weak=("나이", "인증", "생년월일"),
        body=_adult,
        commands=("/성인인증",),
    ),
    Topic(
        key="voice_level",
        title="🎙️ 음성 활동 레벨",
        strong=("음성레벨", "음성랭킹", "통화 레벨", "음성 레벨", "통화방 레벨",
                "수다쟁이", "말동무", "터줏대감",
                # 악귀봇에 '레벨'이라는 개념은 이것뿐이라 단독으로 둬도 안전해요.
                "레벨"),
        weak=("레벨", "통화", "음성", "랭킹", "역할"),
        body=_voice_level_topic,
        commands=("/음성레벨", "/음성랭킹"),
    ),
    Topic(
        key="event",
        title="📅 일정 예약",
        strong=("일정", "약속", "약속 잡", "일정목록", "예약", "모임",
                "언제 모여", "몇 시에 모여", "미리 잡"),
        weak=("참가", "리마인더", "알림", "시간"),
        body=_event_topic,
        commands=("/일정", "/일정목록"),
    ),
    Topic(
        key="suggestion",
        title="💡 건의함",
        strong=("건의", "건의목록", "제안", "요청하고 싶", "추천하고 싶", "바라는"),
        weak=("투표", "의견", "불편"),
        body=_suggestion_topic,
        commands=("/건의", "/건의목록"),
    ),
    Topic(
        key="match_feed",
        title="🔔 경기 결과 자동 공개",
        strong=("자동으로 올라", "전적이 올라", "경기 결과", "자동 공개", "경기 알림",
                "전적 공개"),
        weak=("자동", "공개", "알림", "전적"),
        body=_match_feed_topic,
        commands=("/알림설정", "/전적"),
    ),
    Topic(
        key="weekly_mvp",
        title="🏅 주간 MVP",
        strong=("mvp", "주간mvp", "이주의", "주간 1위"),
        weak=("주간", "1위", "역할"),
        body=_mvp_topic,
        commands=("/주간랭킹", "/전적"),
    ),
    Topic(
        key="ask_bot",
        title="❓ 봇에게 물어보기",
        strong=(
            "도움말", "/도움", "봇에게 물어", "봇한테 물어", "어떻게 물어",
            "질문하는", "질문은 어디", "매니저한테",
        ),
        weak=("도움", "질문", "물어", "사용법", "쓰는 법"),
        body=_ask_bot,
        commands=("/도움",),
    ),
    Topic(
        key="birthday",
        title="🎂 생일",
        strong=("생일",),
        weak=("축하", "등록"),
        body=_birthday,
        commands=("/생일등록", "/생일확인", "/다가오는생일"),
    ),
)

TOPIC_BY_KEY: dict[str, Topic] = {t.key: t for t in TOPICS}


# ------------------------------------------------------------------
# 규칙 검색
# ------------------------------------------------------------------
# 🚨 점수 기준을 바꿀 땐 `scripts/test_faq_knowledge.py`를 같이 돌려주세요.
#    기준이 너무 낮으면 엉뚱한 주제를 자신 있게 답해버리고(그게 "모르겠다"보다 나빠요),
#    너무 높으면 전부 Claude로 넘어가서 돈이 들어요. 테스트가 양쪽을 다 봐요.
COMMAND_SCORE = 4.0   # 명령어 이름을 직접 말함 = 사실상 확정
STRONG_SCORE = 3.0    # 고유어 하나 = 답해도 되는 수준
WEAK_SCORE = 0.8      # 보조어는 모여야 의미가 생겨요

HIT_SCORE = 3.0        # 이 점수 이상이면 "규칙으로 답할 수 있다"
AMBIGUOUS_GAP = 1.0    # 1위와 2위 차이가 이보다 작으면 애매하다고 보고 Claude로 넘겨요


def _normalize(text: str) -> str:
    """띄어쓰기를 없애고 소문자로. "코인 모으는" / "코인모으는"을 같게 보려고요."""
    return "".join(text.lower().split())


def score_topics(question: str) -> list[tuple[float, Topic]]:
    """질문과 주제들의 관련도. 높은 것부터 돌려줘요."""
    raw = question.lower()
    squeezed = _normalize(question)
    scored: list[tuple[float, Topic]] = []

    for topic in TOPICS:
        score = 0.0

        for command in topic.commands:
            if command.lower() in raw or _normalize(command) in squeezed:
                score += COMMAND_SCORE

        # strong은 **맞은 개수만큼** 쌓아요("낚시"+"낚시대"처럼 겹쳐 맞으면 더 또렷해요).
        for keyword in topic.strong:
            if _normalize(keyword) in squeezed:
                score += STRONG_SCORE

        for keyword in topic.weak:
            if _normalize(keyword) in squeezed:
                score += WEAK_SCORE

        if score > 0:
            scored.append((score, topic))

    scored.sort(key=lambda pair: (-pair[0], pair[1].key))
    return scored


def search(question: str) -> tuple[Topic | None, list[Topic]]:
    """(자신 있게 답할 주제, 참고로 보여줄 주제들).

    첫 값이 None이면 규칙으로는 모르겠다는 뜻이라 Claude로 넘겨요. 그때도 두 번째 값으로
    "이런 거 찾으셨나요"는 보여줄 수 있어요(Claude를 못 쓰는 상황의 보험이에요)."""
    scored = score_topics(question)
    if not scored:
        return None, []

    top_score, top_topic = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    confident = top_score >= HIT_SCORE and (top_score - runner_up) >= AMBIGUOUS_GAP
    related = [topic for _, topic in scored[:3]]
    return (top_topic if confident else None), related


# ------------------------------------------------------------------
# 명령어 카탈로그 — bot.tree에서 그대로 긁어요
# ------------------------------------------------------------------
def _walk(commands) -> list[discord.app_commands.Command]:
    """그룹 명령어(`/도박 슬롯`처럼)도 펼쳐서 모아요."""
    found: list[discord.app_commands.Command] = []
    for command in commands:
        if isinstance(command, discord.app_commands.Group):
            found.extend(_walk(command.commands))
        elif isinstance(command, discord.app_commands.Command):
            found.append(command)
    return found


def build_command_catalog(bot: discord.Client) -> list[dict]:
    """등록된 슬래시 명령어를 이름·설명·파라미터로 정리해요.

    ⚠️ `bot.tree`는 **동기화된 뒤**에 채워져요. 기동 직후 호출하면 빈 목록이 나올 수 있어서
    매니저는 쓸 때마다 다시 불러요(캐시해두면 빈 목록을 계속 들고 있게 돼요)."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return []

    catalog: list[dict] = []
    for command in _walk(tree.get_commands()):
        params = [
            {
                "name": p.display_name or p.name,
                "required": p.required,
                "description": p.description or "",
            }
            for p in command.parameters
        ]
        catalog.append(
            {
                "name": command.qualified_name,
                "description": command.description or "",
                "params": params,
            }
        )
    catalog.sort(key=lambda item: item["name"])
    return catalog


def _catalog_text(catalog: list[dict]) -> str:
    lines = []
    for item in catalog:
        required = [p["name"] for p in item["params"] if p["required"]]
        optional = [p["name"] for p in item["params"] if not p["required"]]
        bits = f"/{item['name']}"
        if required:
            bits += " " + " ".join(f"<{name}>" for name in required)
        if optional:
            bits += " " + " ".join(f"[{name}]" for name in optional)
        lines.append(f"- {bits} — {item['description']}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Claude용 시스템 프롬프트
# ------------------------------------------------------------------
GUIDE_HEADER = """너는 디스코드 서버 "겜악귀들의 천국"의 봇 안내 도우미야.
서버원이 봇 쓰는 법을 물으면 아래 자료만 보고 답해.

답할 때 지킬 것:
- 한국어 존댓말로, 3~6줄 안에 끝내. 명령어는 `/출석`처럼 백틱으로 감싸.
- 자료에 없는 건 모른다고 말하고, 매니저에게 물어보라고 안내해. 절대 지어내지 마.
- 숫자(가격·한도·확률)는 자료에 적힌 값만 써. 기억으로 추측하지 마.
- 질문이 봇과 무관하면(게임 공략, 잡담 등) 그건 내가 답할 수 있는 범위가 아니라고 짧게 말해.
- 사람을 비난하거나 혼내지 마. 모르는 건 당연하다는 태도로 알려줘."""


def build_system_prompt(bot: discord.Client) -> str:
    """Claude에게 먹일 지식 베이스 전체. 규칙 매칭과 **같은 사실**을 보게 해요."""
    sections = [GUIDE_HEADER, "", "# 주제별 안내", ""]
    for topic in TOPICS:
        sections.append(f"## {topic.title}")
        sections.append(topic.text())
        sections.append("")

    catalog = build_command_catalog(bot)
    if catalog:
        sections.append("# 전체 슬래시 명령어 목록 (<> 필수 · [] 선택)")
        sections.append(_catalog_text(catalog))
        sections.append("")

    sections.append(
        "# 참고\n"
        "- 명령어가 특정 채널에서만 되는 경우가 있어요. "
        "\"이 명령어는 #채널에서만 쓸 수 있어요\"가 나오면 그 채널로 가서 다시 해보라고 안내해.\n"
        "- 악귀포켓몬은 2026-09-30에 종료됐어. 포켓몬 관련 기능은 이제 없어. "
        "다만 악귀코인·출석·미션·칭호·베팅은 그대로 살아있어.\n"
        "- 🚨 **아래 명령어는 서버 소유자만 쓸 수 있어.** 일반 서버원에게 써보라고 안내하지 마:\n"
        "  `/채널설정` · `/내전시즌` · `/서버리포트` · `/안내게시` · `/규칙설정` · `/설명설정`\n"
        "- 낚시는 **한 번에 한 판만** 돼. 던지는 중에 또 치면 거절되고, 그때 낚시대는 안 줄어."
    )
    return "\n".join(sections)
