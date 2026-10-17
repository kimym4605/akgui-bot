"""🩺 bot.py의 메모리 계측 검증.

## 왜 이 테스트가 있나

2026-10-17, 메모리 계측을 배포하고 로그를 봤는데 한 줄도 없었어요. 코드 결함으로
의심했지만 **아니었어요 - 기동 28초 뒤에 봤을 뿐이고, 첫 보고는 10분 뒤 예정이었어요.**

🚨 **계측 코드는 "언제 찍히나"까지가 기능이에요.** 파서만 테스트해두면(그때 그랬어요)
간격 로직이 틀려도, 반대로 **멀쩡한데 틀렸다고 오진해도** 알 수가 없어요.
실제로 두 번째 쪽으로 헛걸음했어요. 그래서 시점을 숫자로 못 박아요.

그 과정에서 고친 실제 문제 하나: `_last_mem_report = 0.0`으로 시작하면 리눅스에서
`time.monotonic()`이 **부팅 후 경과초**라, 첫 보고가 "프로세스 기동 +10분"이 아니라
"**VM 부팅** +10분"이 돼요. 치명적이진 않지만 간격이 예측 불가라 추세를 못 읽어요.
지금은 스레드 시작 때 기준선을 한 줄 찍고 `monotonic()`으로 맞춰요.

## 쓰는 법

    python scripts/test_mem_report.py
"""
import io
import os
import re
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        failures.append(label)


SRC = (BOT_DIR / "bot.py").read_text(encoding="utf-8")


def _load(names):
    """bot.py에서 함수/상수만 떼어 실행해요.

    ⚠️ bot.py를 그대로 import하면 디스코드에 로그인하려 들어요. 계측 부분만
    잘라내서 돌려요."""
    start = SRC.index("MEM_REPORT_INTERVAL")
    end = SRC.index("class MainBot")
    ns = {"os": os, "time": __import__("time")}
    exec(SRC[start:end], ns)
    return {n: ns[n] for n in names}


# ==================================================================
print("\n[1] /proc/meminfo 파싱")
# ------------------------------------------------------------------
env = _load(["_meminfo_mb", "_report_memory", "MEM_WARN_MB", "MEM_REPORT_INTERVAL"])

FAKE = b"""MemTotal:         249608 kB
MemFree:           12345 kB
MemAvailable:      40960 kB
SwapTotal:        524284 kB
SwapFree:         400000 kB
"""


class _FakeOpen:
    """`/proc/meminfo`만 가로채요. 다른 파일은 그대로 열려야 해요."""

    def __init__(self, payload):
        self.payload = payload
        self.real = __builtins__["open"] if isinstance(__builtins__, dict) \
            else __builtins__.open

    def __enter__(self):
        outer = self

        def fake(path, *a, **k):
            if str(path) == "/proc/meminfo":
                if outer.payload is None:
                    raise OSError("no such file")
                return io.BytesIO(outer.payload)
            return outer.real(path, *a, **k)

        if isinstance(__builtins__, dict):
            __builtins__["open"] = fake
        else:
            __builtins__.open = fake
        return self

    def __exit__(self, *exc):
        if isinstance(__builtins__, dict):
            __builtins__["open"] = self.real
        else:
            __builtins__.open = self.real


with _FakeOpen(FAKE):
    got = env["_meminfo_mb"]()
check("MemAvailable·SwapFree를 MB로 읽는다", got is not None
      and abs(got[0] - 40.0) < 0.1 and abs(got[1] - 390.6) < 0.2,
      f"{tuple(round(v, 1) for v in got) if got else None}")

with _FakeOpen(b"MemFree: 100 kB\n"):
    check("MemAvailable이 없으면 None (옛 커널)", env["_meminfo_mb"]() is None)

with _FakeOpen(None):
    check("/proc가 없으면 None (윈도우 로컬 실행)", env["_meminfo_mb"]() is None)


# ==================================================================
print("\n[2] 🚨 언제 찍히나")
# ------------------------------------------------------------------
# `_last_mem_report = 0.0`으로 두면 리눅스에서 monotonic()이 부팅 후 경과초라
# 첫 보고가 "프로세스 기동 +10분"이 아니라 "VM 부팅 +10분"이 돼요.

check("스레드 시작 직후 기준선을 한 줄 남긴다",
      re.search(r"def _watchdog_thread.*?_report_memory\(\)",
                SRC, re.S) is not None)

m = re.search(r"def _watchdog_thread.*?_report_memory\(\)\s*\n"
              r"\s*_last_mem_report = time\.monotonic\(\)", SRC, re.S)
check("🚨 기준선 직후 _last_mem_report를 monotonic()으로 맞춘다",
      m is not None,
      "0.0으로 두면 첫 보고 시점이 VM 부팅 시각에 좌우돼요")

# 부팅 직후(monotonic이 작음) / 오래 켜둠(큼) 양쪽에서 간격이 같아야 해요.
for boot_elapsed in (12.0, 50_000.0):
    last = boot_elapsed                      # 수정된 코드: 기준선 찍고 now로 맞춤
    fired = []
    t = boot_elapsed
    for _ in range(180):                     # 10초 간격 × 180 = 30분
        t += 10.0
        if t - last >= env["MEM_REPORT_INTERVAL"]:
            last = t
            fired.append(round(t - boot_elapsed))
    check(f"monotonic={boot_elapsed:.0f}일 때 30분간 보고 3회",
          fired == [600, 1200, 1800], f"{fired}")

