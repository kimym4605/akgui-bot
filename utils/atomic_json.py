"""JSON 파일을 안전하게(원자적으로) 쓰기 위한 공용 헬퍼예요.

⚠️ 왜 필요한가 (2026-09-04):
예전엔 저장하는 곳마다 이렇게 했어요.

    DATA_FILE.write_text(json.dumps(data), encoding="utf-8")   # 또는 open(..., "w") + json.dump

이건 **파일을 먼저 0바이트로 비우고 나서** 내용을 쓰는 동작이에요. 그 찰나에 프로세스가
죽으면 파일이 빈 채로/잘린 채로 남고, 다음 부팅 때 데이터가 통째로 사라진 것처럼 보여요.

이게 이론상의 위험이 아닌 이유:
  - 이 파일들은 전부 Fly 볼륨(`/app/data`)에 있고, 머신은 배포·재시작 때 언제든 죽어요.
  - `bot.py`의 워치독이 이벤트 루프가 멈추면 `os._exit(1)`로 **강제 종료**해요.
    복구 장치가 오히려 데이터를 깨뜨릴 수 있는 구조였어요.
  - `riot_session_store.json`이 깨지면 /오상 유저 전원이 로그아웃돼요.

그래서 "같은 폴더에 임시 파일로 다 쓰고 → fsync → os.replace로 갈아끼우기" 방식으로 바꿨어요.
`os.replace()`는 같은 파일시스템 안에서 원자적이라, 어느 순간에 죽어도 파일은 **옛 내용**이거나
**새 내용**이지 그 중간(빈 파일/잘린 JSON)이 될 수 없어요.
"""
import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def read_json(path, default=None):
    """JSON을 읽어요. 파일이 없거나 깨져 있으면 default를 돌려줘요(예외 안 던짐)."""
    path = Path(path)
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("JSON 읽기 실패, 기본값으로 진행해요 (%s): %s", path, e)
        return default


_STALE_TEMP_AGE_SECONDS = 3600


def _sweep_stale_temps(path: Path):
    """교체 직전에 프로세스가 죽으면 임시파일이 남아요. 오래된 것만 치워요.

    1시간이라는 여유를 두는 이유: 지금 다른 스레드가 쓰고 있는 임시파일을
    실수로 지우면 안 되기 때문이에요.
    """
    import time

    cutoff = time.time() - _STALE_TEMP_AGE_SECONDS
    try:
        for leftover in path.parent.glob(f".{path.name}.*.tmp"):
            try:
                if leftover.stat().st_mtime < cutoff:
                    leftover.unlink()
                    log.info("남아있던 임시파일을 정리했어요: %s", leftover.name)
            except OSError:
                pass
    except OSError:
        pass


def write_json(path, data):
    """JSON을 원자적으로 써요. 쓰다가 죽어도 기존 파일은 안 망가져요."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 임시 파일은 반드시 **같은 폴더**에 만들어야 해요.
    # /tmp 등 다른 파일시스템에 만들면 os.replace가 원자적이지 않아요.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())  # 디스크에 실제로 내려간 걸 확인하고 나서 갈아끼워요
        os.replace(tmp_name, path)  # ★ 원자적 교체
        _sweep_stale_temps(path)
    except BaseException:
        # 실패하면 임시 파일을 남기지 않아요(볼륨에 쓰레기가 쌓이지 않게).
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
