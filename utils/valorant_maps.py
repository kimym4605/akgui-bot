"""발로란트 맵 목록이에요. `/맵추천`·내전 맵 기록·내전 KDA 가져오기가 같은 목록을 써요.

원래 `cogs/map.py` 안에만 있었는데, 내전 결과에 맵을 남기게 되면서 여러 곳에서 필요해졌어요.
cog가 다른 cog를 import하는 모양을 피하려고 여기로 옮겼어요.

## 이름이 두 벌인 이유

서버원에게 보여주는 건 한글(`어센트`)인데, **HenrikDev 경기 데이터의 맵 이름은 영문**
(`Ascent`)이에요. 그래서 영문→한글 표(`EN_TO_KO`)를 같이 둬요.

표는 손으로 적은 게 아니라 HenrikDev `/valorant/v1/content`를 `locale=en-US`와 `ko-KR`로
각각 받아서 **맵 id로 짝지어** 뽑은 값이에요(2026-10-03 확인). 그래서 라이엇 공식 한글
표기와 같아요.

⚠️ 맵 로테이션은 시즌마다 바뀌어요. 새 맵이 들어오면 `MAPS`와 `EN_TO_KO` 둘 다 고쳐야 해요.
⚠️ 한글 이름을 바꾸면 이미 쌓인 내전 기록(`scrim_matches.map`)과 어긋나서 맵별 전적이
   둘로 쪼개져요. 이름 변경은 신중하게.
"""

# `/맵추천`과 내전 맵 고르기에 뜨는 목록이에요. **5대5로 돌리는 맵만** 넣어요.
# (데스매치/난투/사격장 맵은 내전 맵이 아니라서 제외해요)
MAPS = [
    "어센트", "바인드", "브리즈", "프랙처", "헤이븐",
    "아이스박스", "로터스", "펄", "스플릿", "선셋", "어비스", "코로드", "서밋",
]

# 경기 데이터(영문) → 화면 표기(한글). 5대5 맵뿐 아니라 데스매치·난투 맵까지 담아둬요.
# `mode=custom`으로 받으면 난투/데스매치가 섞여 들어오는데, 걸러낼 때 이름이 필요해요.
EN_TO_KO = {
    "Ascent": "어센트",
    "Bind": "바인드",
    "Breeze": "브리즈",
    "Fracture": "프랙처",
    "Haven": "헤이븐",
    "Icebox": "아이스박스",
    "Lotus": "로터스",
    "Pearl": "펄",
    "Split": "스플릿",
    "Sunset": "선셋",
    "Abyss": "어비스",
    "Corrode": "코로드",
    "Summit": "서밋",
    # 아래는 5대5 맵이 아니에요(데스매치·팀데스매치·난투·사격장·이벤트).
    "District": "디스트릭트",
    "Kasbah": "카즈바",
    "Drift": "드리프트",
    "Piazza": "피아자",
    "Glitch": "글리치",
    "Gauntlet": "건틀릿",
    "Skirmish A": "난투 A",
    "Skirmish B": "난투 B",
    "Skirmish C": "난투 C",
    "Skirmish D": "난투 D",
    "Skirmish E": "난투 E",
    "Basic Training": "기초 훈련",
    "The Range": "사격장",
}

# 디스코드 Select 컴포넌트는 옵션을 25개까지만 담을 수 있어요.
MAX_SELECT_OPTIONS = 25


def is_known(name: str | None) -> bool:
    """`/맵추천`·내전 맵 목록(5대5)에 있는 한글 이름인지."""
    return bool(name) and name in MAPS


def to_korean(name: str | None) -> str | None:
    """경기 데이터의 영문 맵 이름을 한글로 바꿔요.

    표에 없는 이름(새로 나온 맵)은 **그대로 돌려줘요.** None으로 버리면 그 경기의 맵 기록이
    통째로 사라지는데, 영문으로라도 남기면 나중에 표만 채워서 복구할 수 있어요.
    이미 한글이면 그대로 나가요(두 번 호출해도 안전해요)."""
    if not name:
        return None
    return EN_TO_KO.get(name, name)


def sort_key(name: str) -> tuple[int, str]:
    """맵 목록 순서대로 정렬하되, 로테이션에서 빠진 옛 맵은 뒤로 보내요."""
    try:
        return (0, f"{MAPS.index(name):02d}")
    except ValueError:
        return (1, name)
