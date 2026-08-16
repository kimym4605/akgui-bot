# 발로란트 디스코드 봇 스타터 (Python)

VS Code에서 폴더를 열어서 바로 시작할 수 있는 Python discord.py 봇 뼈대예요.
`cogs/` 폴더로 기능이 나뉘어 있어서, 새 기능을 추가하고 싶으면 이 폴더에
파일 하나만 추가하면 자동으로 인식돼요.

## 1. 사전 준비

- **Python 3.10 이상** 설치 → https://python.org
- **Discord Developer Portal**(https://discord.com/developers/applications)에서:
  1. New Application으로 앱 생성
  2. Bot 탭 → Reset Token으로 봇 토큰 발급 (`DISCORD_TOKEN`)
  3. OAuth2 → URL Generator에서 `bot`, `applications.commands` 체크 → 생성된 링크로 내 테스트 서버에 봇 초대
  4. 디스코드 앱에서 서버 우클릭 → ID 복사 (개발자 모드 켜야 보임) → `GUILD_ID`
- **HenrikDev API 키** (`/전적` 명령어용): https://docs.henrikdev.xyz 안내를 따라 Discord 서버 가입 후 발급 (승인 대기 없는 Basic 키로 충분해요)

## 2. 설치

```bash
python -m venv .venv
source .venv/bin/activate      # Windows는 .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. 환경변수 설정

```bash
cp .env.example .env
```
`.env` 파일을 열어서 값을 채워주세요.

## 4. 실행

```bash
python bot.py
```

콘솔에 `✅ (봇이름)(으)로 로그인 완료!`가 뜨면 성공이에요. (슬래시 명령어는 봇이 시작될 때 자동으로 등록돼요)

## 폴더 구조

```
discord-bot-starter-py/
├── cogs/       기능(명령어) 단위 파일. 파일 하나 = 명령어 하나
├── utils/      여러 명령어가 같이 쓰는 공용 함수
├── data/       로컬 저장 데이터 (실행하면 자동 생성돼요)
└── bot.py      봇 진입점
```

## 포함된 기능

| 명령어 | 설명 | 외부 API |
|---|---|---|
| `/핑` | 봇 상태·지연시간 확인 | 없음 |
| `/스킨검색 [이름]` | 발로란트 무기 스킨 검색 + 이미지 | valorant-api.com (인증 불필요) |
| `/팀짜기` | 음성채널 인원을 랜덤 2팀으로 분배 | 없음 |
| `/티어 등록`, `/티어 확인` | 자진 등록형 티어 프로필 카드 | 없음 (로컬 JSON 저장) |
| `/전적 [닉네임] [태그] [지역]` | **실제 라이엇 티어/RR/Elo 조회** | HenrikDev API (비공식, 서드파티) |

## `/전적`에 대해

이 명령어는 라이엇 공식 API가 아니라 **HenrikDev API**(`api.henrikdev.xyz`)라는 서드파티 서비스를 사용해요.

- 비밀번호나 로컬 발로란트 클라이언트가 전혀 필요 없어요 — 서버에 배포해서 24시간 돌려도 돼요
- 닉네임#태그만 알면 (본인이든 다른 사람이든) 조회 가능해요
- 다만 여전히 라이엇의 **공식 파트너는 아닌 서드파티 API**라는 점은 알아두세요. API 자체는 활발히
  유지보수되고 있고 많은 발로란트 봇들이 실제로 이걸 씁니다
- 무료(Basic) 키는 분당 30회 요청 제한이 있어요. 더 필요하면 문서에서 Advanced 키를 신청할 수 있어요
- 자세한 내용: https://docs.henrikdev.xyz

## 새 기능 추가하는 법

1. `cogs/` 폴더에 새 파일 생성 (예: `cogs/mapinfo.py`)
2. `ping.py`나 `skin.py`를 참고해서 `commands.Cog` 클래스와 `setup(bot)` 함수 작성
3. `python bot.py`로 재실행하면 자동으로 인식돼요
