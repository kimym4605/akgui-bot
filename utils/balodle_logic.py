"""🧩 발로들 순수 로직 — 채점·이름 인식·보상·연속·확대 단계·결과 칸.

🚨 **여기는 DB도 디스코드도 몰라요.** 받는 건 전부 dict·문자열·숫자예요. 그래서
`scripts/test_balodle.py`가 DB 없이 규칙 전체를 돌려볼 수 있어요. DB는 `balodle_store`,
화면은 `cogs/balodle.py`가 맡아요.

규칙의 출처는 볼트 `악귀봇 설계서` "기능: 발로들"이에요. 숫자(보상·기회·🟨 기준)는 전부
`config/balodle/settings.json`에서 와요 — 여기에 숫자를 박지 않아요.
"""
import difflib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

KINDS = ("agent", "ability", "map")
GREEN, YELLOW, BLACK = "🟩", "🟨", "⬛"
UP, DOWN = "⬆", "⬇"          # ⬆ 정답이 더 나중 · ⬇ 정답이 더 먼저
UNKNOWN = "알 수 없음"
# 요원 속성 칸 순서. 화면·결과 칸이 이 순서를 그대로 써요(디자인: 역할군 · 출신 · 출시 · 성별).
AGENT_COLUMNS = ("role", "origin", "release", "gender")
# 속성이 다 채워져야 요원 문제의 정답 후보가 돼요.
REQUIRED_ATTRS = ("role", "origin", "continent", "released", "gender")