# 반대로 **옛 버전**(0.0 시작)은 어떻게 깨졌나 - 회귀 방지용 재현
for boot_elapsed, expect in ((12.0, "프로세스 기준 10분이 아님"),
                             (50_000.0, "기동 10초 만에 찍힘")):
    last = 0.0
    fired = []
    t = boot_elapsed
    for _ in range(180):
        t += 10.0
        if t - last >= env["MEM_REPORT_INTERVAL"]:
            last = t
            fired.append(round(t - boot_elapsed))
    broken = fired[:1] != [600]
    check(f"(옛 버전 재현) monotonic={boot_elapsed:.0f} -> {expect}", broken,
          f"첫 보고 {fired[:3]}")


# ==================================================================
print("\n[3] 🚨 락 없는 쓰기 - 멈춤 중에도 찍혀야 한다")
# ------------------------------------------------------------------
# 멈춘 스레드가 logging 락을 쥔 채 굳으면, 로그를 찍으려는 순간 워치독까지
# 같이 멈춰요. 하필 "모든 게 멈췄을 때 동작해야 하는 코드"예요.
_rm = SRC.index("def _report_memory")
# ⚠️ `class MainBot`까지 자르면 사이에 있는 `_beat_loop`의 `log.info`까지 잡혀서
#    멀쩡한 코드가 FAIL로 나와요. **다음 최상위 정의까지만** 잘라요.
#    🚨 `"\ndef "`만 찾으면 안 돼요 - 바로 다음이 `async def _beat_loop`라
#    그걸 건너뛰고 더 뒤까지 삼켜버려요(이것 때문에 한 번 오탐이 났어요).
_next = re.search(r"\n(?:async )?def ", SRC[_rm + 1:])
body = SRC[_rm:_rm + 1 + _next.start()]
check("_report_memory는 os.write(2, ...)를 쓴다", "os.write(2" in body)
check("_report_memory는 logging/print를 쓰지 않는다",
      "log." not in body and "print(" not in body)

stall = SRC[SRC.index("🚨 워치독: 이벤트 루프가"):SRC.index("os._exit(1)")]
check("멈춤 감지 시에도 메모리를 남긴다", "_report_memory()" in stall)


# ==================================================================
print("\n[4] 경고 임계값")
# ------------------------------------------------------------------
with _FakeOpen(FAKE):
    r, w = os.pipe()
    saved = os.dup(2)
    os.dup2(w, 2)
    try:
        env["_report_memory"]()
    finally:
        os.dup2(saved, 2)
        os.close(w)
        os.close(saved)
        out = os.read(r, 4096).decode("utf-8", "replace")
        os.close(r)
check("여유 40MB(<48)면 🚨가 붙는다", "🚨" in out, out.strip())
check("숫자가 사람이 읽을 형태로 들어간다", "40MB" in out and "391MB" in out,
      out.strip())


# ==================================================================
print("\n[5] 🚨 스왑 추세 - RAM만 보면 놓치는 신호")
# ------------------------------------------------------------------
# 2026-10-17에 실제로 놓쳤던 것: 여유 RAM은 10~46MB에서 진동만 하는데(= 꽉 찬 채 평평)
# 스왑 여유가 3시간 20분에 434 → 368MB로 단조 감소하고 있었어요. 512MB로 올린 뒤에는
# 여유가 넉넉해 [4]의 경고가 아예 안 뜨니, 같은 일이 또 나면 더더욱 안 보여요.
# 그래서 ① 한 줄에 기동 대비 증감이 들어가는지 ② 스왑이 마르면 🚨가 뜨는지를 못 박아요.


def _say(fn, payload):
    """`_report_memory()` 한 번의 stderr를 문자열로 받아와요."""
    with _FakeOpen(payload):
        r, w = os.pipe()
        saved = os.dup(2)
        os.dup2(w, 2)
        try:
            fn()
        finally:
            os.dup2(saved, 2)
            os.close(w)
            os.close(saved)
            got = os.read(r, 4096).decode("utf-8", "replace")
            os.close(r)
    return got.strip()


def _meminfo(avail_mb, swap_mb):
    return (f"MemTotal:         499216 kB\nMemAvailable:{avail_mb * 1024:>12} kB\n"
            f"SwapTotal:        524284 kB\nSwapFree:{swap_mb * 1024:>16} kB\n").encode()


# ⚠️ `_load`는 매번 새 네임스페이스에 실행하니, 새로 부르면 기준선도 초기화돼요.
#    같은 env로 연달아 부르면 **같은 프로세스가 계속 떠 있는 것**과 같아요.
fresh = _load(["_report_memory"])["_report_memory"]
first = _say(fresh, _meminfo(250, 434))
check("기동 첫 줄은 기동 대비 +0MB", "+0MB" in first, first)
check("여유·스왑 다 넉넉하면 🩺", first.startswith("🩺"), first)

later = _say(fresh, _meminfo(250, 368))
check("3시간 뒤 66MB 밀린 걸 한 줄에 적는다", "-66MB" in later, later)
check("아직 128MB 위면 경고는 안 띄운다", later.startswith("🩺"), later)

dry = _say(fresh, _meminfo(250, 100))
check("스왑 여유가 128MB 밑이면 🚨 (여유 RAM은 250MB로 멀쩡)",
      "🚨 스왑 고갈" in dry, dry)

# 둘 다 나쁠 때는 더 급한 쪽(RAM)을 띄워요 - 그쪽이 먼저 OOM으로 갑니다.
both = _say(_load(["_report_memory"])["_report_memory"], _meminfo(20, 50))
check("여유·스왑이 다 나쁘면 RAM 쪽을 띄운다", "🚨 여유 부족" in both, both)

print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
