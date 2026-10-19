"""🎣 "한 사람당 동시에 한 판만" 가드 검증. 실제 DB·디스코드 없이 돌아가요.

    python scripts/test_fishing_guard.py

## 무엇을 막으려고 만들었나

`/낚시`를 연달아 쳐서 찌를 여러 개 띄워두고 기다리는 방법이 있었어요. 코인이 복제되는
건 아니었지만(내구도는 던질 때마다 정직하게 깎여요), **입질 대기라는 유일한 속도 제한이
무력화**됐어요. 10-18 실측으로 한 사람이 낚시대를 중앙 2초 간격으로 147개 사며
서버 전체 캐스트의 47%를 혼자 돌리고 있었어요.

## 🚨 여기서 제일 중요한 검사

막는 것보다 **갇히지 않는 것**이에요. 플래그가 안 풀리면 그 사람은 낚시를 영영 못 해요.
그래서 "예외가 나도 풀린다"와 "TTL이 지나면 저절로 풀린다"를 반드시 같이 봐요.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("MONGODB_DB_NAME", "agwi_fish_test")

from cogs import fishing  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


class FakeResponse:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, content, **kw):
        self.sent.append(content)


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeInteraction:
    """가드가 보는 것만 흉내내요 — user.id 와 response.send_message."""

    def __init__(self, uid):
        self.user = FakeUser(uid)
        self.response = FakeResponse()


USER_A, USER_B = 111, 222


async def main():
    # ── ⒜ 한 판이 도는 중에 또 던지면 거절 ──────────────────────────────
    print("⒜ 동시 2판 시도")
    release = asyncio.Event()
    calls = []

    async def slow_cast(interaction, *, edit):
        calls.append(interaction.user.id)
        await release.wait()
        return True

    fishing._run_cast = slow_cast

    first = FakeInteraction(USER_A)
    task = asyncio.create_task(fishing.run_cast(first, edit=False))
    await asyncio.sleep(0.05)          # 첫 판이 가드를 잡을 틈을 줘요

    second = FakeInteraction(USER_A)
    blocked = await fishing.run_cast(second, edit=False)

    check("두 번째 던지기가 거절된다", blocked is False)
    check("안쪽 로직이 한 번만 불린다", len(calls) == 1, f"{len(calls)}회")
    check("거절 안내가 간다", any("이미 찌를 던져뒀어요" in s for s in second.response.sent))
    check("🚨 거절된 쪽은 낚시대를 안 쓴다 (안쪽 진입 자체가 없음)", USER_A not in calls[1:])

    # ── ⒝ 다른 사람은 영향 없음 ─────────────────────────────────────────
    print("\n⒝ 다른 사람은 막히지 않는다")
    other = FakeInteraction(USER_B)
    task_b = asyncio.create_task(fishing.run_cast(other, edit=False))
    await asyncio.sleep(0.05)
    check("B는 진입한다", USER_B in calls, f"calls={calls}")

    release.set()
    await task
    await task_b

    # ── ⒞ 판이 끝나면 다시 가능 ────────────────────────────────────────
    print("\n⒞ 판이 끝나면 다시 던질 수 있다")
    check("가드가 비워졌다", USER_A not in fishing._casting)

    async def quick_cast(interaction, *, edit):
        calls.append(interaction.user.id)
        return True

    fishing._run_cast = quick_cast
    again = await fishing.run_cast(FakeInteraction(USER_A), edit=False)
    check("다시 던질 수 있다", again is True)

    # ── ⒟ 🚨 예외가 나도 갇히지 않는다 ──────────────────────────────────
    print("\n⒟ 🚨 안쪽에서 예외가 나도 플래그가 풀린다")

    async def boom_cast(interaction, *, edit):
        raise RuntimeError("낚시 도중 터짐 시뮬레이션")

    fishing._run_cast = boom_cast
    try:
        await fishing.run_cast(FakeInteraction(USER_A), edit=False)
    except RuntimeError:
        pass
    check("예외 뒤에도 가드가 비어 있다", USER_A not in fishing._casting,
          f"_casting={fishing._casting}")

    fishing._run_cast = quick_cast
    recovered = await fishing.run_cast(FakeInteraction(USER_A), edit=False)
    check("예외 뒤에도 다시 던질 수 있다", recovered is True)

    # ── ⒠ 🚨 TTL — 플래그가 어떤 이유로 남아도 저절로 풀린다 ─────────────
    print("\n⒠ 🚨 플래그가 남아도 TTL이 지나면 풀린다")
    import time as _time

    # finally가 안 돌았다고 가정하고 **오래된** 플래그를 심어요.
    fishing._casting[USER_A] = _time.monotonic() - fishing.CAST_GUARD_TTL - 1
    freed = await fishing.run_cast(FakeInteraction(USER_A), edit=False)
    check("TTL이 지난 플래그는 무시된다", freed is True,
          f"TTL={fishing.CAST_GUARD_TTL:.0f}초")

    # 아직 안 지난 플래그는 그대로 막혀야 해요(TTL이 너무 짧으면 가드가 무의미해져요).
    fishing._casting[USER_B] = _time.monotonic()
    still = await fishing.run_cast(FakeInteraction(USER_B), edit=False)
    check("TTL 안쪽 플래그는 계속 막는다", still is False)
    fishing._casting.pop(USER_B, None)

    # ── ⒡ TTL이 한 판 길이보다 넉넉한가 ────────────────────────────────
    print("\n⒢ TTL 길이 점검")
    one_round = fishing.BITE_MAX + fishing.STRIKE_WAIT
    check("TTL이 한 판 최대 길이보다 길다", fishing.CAST_GUARD_TTL > one_round,
          f"TTL {fishing.CAST_GUARD_TTL:.0f}초 > 한 판 최대 {one_round:.1f}초")
    check("TTL이 과하게 길지 않다 (갇혀도 1분 안에 풀림)", fishing.CAST_GUARD_TTL <= 60,
          f"{fishing.CAST_GUARD_TTL:.0f}초")

    # 가드 딕셔너리가 새지 않는지
    check("가드 딕셔너리가 비어 있다 (누수 없음)", not fishing._casting,
          f"{fishing._casting}")


asyncio.run(main())

print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
