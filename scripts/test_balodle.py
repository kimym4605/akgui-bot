# -*- coding: utf-8 -*-
"""🧩 발로들 검증.

    python scripts/test_balodle.py            # 전부 (DB 흐름 포함)
    python scripts/test_balodle.py --no-db    # 규칙·화면만 (DB 없이)

⚠️ MONGODB_DB_NAME을 `agwi_balodle_test`로 덮어써서 **프로덕션 DB는 건드리지 않아요.**
   같은 Atlas 클러스터를 쓰지만 DB가 달라서 섞이지 않고, 끝나면 만든 컬렉션을 지워요.
   (맨 위 assert가 테스트 DB가 맞는지 한 번 더 확인해요.)

여기서 확인하는 것 (설계서 "작업 목록 > 개발" 12번):
  [1] 재료 정합성 (요원 30명 속성·스킬 아이콘·맵 그림·이름 겹침)
  [2] 이름 인식 (한글·영문·별칭·`KAY/O`·오타 제안)
  [3] 속성 비교 (같은 대륙 🟨 · 알 수 없음끼리 🟩 · 괄호 붙은 출신 · 순서 ±2 · 연도 ±1 · ⬆⬇)
  [4] 보상 표
  [5] 연속 (어제·건너뜀·같은 날 두 번)
  [6] 칭호 (7·30 경계)
  [7] 확대 단계 크기
  [8] 채점·결과 칸·채널 결과 메시지·힌트·분포 막대
  [9] 화면 글 (디자인 문구)
 [10] 영속 뷰 규칙 3가지 + `[정답 입력]`은 ack 없이 바로 입력창
 [11] 지표 스크립트 계산
 [12] 🚨 DB: 같은 답 두 번 무시 · 동시에 두 번 보내도 한 번만 · 연속·칭호(끊겨도 유지)
 [13] 🚨 흐름: 코인이 **한 번만** 나가고 채널 결과 메시지가 **한 사람에 하나**
"""
import ast
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
# ★ 프로덕션 DB 보호: 반드시 .env 로드 '뒤에' 덮어써요.
os.environ["MONGODB_DB_NAME"] = "agwi_balodle_test"

USE_DB = "--no-db" not in sys.argv

import discord  # noqa: E402

import cogs.balodle as balodle  # noqa: E402
from utils import balodle_art, balodle_data, balodle_logic as L, balodle_store  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

assert _db.name == "agwi_balodle_test", f"테스트 DB가 아니에요: {_db.name}"

AGENTS, ABILITIES, SETTINGS = balodle_data.AGENTS, balodle_data.ABILITIES, balodle_data.SETTINGS
ORDER = {**SETTINGS, "release_mode": "order", "order_close": 2}
YEAR = {**SETTINGS, "release_mode": "year", "year_close": 1}
KST = timezone(timedelta(hours=9))

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + str(detail)) if detail else ''}")
    if not ok:
        failures.append(label)


def cell(guess, answer, column, settings=ORDER):
    """(값, 표시) — column: role·origin·release·gender"""
    return L.compare_agent(guess, answer, AGENTS, settings)[L.AGENT_COLUMNS.index(column)]


# ==================================================================
print("\n[1] 재료 정합성")
check("요원 30명", len(AGENTS) == 30, len(AGENTS))
check("요원 속성이 전부 채워져 정답 후보가 30명", len(balodle_data.agent_candidates()) == 30,
      [k for k, a in AGENTS.items() if not L.is_complete(a)])
check("스킬은 요원당 4개(패시브 제외) = 120개", len(ABILITIES) == 120, len(ABILITIES))
check("스킬 아이콘 파일이 전부 있다", len(balodle_data.ability_candidates()) == len(ABILITIES))
check("스킬 키는 Q·E·C·X뿐", {a["slot"] for a in ABILITIES.values()} == set("QECX"))
check("맵 그림이 5대5 맵 13개 전부 있다",
      balodle_data.map_candidates() == balodle_data.map_choices(), balodle_data.map_candidates())
check("대륙 값은 정해진 여섯 가지뿐",
      {a["continent"] for a in AGENTS.values()}
      <= {"아시아", "유럽", "아메리카", "아프리카", "오세아니아", L.UNKNOWN})
check("성별 값은 남·여·논바이너리뿐", {a["gender"] for a in AGENTS.values()} == {"남", "여", "논바이너리"})
check("출신 없는 요원은 오멘·케이/오·바이스 3명",
      {k for k, a in AGENTS.items() if a["origin"] == L.UNKNOWN} == {"omen", "kayo", "vyse"})
# 이름이 겹치면 한 요원이 다른 요원 이름으로 인식돼요(조용히 틀려요).
seen, clash = {}, []
for key, agent in AGENTS.items():
    for name in [key, agent["ko"], agent["en"], *agent["aliases"]]:
        norm = L.normalize(name)
        if seen.setdefault(norm, key) != key:
            clash.append((name, key, seen[norm]))
check("요원 이름·별칭이 서로 겹치지 않는다", not clash, clash)
ranks = L.release_rank(AGENTS)
beta = [k for k, a in AGENTS.items() if a["released"] == "2020-04-07"]
check("비공개 베타 10명은 모두 출시 순서 1번", len(beta) == 10 and {ranks[k] for k in beta} == {1})
check("레이나 2번 … 허시 21번", ranks["reyna"] == 2 and ranks["hush"] == 21, (ranks["reyna"], ranks["hush"]))
check("설정에 필요한 값이 다 있다",
      all(k in SETTINGS for k in balodle_data.DEFAULT_SETTINGS))
check("칭호 이름이 업적 이름과 같다 (프로필과 업적이 같은 이름을 써요)",
      __import__("utils.achievement_data", fromlist=["BY_KEY"]).BY_KEY["balodle_7"]["name"] == SETTINGS["titles"]["7"]
      and __import__("utils.achievement_data", fromlist=["BY_KEY"]).BY_KEY["balodle_30"]["name"] == SETTINGS["titles"]["30"])
_ach = __import__("utils.achievement_data", fromlist=["BY_KEY"]).BY_KEY
check("🚨 발로들 업적 2개는 보상 0코인", _ach["balodle_7"]["reward"] == 0 and _ach["balodle_30"]["reward"] == 0)
check("다른 업적 보상은 그대로 (등급 보상)", _ach["attend_1"]["reward"] == 1 and _ach["coin_500"]["reward"] == 5)

# ==================================================================
print("\n[2] 이름 인식")
for text, want in [("제트", "jett"), ("jett", "jett"), ("JETT", "jett"), (" 제 트 ", "jett"),
                   ("KAY/O", "kayo"), ("kayo", "kayo"), ("케이/오", "kayo"), ("케이오", "kayo"),
                   ("챔버", "chamber"), ("체임버", "chamber"), ("브림", "brimstone"),
                   ("Brimstone", "brimstone"), ("데드락", "deadlock")]:
    got, _ = L.resolve_agent(text, AGENTS, balodle_data.NAME_INDEX)
    check(f"`{text}` → {want}", got == want, got)