# ------------------------------------------------------------------
# 이름 인식
# ------------------------------------------------------------------
def normalize(text) -> str:
    """비교용 이름. 소문자로 바꾸고 공백·기호를 지워요 (`KAY/O` → `kayo`, `케이/오` → `케이오`)."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def _jamo(text: str) -> str:
    """한글을 자모로 풀어요. `재트`와 `제트`가 글자 단위로는 반만 같지만 자모로는 3/4이 같아요."""
    return unicodedata.normalize("NFD", text)


def build_name_index(agents: dict) -> dict:
    """정규화한 이름 → 요원키. 한글·영문·키·별칭을 모두 넣어요."""
    index = {}
    for key, agent in agents.items():
        names = [key, agent.get("ko"), agent.get("en"), *(agent.get("aliases") or [])]
        for name in names:
            norm = normalize(name)
            if norm:
                index.setdefault(norm, key)
    return index


def resolve_agent(text, agents: dict, index: dict | None = None) -> tuple[str | None, str | None]:
    """(요원키, 제안키). 아는 이름이면 (키, None), 모르는 이름이면 (None, 가장 비슷한 요원키 또는 None)."""
    index = index if index is not None else build_name_index(agents)
    norm = normalize(text)
    if not norm:
        return None, None
    if norm in index:
        return index[norm], None
    by_jamo = {_jamo(name): key for name, key in index.items()}
    close = difflib.get_close_matches(_jamo(norm), list(by_jamo), n=1, cutoff=0.6)
    return None, (by_jamo[close[0]] if close else None)


# ------------------------------------------------------------------
# 요원 속성 비교
# ------------------------------------------------------------------
def is_complete(agent: dict) -> bool:
    return all(agent.get(field) for field in REQUIRED_ATTRS)


def release_rank(agents: dict) -> dict:
    """요원키 → 출시 순서. **출시일이 같으면 같은 번호**예요(비공개 베타 10명은 모두 1번)."""
    dates = sorted({a["released"] for a in agents.values() if a.get("released")})
    order = {day: i + 1 for i, day in enumerate(dates)}
    return {key: order[a["released"]] for key, a in agents.items() if a.get("released")}


def _country(origin: str) -> str:
    """`영국(스코틀랜드)` → `영국`. 괄호 앞 나라로 비교해요(화면에는 괄호까지 보여줘요)."""
    return re.sub(r"\(.*?\)", "", origin or "").strip()


def _release_value(key: str, agents: dict, mode: str, ranks: dict) -> int:
    if mode == "year":
        return int(agents[key]["released"][:4])
    return ranks[key]


def compare_agent(guess: str, answer: str, agents: dict, settings: dict) -> list[tuple[str, str]]:
    """넣은 요원과 정답을 칸마다 비교해요. [(보여줄 값, 표시)] — 순서는 `AGENT_COLUMNS`.

    표시는 🟩/🟨/⬛ 한 글자예요. 출시 칸은 🟩가 아니면 값 뒤에 ⬆/⬇가 붙어요
    (예: `("5번째⬆", "🟨")`). 🟨만으로는 더 나중인지 먼저인지 알 수 없어서예요."""
    g, a = agents[guess], agents[answer]
    cells = []

    # 역할군 — 네 가지뿐이라 🟨가 없어요.
    cells.append((g["role"], GREEN if g["role"] == a["role"] else BLACK))

    # 출신 — 같은 나라 🟩, 나라는 다르고 대륙이 같으면 🟨. `알 수 없음`끼리만 🟩예요(🟨 없음).
    g_country, a_country = _country(g["origin"]), _country(a["origin"])
    if g_country == a_country:
        mark = GREEN
    elif UNKNOWN in (g_country, a_country) or UNKNOWN in (g["continent"], a["continent"]):
        mark = BLACK
    elif g["continent"] == a["continent"]:
        mark = YELLOW
    else:
        mark = BLACK
    cells.append((g["origin"], mark))

    # 출시 — 설정으로 연도/순서를 골라요.
    mode = settings.get("release_mode", "order")
    ranks = release_rank(agents)
    gv, av = _release_value(guess, agents, mode, ranks), _release_value(answer, agents, mode, ranks)
    close = int(settings.get("year_close" if mode == "year" else "order_close", 0))
    label = str(gv) if mode == "year" else f"{gv}번째"
    if gv == av:
        cells.append((label, GREEN))
    else:
        arrow = UP if av > gv else DOWN
        cells.append((label + arrow, YELLOW if abs(av - gv) <= close else BLACK))

    # 성별 — 남·여·논바이너리 세 값, 🟨 없음.
    cells.append((g["gender"], GREEN if g["gender"] == a["gender"] else BLACK))
    return cells


def agent_squares(guess: str, answer: str, agents: dict, settings: dict) -> str:
    """결과 칸 한 줄 (`🟨🟩⬛🟩`). 화살표는 넣지 않아요 — 복사해 붙였을 때 칸이 맞게."""
    return "".join(mark for _, mark in compare_agent(guess, answer, agents, settings))


# ------------------------------------------------------------------
# 채점 공통
# ------------------------------------------------------------------
def is_duplicate(guesses: list, guess: str) -> bool:
    return guess in (guesses or [])


def is_correct(kind: str, guess: str, day: dict, abilities: dict) -> bool:
    """요원: 요원키 일치 · 스킬: **그 스킬을 가진 요원** · 맵: 맵 이름 일치."""
    if kind == "ability":
        return guess == (abilities.get(day.get("ability")) or {}).get("agent")
    return guess == day.get(kind)


def max_attempts(kind: str, settings: dict) -> int:
    return int((settings.get("max_attempts") or {}).get(kind, 6))


def reward(attempts: int, solved: bool, settings: dict) -> int:
    """`rewards`는 `[[몇 번째까지, 코인], …]`이에요. 실패는 0."""
    if not solved:
        return 0
    for upto, coin in settings.get("rewards") or []:
        if attempts <= upto:
            return int(coin)
    return 0


def squares(kind: str, play_kind: dict, day: dict, agents: dict, settings: dict) -> list[str]:
    """한 종류의 결과 칸 줄들. 요원은 답마다 한 줄(네 칸), 스킬·맵은 한 줄(틀린 만큼 ⬛, 맞히면 끝에 🟩)."""
    guesses = play_kind.get("guesses") or []
    if kind == "agent":
        return [agent_squares(g, day["agent"], agents, settings) for g in guesses if g in agents]
    solved = play_kind.get("status") == "solved"
    wrong = len(guesses) - (1 if solved else 0)
    return [BLACK * max(wrong, 0) + (GREEN if solved else "")]


# ------------------------------------------------------------------
# 스킬 힌트
# ------------------------------------------------------------------
HINT_HEADS = ("① 키", "② 역할군", "③ 요원 출시 연도", "④ 첫 글자", "⑤ 스킬 이름")


def ability_hints(wrong: int, ability: dict, agent: dict) -> list[tuple[str, str]]:
    """틀린 횟수만큼 힌트를 열어요. [(머리말, 값)] — 최대 다섯 개."""
    values = (
        ability.get("slot", ""),
        agent.get("role", ""),
        (agent.get("released") or "")[:4] or UNKNOWN,
        (ability.get("ko") or "")[:1],
        ability.get("ko", ""),
    )
    return list(zip(HINT_HEADS, values))[:max(0, min(wrong, len(HINT_HEADS)))]


# ------------------------------------------------------------------
# 연속·칭호
# ------------------------------------------------------------------
def day_before(day_iso: str) -> str:
    return (date.fromisoformat(day_iso) - timedelta(days=1)).isoformat()


def next_streak(last_day: str | None, today: str, streak: int) -> tuple[int, bool]:
    """(새 연속, 올랐는지). 그날 첫 정답 때만 올라요.

    - 오늘 이미 올렸으면(또는 더 뒤 날짜가 적혀 있으면) 그대로
    - 어제까지 이어져 있으면 +1
    - 하루 이상 건너뛰었으면 1부터"""
    if last_day and last_day >= today:
        return int(streak or 0), False
    if last_day == day_before(today):
        return int(streak or 0) + 1, True
    return 1, True


def live_streak(streak: int, last_day: str | None, today: str) -> int:
    """지금 살아 있는 연속. 어제도 오늘도 맞히지 않았으면 끊긴 거라 0이에요."""
    if not last_day or not streak:
        return 0
    return int(streak) if last_day >= day_before(today) else 0


def _thresholds(titles: dict) -> list[tuple[int, str]]:
    return sorted((int(days), name) for days, name in (titles or {}).items())


def new_titles(best_before: int, best_after: int, titles: dict) -> list[str]:
    """최고 연속이 이번에 처음 넘은 칭호들. 한 번 얻으면 끊겨도 남으니 **최고 기록**으로 봐요."""
    return [name for days, name in _thresholds(titles) if best_before < days <= best_after]


def top_title(owned: list, titles: dict) -> str | None:
    """얻은 칭호 중 가장 높은 것."""
    have = [name for _, name in _thresholds(titles) if name in (owned or [])]
    return have[-1] if have else None


def title_days(name: str, titles: dict) -> int:
    return next((days for days, n in _thresholds(titles) if n == name), 0)


# ------------------------------------------------------------------
# 날짜·번호
# ------------------------------------------------------------------
def today_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(KST)).astimezone(KST).date().isoformat()


def puzzle_no(day_iso: str, start_date: str) -> int:
    """`start_date`가 1번이에요. 시작일보다 앞이면 1로 막아요."""
    return max(1, (date.fromisoformat(day_iso) - date.fromisoformat(start_date)).days + 1)


def next_reset(now: datetime | None = None) -> datetime:
    """다음 문제가 나오는 시각(다음 KST 0시)."""
    now = (now or datetime.now(KST)).astimezone(KST)
    return datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=KST)


def left_text(now: datetime | None = None) -> str:
    """`5시간 12분` — 다음 문제까지 남은 시간."""
    now = (now or datetime.now(KST)).astimezone(KST)
    minutes = max(0, int((next_reset(now) - now).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}시간 {minutes}분" if hours else f"{minutes}분"


def parse_time(text: str, default: tuple[int, int] = (9, 0)) -> tuple[int, int]:
    """`"09:00"` → (9, 0). 잘못 적혀 있으면 기본값."""
    try:
        hour, minute = (int(x) for x in str(text).split(":")[:2])
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
    except (ValueError, TypeError):
        pass
    return default


def time_label(text: str) -> str:
    """알림 안내에 넣는 시각. `09:00` → `아침 9시`, `21:30` → `밤 9시 30분`."""
    hour, minute = parse_time(text)
    part = "새벽" if hour < 6 else "아침" if hour < 12 else "낮" if hour < 18 else "밤"
    shown = hour if hour <= 12 else hour - 12
    return f"{part} {shown or 12}시" + (f" {minute}분" if minute else "")


# ------------------------------------------------------------------
# 오늘 문제 고르기
# ------------------------------------------------------------------
def pick_answer(candidates: list, recent: set | list, rng):
    """최근에 나온 답을 피해 하나 골라요. 피하고 나면 남는 게 없을 때는 전체에서 골라요."""
    pool = [c for c in candidates if c not in set(recent or ())] or list(candidates)
    return rng.choice(pool) if pool else None


# ------------------------------------------------------------------
# 맵 확대
# ------------------------------------------------------------------
def zoom_box(step: int, focus, size, zoom_steps) -> tuple[int, int, int, int]:
    """확대 단계 `step`(0부터)에서 잘라낼 네모 (왼, 위, 오른, 아래).

    잘라낼 너비는 그림 너비의 `zoom_steps[step]`이고 높이도 같은 비율이라 가로세로비가 유지돼요.
    중심은 `focus`(0~1)인데, 네모가 그림 밖으로 나가면 안쪽으로 밀어요.
    단계가 끝났으면(`step >= len(zoom_steps)`) 그림 전체예요."""
    width, height = size
    if step >= len(zoom_steps):
        return 0, 0, width, height
    frac = float(zoom_steps[step])
    w, h = max(1, round(width * frac)), max(1, round(height * frac))
    left = min(max(round(focus[0] * width - w / 2), 0), width - w)
    top = min(max(round(focus[1] * height - h / 2), 0), height - h)
    return left, top, left + w, top + h


# ------------------------------------------------------------------
# 채널 결과 메시지
# ------------------------------------------------------------------
KIND_HEAD = {"agent": "🕵️ 요원", "ability": "✨ 스킬", "map": "🗺️ 맵"}


def success_rate(day: dict, kind: str) -> int | None:
    finished = int(((day.get("finished") or {}).get(kind)) or 0)
    if not finished:
        return None
    return round(int(((day.get("solved") or {}).get(kind)) or 0) * 100 / finished)


def share_lines(play: dict, day: dict, mention: str, streak: int,
                agents: dict, settings: dict) -> list[str]:
    """채널에 올리는 결과 메시지 줄들. **끝난 종류만** 들어가요(정답은 안 보여요).

        🧩 발로들 #12 · @악귀 · 🔥4일
        🕵️ 요원 3/6 — 오늘 5번째 · 정답률 62%
        ⬛🟨⬛⬛ …

    `🔥N일`은 연속이 2일 이상일 때만 붙어요. "오늘 N번째"는 맞힌 줄에만 있어요."""
    head = f"🧩 발로들 #{day.get('no', 1)} · {mention}"
    if streak >= 2:
        head += f" · 🔥{streak}일"
    lines = [head]
    for kind in KINDS:
        part = play.get(kind) or {}
        if part.get("status") not in ("solved", "failed"):
            continue
        limit = max_attempts(kind, settings)
        solved = part["status"] == "solved"
        score = str(len(part.get("guesses") or [])) if solved else "X"
        tail = []
        if solved and part.get("rank"):
            tail.append(f"오늘 {part['rank']}번째")
        rate = success_rate(day, kind)
        if rate is not None:
            tail.append(f"정답률 {rate}%")
        lines.append(f"{KIND_HEAD[kind]} {score}/{limit}" + (" — " + " · ".join(tail) if tail else ""))
        lines.extend(squares(kind, part, day, agents, settings))
    return lines


# ------------------------------------------------------------------
# 내 기록 — 시도 분포 막대
# ------------------------------------------------------------------
BAR_MAX = 8


def dist_rows(dist: dict, limit: int) -> list[str]:
    """`1`~`limit`과 `X` 줄. 가장 많은 줄이 🟩 8칸이 되게 줄이고, 1 이상이면 최소 1칸이에요."""
    keys = [str(n) for n in range(1, limit + 1)] + ["x"]
    counts = {k: int((dist or {}).get(k, 0) or 0) for k in keys}
    top = max(counts.values(), default=0)
    rows = []
    for key in keys:
        n = counts[key]
        cells = max(1, round(n * BAR_MAX / top)) if n and top else 0
        block = BLACK if key == "x" else GREEN
        rows.append(f"`{key.upper()}` {block * cells}{' ' if cells else ''}{n}")
    return rows
