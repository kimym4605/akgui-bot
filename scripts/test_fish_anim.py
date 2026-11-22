# -*- coding: utf-8 -*-
"""🎞️ 낚시 움직이는 그림 검사 (2026-11-22). DB·디스코드를 안 건드려요.

    python scripts/test_fish_anim.py

막으려는 사고:
- 그림을 고쳤는데 `assets/fish/anim/*.gif`를 다시 안 만들어 옛 그림이 배포되는 것
- 기다리기·입질 GIF가 한 번 돌고 멈추는 것(찌가 굳어 보여요) / 튀어오르기가 계속 반복되는 것
- 대물·전설 중 그림이 안 그려지는 종이 있는 것
- 파일이 너무 커서 던질 때마다 화면이 늦게 뜨는 것
- GIF 파일이 없을 때 지난 그림이 남는 것
"""
import io
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")     # 접속하지 않아요

from PIL import Image  # noqa: E402

from utils import fish_anim  # noqa: E402
from utils.fish_data import FISH  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


def info(data: bytes):
    im = Image.open(io.BytesIO(data))
    return im, im.n_frames, im.info.get("loop")


print("[1] 기다리기·입질 GIF (미리 만든 파일)")
for name, path, fn, frames in (("기다리기", fish_anim.WAIT_FILE, fish_anim.render_wait, fish_anim.WAIT_FRAMES),
                               ("입질", fish_anim.BITE_FILE, fish_anim.render_bite, fish_anim.BITE_FRAMES)):
    check(f"{name}: 파일이 있다", path.exists())
    if not path.exists():
        continue
    data = path.read_bytes()
    check(f"{name}: 🚨 저장된 파일 = 지금 코드로 그린 것 (그림을 고쳤으면 build_fish_anim.py를 다시 돌리세요)",
          data == fn())
    im, n, loop = info(data)
    check(f"{name}: 끝없이 돈다 (loop=0) · {n}장", loop == 0 and n == frames, f"loop={loop} n={n}")
    check(f"{name}: {im.size} · {len(data) // 1024}KB (150KB 안)", im.size == (fish_anim.W, fish_anim.H)
          and len(data) < 150 * 1024)
check("경로 함수가 파일을 가리킨다", fish_anim.wait_path() == fish_anim.WAIT_FILE
      and fish_anim.bite_path() == fish_anim.BITE_FILE)

print("[2] 🐟 튀어오르기 (대물·전설 전 종)")
big = [(grade, e["key"]) for grade in ("대물", "전설") for e in FISH[grade]]
sizes = []
for grade, key in big:
    data = fish_anim.render_catch(key, grade)
    if not data:
        check(f"{grade} {key}: 그려진다", False)
        continue
    im, n, loop = info(data)
    sizes.append(len(data))
    if loop is not None:
        check(f"{grade} {key}: 🚨 한 번만 돈다 (loop 없음)", False, f"loop={loop}")
check(f"대물·전설 {len(big)}종 모두 그려지고 한 번만 돈다", len(sizes) == len(big))
check(f"제일 큰 GIF {max(sizes) // 1024}KB (600KB 안)", sizes and max(sizes) < 600 * 1024)
im, n, _ = info(fish_anim.render_catch(big[0][1], big[0][0]))
durs = []
for i in range(n):
    im.seek(i)
    durs.append(im.info.get("duration", 0))
check(f"움직이는 시간 = catch_seconds() ({fish_anim.catch_seconds():.2f}초) · 마지막 장은 오래 붙든다",
      abs(sum(durs[:-1]) / 1000 - fish_anim.catch_seconds()) < 0.05 and durs[-1] >= 60_000, str(durs[-3:]))
check("그림이 없는 종이면 None (낚시는 원래 그림으로)", fish_anim.render_catch("zzz", "전설") is None)

print("[3] cogs.fishing 연결")
try:
    import discord
    from cogs import fishing
    e = discord.Embed(title="t")
    files = fishing.anim_file(e, fish_anim.wait_path(), fishing.WAIT_GIF_NAME)
    check("anim_file: 파일이 있으면 크게 걸고 한 장 붙인다",
          len(files) == 1 and files[0].filename == fishing.WAIT_GIF_NAME
          and e.image.url == f"attachment://{fishing.WAIT_GIF_NAME}")
    files = fishing.anim_file(e, None, fishing.BITE_GIF_NAME)
    check("anim_file: 🚨 파일이 없으면 그림 자리를 비우고 빈 목록 (지난 GIF가 남지 않게)",
          files == [] and not e.image.url)
    names = [fishing.WAIT_GIF_NAME, fishing.BITE_GIF_NAME, fishing.CATCH_GIF_NAME]
    check("첨부 이름 3개가 서로 다르고 .gif", len(set(names)) == 3 and all(n.endswith(".gif") for n in names))
except Exception as exc:                                     # noqa: BLE001
    check("cogs.fishing 불러오기", False, repr(exc))

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