got, suggestion = L.resolve_agent("재트", AGENTS, balodle_data.NAME_INDEX)
check("오타 `재트`는 요원이 아니고 제트를 제안한다", got is None and suggestion == "jett", (got, suggestion))
got, suggestion = L.resolve_agent("jet", AGENTS, balodle_data.NAME_INDEX)
check("오타 `jet`는 제트를 제안한다", got is None and suggestion == "jett", (got, suggestion))
got, suggestion = L.resolve_agent("ㅋㅋㅋㅋㅋ", AGENTS, balodle_data.NAME_INDEX)
check("전혀 다른 글자는 제안이 없다", got is None and suggestion is None, (got, suggestion))
check("빈 입력은 요원도 제안도 없다", L.resolve_agent("  ", AGENTS) == (None, None))

# ==================================================================
print("\n[3] 요원 속성 비교")
check("역할군 같으면 🟩", cell("jett", "raze", "role") == ("타격대", L.GREEN))
check("역할군 다르면 ⬛ (🟨 없음)", cell("jett", "sova", "role") == ("타격대", L.BLACK))
check("같은 나라 🟩 (세이지·아이소 = 중국)", cell("sage", "iso", "origin")[1] == L.GREEN)
check("나라는 다르고 대륙이 같으면 🟨 (소바 러시아 · 피닉스 영국 = 유럽)",
      cell("sova", "phoenix", "origin") == ("러시아", L.YELLOW))
check("대륙도 다르면 ⬛ (제트 아시아 · 피닉스 유럽)", cell("jett", "phoenix", "origin")[1] == L.BLACK)
check("괄호 붙은 출신은 괄호 앞 나라로 비교 (허시 중국(광둥) = 세이지 중국)",
      cell("hush", "sage", "origin") == ("중국(광둥)", L.GREEN))
check("괄호 붙은 출신 (클로브 영국(스코틀랜드) = 피닉스 영국)",
      cell("phoenix", "clove", "origin")[1] == L.GREEN and cell("clove", "phoenix", "origin")[0] == "영국(스코틀랜드)")
check("알 수 없음끼리 🟩 (오멘·케이/오)", cell("omen", "kayo", "origin") == (L.UNKNOWN, L.GREEN))
check("알 수 없음 vs 나라 있음은 ⬛ (🟨 없음)",
      cell("omen", "jett", "origin")[1] == L.BLACK and cell("jett", "vyse", "origin")[1] == L.BLACK)
check("성별 같으면 🟩, 다르면 ⬛", cell("jett", "sage", "gender")[1] == L.GREEN
      and cell("jett", "sova", "gender")[1] == L.BLACK)
check("논바이너리는 남·여와 ⬛", cell("clove", "jett", "gender") == ("논바이너리", L.BLACK))
# 출시 순서: 베타 1 · 레이나 2 · 킬조이 3 · 스카이 4 · 요루 5 · 아스트라 6 · 케이/오 7
check("[순서] 같은 순서 🟩, 화살표 없음", cell("skye", "skye", "release") == ("4번째", L.GREEN))
check("[순서] 베타끼리는 같은 순서라 🟩", cell("jett", "sova", "release") == ("1번째", L.GREEN))
check("[순서] ±2는 🟨 + ⬆ (정답이 더 나중)", cell("reyna", "skye", "release") == ("2번째⬆", L.YELLOW))
check("[순서] ±3은 ⬛ + ⬆", cell("jett", "skye", "release") == ("1번째⬆", L.BLACK))
check("[순서] ±2는 🟨 + ⬇ (정답이 더 먼저)", cell("astra", "skye", "release") == ("6번째⬇", L.YELLOW))
check("[순서] ±3은 ⬛ + ⬇", cell("kayo", "skye", "release") == ("7번째⬇", L.BLACK))
check("[연도] 같은 해 🟩", cell("chamber", "yoru", "release", YEAR) == ("2021", L.GREEN))
check("[연도] ±1년 🟨 + ⬆", cell("jett", "yoru", "release", YEAR) == ("2020⬆", L.YELLOW))
check("[연도] ±1년 🟨 + ⬇", cell("neon", "yoru", "release", YEAR) == ("2022⬇", L.YELLOW))
check("[연도] ±2년 ⬛ + ⬇", cell("gekko", "yoru", "release", YEAR) == ("2023⬇", L.BLACK))
check("정답을 넣으면 네 칸 모두 🟩", L.agent_squares("jett", "jett", AGENTS, ORDER) == L.GREEN * 4)
check("결과 칸에는 화살표가 없다 (네 글자)",
      len(L.agent_squares("jett", "skye", AGENTS, ORDER)) == 4)

# ==================================================================
print("\n[4] 보상 표")
for attempts, want in [(1, 3), (2, 2), (3, 2), (4, 1), (5, 1), (6, 1)]:
    check(f"{attempts}번 만에 맞히면 {want}코인", L.reward(attempts, True, SETTINGS) == want)
check("실패는 0코인", L.reward(6, False, SETTINGS) == 0)
check("하루 최대 9코인 (세 문제를 한 번에)", sum(L.reward(1, True, SETTINGS) for _ in L.KINDS) == 9)
check("연속 보너스 코인은 없다", SETTINGS.get("streak_bonus") == 0)
check("기회는 문제당 6번", all(L.max_attempts(k, SETTINGS) == 6 for k in L.KINDS))

# ==================================================================
print("\n[5] 연속")
check("어제 맞혔으면 +1", L.next_streak("2026-11-23", "2026-11-24", 3) == (4, True))
check("하루 건너뛰면 1부터", L.next_streak("2026-11-22", "2026-11-24", 3) == (1, True))
check("같은 날 두 번째 정답은 안 오른다", L.next_streak("2026-11-24", "2026-11-24", 4) == (4, False))
check("처음이면 1", L.next_streak(None, "2026-11-24", 0) == (1, True))
check("더 뒤 날짜가 적혀 있으면 뒤로 가지 않는다", L.next_streak("2026-11-25", "2026-11-24", 5) == (5, False))
check("달이 바뀌어도 어제를 안다", L.next_streak("2026-11-30", "2026-12-01", 2) == (3, True))
check("지금 연속: 오늘 맞힘", L.live_streak(4, "2026-11-24", "2026-11-24") == 4)
check("지금 연속: 어제 맞히고 오늘 아직", L.live_streak(4, "2026-11-23", "2026-11-24") == 4)
check("지금 연속: 그저께가 마지막이면 끊겨서 0", L.live_streak(4, "2026-11-22", "2026-11-24") == 0)

# ==================================================================
print("\n[6] 칭호")
T = SETTINGS["titles"]
check("6→7일에 「발로들 단골」", L.new_titles(6, 7, T) == ["발로들 단골"])
check("7→8일에는 새 칭호 없음", L.new_titles(7, 8, T) == [])
check("29→30일에 「발로들 박사」", L.new_titles(29, 30, T) == ["발로들 박사"])
check("5→6일에는 없음", L.new_titles(5, 6, T) == [])
check("가장 높은 칭호", L.top_title(["발로들 단골", "발로들 박사"], T) == "발로들 박사"
      and L.top_title(["발로들 단골"], T) == "발로들 단골" and L.top_title([], T) is None)

