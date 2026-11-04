# -*- coding: utf-8 -*-
"""🎴 세로 팬아트를 **카드 비율(1000x560)로 합성**해요 (2026-11-04).

## 🚨 왜 필요한가 — 원본을 그대로 넣으면 안 돼요

요청으로 들어오는 그림은 거의 **세로**예요(휴대폰 스크린샷·팬아트). 그런데 카드는
**1000x560 가로**라, `profile_card._cover_resize`가 꽉 채우려고 **세로를 잘라요.**

실측(`IMG_5014.png` 385x546):

    2.60배 확대 → 1000x1418 → 세로 214~774만 보임 (원본의 15%~55%)

⒜ 385픽셀 폭을 1000으로 늘리니 **뭉개지고** ⒝ 얼굴 위아래가 **잘리고**
⒞ 글씨 영역(왼쪽 62%)에 `SCRIM_LEFT=0.90`이 덮여서 **캐릭터가 거기 있으면 안 보여요.**

🚨 `card_theme_assets._validate`는 **너무 작은 그림을 아예 빼요**(가로 500·세로 280 미만).
   385x546짜리를 그냥 넣으면 **상점에 안 뜨고** 로그에만 경고가 남아요.

## ⭐ 그래서 이렇게 합성해요

    ┌───────────────────────────────┬──────────────┐
    │ 흐린 배경(원본에서 뽑은 색·반짝임)   │  선명한 원본    │
    │ ← 글씨가 얹히는 자리(스크림 0.90)   │  ← 보이는 자리  │
    └───────────────────────────────┴──────────────┘
                                   x=620부터 밝아져요

- 인물은 **오른쪽**에 세로를 꽉 채워 놓아요(확대율 1.0배 언저리 = 안 뭉개져요)
- 왼쪽은 원본을 **cover + 블러**한 배경이라 색·분위기가 이어져요
- 둘 사이는 **가로 그라데이션으로 섞어서** 이음매가 안 보여요

## 쓰는 법

    python scripts/make_card_theme.py <그림> --key 사이퍼 --emoji 🎀 --desc "설명"
    python scripts/make_card_theme.py <그림> --key 사이퍼 ... --register   # themes.json까지

🚨 만든 뒤에는 **반드시** `python scripts/preview_card_theme.py <key>` 로 카드를 뽑아
   눈으로 보세요 — 색 값만 봐서는 글씨가 읽히는지 알 수 없어요.
"""
import argparse
import json
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from PIL import Image, ImageEnhance, ImageFilter     # noqa: E402

from utils import card_theme_assets as cta           # noqa: E402

CARD_W, CARD_H = cta.CARD_SIZE

# 🚨 이 값들은 `profile_card`에서 가져와야 어긋나지 않아요(스크림이 거기 있어요).
from utils.profile_card import SCRIM_HOLD            # noqa: E402

# 인물을 놓을 자리. 스크림이 옅어지기 시작하는 x(=SCRIM_HOLD)보다 **오른쪽**이어야
# 얼굴이 어둠에 안 묻혀요. 폭이 남으면 오른쪽 끝에 붙여요.
FEATHER = 150          # 인물 왼쪽 가장자리를 섞는 폭(px)
BG_BLUR = 28           # 배경 블러 세기
BG_DIM = 0.82          # 배경을 살짝 눌러 인물이 떠 보이게


def _cover(img: "Image.Image", size: tuple[int, int]) -> "Image.Image":
    """비율을 지키며 꽉 채우고 넘치는 쪽을 잘라요 (object-fit: cover)."""
    tw, th = size
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    new = (max(1, round(sw * scale)), max(1, round(sh * scale)))
    img = img.resize(new, Image.LANCZOS)
    off_x = (new[0] - tw) // 2
    off_y = (new[1] - th) // 2
    return img.crop((off_x, off_y, off_x + tw, off_y + th))


