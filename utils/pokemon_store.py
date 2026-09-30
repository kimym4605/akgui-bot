"""MongoDB 커넥션과 `trainers` 컬렉션을 다른 모듈에 나눠주는 공용 DB 모듈이에요.

## 이름이 왜 아직 pokemon_store인가

원래는 포켓몬 육성 데이터를 다루던 파일이었어요. 2026-09-30에 포켓몬 기능을 전부
접으면서 육성 로직은 다 걷어냈고, **DB 커넥션과 컬렉션 핸들을 내주는 역할만** 남았어요.
파일명을 바꾸면 이걸 import하는 저장소 모듈 10곳을 같이 고쳐야 해서 이름은 그대로 뒀어요.

## `trainers` 컬렉션은 이제 "악귀코인 계정"이에요

포켓몬을 시작했던 사람들의 문서가 그대로 남아 있고, 거기에 코인과 출석이 들어있어요.

    {"_id": "<디스코드 user_id 문자열>",
     "coin": int,                   # 악귀코인 잔액
     "attendance": int,             # 누적 출석 횟수
     "attendanceStreak": int,       # 연속 출석일수 (하루라도 빠지면 1로 리셋)
     "lastAttendanceDate": str|None}

포켓몬을 시작한 적 없는 사람은 이 컬렉션에 문서가 없고, 코인은 `coin_reset_backup`
컬렉션(=지갑)에 들어가요. `utils/coin_wallet.py`가 둘 중 맞는 곳을 알아서 골라줘요
— 판별 기준은 **문서 존재 여부**라서, 포켓몬 필드를 지운 뒤에도 그대로 동작해요.

⚠️ 이 모듈은 커넥션만 내줘요. 실제 읽기/쓰기는 각 저장소 모듈(coin_wallet,
attend_service, mission_store, ...)이 **필드 단위 update_one**으로 해요.
문서를 통째로 갈아끼우는 방식은 쓰지 마세요 — 그것 때문에 통화 중 `/출석`이
사라지고 연속 출석이 리셋되던 사고가 있었어요(2026-09-30 수정).
"""
import asyncio
import logging
import os
from datetime import timedelta, timezone

from pymongo import MongoClient

log = logging.getLogger(__name__)

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "pokemon_game")

# ------------------------------------------------------------------
# ⚠️ 동기 pymongo 사고 (2026-09-04)
#
# 예전엔 `MongoClient(MONGODB_URI)`로 끝이었고, DB 함수들도 전부 동기 함수라
# async 핸들러에서 그대로 불렸다. 문제가 두 겹이었다:
#
#  1) pymongo의 `socketTimeoutMS` 기본값은 **None = 무한 대기**다. 소켓이 한 번
#     멈추면(네트워크 블립, Atlas 페일오버, Fly NAT 끊김) 그 호출은 영원히 안 돌아온다.
#  2) 그 호출이 이벤트 루프 위에서 일어나니, 루프 전체가 같이 영구 정지한다.
#     → 봇이 통째로 먹통. 자체 복구 경로가 없어서 재시작만이 답이었다.
#
# 그래서 두 가지를 같이 고쳤다:
#  - 아래 타임아웃들로 "무한 대기"를 없앤다 (실패는 하되 멈추지는 않게).
#  - DB를 만지는 공개 함수는 async로 두고 실제 작업은 asyncio.to_thread로 넘긴다.
#    이제 DB가 느려도 이벤트 루프는 계속 돈다.
#    (이 규칙은 이 모듈을 쓰는 저장소 모듈들에도 그대로 적용된다)
# ------------------------------------------------------------------
_client = MongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=5_000,   # 서버 못 찾으면 5초 만에 포기 (기본 30초)
    connectTimeoutMS=5_000,           # 연결 수립 5초 (기본 20초)
    socketTimeoutMS=10_000,           # ★ 핵심: 기본값 None(무한) → 10초
    retryWrites=True,                 # 일시적 네트워크 오류는 드라이버가 1회 재시도
)
_db = _client[MONGODB_DB_NAME]
_trainers = _db["trainers"]

# 다른 저장소 모듈이 같은 커넥션 풀을 나눠 쓰라고 내놓는다. 머신 메모리가 256MB라
# 같은 Atlas에 클라이언트를 하나 더 띄우는 건 낭비다(위 타임아웃 설정도 그대로 물려받는다).
client = _client
db = _db

COIN_PER_ATTENDANCE = 1

KST = timezone(timedelta(hours=9))


async def ping_db() -> bool:
    """DB가 살아있는지 가볍게 확인해요. 부팅 때 한 번 불러서 설정 오류를 일찍 잡아요."""
    try:
        await asyncio.to_thread(_db.command, "ping")
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("MongoDB ping 실패: %s", e)
        return False