# ==================================================================
print("\n[7] 맵 확대 단계")
SIZE = (1920, 1080)
steps = SETTINGS["zoom_steps"]
# 2026-11-24 8% → 15% 시작으로 완화("맵 그림이 잘 안 보여요" — 8%는 원본 154px를 4배 넘게 늘려 뭉개졌어요)
check("확대 단계는 6개 (15·21·29·40·55·75%)", steps == [0.15, 0.21, 0.29, 0.40, 0.55, 0.75], steps)
widths = []
for i, frac in enumerate(steps):
    l, t, r, b = L.zoom_box(i, (0.5, 0.5), SIZE, steps)
    widths.append(r - l)
    check(f"{i + 1}단계 너비 {round(frac * 100)}% · 가로세로비 유지",
          r - l == round(1920 * frac) and b - t == round(1080 * frac), (r - l, b - t))
check("단계가 갈수록 넓어진다", widths == sorted(widths) and len(set(widths)) == len(widths))
check("끝나면 그림 전체", L.zoom_box(len(steps), (0.1, 0.9), SIZE, steps) == (0, 0, 1920, 1080))
for focus in [(0.0, 0.0), (1.0, 1.0), (0.02, 0.97)]:
    boxes = [L.zoom_box(i, focus, SIZE, steps) for i in range(len(steps))]
    check(f"구석 {focus}을 봐도 그림 밖으로 안 나간다",
          all(l >= 0 and t >= 0 and r <= 1920 and b <= 1080 for l, t, r, b in boxes))
shots = balodle_art.map_steps("어센트", [0.5, 0.5])
check("맵 그림은 6단계 + 전체 = 7장", len(shots) == 7, len(shots))
check("장당 200KB를 넘지 않는다 (메모리에 들고 있어요)", max(len(s) for s in shots) < 200_000,
      max(len(s) for s in shots))
focus = balodle_art.pick_focus("어센트")
check("확대 중심점은 0~1 안", all(0 <= v <= 1 for v in focus), focus)
check("스킬 카드가 그려진다 (PNG)", balodle_art.ability_card("jett:E")[:4] == b"\x89PNG")

# ==================================================================
print("\n[8] 채점 · 결과 칸 · 채널 결과 메시지")
DAY = {"_id": "2026-11-24", "no": 12, "agent": "jett", "ability": "jett:E", "map": "어센트",
       "map_focus": [0.5, 0.5], "solved": {"agent": 5, "ability": 2, "map": 5},
       "finished": {"agent": 8, "ability": 5, "map": 7}}
check("같은 답은 이미 넣은 답으로 본다", L.is_duplicate(["sova", "jett"], "jett")
      and not L.is_duplicate(["sova"], "jett"))
check("요원 문제: 요원키가 같아야 정답", L.is_correct("agent", "jett", DAY, ABILITIES)
      and not L.is_correct("agent", "sova", DAY, ABILITIES))
check("스킬 문제: 답은 **그 스킬을 가진 요원**", L.is_correct("ability", "jett", DAY, ABILITIES)
      and not L.is_correct("ability", "sova", DAY, ABILITIES))
check("맵 문제: 맵 이름이 같아야 정답", L.is_correct("map", "어센트", DAY, ABILITIES)
      and not L.is_correct("map", "바인드", DAY, ABILITIES))
PLAY = {
    "agent": {"status": "solved", "guesses": ["sova", "reyna", "jett"], "rank": 5},
    "ability": {"status": "solved", "guesses": ["jett"], "rank": 2},
    "map": {"status": "failed", "guesses": ["바인드", "브리즈", "펄", "스플릿", "선셋", "어비스"]},
}
lines = L.share_lines(PLAY, DAY, "@악귀", 4, AGENTS, ORDER)
check("첫 줄: 번호 · 사람 · 연속", lines[0] == "🧩 발로들 #12 · @악귀 · 🔥4일", lines[0])
check("요원 줄: 시도/기회 — 오늘 N번째 · 정답률", lines[1] == "🕵️ 요원 3/6 — 오늘 5번째 · 정답률 62%", lines[1])
check("요원 결과 칸은 답마다 한 줄(네 칸), 마지막 줄은 🟩🟩🟩🟩",
      len(lines[2]) == 4 and lines[4] == L.GREEN * 4, lines[2:5])
check("스킬 줄: 한 번에 맞히면 🟩 한 칸", lines[5] == "✨ 스킬 1/6 — 오늘 2번째 · 정답률 40%" and lines[6] == L.GREEN,
      lines[5:7])
check("실패한 줄은 X/6이고 '오늘 N번째'가 없다", lines[7] == "🗺️ 맵 X/6 — 정답률 71%", lines[7])
check("실패한 맵 결과 칸은 ⬛ 여섯 칸", lines[8] == L.BLACK * 6, lines[8])
check("🚨 결과 메시지에 정답이 안 보인다",
      not any(w in "\n".join(lines) for w in ("제트", "jett", "순풍", "어센트")))
check("연속 1일이면 🔥를 안 붙인다", "🔥" not in L.share_lines(PLAY, DAY, "@악귀", 1, AGENTS, ORDER)[0])
check("아직 안 끝낸 종류는 결과 메시지에 없다",
      len(L.share_lines({"agent": PLAY["agent"], "map": {"status": "playing", "guesses": ["펄"]}},
                        DAY, "@악귀", 0, AGENTS, ORDER)) == 5)
ab, ag = ABILITIES["jett:E"], AGENTS["jett"]
check("스킬 힌트: 틀릴 때마다 하나씩 (0→0개, 2→2개, 9→5개)",
      [len(L.ability_hints(n, ab, ag)) for n in (0, 2, 9)] == [0, 2, 5])
check("스킬 힌트 순서: 키 → 역할군 → 출시 연도 → 첫 글자 → 이름",
      [v for _, v in L.ability_hints(5, ab, ag)] == ["E", "타격대", "2020", ab["ko"][0], ab["ko"]])
rows = L.dist_rows({"1": 1, "2": 3, "3": 4, "4": 1, "x": 3}, 6)
check("분포 막대: 가장 많은 줄이 🟩 8칸", rows[2] == "`3` " + L.GREEN * 8 + " 4", rows[2])
check("분포 막대: 1 이상이면 최소 1칸, 0이면 숫자만", rows[0].count(L.GREEN) >= 1 and rows[4] == "`5` 0", rows)
check("분포 막대: 실패 줄만 ⬛", rows[-1].startswith("`X` " + L.BLACK) and L.GREEN not in rows[-1], rows[-1])
check("퍼즐 번호: 시작일이 1번", L.puzzle_no("2026-11-24", "2026-11-24") == 1
      and L.puzzle_no("2026-12-05", "2026-11-24") == 12)
now = datetime(2026, 11, 24, 18, 48, tzinfo=KST)
check("다음 문제까지 남은 시간", L.left_text(now) == "5시간 12분", L.left_text(now))
check("0시 직전도 KST 날짜로 본다", L.today_iso(datetime(2026, 11, 24, 14, 59, 59, tzinfo=timezone.utc)) == "2026-11-24"
      and L.today_iso(datetime(2026, 11, 24, 15, 0, 0, tzinfo=timezone.utc)) == "2026-11-25")
check("알림 시각 글", L.time_label("09:00") == "아침 9시" and L.time_label("21:30") == "밤 9시 30분",
      (L.time_label("09:00"), L.time_label("21:30")))
import random as _random  # noqa: E402
rng = _random.Random(7)
check("최근에 나온 답은 피한다",
      all(L.pick_answer(["a", "b", "c"], {"a", "b"}, rng) == "c" for _ in range(20)))
check("피하고 나면 남는 게 없을 때는 전체에서 고른다",
      L.pick_answer(["a", "b"], {"a", "b"}, rng) in ("a", "b"))

