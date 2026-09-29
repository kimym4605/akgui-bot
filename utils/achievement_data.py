"""업적 정의 60개 - "무엇을 하면 무엇이 열리는가"만 적어둔 순수 데이터예요.

## 설계 원칙

**이미 쌓이고 있는 숫자로만 만들었어요.** 업적을 위해 새로 추적을 시작해야 하는 조건
(예: "장판 킬 10회")은 일부러 넣지 않았어요. 그런 건 기록이 없어서 다는 순간 전원 0이 되고,
새로 들어온 사람과 1년 쓴 사람이 똑같이 0이라 아무 의미가 없어요. 여기 있는 60개는 전부
**과거 데이터로 소급 해금돼요** - 다는 순간 오래 활동한 사람은 바로 20~30개가 열려요.

(내전 관련 업적만은 예외예요. 개인 승패 기록 자체가 이번에 처음 생겨서, 전원 0승에서
시작해요. 이건 어쩔 수 없어요 - 지난 내전 결과가 어디에도 남아있지 않거든요.)

## 판정 방식

모든 업적은 `metric`(숫자 하나)과 `need`(그 숫자가 얼마 이상이면 되는지)로만 정의돼요.
`utils/achievement_store.collect_stats()`가 metric 값을 한 번에 모아오고, 판정은
단순 비교예요. 조건을 함수로 두지 않은 건 **진행도(23/60, "45/50승")를 보여주기 위해서**예요.
함수면 "열렸다/안 열렸다"밖에 못 보여줘요.

## 등급과 보상

등급은 색과 보상 코인만 정해요(bronze 1 / silver 2 / gold 3 / platinum 5).
코인을 붙인 이유는 지금 **서버에 코인 버는 길이 출석과 미션뿐**이라서예요. 업적은 한 번만
주는 일회성 보상이라 인플레를 크게 일으키지 않으면서, 오래 활동한 사람에게 소급으로
목돈이 한 번 들어가요(칭호 20코인, 뽑기 10코인짜리 소비처가 놀고 있어요).
"""

# 등급 -> (보상 코인, 색, 라벨)
GRADES = {
    "bronze": (1, 0xCD7F32, "브론즈"),
    "silver": (2, 0xC0C0C0, "실버"),
    "gold": (3, 0xFFD700, "골드"),
    "platinum": (5, 0x7FFFD4, "플래티넘"),
}

# 카테고리 -> 화면에 쓸 이름
CATEGORIES = {
    "attend": "📅 출석",
    "coin": "🪙 악귀코인",
    "pokemon": "🐾 포켓몬",
    "scrim": "⚔️ 내전",
    "valorant": "🎯 발로란트",
    "mission": "📋 미션",
    "etc": "✨ 그 외",
}


def _a(key, name, desc, emoji, category, metric, need, grade):
    return {
        "key": key, "name": name, "desc": desc, "emoji": emoji,
        "category": category, "metric": metric, "need": need, "grade": grade,
        "reward": GRADES[grade][0],
    }


