# -*- coding: utf-8 -*-
"""🎰 Higgsfield로 뽑은 도박장 그림 → `assets/casino/*.webp`.

    python scripts/build_casino_assets.py <원본 png 폴더> [이름 ...]

| 원본 (폴더 안 파일)              | 결과                 | 처리 |
|---|---|---|
| `sym_bomb`·`sym_gun`·`sym_shield`·`sym_diamond`.png (1:1, 밝은 회색 단색 배경) | `sym_*.webp` 256×256 | 배경을 빼고(물고기와 같은 방식) 딱 맞게 앉혀요 |
| `hall.png` (16:9, 도박장 내부)   | `hall.webp` 800×450  | 줄이기만 해요 |
| `felt.png` (16:9, 블랙잭 테이블) | `felt.webp` 640×400  | **비율을 무시하고** 맞춰요(아래) |
| `cardback.png` (2:3, 카드 뒷면)  | `cardback.webp` 172×244 | 가장자리를 조금 잘라내고 맞춰요 |

⚠️ 테이블·카드 뒷면은 가운데를 자르지 않고 **살짝 눌러서** 맞춰요(가로 10%·5%). 둘 다
   가장자리에 금테 무늬가 있어서, 잘라 맞추면 위아래 테만 남고 좌우 테가 사라져요.
   무늬뿐인 그림이라 그 정도 눌림은 눈에 안 띄어요.
⚠️ 크기는 `utils/casino_art.py`의 `BJ_W/BJ_H`·`CARD_W/CARD_H`와 맞물려 있어요
   (`scripts/test_casino_art.py`가 같이 봐요).

📁 원본(1024px PNG, 7장 ≈ 10MB)은 저장소에 없어요. 상위 폴더 `악귀봇프로젝트/도박장그림/원본/`에
   **한글 이름**(`폭탄.png` · `도박장_배경.png` …)으로 보관해요 — 아래 `SOURCE_NAMES`가 짝을 알아요.
   화풍: Higgsfield Nano Banana 2, "애니 게임 아이템 아이콘 · 보라+금 카지노" 프롬프트.
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from build_fish_assets import cutout  # noqa: E402  (배경 빼기는 물고기와 같은 코드를 써요)

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(BOT_DIR, "assets", "casino")

SYMBOLS = ("sym_bomb", "sym_gun", "sym_shield", "sym_diamond")
SYMBOL_SIZE = 256
HALL_SIZE = (800, 450)
FELT_SIZE = (640, 400)          # = casino_art.BJ_W, BJ_H
CARDBACK_SIZE = (172, 244)      # = casino_art.CARD_W, CARD_H 의 2배
CARDBACK_TRIM = 0.025           # 원본 네 귀퉁이의 둥근 모서리 밖 여백을 잘라내요
# 결과 이름 → 보관 폴더의 원본 이름. 원본은 사람이 보는 폴더라 한글로 둬요(둘 다 받아요).
SOURCE_NAMES = {
    "sym_bomb": "폭탄", "sym_gun": "총", "sym_shield": "방패", "sym_diamond": "다이아",
    "hall": "도박장_배경", "felt": "블랙잭_테이블", "cardback": "카드_뒷면",
}


def _save(im: Image.Image, name: str, quality: int = 90) -> None:
    path = os.path.join(OUT_DIR, f"{name}.webp")
    im.save(path, "WEBP", quality=quality, method=6)
    print(f"✅ {name} {im.size[0]}×{im.size[1]} → {os.path.getsize(path) // 1024}KB")


def main() -> None:
    src_dir = sys.argv[1]
    only = set(sys.argv[2:])
    os.makedirs(OUT_DIR, exist_ok=True)

    def want(name: str) -> str | None:
        if only and name not in only and SOURCE_NAMES[name] not in only:
            return None
        for stem in (SOURCE_NAMES[name], name):
            path = os.path.join(src_dir, f"{stem}.png")
            if os.path.exists(path):
                return path
        print(f"⚠️ {SOURCE_NAMES[name]}.png (또는 {name}.png) 이 없어요 - 건너뛰어요")
        return None

    for name in SYMBOLS:
        if (path := want(name)):
            icon = cutout(path)
            pockets, rejected = icon.info.pop("pockets", 0), icon.info.pop("rejected", [])
            _save(icon.resize((SYMBOL_SIZE, SYMBOL_SIZE), Image.LANCZOS), name)
            if pockets or rejected:
                print(f"   안쪽 빈 공간 {pockets}곳 · 떨어진 큰 후보(넓이, 배경색 비율): {rejected}")
    if (path := want("hall")):
        _save(Image.open(path).convert("RGB").resize(HALL_SIZE, Image.LANCZOS), "hall", 88)
    if (path := want("felt")):
        _save(Image.open(path).convert("RGB").resize(FELT_SIZE, Image.LANCZOS), "felt", 88)
    if (path := want("cardback")):
        im = Image.open(path).convert("RGB")
        dx, dy = round(im.width * CARDBACK_TRIM), round(im.height * CARDBACK_TRIM)
        _save(im.crop((dx, dy, im.width - dx, im.height - dy)).resize(CARDBACK_SIZE, Image.LANCZOS), "cardback")


if __name__ == "__main__":
    main()