def compose(src_path: str, zoom: float = 1.0, shift_y: int = 0) -> "Image.Image":
    """🚨 `zoom`·`shift_y`가 필요한 이유 — **카드의 빈 자리는 "ㄴ"자 모양**이에요.

    실제로 뽑아보니 통계 패널 4개가 `y≈215~335`를, 업적 바가 `y≈355~440`을,
    **가로 955px까지** 덮어요. 그림이 온전히 보이는 곳은
    ⒜ **오른쪽 위 모서리**(`y<210`) ⒝ 오른쪽 끝 띠 ⒞ 업적 바 아래뿐이에요.

    그래서 인물을 세로에 딱 맞추면 **얼굴만 보이고 몸통은 패널에 가려요.**
    `zoom`으로 키우고 `shift_y`로 올려 **얼굴·소품을 ⒜ 자리에** 앉혀요.
    """
    with Image.open(src_path) as raw:
        src = raw.convert("RGB")

    # ① 배경 — 원본을 카드 비율로 덮고 흐리게. 색·반짝임이 이어져요.
    bg = _cover(src, (CARD_W, CARD_H)).filter(ImageFilter.GaussianBlur(BG_BLUR))
    bg = ImageEnhance.Brightness(bg).enhance(BG_DIM)

    # ② 인물 — 세로를 카드에 맞춰요(zoom으로 키울 수 있어요).
    sw, sh = src.size
    scale = CARD_H / sh * zoom
    fig = src.resize((max(1, round(sw * scale)), max(1, round(sh * scale))),
                     Image.LANCZOS)
    # 넘치는 세로는 **아래를 잘라요** — 얼굴이 위에 있으니까요. shift_y로 미세조정.
    if fig.size[1] > CARD_H:
        top = max(0, min(fig.size[1] - CARD_H, shift_y))
        fig = fig.crop((0, top, fig.size[0], top + CARD_H))
    fw = fig.size[0]

    # 너무 넓으면(가로 그림) 가운데를 잘라서 오른쪽 자리에 맞춰요.
    max_w = CARD_W - int(CARD_W * SCRIM_HOLD) + FEATHER
    if fw > max_w:
        off = (fw - max_w) // 2
        fig = fig.crop((off, 0, off + max_w, CARD_H))
        fw = max_w

    left = CARD_W - fw          # 오른쪽 끝에 붙여요
    # ③ 이음매 — 왼쪽 FEATHER만큼 서서히 나타나게 해요(세로줄이 안 생겨요).
    mask = Image.new("L", (fw, 1), 255)
    for x in range(min(FEATHER, fw)):
        mask.putpixel((x, 0), int(255 * (x / max(1, FEATHER))))
    mask = mask.resize((fw, CARD_H))

    out = bg.copy()
    out.paste(fig, (left, 0), mask)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="원본 그림 경로")
    ap.add_argument("--key", required=True, help="테마 이름 (상점에 뜨는 이름)")
    ap.add_argument("--emoji", default="🎴")
    ap.add_argument("--desc", default="")
    ap.add_argument("--register", action="store_true",
                    help="themes.json에 줄까지 추가해요")
    ap.add_argument("--zoom", type=float, default=1.0,
                    help="인물 확대율 (1.0=세로 꽉. 키우면 얼굴이 커져요)")
    ap.add_argument("--shift-y", type=int, default=0,
                    help="zoom>1일 때 위에서 잘라낼 픽셀 (0=머리 끝까지 보여요)")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        sys.exit(f"🚨 그림이 없어요: {args.source}")

    with Image.open(args.source) as probe:
        print(f"원본: {probe.size[0]}x{probe.size[1]} {probe.mode}")

    out = compose(args.source, zoom=args.zoom, shift_y=args.shift_y)
    cta.THEME_DIR.mkdir(parents=True, exist_ok=True)
    dest = cta.THEME_DIR / f"{args.key}.png"
    out.save(dest, "PNG", optimize=True)
    print(f"✅ 합성: {dest}  ({out.size[0]}x{out.size[1]} · "
          f"{dest.stat().st_size // 1024}KB)")

    # 🚨 **검증은 로더 코드 그대로** 돌려요. 여기에 규칙을 베껴 적으면 어긋나요.
    why = cta._validate(dest)
    if why:
        sys.exit(f"🚨 로더가 이 그림을 뺄 거예요: {why}")
    print("✅ _validate 통과 (상점에 뜰 크기예요)")

    colors = cta._dominant(dest)
    print(f"   패널 파생색 top={colors[0]} bottom={colors[1]}" if colors
          else "   ⚠️ 색을 못 뽑았어요 — 기본 남색으로 그려져요")

    entry = {"key": args.key, "emoji": args.emoji,
             "desc": args.desc or f"{args.key} 테마", "image": dest.name}
    line = json.dumps(entry, ensure_ascii=False, indent=2)

    if not args.register:
        print("\nthemes.json 에 넣을 줄 (--register 로 자동 추가):")
        print(line)
        return 0

    entries = cta._load_manifest()
    if any(str(e.get("key")) == args.key for e in entries):
        print(f"\n⚠️ '{args.key}'는 이미 목록에 있어요 — 그림만 덮어썼어요.")
    else:
        entries.append(entry)
        cta.MANIFEST.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"\n✅ themes.json 에 '{args.key}' 추가 ({len(entries)}종)")

    print("\n다음: python scripts/check_card_themes.py"
          f" → python scripts/preview_card_theme.py {args.key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