ACHIEVEMENTS = [
    # -- 📅 출석 (6) -----------------------------------------------
    _a("attend_1",    "첫 발자국",      "출석 1회",      "👣", "attend", "attendance", 1,   "bronze"),
    _a("attend_7",    "일주일 개근",    "출석 7회",      "📗", "attend", "attendance", 7,   "bronze"),
    _a("attend_30",   "한 달 개근",     "출석 30회",     "📘", "attend", "attendance", 30,  "silver"),
    _a("attend_100",  "백일장",         "출석 100회",    "📙", "attend", "attendance", 100, "gold"),
    _a("attend_200",  "터줏대감",       "출석 200회",    "🏛️", "attend", "attendance", 200, "gold"),
    _a("attend_365",  "1년 개근",       "출석 365회",    "🎖️", "attend", "attendance", 365, "platinum"),

    # -- 📅 연속 출석 (5) ------------------------------------------
    _a("streak_3",    "삼일천하",       "연속 출석 3일",   "🔥", "attend", "attendance_streak", 3,   "bronze"),
    _a("streak_7",    "칠일의 약속",    "연속 출석 7일",   "🔥", "attend", "attendance_streak", 7,   "bronze"),
    _a("streak_30",   "한 달을 거르지 않고", "연속 출석 30일", "🔥", "attend", "attendance_streak", 30,  "silver"),
    _a("streak_60",   "습관이 된 사람",  "연속 출석 60일",  "🔥", "attend", "attendance_streak", 60,  "gold"),
    _a("streak_100",  "백일의 불꽃",    "연속 출석 100일", "🔥", "attend", "attendance_streak", 100, "platinum"),

    # -- 🪙 악귀코인 (5) -------------------------------------------
    _a("coin_10",     "첫 주머니",      "악귀코인 10개 보유",  "🪙", "coin", "coin", 10,  "bronze"),
    _a("coin_50",     "짤랑짤랑",       "악귀코인 50개 보유",  "💰", "coin", "coin", 50,  "bronze"),
    _a("coin_100",    "세 자리 부자",   "악귀코인 100개 보유", "💵", "coin", "coin", 100, "silver"),
    _a("coin_300",    "악귀 자산가",    "악귀코인 300개 보유", "💎", "coin", "coin", 300, "gold"),
    _a("coin_500",    "코인 금고",      "악귀코인 500개 보유", "🏦", "coin", "coin", 500, "platinum"),

    # -- 🐾 포켓몬 도감 (5) ----------------------------------------
    _a("dex_1",       "도감 개시",      "도감 1종 등록",   "📖", "pokemon", "pokedex", 1,   "bronze"),
    _a("dex_10",      "수집의 재미",    "도감 10종 등록",  "📖", "pokemon", "pokedex", 10,  "bronze"),
    _a("dex_30",      "제법 모았네",    "도감 30종 등록",  "📚", "pokemon", "pokedex", 30,  "silver"),
    _a("dex_60",      "도감 절반",      "도감 60종 등록",  "📚", "pokemon", "pokedex", 60,  "gold"),
    _a("dex_151",     "도감 마스터",    "도감 151종 등록", "🏆", "pokemon", "pokedex", 151, "platinum"),

    # -- 🐾 포켓몬 레벨 (4) ----------------------------------------
    _a("lv_10",       "첫 성장",        "포켓몬 Lv.10 달성",  "🌱", "pokemon", "level", 10,  "bronze"),
    _a("lv_30",       "듬직해졌어",     "포켓몬 Lv.30 달성",  "🌿", "pokemon", "level", 30,  "bronze"),
    _a("lv_60",       "믿음직한 파트너", "포켓몬 Lv.60 달성",  "🌳", "pokemon", "level", 60,  "silver"),
    _a("lv_100",      "만렙 트레이너",  "포켓몬 Lv.100 달성", "👑", "pokemon", "level", 100, "platinum"),

    # -- ⚔️ 내전 승수 (7) ------------------------------------------
    _a("win_1",       "첫 승",          "내전 1승",    "🥉", "scrim", "scrim_wins", 1,   "bronze"),
    _a("win_5",       "이기는 맛",      "내전 5승",    "🥈", "scrim", "scrim_wins", 5,   "bronze"),
    _a("win_10",      "두 자리 승수",   "내전 10승",   "🥇", "scrim", "scrim_wins", 10,  "silver"),
    _a("win_25",      "내전 단골",      "내전 25승",   "⭐", "scrim", "scrim_wins", 25,  "silver"),
    _a("win_50",      "반백 승",        "내전 50승",   "🌟", "scrim", "scrim_wins", 50,  "gold"),
    _a("win_100",     "백승 장군",      "내전 100승",  "🏅", "scrim", "scrim_wins", 100, "platinum"),
    _a("win_200",     "내전의 지배자",  "내전 200승",  "👑", "scrim", "scrim_wins", 200, "platinum"),

    # -- ⚔️ 내전 참가 (4) ------------------------------------------
    _a("play_10",     "몸 좀 풀었다",   "내전 10판 참가",  "🎮", "scrim", "scrim_matches", 10,  "bronze"),
    _a("play_50",     "주전 멤버",      "내전 50판 참가",  "🎮", "scrim", "scrim_matches", 50,  "silver"),
    _a("play_100",    "내전 중독",      "내전 100판 참가", "🕹️", "scrim", "scrim_matches", 100, "gold"),
    _a("play_200",    "내전이 곧 인생", "내전 200판 참가", "🕹️", "scrim", "scrim_matches", 200, "platinum"),

    # -- ⚔️ 연승 (5) -----------------------------------------------
    _a("strk_3",      "3연승",          "내전 3연승",   "🔺", "scrim", "scrim_best_streak", 3,  "bronze"),
    _a("strk_5",      "5연승",          "내전 5연승",   "🔺", "scrim", "scrim_best_streak", 5,  "silver"),
    _a("strk_7",      "7연승",          "내전 7연승",   "🔥", "scrim", "scrim_best_streak", 7,  "gold"),
    _a("strk_10",     "10연승",         "내전 10연승",  "💥", "scrim", "scrim_best_streak", 10, "platinum"),
    _a("strk_15",     "막을 수 없는",   "내전 15연승",  "⚡", "scrim", "scrim_best_streak", 15, "platinum"),

    # -- 🎯 악귀력 (5) ---------------------------------------------
    _a("agwi_700",    "각성",           "주간 악귀력 700 달성",  "😈", "valorant", "agwi_best", 700,  "bronze"),
    _a("agwi_900",    "쓸 만한 악귀",   "주간 악귀력 900 달성",  "😈", "valorant", "agwi_best", 900,  "silver"),
    _a("agwi_1100",   "상위 악귀",      "주간 악귀력 1100 달성", "👿", "valorant", "agwi_best", 1100, "gold"),
    _a("agwi_1300",   "악귀 중의 악귀", "주간 악귀력 1300 달성", "👿", "valorant", "agwi_best", 1300, "platinum"),
    _a("agwi_1500",   "인간이 맞나요",  "주간 악귀력 1500 달성", "🔱", "valorant", "agwi_best", 1500, "platinum"),

    # -- 🎯 티어 (6) — 티어 인덱스는 아이언1=1 … 레디언트=25 --------
    _a("tier_gold",   "골드 진입",      "골드 티어 달성",       "🥇", "valorant", "tier_index", 10, "bronze"),
    _a("tier_plat",   "플래티넘 진입",  "플래티넘 티어 달성",   "🔷", "valorant", "tier_index", 13, "silver"),
    _a("tier_dia",    "다이아 진입",    "다이아몬드 티어 달성", "💠", "valorant", "tier_index", 16, "gold"),
    _a("tier_asc",    "초월자 진입",    "초월자 티어 달성",     "🔮", "valorant", "tier_index", 19, "gold"),
    _a("tier_imm",    "불멸 진입",      "불멸 티어 달성",       "❤️‍🔥", "valorant", "tier_index", 22, "platinum"),
    _a("tier_rad",    "레디언트",       "레디언트 달성",        "✨", "valorant", "tier_index", 25, "platinum"),

    # -- 📋 미션 (4) -----------------------------------------------
    _a("mission_1",   "첫 미션",        "미션 1개 완료",   "📋", "mission", "mission_total", 1,   "bronze"),
    _a("mission_10",  "미션 수행자",    "미션 10개 완료",  "📋", "mission", "mission_total", 10,  "bronze"),
    _a("mission_50",  "성실한 악귀",    "미션 50개 완료",  "📝", "mission", "mission_total", 50,  "silver"),
    _a("mission_150", "미션 장인",      "미션 150개 완료", "🗂️", "mission", "mission_total", 150, "gold"),

    # -- ✨ 그 외 (4) ----------------------------------------------
    _a("has_title",   "이름을 얻다",    "칭호를 달아본 적 있음", "🏷️", "etc", "title_owned",     1, "silver"),
    _a("riot_link",   "연결된 자",      "라이엇 계정 연동",      "🔗", "etc", "riot_linked",     1, "bronze"),
    _a("birthday",    "생일 등록",      "생일을 등록해둠",       "🎂", "etc", "birthday_set",    1, "bronze"),
    _a("starter",     "여정의 시작",    "스타팅 포켓몬 선택",    "🎒", "etc", "pokemon_started", 1, "bronze"),
]

TOTAL = len(ACHIEVEMENTS)
BY_KEY = {a["key"]: a for a in ACHIEVEMENTS}

# 카테고리 순서를 CATEGORIES 선언 순서대로 고정해둬요(화면에서 매번 순서가 바뀌면 찾기 힘들어요).
BY_CATEGORY = {
    category: [a for a in ACHIEVEMENTS if a["category"] == category]
    for category in CATEGORIES
}


def grade_color(grade: str) -> int:
    return GRADES[grade][1]


def grade_label(grade: str) -> str:
    return GRADES[grade][2]


def progress_of(achievement: dict, stats: dict) -> tuple[int, int]:
    """(지금 값, 필요한 값). 화면에 '45 / 50' 을 찍기 위한 거예요."""
    have = stats.get(achievement["metric"], 0) or 0
    return int(have), int(achievement["need"])


def is_unlocked(achievement: dict, stats: dict) -> bool:
    have, need = progress_of(achievement, stats)
    return have >= need
