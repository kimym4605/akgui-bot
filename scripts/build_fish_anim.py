# -*- coding: utf-8 -*-
"""🎣 낚시 기다리기·입질 GIF를 만들어 `assets/fish/anim/`에 저장해요 (2026-11-22).

    python scripts/build_fish_anim.py            # 저장
    python scripts/build_fish_anim.py --preview  # 저장 + 대물·전설 튀어오르기 미리보기(저장소 밖 물고기그림 폴더)

그림을 고치면(`utils/fish_anim.py`) 이걸 다시 돌려서 파일을 새로 만들고 같이 커밋해요.
"""
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from utils import fish_anim  # noqa: E402
from utils.fish_data import FISH  # noqa: E402

fish_anim.ANIM_DIR.mkdir(parents=True, exist_ok=True)
for path, fn in ((fish_anim.WAIT_FILE, fish_anim.render_wait), (fish_anim.BITE_FILE, fish_anim.render_bite)):
    data = fn()
    path.write_bytes(data)
    print(f"{path.name}: {len(data) // 1024}KB")

if "--preview" in sys.argv:
    out = os.path.join(BOT_DIR, "..", "물고기그림")
    os.makedirs(out, exist_ok=True)
    for grade in ("대물", "전설"):
        key = FISH[grade][0]["key"]
        data = fish_anim.render_catch(key, grade)
        if data:
            with open(os.path.join(out, f"튀어오르기_미리보기_{grade}.gif"), "wb") as f:
                f.write(data)
            print(f"튀어오르기 {grade}({key}): {len(data) // 1024}KB")
