"""henrik_api 레이트리밋이 '서버가 알려준 잔여량'을 따르는지 확인해요.

2026-10-05에 고친 부분이에요. 그 전에는 우리 쪽 카운터만 믿어서, 봇이 자기 한도의 1/6만
썼는데도("봇 집계 4/28회") 429를 맞고 미션 자동판정의 64%가 실패하고 있었어요.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import henrik_api

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


async def main():
    print("1) 서버 잔여량을 모르면 예전처럼 우리 카운터만 쓴다")
    lim = henrik_api._RateLimiter(limit=5, window=60.0)
    for _ in range(5):
        await asyncio.wait_for(lim.acquire(), timeout=1)
    check("한도까지는 즉시 통과", lim.snapshot()["used"] == 5, str(lim.snapshot()))

    print("2) 잔여량이 여유로우면 통과한다")
    lim = henrik_api._RateLimiter(limit=28, window=60.0)
    lim.note_server_state(remaining=20, reset_seconds=60.0)
    await asyncio.wait_for(lim.acquire(), timeout=1)
    check("잔여 20 -> 통과", True)

    print("3) ⭐ 우리 카운터는 여유로워도 서버 잔여량이 바닥이면 막는다")
    lim = henrik_api._RateLimiter(limit=28, window=60.0)
    # 봇은 2회밖에 안 썼지만(= 예전 로그의 "4/28" 상황) 서버는 얼마 안 남았다고 말한다.
    await lim.acquire()
    await lim.acquire()
    lim.note_server_state(remaining=henrik_api.RESERVE_HEADROOM, reset_seconds=60.0)
    blocked = False
    try:
        await asyncio.wait_for(lim.acquire(), timeout=0.4)
    except asyncio.TimeoutError:
        blocked = True
    check("잔여 <= RESERVE_HEADROOM 이면 대기", blocked,
          f"used={lim.snapshot()['used']}, server_remaining={lim.snapshot()['server_remaining']}")

    print("4) 창이 지나면 낡은 잔여량은 버리고 다시 보낸다")
    lim = henrik_api._RateLimiter(limit=28, window=60.0)
    lim.note_server_state(remaining=0, reset_seconds=0.2)
    await asyncio.sleep(0.3)
    passed = False
    try:
        await asyncio.wait_for(lim.acquire(), timeout=0.5)
        passed = True
    except asyncio.TimeoutError:
        pass
    check("리셋 후 통과", passed)

    print("5) 응답 전에 연달아 나가도 낙관적으로 미리 깎는다")
    lim = henrik_api._RateLimiter(limit=28, window=60.0)
    lim.note_server_state(remaining=henrik_api.RESERVE_HEADROOM + 2, reset_seconds=60.0)
    await lim.acquire()
    await lim.acquire()
    blocked = False
    try:
        await asyncio.wait_for(lim.acquire(), timeout=0.4)
    except asyncio.TimeoutError:
        blocked = True
    check("여유분을 다 쓰면 세 번째는 대기", blocked,
          f"server_remaining={lim.snapshot()['server_remaining']}")

    print("6) 헤더 파서")
    class FakeResp:
        def __init__(self, h):
            self.headers = h
    check("remaining 읽기", henrik_api._remaining_of(FakeResp({"x-ratelimit-remaining": "21"})) == 21)
    check("remaining 없으면 None", henrik_api._remaining_of(FakeResp({})) is None)
    check("remaining 이상값은 None", henrik_api._remaining_of(FakeResp({"x-ratelimit-remaining": "?"})) is None)
    check("reset 읽기", henrik_api._reset_seconds(FakeResp({"x-ratelimit-reset": "41"})) == 41.0)

    print("7) 백그라운드 작업은 재시도 대기를 길게 줄 수 있다")
    import inspect
    sig = inspect.signature(henrik_api.request)
    check("request에 max_retry_wait 인자 있음", "max_retry_wait" in sig.parameters)
    check("기본값은 짧게 유지", sig.parameters["max_retry_wait"].default == henrik_api.MAX_RETRY_WAIT_SECONDS)
    src = inspect.getsource(sys.modules["cogs.mission"]) if "cogs.mission" in sys.modules else ""
    if not src:
        with open(os.path.join(os.path.dirname(__file__), "..", "cogs", "mission.py"), encoding="utf-8") as f:
            src = f.read()
    check("미션 자동판정이 긴 대기를 넘긴다", "max_retry_wait=90.0" in src)


asyncio.run(main())
print()
if failures:
    print(f"실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("전부 통과")
