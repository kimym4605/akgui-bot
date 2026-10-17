"""🎴 카드 도감 데이터 — `scripts/build_card_assets.py`가 생성해요. 직접 고치지 마세요.

원본 아트는 `Desktop\악귀카드수정본`이고, 이 파일과 `assets/cards/*.webp`는
그 폴더를 스크립트로 변환한 결과예요. 아트가 갱신되면 스크립트를 다시 돌리세요.
"""

# 등급 -> 카드 목록. key는 파일명(ASCII), name은 보여줄 한글 이름이에요.
CARDS: dict[str, list[dict]] = {
    "일반": [
        {
            "key": "n19",
            "name": "출석악귀",
            "file": "n19.webp",
            "no": 1
        },
        {
            "key": "n07",
            "name": "미션악귀",
            "file": "n07.webp",
            "no": 2
        },
        {
            "key": "n15",
            "name": "잠수악귀",
            "file": "n15.webp",
            "no": 3
        },
        {
            "key": "n12",
            "name": "야행성악귀",
            "file": "n12.webp",
            "no": 4
        },
        {
            "key": "n04",
            "name": "눈팅악귀",
            "file": "n04.webp",
            "no": 5
        },
        {
            "key": "n18",
            "name": "지각악귀",
            "file": "n18.webp",
            "no": 6
        },
        {
            "key": "n22",
            "name": "퇴근악귀",
            "file": "n22.webp",
            "no": 7
        },
        {
            "key": "n03",
            "name": "노래악귀",
            "file": "n03.webp",
            "no": 8
        },
        {
            "key": "n10",
            "name": "스킵악귀",
            "file": "n10.webp",
            "no": 9
        },
        {
            "key": "n08",
            "name": "볼륨악귀",
            "file": "n08.webp",
            "no": 10
        },
        {
            "key": "n05",
            "name": "랭크악귀",
            "file": "n05.webp",
            "no": 11
        },
        {
            "key": "n14",
            "name": "일반전악귀",
            "file": "n14.webp",
            "no": 12
        },
        {
            "key": "n13",
            "name": "오상악귀",
            "file": "n13.webp",
            "no": 13
        },
        {
            "key": "n09",
            "name": "스킨악귀",
            "file": "n09.webp",
            "no": 14
        },
        {
            "key": "n01",
            "name": "VP악귀",
            "file": "n01.webp",
            "no": 15
        },
        {
            "key": "n23",
            "name": "팀짜기악귀",
            "file": "n23.webp",
            "no": 16
        },
        {
            "key": "n06",
            "name": "맵악귀",
            "file": "n06.webp",
            "no": 17
        },
        {
            "key": "n02",
            "name": "내전악귀",
            "file": "n02.webp",
            "no": 18
        },
        {
            "key": "n21",
            "name": "코인악귀",
            "file": "n21.webp",
            "no": 19
        },
        {
            "key": "n16",
            "name": "절약악귀",
            "file": "n16.webp",
            "no": 20
        },
        {
            "key": "n20",
            "name": "칭호악귀",
            "file": "n20.webp",
            "no": 21
        },
        {
            "key": "n24",
            "name": "포켓몬악귀",
            "file": "n24.webp",
            "no": 22
        },
        {
            "key": "n17",
            "name": "정모악귀",
            "file": "n17.webp",
            "no": 23
        },
        {
            "key": "n11",
            "name": "알림악귀",
            "file": "n11.webp",
            "no": 24
        }
    ],
    "레어": [
        {
            "key": "r09",
            "name": "올인악귀",
            "file": "r09.webp",
            "no": 1
        },
        {
            "key": "r06",
            "name": "역배악귀",
            "file": "r06.webp",
            "no": 2
        },
        {
            "key": "r01",
            "name": "대박악귀",
            "file": "r01.webp",
            "no": 3
        },
        {
            "key": "r16",
            "name": "파산악귀",
            "file": "r16.webp",
            "no": 4
        },
        {
            "key": "r07",
            "name": "연승악귀",
            "file": "r07.webp",
            "no": 5
        },
        {
            "key": "r08",
            "name": "연패악귀",
            "file": "r08.webp",
            "no": 6
        },
        {
            "key": "r12",
            "name": "캐리악귀",
            "file": "r12.webp",
            "no": 7
        },
        {
            "key": "r15",
            "name": "트롤악귀",
            "file": "r15.webp",
            "no": 8
        },
        {
            "key": "r14",
            "name": "클러치악귀",
            "file": "r14.webp",
            "no": 9
        },
        {
            "key": "r05",
            "name": "에이스악귀",
            "file": "r05.webp",
            "no": 10
        },
        {
            "key": "r02",
            "name": "막차악귀",
            "file": "r02.webp",
            "no": 11
        },
        {
            "key": "r10",
            "name": "정모생존자",
            "file": "r10.webp",
            "no": 12
        },
        {
            "key": "r03",
            "name": "새벽수호자",
            "file": "r03.webp",
            "no": 13
        },
        {
            "key": "r13",
            "name": "코인부자",
            "file": "r13.webp",
            "no": 14
        },
        {
            "key": "r04",
            "name": "수집악귀",
            "file": "r04.webp",
            "no": 15
        },
        {
            "key": "r11",
            "name": "중복악귀",
            "file": "r11.webp",
            "no": 16
        }
    ],
    "에픽": [
        {
            "key": "e24",
            "name": "악귀침공",
            "file": "e24.webp",
            "no": 1
        },
        {
            "key": "e12",
            "name": "서버대정전",
            "file": "e12.webp",
            "no": 2
        },
        {
            "key": "e28",
            "name": "코인폭우",
            "file": "e28.webp",
            "no": 3
        },
        {
            "key": "e30",
            "name": "황금시간",
            "file": "e30.webp",
            "no": 4
        },
        {
            "key": "e02",
            "name": "금지된채널",
            "file": "e02.webp",
            "no": 5
        },
        {
            "key": "e18",
            "name": "악귀시장",
            "file": "e18.webp",
            "no": 6
        },
        {
            "key": "e14",
            "name": "서버축제",
            "file": "e14.webp",
            "no": 7
        },
        {
            "key": "e19",
            "name": "악귀열차",
            "file": "e19.webp",
            "no": 8
        },
        {
            "key": "e01",
            "name": "균열발생",
            "file": "e01.webp",
            "no": 9
        },
        {
            "key": "e17",
            "name": "악귀보물섬",
            "file": "e17.webp",
            "no": 10
        },
        {
            "key": "e13",
            "name": "서버유성우",
            "file": "e13.webp",
            "no": 11
        },
        {
            "key": "e16",
            "name": "악귀경매장",
            "file": "e16.webp",
            "no": 12
        },
        {
            "key": "e29",
            "name": "폭주봇",
            "file": "e29.webp",
            "no": 13
        },
        {
            "key": "e22",
            "name": "악귀일식",
            "file": "e22.webp",
            "no": 14
        },
        {
            "key": "e15",
            "name": "소원분수",
            "file": "e15.webp",
            "no": 15
        },
        {
            "key": "e23",
            "name": "악귀재판",
            "file": "e23.webp",
            "no": 16
        },
        {
            "key": "e27",
            "name": "운명의룰렛",
            "file": "e27.webp",
            "no": 17
        },
        {
            "key": "e21",
            "name": "악귀운동회",
            "file": "e21.webp",
            "no": 18
        },
        {
            "key": "e10",
            "name": "보물창고개방",
            "file": "e10.webp",
            "no": 19
        },
        {
            "key": "e11",
            "name": "붉은달",
            "file": "e11.webp",
            "no": 20
        },
        {
            "key": "e09",
            "name": "별빛정원",
            "file": "e09.webp",
            "no": 21
        },
        {
            "key": "e04",
            "name": "달빛도서관",
            "file": "e04.webp",
            "no": 22
        },
        {
            "key": "e07",
            "name": "벛꽃연회",
            "file": "e07.webp",
            "no": 23
        },
        {
            "key": "e25",
            "name": "안개의오아시스",
            "file": "e25.webp",
            "no": 24
        },
        {
            "key": "e03",
            "name": "눈꽃정원",
            "file": "e03.webp",
            "no": 25
        },
        {
            "key": "e06",
            "name": "바람의언덕",
            "file": "e06.webp",
            "no": 26
        },
        {
            "key": "e20",
            "name": "악귀온천",
            "file": "e20.webp",
            "no": 27
        },
        {
            "key": "e05",
            "name": "무지개다리",
            "file": "e05.webp",
            "no": 28
        },
        {
            "key": "e26",
            "name": "약속의별",
            "file": "e26.webp",
            "no": 29
        },
        {
            "key": "e08",
            "name": "별빛등대",
            "file": "e08.webp",
            "no": 30
        }
    ],
    "레전드": [
        {
            "key": "l06",
            "name": "수호악귀",
            "file": "l06.webp",
            "no": 1
        },
        {
            "key": "l02",
            "name": "나쁜말악귀",
            "file": "l02.webp",
            "no": 2
        },
        {
            "key": "l09",
            "name": "줍줍악귀",
            "file": "l09.webp",
            "no": 3
        },
        {
            "key": "l01",
            "name": "긴코악귀",
            "file": "l01.webp",
            "no": 4
        },
        {
            "key": "l05",
            "name": "새벽악귀",
            "file": "l05.webp",
            "no": 5
        },
        {
            "key": "l07",
            "name": "알바악귀",
            "file": "l07.webp",
            "no": 6
        },
        {
            "key": "l11",
            "name": "통금악귀",
            "file": "l11.webp",
            "no": 7
        },
        {
            "key": "l04",
            "name": "새따르악귀",
            "file": "l04.webp",
            "no": 8
        },
        {
            "key": "l12",
            "name": "펭귄악귀",
            "file": "l12.webp",
            "no": 9
        },
        {
            "key": "l03",
            "name": "막내악귀",
            "file": "l03.webp",
            "no": 10
        },
        {
            "key": "l08",
            "name": "음침악귀",
            "file": "l08.webp",
            "no": 11
        },
        {
            "key": "l10",
            "name": "침묵악귀",
            "file": "l10.webp",
            "no": 12
        },
        {
            "key": "l13",
            "name": "피방악귀",
            "file": "l13.webp",
            "no": 13
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
