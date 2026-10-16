"""🎴 카드 뽑기용 이미지·레지스트리 생성기 — 원본 아트를 봇이 쓸 형태로 바꿔요.

## 왜 변환이 필요한가

원본(`Desktop\악귀카드수정본`)은 **273MB**예요. 해상도가 제각각이고(975×1465가 대부분인데
5장은 4063×6108짜리 25메가픽셀) 장당 2.7~20MB짜리 PNG거든요.

그대로 쓸 수 없는 이유가 둘이에요.
1. **Fly 머신이 256MB**예요(`fly.toml`). 25메가픽셀 PNG 하나를 Pillow로 열면 RGBA로
   약 100MB를 먹어요 — 뽑기 한 번에 봇이 죽어요.
2. 도커 이미지에 273MB가 들어가면 배포가 느려지고 디스크도 먹어요.

그래서 **긴 변 768px WebP**로 줄여요. 83장 전부 합쳐 6~8MB면 끝나요.

## 왜 crop이 아니라 contain인가

원본 비율이 0.597~0.667로 조금씩 달라요. 고정 2:3으로 맞추려면 자르거나 늘여야 하는데,
카드 아트는 테두리·글씨가 가장자리에 있어서 **자르면 잘린 게 보여요**. `ImageOps.contain`은
비율을 지키며 안쪽에 맞추니 왜곡도 손실도 없어요. 디스코드는 각 이미지를 자기 비율대로
띄우니 몇 px 차이는 눈에 안 띄어요.

## 알파를 지키는 이유

원본이 RGBA고 alpha 최소값이 0이에요 — **실제로 투명한 픽셀이 있어요**(둥근 모서리·글로우).
RGB로 납작하게 만들면 그 자리가 검게 나와서 WebP도 알파를 그대로 들고 가요.

## 파일명을 ASCII 키로 바꾸는 이유

원본은 `레전드_긴코 악귀.png`처럼 한글에 공백까지 있어요. 디스코드 첨부 파일명으로 쓰면
클라이언트에 따라 깨지고, `attachment://` URL 참조도 불안해요. 그래서 파일은 `l01.webp`
같은 ASCII 키로 두고, **보여줄 한글 이름은 레지스트리에** 담아요.

## 쓰는 법

    python scripts/build_card_assets.py

`assets/cards/*.webp` 와 `utils/card_data.py`(레지스트리)를 덮어써요. 아트가 갱신되면
원본 폴더만 바꿔놓고 다시 돌리면 돼요.
"""
import collections
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageOps

SRC = Path(r"C:\Users\user\Desktop\악귀카드수정본")
ROOT = Path(__file__).resolve().parent.parent
OUT_IMG = ROOT / "assets" / "cards"
OUT_PY = ROOT / "utils" / "card_data.py"

# 긴 변 기준. 디스코드가 임베드 이미지를 보여주는 크기(최대 ~600px 폭)를 생각하면
# 768이면 고화질로 충분하고, 더 키워도 화면에선 차이가 안 보여요.
MAX_LONG_SIDE = 768
WEBP_QUALITY = 82

# 등급 -> (키 접두어, 표시 순서). 접두어는 파일명이 되니 ASCII여야 해요.
GRADES = {
    "일반": "n",
    "레어": "r",
    "에픽": "e",
    "레전드": "l",
}


def main() -> int:
    if not SRC.is_dir():
        print(f"❌ 원본 폴더가 없어요: {SRC}")
        return 1

    # 등급별로 모아요. 접두어가 없는 파일은 등급을 알 수 없으니 건너뛰어요
    # (2026-10-16 시점에 `역배악귀.png`가 `레어_역배악귀.png`와 md5가 같은 중복 사본으로
    #  들어있었어요 — 접두어 없는 건 전부 이런 사고라 조용히 무시하지 말고 찍어줘요).
    buckets: dict[str, list[Path]] = collections.defaultdict(list)
    skipped: list[str] = []
    for path in sorted(SRC.glob("*.png")):
        grade, sep, _ = path.stem.partition("_")
        if not sep or grade not in GRADES:
            skipped.append(path.name)
            continue
        buckets[grade].append(path)

    if skipped:
        print(f"⚠️  등급 접두어가 없어 건너뜀 ({len(skipped)}장): {', '.join(skipped)}")

    OUT_IMG.mkdir(parents=True, exist_ok=True)
    # 이전 실행의 잔재를 지워요. 아트가 줄었을 때 옛 파일이 남아 레지스트리에 없는
    # 유령 카드 이미지가 되는 걸 막아요.
    for old in OUT_IMG.glob("*.webp"):
        old.unlink()

    registry: dict[str, list[dict]] = {}
    total_src = total_out = 0

    for grade, prefix in GRADES.items():
        paths = buckets.get(grade, [])
        cards = []
        for i, path in enumerate(paths, start=1):
            key = f"{prefix}{i:02d}"
            name = path.stem.split("_", 1)[1].replace(" ", "")   # "긴코 악귀" -> "긴코악귀"
            dest = OUT_IMG / f"{key}.webp"

            with Image.open(path) as im:
                im = im.convert("RGBA")
                # contain = 비율 유지하며 박스 안에 맞춤 (잘림·왜곡 없음)
                im = ImageOps.contain(im, (MAX_LONG_SIDE, MAX_LONG_SIDE), Image.LANCZOS)
                im.save(dest, "WEBP", quality=WEBP_QUALITY, method=6)

            total_src += path.stat().st_size
            total_out += dest.stat().st_size
            cards.append({"key": key, "name": name, "file": dest.name})

        registry[grade] = cards
        print(f"  {grade:4s} {len(cards):2d}장")

    _write_registry(registry)

    print(f"\n✅ {sum(len(v) for v in registry.values())}장 변환")
    print(f"   {total_src / 1024 / 1024:.1f}MB → {total_out / 1024 / 1024:.1f}MB "
          f"({total_out / total_src * 100:.1f}%)")
    print(f"   이미지: {OUT_IMG.relative_to(ROOT)}")
    print(f"   레지스트리: {OUT_PY.relative_to(ROOT)}")
    return 0


def _write_registry(registry: dict[str, list[dict]]) -> None:
    """`utils/card_data.py`를 생성해요.

    JSON 파일이 아니라 **파이썬 모듈**로 내보내는 이유는 `utils/achievement_data.py`가
    이미 같은 방식이기 때문이에요(런타임 파일 읽기·경로 문제가 아예 없어요).
    """
    body = json.dumps(registry, ensure_ascii=False, indent=4)
    OUT_PY.write_text(
        '"""🎴 카드 도감 데이터 — `scripts/build_card_assets.py`가 생성해요. 직접 고치지 마세요.\n'
        "\n"
        "원본 아트는 `Desktop\악귀카드수정본`이고, 이 파일과 `assets/cards/*.webp`는\n"
        "그 폴더를 스크립트로 변환한 결과예요. 아트가 갱신되면 스크립트를 다시 돌리세요.\n"
        '"""\n\n'
        "# 등급 -> 카드 목록. key는 파일명(ASCII), name은 보여줄 한글 이름이에요.\n"
        f"CARDS: dict[str, list[dict]] = {body}\n\n\n"
        "# key -> (등급, 이름) 역인덱스. 보유 목록을 그릴 때 등급을 되찾는 데 써요.\n"
        "BY_KEY: dict[str, tuple[str, str]] = {\n"
        "    c['key']: (grade, c['name'])\n"
        "    for grade, cards in CARDS.items()\n"
        "    for c in cards\n"
        "}\n\n"
        "TOTAL = len(BY_KEY)\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