# ==================================================================
print("\n[9] 화면 글 (디자인 문구)")
e = balodle.problem_embed("agent", DAY, {"status": "playing", "guesses": []})
check("요원 화면: 제목과 빈 화면 안내", e.title == "🕵️ 요원 맞히기 · 1/6" and "아직 넣은 답이 없어요" in e.description,
      e.title)
e = balodle.problem_embed("agent", DAY, {"status": "playing", "guesses": ["sova", "reyna"]})
check("요원 화면: 이모지 네 칸이 줄 맨 앞, 이름 — 값 · 값",
      "⬛⬛🟩⬛  **소바** — 척후대 · 러시아 · 1번째 · 남" in e.description, e.description)
check("요원 화면: 열 이름 줄과 범례", "`역할군 · 출신 · 출시 · 성별`" in e.description
      and "⬆ 정답이 더 나중" in e.description)
e = balodle.problem_embed("ability", DAY, {"status": "playing", "guesses": ["sova", "raze"]})
check("스킬 화면: 요원을 묻고, 힌트 2개와 넣은 답", "어느 요원의 스킬일까요" in e.description
      and "① 키: **E**" in e.description and "② 역할군: **타격대**" in e.description
      and "넣은 답: ~~소바~~ · ~~레이즈~~" in e.description and e.title == "✨ 스킬 맞히기 · 3/6", e.description)
check("🚨 스킬 화면에 정답 요원·스킬 이름이 안 보인다 (힌트 2개까지)",
      "제트" not in e.description and ab["ko"] not in e.description)
e = balodle.problem_embed("map", DAY, {"status": "playing", "guesses": ["바인드"]})
check("맵 화면: 확대 단계와 넣은 답", e.title == "🗺️ 맵 맞히기 · 확대 2/6"
      and "넣은 답: ~~바인드~~" in e.description, e.title)
out = {"coin": 2, "coin_failed": False, "rank": 5, "streak": 7, "bumped": True, "new_titles": ["발로들 단골"]}
e = balodle.done_embed("agent", DAY, PLAY["agent"], out)
check("맞힌 화면: 제목·횟수·코인·순서·연속·칭호", e.title == "🎉 정답! 제트"
      and "3번 만에 맞혔어요. **+2코인**" in e.description and "오늘 5번째로 맞혔어요." in e.description
      and "🔥 발로들 연속 **7일**" in e.description
      and "🧩 연속 7일! 칭호 **「발로들 단골」**을 얻었어요." in e.description
      and e.color.value == balodle.COLOR_SOLVED, e.description)
e = balodle.done_embed("ability", DAY, PLAY["ability"], {"coin": 3, "rank": 2, "bumped": False, "new_titles": []})
check("한 번에 맞힌 화면 + 스킬 정답 제목", e.title == f"🎉 정답! 제트 — {ab['ko']} (E)"
      and "**한 번에** 맞혔어요. **+3코인**" in e.description and "🔥" not in e.description, e.title)
e = balodle.done_embed("agent", DAY, {"status": "solved", "guesses": ["jett"]},
                       {"coin": 3, "new_titles": ["발로들 박사"], "bumped": True, "streak": 30})
check("30일 칭호 안내는 🎓 · '를'", "🎓 연속 30일! 칭호 **「발로들 박사」**를 얻었어요." in e.description, e.description)
e = balodle.done_embed("map", DAY, PLAY["map"], {"coin": 0})
check("실패 화면: 정답 공개 · 회색 띠", e.title == "😵 아쉬워요" and "정답은 **어센트**였어요." in e.description
      and e.color.value == balodle.COLOR_FAILED, e.description)
e = balodle.done_embed("map", {**DAY, "map": "펄"}, PLAY["map"], {"coin": 0})
check("받침 있는 정답은 '이었어요'", "정답은 **펄**이었어요." in e.description, e.description)
e = balodle.done_embed("ability", DAY, {"status": "failed", "guesses": ["sova"] * 6}, {"coin": 0})
check("스킬 실패 화면 문구", f"정답은 **제트**의 **{ab['ko']} (E)**이었어요." in e.description, e.description)
e = balodle.already_embed("agent", DAY, PLAY["agent"])
check("이미 푼 문제 화면", e.title == "✅ 오늘 요원 문제는 이미 풀었어요" and "다음 문제까지" in e.description
      and "제트" not in e.description)
e = balodle.panel_embed(DAY, {"agent": "sova", "ability": "jett:E", "map": "바인드"})
# 2026-11-24: 정답이 사람마다 달라서 '어제 정답' 줄은 없어요. 대신 사람마다 다르다는 안내와 연습 안내.
check("패널: 번호 · 푼 사람 수 · 사람마다 다른 정답 · 연습 안내 (어제 정답 없음)",
      e.title == "🧩 오늘의 발로들 #12"
      and "🕵️ 8명 · ✨ 5명 · 🗺️ 7명" in e.description and "어제 정답" not in e.description
      and "||소바||" not in e.description and "사람마다 정답이 달라요" in e.description
      and "연습 문제" in e.description and "기회는 6번" in e.description, e.description)
check("merge_answers: 그 사람 정답이 그날 문서를 덮는다",
      balodle.merge_answers({"_id": "d", "no": 3, "agent": "jett"},
                            {"answers": {"agent": "sova", "map": "펄"}}) == {"_id": "d", "no": 3,
                                                                           "agent": "sova", "map": "펄"})
check("merge_answers: 정답 없는 옛 풀이는 그날 문서 그대로",
      balodle.merge_answers({"_id": "d", "agent": "jett"}, {"agent": {}}) == {"_id": "d", "agent": "jett"})
check("맵 그림 종류: 어센트는 로딩 화면·장면 2종, 헤이븐은 로딩 화면만",
      balodle_data.map_variants("어센트") == ["", "_scene"] and balodle_data.map_variants("헤이븐") == [""],
      (balodle_data.map_variants("어센트"), balodle_data.map_variants("헤이븐")))
e = balodle.stats_embed({"streak": 4, "best_streak": 9, "last_solved_day": "2026-11-24",
                         "titles": ["발로들 단골"],
                         "agent": {"played": 12, "solved": 9, "dist": {"1": 1, "2": 3, "3": 4, "4": 1, "x": 3}}},
                        "2026-11-24")
check("내 기록: 연속·칭호·정답률·안 푼 종류", "🔥 지금 연속 **4일** · 최고 **9일**" in e.description
      and "🏷️ 칭호 **「발로들 단골」**" in e.description
      and "🕵️ 요원 — 12번 풀어 9번 맞힘 (75%)" in e.description
      and "✨ 스킬 — 아직 푼 적이 없어요" in e.description, e.description)
check("화면 글이 embed 한도(4096자) 안", all(
    len(x.description) < 4096 for x in (
        balodle.problem_embed("agent", DAY, {"status": "playing", "guesses": list(AGENTS)[:6]}), e)))

# ==================================================================
print("\n[10] 영속 뷰 규칙")


