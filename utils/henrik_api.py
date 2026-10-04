"""HenrikDev API(발로란트 전적 서드파티 API) 호출을 한 군데로 모으는 게이트웨이예요.

⚠️ 왜 만들었나 (2026-09-14 "Rate limit exceeded" 신고):

우리 API 키는 **분당 30회**가 한도인데, 그게 엔드포인트별이 아니라 **키 하나에 통째로**
걸려요. (`x-ratelimit-bucket`이 mmr·matches·store 전부 같은 값으로 내려와요)

그런데 `/전적` 한 번이 API를 **3회**(티어+경쟁전+일반전) 쓰고, 여기에 `/미션`·`/오늘의번들`도
같은 키를 나눠 써요. 저녁에 몇 명이 겹쳐 쓰거나 한 사람이 연타하면 10번 만에 한도가 차버려요.
게다가 예전엔 재시도도 캐시도 없어서, 한도가 차는 순간 HenrikDev가 준 영어 원문
("Rate limit exceeded, please try again later...")이 그대로 유저에게 나갔어요.

그래서 이 모듈이 네 가지를 맡아요:
  1. **속도 제한** - 봇 전체 호출을 분당 RATE_LIMIT_PER_MIN회로 묶어서 한도 자체를 안 넘겨요.
     넘칠 것 같으면 실패시키는 게 아니라 잠깐 기다렸다가 보내요(큐잉).
  2. **서버가 알려준 잔여량 따르기** - 아래 2026-10-05 문단 참고. 우리 계산보다 서버 말이 우선이에요.
  3. **응답 캐시** - 같은 요청은 CACHE_TTL_SECONDS초 동안 재사용해요. 연타가 API를 안 먹어요.
  4. **429 자동 재시도** - 그래도 막히면 응답 헤더가 알려주는 만큼 기다렸다가 한 번 더 시도해요.

⚠️ 2026-10-05 - 우리 계산만 믿으면 안 된다는 걸 실측으로 확인했어요:

운영 로그에서 **"봇 집계 4/28회"인데도 429**를 맞고 있었어요. 자기 한도의 1/6만 썼는데 막힌 거예요.
그래서 미션 자동판정의 전적 조회가 **64%(9건 중 5건 성공)** 실패하고 있었고, 미션 완료율이
14%에 머물러 있었어요. 직접 찔러보니 `v1/account` 1회는 잔여량을 1 깎는데 `v3/matches` 1회는
한 번에 여러 개가 깎이는 것처럼 보였어요(가중치인지 동시 호출인지는 확정 못 했어요).

원인을 확정하지 못해도 통하는 방법을 택했어요. **HenrikDev는 응답마다
`x-ratelimit-remaining`으로 "앞으로 몇 번 더 돼요"를 알려주는데, 우리는 그걸 안 읽고 있었어요.**
이제 매 응답에서 그 값을 읽어두고, 남은 횟수가 RESERVE_HEADROOM 이하면 창이 풀릴 때까지
스스로 멈춰요. 가중치 때문이든 다른 곳에서 같은 키를 써서든, 서버가 "얼마 안 남았다"고 하면
그 말을 그대로 따르는 거라 원인과 상관없이 막혀요.

호출부는 `(status, payload)` 튜플을 그대로 돌려받아요. 기존 코드와 모양이 같아요.
"""
import asyncio
import json
import logging
import time
from collections import deque

import aiohttp

log = logging.getLogger(__name__)

HENRIK_BASE = "https://api.henrikdev.xyz"

# 실제 한도는 분당 30회예요. 사람이 손으로 찔러보는 경우까지 고려해서 2회를 여유로 남겨둬요.
# (예전엔 웹 akgui-pokemon도 같은 키를 썼는데, 그건 2026-09-30에 종료됐어요.)
# ⚠️ 이 숫자는 어디까지나 "우리 쪽 추정"이에요. 진짜 기준은 서버가 주는 x-ratelimit-remaining이에요.
RATE_LIMIT_PER_MIN = 28
RATE_WINDOW_SECONDS = 60.0

# 서버가 알려준 잔여 호출수가 이 값 이하로 떨어지면, 창이 풀릴 때까지 새로 안 내보내요.
# 0으로 두면 "마지막 한 발"까지 쓰다가 경합에서 429를 맞아요. 몇 개는 남겨둬야 안전해요.
RESERVE_HEADROOM = 3

