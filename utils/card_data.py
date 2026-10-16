"""🎴 카드 도감 데이터 — `scripts/build_card_assets.py`가 생성해요. 직접 고치지 마세요.

원본 아트는 `Desktop\악귀카드수정본`이고, 이 파일과 `assets/cards/*.webp`는
그 폴더를 스크립트로 변환한 결과예요. 아트가 갱신되면 스크립트를 다시 돌리세요.
"""

# 등급 -> 카드 목록. key는 파일명(ASCII), name은 보여줄 한글 이름이에요.
CARDS: dict[str, list[dict]] = {
    "일반": [
        {
            "key": "n01",
            "name": "VP악귀",
            "file": "n01.webp"
        },
        {
            "key": "n02",
            "name": "내전악귀",
            "file": "n02.webp"
        },
        {
            "key": "n03",
            "name": "노래악귀",
            "file": "n03.webp"
        },
        {
            "key": "n04",
            "name": "눈팅악귀",
            "file": "n04.webp"
        },
        {
            "key": "n05",
            "name": "랭크악귀",
            "file": "n05.webp"
        },
        {
            "key": "n06",
            "name": "맵악귀",
            "file": "n06.webp"
        },
        {
            "key": "n07",
            "name": "미션악귀",
            "file": "n07.webp"
        },
        {
            "key": "n08",
            "name": "볼륨악귀",
            "file": "n08.webp"
        },
        {
            "key": "n09",
            "name": "스킨악귀",
            "file": "n09.webp"
        },
        {
            "key": "n10",
            "name": "스킵악귀",
            "file": "n10.webp"
        },
        {
            "key": "n11",
            "name": "알림악귀",
            "file": "n11.webp"
        },
        {
            "key": "n12",
            "name": "야행성악귀",
            "file": "n12.webp"
        },
        {
            "key": "n13",
            "name": "오상악귀",
            "file": "n13.webp"
        },
        {
            "key": "n14",
            "name": "일반전악귀",
            "file": "n14.webp"
        },
        {
            "key": "n15",
            "name": "잠수악귀",
            "file": "n15.webp"
        },
        {
            "key": "n16",
            "name": "절약악귀",
            "file": "n16.webp"
        },
        {
            "key": "n17",
            "name": "정모악귀",
            "file": "n17.webp"
        },
        {
            "key": "n18",
            "name": "지각악귀",
            "file": "n18.webp"
        },
        {
            "key": "n19",
            "name": "출석악귀",
            "file": "n19.webp"
        },
        {
            "key": "n20",
            "name": "칭호악귀",
            "file": "n20.webp"
        },
        {
            "key": "n21",
            "name": "코인악귀",
            "file": "n21.webp"
        },
        {
            "key": "n22",
            "name": "퇴근악귀",
            "file": "n22.webp"
        },
        {
            "key": "n23",
            "name": "팀짜기악귀",
            "file": "n23.webp"
        },
        {
            "key": "n24",
            "name": "포켓몬악귀",
            "file": "n24.webp"
        }
    ],
    "레어": [
        {
            "key": "r01",
            "name": "대박악귀",
            "file": "r01.webp"
        },
        {
            "key": "r02",
            "name": "막차악귀",
            "file": "r02.webp"
        },
        {
            "key": "r03",
            "name": "새벽수호자",
            "file": "r03.webp"
        },
        {
            "key": "r04",
            "name": "수집악귀",
            "file": "r04.webp"
        },
        {
            "key": "r05",
            "name": "에이스악귀",
            "file": "r05.webp"
        },
        {
            "key": "r06",
            "name": "역배악귀",
            "file": "r06.webp"
        },
        {
            "key": "r07",
            "name": "연승악귀",
            "file": "r07.webp"
        },
        {
            "key": "r08",
            "name": "연패악귀",
            "file": "r08.webp"
        },
        {
            "key": "r09",
            "name": "올인악귀",
            "file": "r09.webp"
        },
        {
            "key": "r10",
            "name": "정모생존자",
            "file": "r10.webp"
        },
        {
            "key": "r11",
            "name": "중복악귀",
            "file": "r11.webp"
        },
        {
            "key": "r12",
            "name": "캐리악귀",
            "file": "r12.webp"
        },
        {
            "key": "r13",
            "name": "코인부자",
            "file": "r13.webp"
        },
        {
            "key": "r14",
            "name": "클러치악귀",
            "file": "r14.webp"
        },
        {
            "key": "r15",
            "name": "트롤악귀",
            "file": "r15.webp"
        },
        {
            "key": "r16",
            "name": "파산악귀",
            "file": "r16.webp"
        }
    ],
    "에픽": [
        {
            "key": "e01",
            "name": "균열발생",
            "file": "e01.webp"
        },
        {
            "key": "e02",
            "name": "금지된채널",
            "file": "e02.webp"
        },
        {
            "key": "e03",
            "name": "눈꽃정원",
            "file": "e03.webp"
        },
        {
            "key": "e04",
            "name": "달빛도서관",
            "file": "e04.webp"
        },
        {
            "key": "e05",
            "name": "무지개다리",
            "file": "e05.webp"
        },
        {
            "key": "e06",
            "name": "바람의언덕",
            "file": "e06.webp"
        },
        {
            "key": "e07",
            "name": "벛꽃연회",
            "file": "e07.webp"
        },
        {
            "key": "e08",
            "name": "별빛등대",
            "file": "e08.webp"
        },
        {
            "key": "e09",
            "name": "별빛정원",
            "file": "e09.webp"
        },
        {
            "key": "e10",
            "name": "보물창고개방",
            "file": "e10.webp"
        },
        {
            "key": "e11",
            "name": "붉은달",
            "file": "e11.webp"
        },
        {
            "key": "e12",
            "name": "서버대정전",
            "file": "e12.webp"
        },
        {
            "key": "e13",
            "name": "서버유성우",
            "file": "e13.webp"
        },
        {
            "key": "e14",
            "name": "서버축제",
            "file": "e14.webp"
        },
        {
            "key": "e15",
            "name": "소원분수",
            "file": "e15.webp"
        },
        {
            "key": "e16",
            "name": "악귀경매장",
            "file": "e16.webp"
        },
        {
            "key": "e17",
            "name": "악귀보물섬",
            "file": "e17.webp"
        },
        {
            "key": "e18",
            "name": "악귀시장",
            "file": "e18.webp"
        },
        {
            "key": "e19",
            "name": "악귀열차",
            "file": "e19.webp"
        },
        {
            "key": "e20",
            "name": "악귀온천",
            "file": "e20.webp"
        },
        {
            "key": "e21",
            "name": "악귀운동회",
            "file": "e21.webp"
        },
        {
            "key": "e22",
            "name": "악귀일식",
            "file": "e22.webp"
        },
        {
            "key": "e23",
            "name": "악귀재판",
            "file": "e23.webp"
        },
        {
            "key": "e24",
            "name": "악귀침공",
            "file": "e24.webp"
        },
        {
            "key": "e25",
            "name": "안개의오아시스",
            "file": "e25.webp"
        },
        {
            "key": "e26",
            "name": "약속의별",
            "file": "e26.webp"
        },
        {
            "key": "e27",
            "name": "운명의룰렛",
            "file": "e27.webp"
        },
        {
            "key": "e28",
            "name": "코인폭우",
            "file": "e28.webp"
        },
        {
            "key": "e29",
            "name": "폭주봇",
            "file": "e29.webp"
        },
        {
            "key": "e30",
            "name": "황금시간",
            "file": "e30.webp"
        }
    ],
    "레전드": [
        {
            "key": "l01",
            "name": "긴코악귀",
            "file": "l01.webp"
        },
        {
            "key": "l02",
            "name": "나쁜말악귀",
            "file": "l02.webp"
        },
        {
            "key": "l03",
            "name": "막내악귀",
            "file": "l03.webp"
        },
        {
            "key": "l04",
            "name": "새따르악귀",
            "file": "l04.webp"
        },
        {
            "key": "l05",
            "name": "새벽악귀",
            "file": "l05.webp"
        },
        {
            "key": "l06",
            "name": "수호악귀",
            "file": "l06.webp"
        },
        {
            "key": "l07",
            "name": "알바악귀",
            "file": "l07.webp"
        },
        {
            "key": "l08",
            "name": "음침악귀",
            "file": "l08.webp"
        },
        {
            "key": "l09",
            "name": "줍줍악귀",
            "file": "l09.webp"
        },
        {
            "key": "l10",
            "name": "침묵악귀",
            "file": "l10.webp"
        },
        {
            "key": "l11",
            "name": "통금악귀",
            "file": "l11.webp"
        },
        {
            "key": "l12",
            "name": "펭귄악귀",
            "file": "l12.webp"
        },
        {
            "key": "l13",
            "name": "피방악귀",
            "file": "l13.webp"
        }
    ]
}


# key -> (등급, 이름) 역인덱스. 보유 목록을 그릴 때 등급을 되찾는 데 써요.
BY_KEY: dict[str, tuple[str, str]] = {
    c['key']: (grade, c['name'])
    for grade, cards in CARDS.items()
    for c in cards
}

TOTAL = len(BY_KEY)