async def view_checks():
    view = balodle.BalodlePanelView()
    check("timeout=None (재시작 뒤에도 살아야 해요)", view.timeout is None)
    ids = [item.custom_id for item in view.children]
    want = ["akgui:balodle:open:agent", "akgui:balodle:open:ability", "akgui:balodle:open:map",
            "akgui:balodle:stats", "akgui:balodle:notify"]
    check("버튼 5개에 고정 custom_id", ids == want, ids)
    check("버튼 이름은 요원·스킬·맵·내 기록·알림",
          [item.label for item in view.children] == ["요원", "스킬", "맵", "내 기록", "알림"])
    check("문제 3개는 파랑, 내 기록·알림은 회색",
          [item.style for item in view.children] == [discord.ButtonStyle.primary] * 3
          + [discord.ButtonStyle.secondary] * 2)
    check("한 줄에 5개 (디스코드 한도 안)", len(view.to_components()) == 1)
    baseline = set(vars(discord.ui.View(timeout=None)))
    leaked = [n for n, v in vars(view).items()
              if n not in baseline and not isinstance(v, discord.ui.Item)]
    check("패널 뷰에 상태를 담지 않는다 (봇 전체에 하나뿐)", not leaked, leaked)

    cog = object.__new__(balodle.Balodle)
    pv = balodle.ProblemView(cog, 1, "agent", "2026-11-24")
    check("요원·스킬 화면에는 [정답 입력] 버튼", isinstance(pv.children[0], balodle.GuessButton)
          and pv.children[0].label == "정답 입력")
    check("문제 화면은 15분 토큰보다 짧게 닫힌다", pv.timeout and pv.timeout < 15 * 60, pv.timeout)
    mv = balodle.ProblemView(cog, 1, "map", "2026-11-24", guessed=["바인드"])
    select = mv.children[0]
    check("맵 화면은 선택 메뉴 (이미 넣은 맵은 빠짐)", isinstance(select, balodle.MapSelect)
          and len(select.options) == 12 and "바인드" not in [o.value for o in select.options])
    modal = balodle.GuessModal(balodle.ProblemView(cog, 1, "ability", "2026-11-24"))
    check("스킬 입력창: 제목 '스킬 맞히기', 칸 이름 '요원 이름', 30자",
          modal.title == "스킬 맞히기" and modal.name.label == "요원 이름"
          and modal.name.max_length == 30 and modal.name.placeholder == "예: 제트, jett")


asyncio.run(view_checks())