CACHE_TTL_SECONDS = 60.0  # 전적은 1분 사이에 바뀔 일이 거의 없어요.
REQUEST_TIMEOUT_SECONDS = 15.0  # 응답이 없을 때 이벤트 루프가 물리지 않게 반드시 걸어둬요.
MAX_RETRY_WAIT_SECONDS = 15.0  # 429가 이보다 더 기다리라고 하면 재시도를 포기해요.

# 429일 때 호출부가 "몇 초 뒤에 다시 시도하세요"를 안내할 수 있도록 payload에 끼워주는 키예요.
# HenrikDev가 주는 값이 아니라 우리가 헤더에서 읽어 넣는 값이라, 이름 앞에 _를 붙였어요.
RETRY_AFTER_KEY = "_retry_after"


class _RateLimiter:
    """최근 60초 동안 보낸 횟수를 세어서, 한도를 넘길 것 같으면 그만큼 재워두는 장치예요."""

    def __init__(self, limit: int, window: float):
        self._limit = limit
        self._window = window
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._blocked_until = 0.0  # 429를 맞으면 이 시각까지는 아무도 못 나가게 막아요.
        # 서버가 마지막으로 알려준 잔여 호출수와, 그 창이 풀리는 시각이에요.
        # None이면 "아직 들은 적 없음"이라서 우리 쪽 계산(_hits)만 써요.
        self._remaining: int | None = None
        self._remaining_reset_at = 0.0

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()

                # 창이 지났으면 서버에게 들은 잔여량은 더 이상 유효하지 않아요.
                if self._remaining is not None and now >= self._remaining_reset_at:
                    self._remaining = None

                if now < self._blocked_until:
                    wait = self._blocked_until - now
                elif self._remaining is not None and self._remaining <= RESERVE_HEADROOM:
                    # ⭐ 서버가 "얼마 안 남았다"고 하면 우리 계산이 여유롭더라도 멈춰요.
                    wait = self._remaining_reset_at - now + 0.05
                    log.debug(
                        "HenrikDev 잔여 %d회뿐이라 %.1f초 기다려요.", self._remaining, wait
                    )
                else:
                    # 창(60초) 밖으로 나간 기록은 버려요.
                    while self._hits and now - self._hits[0] >= self._window:
                        self._hits.popleft()

                    if len(self._hits) < self._limit:
                        self._hits.append(now)
                        # 응답이 오기 전에 다음 요청이 또 나가면 안 되니, 낙관적으로 미리 깎아둬요.
                        # 실제 값은 응답이 오는 대로 note_server_state()가 덮어써요.
                        if self._remaining is not None:
                            self._remaining -= 1
                        return

                    # 가장 오래된 기록이 창 밖으로 나가야 한 자리가 비어요.
                    wait = self._window - (now - self._hits[0]) + 0.05

            # ⚠️ 반드시 락을 놓고 자야 해요. 락을 쥔 채로 자면 그동안 다른 요청까지 전부 멈춰요.
            log.debug("HenrikDev 호출이 한도에 닿아서 %.1f초 대기해요.", wait)
            await asyncio.sleep(wait)

    def note_rate_limited(self, reset_seconds: float):
        """429를 맞았을 때, 그 시간만큼은 아예 안 내보내도록 표시해둬요."""
        self._blocked_until = max(self._blocked_until, time.monotonic() + reset_seconds)

    def note_server_state(self, remaining: int | None, reset_seconds: float):
        """응답 헤더가 알려준 '진짜' 잔여량을 받아둬요. 우리 추정보다 이게 우선이에요."""
        if remaining is None:
            return
        self._remaining = remaining
        self._remaining_reset_at = time.monotonic() + max(0.0, reset_seconds)

    def snapshot(self) -> dict:
        """지금 얼마나 썼는지 (로그/디버그용)."""
        now = time.monotonic()
        recent = sum(1 for t in self._hits if now - t < self._window)
        remaining = self._remaining if now < self._remaining_reset_at else None
        return {"used": recent, "limit": self._limit, "server_remaining": remaining}


_limiter = _RateLimiter(RATE_LIMIT_PER_MIN, RATE_WINDOW_SECONDS)
_cache: dict[str, tuple[float, int, dict]] = {}  # key -> (만료시각, status, payload)


def _cache_key(path: str, params: dict | None) -> str:
    return path + "?" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)


def _purge_expired(now: float):
    """오래된 캐시를 정리해요. 봇이 몇 주씩 떠 있으니 안 지우면 계속 쌓여요."""
    for key in [k for k, (expire_at, _, _) in _cache.items() if expire_at <= now]:
        _cache.pop(key, None)


