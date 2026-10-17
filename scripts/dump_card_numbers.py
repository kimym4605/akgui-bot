"""🔢 카드에 **그려진 번호**(C-015 등)를 눈으로 읽기 위한 시트를 만들어요.

## 왜 필요한가

카드 번호는 **파일명에도, 어떤 메타데이터에도 없고 그림 안에만** 있어요. 그래서
`build_card_assets.py`의 `CARD_NUMBERS` 표는 사람이 눈으로 읽어 채워야 해요.

83장을 한 장씩 열어 보는 건 느리니까, **좌상단 번호 뱃지만 잘라 등급별로 모아** 한
장짜리 시트로 만들어요. 2026-10-18에 이 방식으로 83장을 전부 읽었어요.

## 쓰는 법

    python scripts/dump_card_numbers.py
    # → scratchpad/nums_<등급>.png 4장이 생겨요. 열어서 번호를 읽고
    #   build_card_assets.py의 CARD_NUMBERS를 고친 뒤
    #   python scripts/build_card_assets.py --registry-only

⚠️ 라벨의 한글은 폰트가 없으면 네모로 깨져요. **키(n01…)는 ASCII라 멀쩡**하고, 순서도
`CARDS` 그대로라 위치로 짚으면 돼요 — 한글이 깨져도 작업에는 지장이 없어요.
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from utils.card_data import CARDS  # noqa: E402

OUT_DIR = Path(os.environ.get("CARD_NUM_OUT", ROOT / "build" / "cardnums"))
# 뱃지 위치(상대 좌표). 카드마다 폭이 510~519로 조금씩 달라서 절대 좌표는 못 써요.
BOX = (0.02, 0.025, 0.32, 0.105)
SCALE = 2
COLS = 2
LABEL_W = 150


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for grade, rows in CARDS.items():
        crops = []
        for c in rows:
            path = ROOT / "assets" / "cards" / c["file"]
            with Image.open(path) as im:
                w, h = im.size
                box = (int(w * BOX[0]), int(h * BOX[1]),
                       int(w * BOX[2]), int(h * BOX[3]))
                crop = im.crop(box).convert("RGB")
            crop = crop.resize((crop.width * SCALE, crop.height * SCALE), Image.LANCZOS)
            crops.append((c, crop))

        cw, ch = crops[0][1].size
        pad = 8
        nrows = -(-len(crops) // COLS)
        sheet = Image.new("RGB",
                          (COLS * (LABEL_W + cw + pad) + pad, nrows * (ch + pad) + pad),
                          "white")
        draw = ImageDraw.Draw(sheet)
        for i, (c, crop) in enumerate(crops):
            x = pad + (i % COLS) * (LABEL_W + cw + pad)
            y = pad + (i // COLS) * (ch + pad)
            # 지금 표에 적힌 번호도 같이 찍어줘요 — 바뀐 곳만 눈으로 찾으면 돼요.
            draw.text((x + 4, y + ch // 2 - 6),
                      f"{c['key']} (now {c.get('no', '?')}) {c['name']}", fill="black")
            sheet.paste(crop, (x + LABEL_W, y))
        dest = OUT_DIR / f"nums_{grade}.png"
        sheet.save(dest)
        print(f"  {grade:4s} {len(crops):2d}장 → {dest}")
    print(f"\n✅ 시트를 열어 번호를 읽고 build_card_assets.py의 CARD_NUMBERS를 고치세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