SRC = open(os.path.join(BOT_DIR, "cogs", "balodle.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)


def _func(cls_name, func_name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if isinstance(item, (ast.AsyncFunctionDef, ast.FunctionDef)) and item.name == func_name:
                    return item
    return None


def _calls(func):
    return [ast.unparse(n.func) for n in ast.walk(func) if isinstance(n, ast.Call)]


load = _func("Balodle", "cog_load")
# ⚠️ 글자 검사(`"add_view" in src`)로 하면 주석·docstring에 걸려 통과해요 → AST로 봐요.
check("cog_load에서 add_view(BalodlePanelView())를 부른다", load is not None and any(
    isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_view"
    and n.args and ast.unparse(n.args[0]) == "BalodlePanelView()" for n in ast.walk(load)))
callback = _func("GuessButton", "callback")
awaits = [ast.unparse(n.value) for n in ast.walk(callback) if isinstance(n, ast.Await)]
check("🚨 [정답 입력]은 ack 없이 바로 send_modal (입력창은 첫 응답으로만 띄울 수 있어요)",
      len(awaits) == 1 and awaits[0].startswith("interaction.response.send_modal("), awaits)
for cls, fn in (("GuessModal", "on_submit"), ("MapSelect", "callback")):
    # ast.walk는 너비 우선이라 '처음 나온 await'로 보면 틀려요 → 함수의 첫 문장을 직접 봐요.
    first = ast.unparse(_func(cls, fn).body[0])
    check(f"{cls}.{fn}은 첫 줄에서 ack", first.startswith("if not await ack(interaction)"), first)
for name in ("new_day_loop", "notify_loop", "panel_loop"):
    handler = next((f for f in ast.walk(TREE) if isinstance(f, ast.AsyncFunctionDef)
                    and any(ast.unparse(d) == f"{name}.error" for d in f.decorator_list)), None)
    check(f"{name}에 error 핸들러가 있고 restart()한다",
          handler is not None and f"self.{name}.restart" in _calls(handler))
check("결과 공유는 멘션 알림을 끈다", "AllowedMentions.none()" in ast.unparse(_func("Balodle", "_share")))
check("매일 알림은 그 역할만 멘션한다", "AllowedMentions(roles=[role])" in ast.unparse(_func("Balodle", "send_notify")))
check("알림 역할은 mentionable=False로 만든다", "mentionable=False" in ast.unparse(_func("Balodle", "notify_role")))
check("역할 이름 비교는 이모지를 뗀 이름의 정확한 일치",
      balodle._plain(balodle.NOTIFY_ROLE_NAME) == balodle.NOTIFY_ROLE_PLAIN
      and balodle._plain("🧩 발로들 알림 2") != balodle.NOTIFY_ROLE_PLAIN)

# ==================================================================
print("\n[11] 지표 스크립트 계산")
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("report_balodle", os.path.join(BOT_DIR, "scripts", "report_balodle.py"))
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)
os.environ["MONGODB_DB_NAME"] = "agwi_balodle_test"      # report가 .env를 다시 읽어도 테스트 DB
PLAYS = [
    {"date": "2026-11-24", "uid": "1", "agent": {"opened_at": "t", "status": "solved", "guesses": ["a", "b"]},
     "map": {"opened_at": "t", "status": "playing", "guesses": []}},
    {"date": "2026-11-24", "uid": "2", "agent": {"opened_at": "t", "status": "failed", "guesses": ["a"] * 6}},
    {"date": "2026-12-09", "uid": "1", "agent": {"opened_at": "t", "status": "solved", "guesses": ["a"]}},
    {"date": "2026-12-09", "uid": "3", "map": {"opened_at": "t", "status": "solved", "guesses": ["a"]}},
]
table = report.daily_rows(PLAYS)
check("하루 참여자: 연 사람 2 · 끝낸 사람 2 (요원), 맵은 열기만 1",
      table["2026-11-24"]["agent"] == {"opened": 2, "finished": 2, "solved": 1, "attempts": 2}
      and table["2026-11-24"]["map"]["opened"] == 1 and table["2026-11-24"]["map"]["finished"] == 0,
      table["2026-11-24"])
total = report.totals(table)
check("정답률·평균 시도: 요원 3건 중 2건, 답 3개", total["agent"]["finished"] == 3
      and total["agent"]["solved"] == 2 and total["agent"]["attempts"] == 3, total["agent"])
check("2주 뒤에도 푸는 사람: 첫 주 2명 중 셋째 주 1명",
      report.retention(PLAYS, "2026-11-24")[:2] == (2, 1), report.retention(PLAYS, "2026-11-24"))


# ==================================================================
# DB가 필요한 검사
# ==================================================================
U1, U2 = 900000000000000101, 900000000000000102
D0, D1, D2, D4 = "2031-01-10", "2031-01-11", "2031-01-12", "2031-01-14"


def _wipe():
    for name in ("balodle_days", "balodle_plays", "balodle_users"):
        _db[name].delete_many({})


class FakeMessage:
    def __init__(self, mid, text):
        self.id, self.content, self.edits = mid, text, 0


class FakePartial:
    def __init__(self, channel, mid):
        self.channel, self.mid = channel, mid

    async def edit(self, *, content=None, allowed_mentions=None, **_):
        self.channel.messages[self.mid].content = content
        self.channel.messages[self.mid].edits += 1


class FakeChannel:
    def __init__(self):
        self.messages, self.mentions = {}, []

    async def send(self, text, *, allowed_mentions=None, **_):
        mid = 5000 + len(self.messages)
        self.messages[mid] = FakeMessage(mid, text)
        self.mentions.append(allowed_mentions)
        return self.messages[mid]

    def get_partial_message(self, mid):
        return FakePartial(self, mid)


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append(kwargs)


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeInteraction:
    def __init__(self, uid):
        self.user, self.followup, self.edits = FakeUser(uid), FakeFollowup(), []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


async def db_checks():
    S = balodle_store
    _wipe()

    # ---------------- [12] 저장소 ----------------
    print("\n[12] 🚨 DB — 답 넣기·끝내기·연속")
    doc = {"no": 1, "agent": "jett", "ability": "jett:E", "map": "어센트", "map_focus": [0.5, 0.5]}
    made = await asyncio.gather(
        S.get_or_create_day(D1, doc), S.get_or_create_day(D1, {**doc, "agent": "sova"}))
    check("두 사람이 동시에 열어도 그날 문제는 하나", made[0]["agent"] == made[1]["agent"]
          and _db["balodle_days"].count_documents({"_id": D1}) == 1, [m["agent"] for m in made])
    day = await S.get_day(D1)
    check("카운터는 0에서 시작", day["solved"] == {"agent": 0, "ability": 0, "map": 0}
          and day["finished"] == {"agent": 0, "ability": 0, "map": 0}, day)

    play = await S.open_play(D1, U1, "agent")
    first_open = play["agent"]["opened_at"]
    check("문제를 열면 opened_at · playing · 빈 답", play["agent"]["status"] == "playing"
          and play["agent"]["guesses"] == [] and bool(first_open))
    again = await S.open_play(D1, U1, "agent")
    check("다시 열어도 opened_at은 처음 것 그대로 (참여자 수가 두 번 안 세져요)",
          again["agent"]["opened_at"] == first_open)
    check("다른 종류는 아직 안 연 상태", "ability" not in again)

    ok = await S.submit_guess(D1, U1, "agent", "sova", 0)
    check("답 하나 넣기", ok is not None and ok["agent"]["guesses"] == ["sova"])
    stale = await S.submit_guess(D1, U1, "agent", "raze", 0)
    check("🚨 넣기 전 개수가 다르면 안 들어간다 (오래된 화면에서 보낸 답)", stale is None)
    both = await asyncio.gather(
        S.submit_guess(D1, U1, "agent", "jett", 1, finish="solved", reward=2),
        S.submit_guess(D1, U1, "agent", "jett", 1, finish="solved", reward=2))
    check("🚨 같은 답을 동시에 두 번 보내도 한 번만 들어간다",
          sum(1 for b in both if b is not None) == 1, [b is not None for b in both])
    play = await S.get_play(D1, U1)
    check("끝난 상태·보상이 같은 업데이트에서 정해진다", play["agent"]["status"] == "solved"
          and play["agent"]["reward"] == 2 and play["agent"]["guesses"] == ["sova", "jett"]
          and bool(play["agent"]["done_at"]), play["agent"])
    late = await S.submit_guess(D1, U1, "agent", "raze", 2)
    check("끝난 문제에는 답이 더 안 들어간다", late is None)

    r1 = await S.finish_counters(D1, "agent", True)
    r2 = await S.finish_counters(D1, "agent", True)
    r3 = await S.finish_counters(D1, "agent", False)
    check("'오늘 N번째'는 맞힌 순서 (1, 2), 실패는 끝낸 사람만 올린다",
          (r1["solved"]["agent"], r2["solved"]["agent"], r3["solved"]["agent"], r3["finished"]["agent"]) == (1, 2, 2, 3),
          (r1["solved"], r3["finished"]))
    check("count_today는 끝낸 사람 수", (await S.count_today(D1))["agent"] == 3)

    T = SETTINGS["titles"]
    b = await S.bump_streak(U1, D1, T)
    check("첫 정답: 연속 1", (b["streak"], b["bumped"]) == (1, True), b)
    b = await S.bump_streak(U1, D1, T)
    check("같은 날 두 번째 정답: 그대로", (b["streak"], b["bumped"]) == (1, False), b)
    b = await S.bump_streak(U1, D2, T)
    check("다음 날: 연속 2", (b["streak"], b["best"], b["bumped"]) == (2, 2, True), b)
    b = await S.bump_streak(U1, D1, T)
    check("🚨 어제 문제를 뒤늦게 맞혀도 기록이 뒤로 가지 않는다", (b["streak"], b["bumped"]) == (2, False), b)
    b = await S.bump_streak(U1, D4, T)
    check("하루 건너뛰면 1부터, 최고 기록은 남는다", (b["streak"], b["best"]) == (1, 2), b)

    # 7일 칭호 → 끊겨도 유지
    _db["balodle_users"].update_one(
        {"_id": str(U2)}, {"$set": {"streak": 6, "best_streak": 6, "last_solved_day": D0}}, upsert=True)
    b = await S.bump_streak(U2, D1, T)
    check("연속 7일에 처음 닿으면 「발로들 단골」", b["streak"] == 7 and b["new_titles"] == ["발로들 단골"], b)
    b = await S.bump_streak(U2, D4, T)
    user = await S.get_user(U2)
    check("🚨 연속이 끊겨도 칭호와 최고 기록은 남는다", b["streak"] == 1 and b["new_titles"] == []
          and user["titles"] == ["발로들 단골"] and user["best_streak"] == 7, user)
    _db["balodle_users"].update_one(
        {"_id": str(U2)}, {"$set": {"streak": 6, "last_solved_day": "2031-01-20"}})
    b = await S.bump_streak(U2, "2031-01-21", T)
    check("두 번째로 7일에 닿아도 칭호를 또 주지 않는다", b["streak"] == 7 and b["new_titles"] == [], b)

    await S.record_result(U1, "agent", True, 2)
    await S.record_result(U1, "agent", False, 6)
    user = await S.get_user(U1)
    check("누적 기록: 푼 횟수·맞힌 횟수·시도 분포(실패는 x)", user["agent"]["played"] == 2
          and user["agent"]["solved"] == 1 and user["agent"]["dist"] == {"2": 1, "x": 1}, user["agent"])
    await S.set_notify(U1, True)
    check("알림 켬", (await S.get_user(U1))["notify"] is True)
    await S.set_notify(U1, False)
    check("알림 끔", (await S.get_user(U1))["notify"] is False)

    await S.get_or_create_day("2031-01-05", {**doc, "agent": "sova", "ability": "sova:Q", "map": "바인드"})
    recent = await S.recent_answers(D1, {"agent": 14, "ability": 30, "map": 5})
    check("최근 답: 요원 14일·스킬 30일 안이면 피하고, 맵은 5일이 지나 다시 나올 수 있다",
          "sova" in recent["agent"] and "sova:Q" in recent["ability"] and "바인드" not in recent["map"], recent)
    check("오늘 문제는 '최근 답'에 안 들어간다", "jett" not in recent["agent"])

    # ---------------- [13] 흐름 ----------------
    print("\n[13] 🚨 흐름 — 코인은 한 번만, 채널 결과 메시지는 한 사람에 하나")
    _wipe()
    await S.get_or_create_day(D1, doc)
    # 🎯 정답은 사람별이에요(2026-11-24). 아래 흐름은 '정답 = 제트·제트 E·어센트'로 짜여 있어서
    #    두 사람에게 그 정답을 미리 적어 둬요(안 적으면 문제를 열 때 무작위로 뽑혀요).
    fixed = {"agent": "jett", "ability": "jett:E", "map": "어센트", "map_variant": "", "map_focus": [0.5, 0.5]}
    for who in (U1, U2):
        await S.set_answers(D1, who, fixed)
    paid = []

    async def fake_add(user_id, amount, *, reason=""):
        paid.append((user_id, amount, reason))
        return 0

    balodle.coin_wallet.add = fake_add
    channel = FakeChannel()
    cog = object.__new__(balodle.Balodle)
    cog.bot = None
    cog._day_lock, cog._shot_lock = asyncio.Lock(), asyncio.Lock()
    cog._map_shots, cog._panel_sig = {}, None
    cog._panel_channel = lambda: channel
    real_today = L.today_iso
    L.today_iso = lambda now=None: D1          # 패널 버튼은 '오늘' 문제를 열어요

    it = FakeInteraction(U1)
    await cog.send_problem(it, "agent")
    sent = it.followup.sent[0]
    view = sent["view"]
    check("문제 버튼 → 나만 보이는 화면(ephemeral) + [정답 입력]", sent["ephemeral"] is True
          and isinstance(view, balodle.ProblemView) and sent["embed"].title == "🕵️ 요원 맞히기 · 1/6")

    it = FakeInteraction(U1)
    await cog.handle_guess(it, view, "재트")
    check("없는 이름: 제안하고 기회는 그대로", "혹시 **제트**인가요?" in it.edits[-1]["content"]
          and (await S.get_play(D1, U1))["agent"]["guesses"] == [], it.edits[-1]["content"])
    await cog.handle_guess(it, view, "소바")
    # 2026-11-24: 비교 줄은 글이 아니라 **그림**(agent_board.png)으로 나와요. 글에는 범례만 남아요.
    check("틀린 답: 비교표 그림이 붙고 안내는 지워진다", it.edits[-1]["content"] is None
          and [f.filename for f in it.edits[-1]["attachments"]] == ["agent_board.png"]
          and "**소바**" not in it.edits[-1]["embed"].description
          and "▲ 정답이 더 나중" in it.edits[-1]["embed"].description
          and it.edits[-1]["embed"].title == "🕵️ 요원 맞히기 · 2/6", it.edits[-1]["embed"].title)
    check("그림 없이 부르면 예전처럼 글 줄로 나온다(그림 실패 대비)",
          "**소바**" in balodle.problem_embed("agent", await S.get_day(D1),
                                             (await S.get_play(D1, U1))["agent"]).description)
    await cog.handle_guess(it, view, "sova")
    check("이미 넣은 답: 안내만 하고 기회는 그대로", "**소바**는 이미 넣었어요" in it.edits[-1]["content"]
          and (await S.get_play(D1, U1))["agent"]["guesses"] == ["sova"], it.edits[-1]["content"])
    check("아직 채널에는 아무것도 안 올라갔다", not channel.messages and not paid)

    # 같은 정답을 동시에 두 번 (입력창을 두 번 빨리 보냄)
    a, b = FakeInteraction(U1), FakeInteraction(U1)
    await asyncio.gather(cog.handle_guess(a, view, "제트"), cog.handle_guess(b, view, "제트"))
    check("🚨 정답을 동시에 두 번 보내도 코인은 한 번만", paid == [(U1, 2, "발로들")], paid)
    day = await S.get_day(D1)
    check("🚨 서버 카운터도 한 번만 오른다", day["solved"]["agent"] == 1 and day["finished"]["agent"] == 1,
          (day["solved"], day["finished"]))
    done = [x.edits[-1] for x in (a, b) if x.edits[-1]["embed"].title.startswith("🎉")]
    check("끝난 화면: 정답 · +2코인 · 오늘 1번째 · 연속", len(done) == 1
          and "2번 만에 맞혔어요. **+2코인**" in done[0]["embed"].description
          and "오늘 1번째로 맞혔어요." in done[0]["embed"].description
          and "🔥 발로들 연속 **1일**" in done[0]["embed"].description
          and isinstance(done[0]["view"], balodle.PracticeView),
          [x.edits[-1]["embed"].title for x in (a, b)])
    check("채널 결과 메시지 1개, 정답은 안 보이고 멘션 알림은 꺼짐", len(channel.messages) == 1
          and "제트" not in channel.messages[5000].content
          and channel.messages[5000].content.split("\n")[0] == f"🧩 발로들 #1 · <@{U1}>"
          and channel.mentions[0].everyone is False and channel.mentions[0].roles is False,
          channel.messages[5000].content)
    play = await S.get_play(D1, U1)
    check("풀이 문서에 순위·결과 메시지 ID가 남는다", play["agent"]["rank"] == 1 and play["share_msg"] == 5000, play)

    it = FakeInteraction(U1)
    await cog.send_problem(it, "agent")
    check("끝낸 문제 버튼을 다시 누르면 '이미 풀었어요' + 🔁 연습 문제 버튼",
          it.followup.sent[0]["embed"].title == "✅ 오늘 요원 문제는 이미 풀었어요"
          and isinstance(it.followup.sent[0].get("view"), balodle.PracticeView))

    # 🔁 연습 문제 — 코인·카운터·연속·채널 결과 전부 안 건드린다
    day_before_practice = await S.get_day(D1)
    paid_before, edits_before = len(paid), channel.messages[5000].edits
    it = FakeInteraction(U1)
    await cog.start_practice(it, U1, "agent")
    pv = it.edits[-1]["view"]
    check("연습 문제: 문제 화면 + 연습 표시, 오늘 내 정답(제트)은 피한다",
          isinstance(pv, balodle.ProblemView) and pv.practice is not None
          and pv.practice["day"]["agent"] != "jett"
          and "연습 문제" in (it.edits[-1]["embed"].footer.text or ""), pv.practice and pv.practice["day"])
    wrong = "jett" if pv.practice["day"]["agent"] != "jett" else "sova"
    await cog.handle_guess(it, pv, AGENTS[wrong]["ko"])
    await cog.handle_guess(it, pv, AGENTS[pv.practice["day"]["agent"]]["ko"])
    last = it.edits[-1]
    check("연습 문제: 맞히면 정답 화면 + 다시 🔁 버튼", last["embed"].title.startswith("🎉")
          and "코인" not in last["embed"].description.split("\n")[0]
          and isinstance(last["view"], balodle.PracticeView), last["embed"].description)
    day_after = await S.get_day(D1)
    check("🚨 연습은 코인·서버 카운터·채널 결과·풀이 문서를 안 건드린다",
          len(paid) == paid_before and day_after["solved"] == day_before_practice["solved"]
          and day_after["finished"] == day_before_practice["finished"]
          and channel.messages[5000].edits == edits_before
          and (await S.get_play(D1, U1))["agent"]["guesses"] == ["sova", "jett"],
          (paid[paid_before:], day_after["solved"]))

    # 스킬 문제: 한 번에 맞힘 → 같은 채널 메시지에 줄이 더해진다
    it = FakeInteraction(U1)
    await cog.send_problem(it, "ability")
    ability_view = it.followup.sent[0]["view"]
    check("스킬 화면에는 아이콘 그림이 붙는다", [f.filename for f in it.followup.sent[0]["files"]] == ["ability.png"])
    await cog.handle_guess(it, ability_view, "jett")
    check("스킬을 한 번에 맞히면 3코인", paid[-1] == (U1, 3, "발로들"), paid)
    check("🚨 채널 결과 메시지는 여전히 1개 (같은 메시지를 고친다)", len(channel.messages) == 1
          and channel.messages[5000].edits == 1 and "✨ 스킬 1/6" in channel.messages[5000].content,
          channel.messages[5000].content)
    user = await S.get_user(U1)
    check("같은 날 두 번째 정답은 연속을 또 올리지 않는다", user["streak"] == 1, user["streak"])

    # 맵 문제: 여섯 번 다 틀림 → 0코인, 정답 공개
    it = FakeInteraction(U2)
    await cog.send_problem(it, "map")
    map_view = it.followup.sent[0]["view"]
    check("맵 화면에는 확대 그림과 선택 메뉴", [f.filename for f in it.followup.sent[0]["files"]] == ["map.jpg"]
          and isinstance(map_view.children[0], balodle.MapSelect))
    before = len(paid)
    for name in ["바인드", "브리즈", "펄", "스플릿", "선셋", "어비스"]:
        await cog.handle_guess(it, map_view, name)
    last = it.edits[-1]
    check("기회를 다 쓰면 실패 화면 + 정답 공개 + 전체 그림", last["embed"].title == "😵 아쉬워요"
          and "정답은 **어센트**였어요." in last["embed"].description
          and isinstance(last["view"], balodle.PracticeView)
          and len(last["attachments"]) == 1, last["embed"].description)
    check("실패는 코인이 없다", len(paid) == before)
    day = await S.get_day(D1)
    check("실패는 끝낸 사람 수만 올린다", day["finished"]["map"] == 1 and day["solved"]["map"] == 0)
    check("두 번째 사람의 결과 메시지는 따로 1개", len(channel.messages) == 2
          and "🗺️ 맵 X/6 — 정답률 0%" in channel.messages[5001].content, channel.messages.get(5001) and channel.messages[5001].content)
    user = await S.get_user(U2)
    check("실패는 연속을 올리지 않고 분포 x에 쌓인다", not user.get("streak") and user["map"]["dist"] == {"x": 1}, user)

    # 0시 직전에 연 문제를 0시가 지나 맞혀도 그 문제로 채점
    L.today_iso = lambda now=None: D2
    it = FakeInteraction(U2)
    await S.open_play(D1, U2, "agent")
    await cog.handle_guess(it, balodle.ProblemView(cog, U2, "agent", D1), "제트")
    play = await S.get_play(D1, U2)
    check("날짜가 바뀐 뒤에도 연 문제 날짜(어제)로 채점·보상",
          play["agent"]["status"] == "solved" and paid[-1] == (U2, 3, "발로들")
          and await S.get_play(D2, U2) is None, (play.get("agent"), paid[-1]))

    # ---------------- [14] 사람별 정답 (2026-11-24) ----------------
    print("\n[14] 🎯 사람별 정답 · 사람별 반복 금지 · 옛 공통 문제 이어 풀기")
    U3, U4 = 900000000000000103, 900000000000000104
    await S.get_or_create_day(D2, {"no": 2})                 # 새 방식의 날 = 그날 문서에 정답 없음
    day2 = await S.get_day(D2)
    check("새 날의 그날 문서엔 정답이 없다", "agent" not in day2 and "map" not in day2, day2)
    mine = await cog.user_day(day2, U3)
    again = await cog.user_day(await S.get_day(D2), U3)
    check("처음 열면 정답 3개 + 맵 그림 종류·확대 중심을 뽑아 저장한다",
          all(mine.get(k) for k in ("agent", "ability", "map")) and "map_variant" in mine
          and len(mine.get("map_focus") or []) == 2, mine)
    check("🚨 다시 열어도 정답이 바뀌지 않는다", {k: again.get(k) for k in balodle.ANSWER_KEYS}
          == {k: mine.get(k) for k in balodle.ANSWER_KEYS})
    many = [await cog.new_answers({}) for _ in range(6)]
    check("사람마다 정답이 달라질 수 있다 (6번 뽑아 요원이 2종 이상)",
          len({m["agent"] for m in many}) >= 2, [m["agent"] for m in many])
    both = await asyncio.gather(S.set_answers(D2, U4, {"agent": "sova"}), S.set_answers(D2, U4, {"agent": "raze"}))
    check("🚨 동시에 두 번 정답을 적어도 하나만 남는다",
          both[0]["answers"] == both[1]["answers"] and _db["balodle_plays"].count_documents({"_id": f"{D2}:{U4}"}) == 1,
          [b["answers"] for b in both])

    # 사람별 반복 금지: U3가 D2에 받은 정답은 U3의 다음 날 '최근 답'에 들어가고, U4에겐 안 들어간다
    days_by = {"agent": 14, "ability": 30, "map": 5}
    r3 = await S.recent_user_answers(U3, "2031-01-13", days_by)
    r4 = await S.recent_user_answers(U4, "2031-01-13", days_by)
    check("최근 답은 사람별: 내가 받은 요원은 피하고, 남이 받은 건 상관없다",
          mine["agent"] in r3["agent"] and r4["agent"] == {both[0]["answers"]["agent"]}
          and (mine["agent"] == both[0]["answers"]["agent"] or mine["agent"] not in r4["agent"]),
          (r3, r4))
    check("옛 공통 문제 날(D1)의 정답도 그날 푼 사람의 '최근 답'에 들어간다",
          "jett" in (await S.recent_user_answers(U2, D2, days_by))["agent"])

    # 11/24처럼 공통 정답이 있는 날, 업데이트 전에 문제를 열어 둔 사람은 그 문제를 그대로 이어 푼다
    legacy_day = "2031-01-20"
    await S.get_or_create_day(legacy_day, doc)               # 옛 방식(정답 있음)
    await S.open_play(legacy_day, U3, "agent")               # 업데이트 전에 열어 둠(answers 없음)
    cont = await cog.user_day(await S.get_day(legacy_day), U3)
    check("🚨 옛 공통 문제를 이미 연 사람은 정답이 그대로 (도중에 안 바뀜)",
          (cont["agent"], cont["ability"], cont["map"]) == ("jett", "jett:E", "어센트"), cont)
    fresh = await cog.user_day(await S.get_day(legacy_day), U4)
    check("같은 날이라도 아직 안 연 사람은 자기 정답을 새로 받는다",
          (await S.get_play(legacy_day, U4)).get("answers") is not None, fresh)

    L.today_iso = real_today
    _wipe()


if USE_DB:
    try:
        _db.command("ping")
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ 테스트 DB에 연결하지 못했어요: {type(exc).__name__}: {exc}")
        failures.append("DB 연결")
    else:
        asyncio.run(db_checks())
else:
    print("\n[12][13] DB 검사는 건너뛰었어요 (--no-db)")

print("\n" + "=" * 50)
if failures:
    print(f"❌ 실패 {len(failures)}개:")
    for label in failures:
        print(f"   - {label}")
    sys.exit(1)
print("✅ 발로들 검사 전부 통과")