def _reset_seconds(resp: aiohttp.ClientResponse) -> float:
    """응답 헤더가 알려주는 '몇 초 뒤에 풀리는지'를 읽어요. 없으면 넉넉히 60초로 봐요."""
    raw = resp.headers.get("x-ratelimit-reset") or resp.headers.get("retry-after")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return RATE_WINDOW_SECONDS


def _remaining_of(resp: aiohttp.ClientResponse) -> int | None:
    """'앞으로 몇 번 더 돼요'를 읽어요. 헤더가 없으면 None(=모름)이에요."""
    raw = resp.headers.get("x-ratelimit-remaining")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


async def _send(
    session: aiohttp.ClientSession, path: str, headers: dict, params: dict | None
) -> tuple[int, dict, float, int | None]:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with session.get(
        f"{HENRIK_BASE}{path}", headers=headers, params=params, timeout=timeout
    ) as resp:
        try:
            payload = await resp.json()
        except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError):
            # HenrikDev가 가끔 점검 중에 HTML을 뱉어요. 그때 json() 파싱에서 터지면
            # 호출부가 "status는 200인데 payload가 없다"로 헷갈리니 빈 dict로 맞춰줘요.
            payload = {}
        return resp.status, payload, _reset_seconds(resp), _remaining_of(resp)


async def request(
    session: aiohttp.ClientSession,
    path: str,
    *,
    headers: dict,
    params: dict | None = None,
    cache_ttl: float = CACHE_TTL_SECONDS,
    max_retry_wait: float = MAX_RETRY_WAIT_SECONDS,
) -> tuple[int, dict]:
    """HenrikDev에 GET을 보내고 `(status, payload)`를 돌려줘요.

    path는 "/valorant/v3/mmr/kr/pc/이름/태그"처럼 HENRIK_BASE 뒤에 붙을 부분만 주면 돼요.
    캐시가 살아있으면 API를 아예 안 쓰고 바로 돌려줘요(= 한도를 안 깎아요).

    `max_retry_wait`은 429를 맞았을 때 "몇 초까지 기다렸다 재시도할지"예요. 기본값은 사람이
    명령어 앞에서 기다리는 상황을 가정해 짧게 잡혀 있어요. **사람을 안 기다리게 하는
    백그라운드 작업(미션 자동판정 등)은 더 길게 줘야** 30~60초짜리 429에서 그냥 포기하지 않아요.
    """
    now = time.monotonic()
    key = _cache_key(path, params)

    cached = _cache.get(key)
    if cached is not None and cached[0] > now:
        log.debug("HenrikDev 캐시 적중: %s", path)
        return cached[1], cached[2]

    _purge_expired(now)

    await _limiter.acquire()
    status, payload, reset, remaining = await _send(session, path, headers, params)
    _limiter.note_server_state(remaining, reset)

    if status == 429:
        # 우리 쪽 계산보다 먼저 막혔어요. (호출 가중치나 다른 소비처 때문일 수 있어요)
        _limiter.note_rate_limited(reset)
        used = _limiter.snapshot()
        log.warning(
            "⚠️ HenrikDev 429 (봇 집계 %d/%d회, 서버 잔여 %s) - %.0f초 뒤 재시도해요: %s",
            used["used"], used["limit"], used["server_remaining"], reset, path,
        )
        if reset <= max_retry_wait:
            await asyncio.sleep(reset + 0.2)
            await _limiter.acquire()
            status, payload, reset, remaining = await _send(session, path, headers, params)
            _limiter.note_server_state(remaining, reset)

    if status == 429:
        # 재시도까지 실패했거나 너무 오래 기다려야 하는 경우. 호출부가 안내 문구에 쓰도록 초를 실어줘요.
        if isinstance(payload, dict):
            payload = {**payload, RETRY_AFTER_KEY: int(reset)}
        else:
            payload = {RETRY_AFTER_KEY: int(reset)}
        return status, payload

    if status == 200 and cache_ttl > 0:
        _cache[key] = (time.monotonic() + cache_ttl, status, payload)

    return status, payload


def retry_after_of(payload: dict) -> int:
    """429 payload에서 '몇 초 뒤에 다시 시도하면 되는지'를 꺼내요. 없으면 30초로 안내해요."""
    if isinstance(payload, dict):
        value = payload.get(RETRY_AFTER_KEY)
        if isinstance(value, int) and value > 0:
            return value
    return 30
