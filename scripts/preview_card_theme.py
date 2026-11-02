# -*- coding: utf-8 -*-
"""🎴 카드 테마를 **실제로 뽑아봐요** (2026-11-03). 디스코드 없이 PNG만 만들어요.

    python scripts/preview_card_theme.py              # 전체 테마
    python scripts/preview_card_theme.py 오로라        # 하나만
    python scripts/preview_card_theme.py --out 경로    # 저장 위치 바꾸기

## 🚨 왜 꼭 뽑아봐야 하나

캐릭터 테마는 **남이 넣은 그림** 위에 글씨를 얹어요. 색 값만 봐서는 읽히는지 알 수 없어요.
만들면서 실제로 뽑아보고 **두 가지 결함**을 찾았어요 — 둘 다 숫자로는 안 보였어요:

1. 🚨 밝은 그림에서 **패널이 중간 회색**이 돼서 보조 글씨가 안 읽혔어요
   → `card_theme_assets._cap()`으로 파생 색에 상한을 걸었어요
2. 🚨 오른쪽 위 **워터마크가 그림에 묻혔어요**
   → 그림 테마일 때만 글씨에 검은 테두리를 둘러요

그러니 캐릭터를 추가할 때마다 이걸 돌려서 **눈으로** 확인하세요.
특히 **밝은 그림**이나 **오른쪽 위가 복잡한 그림**을 조심하세요.
"""
import argparse
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from utils import profile_card as pc                 # noqa: E402

# 글씨가 길거나 많을 때를 보려고 일부러 꽉 채운 표본이에요.
SAMPLE = {
    "name": "피츄민영", "title": "악귀대장", "title_color": (255, 200, 80),
    "tier": "다이아몬드 2", "accent_color": (120, 160, 255), "riot_id": "akgui#KR1",
    "valorant": {"kd": 1.24, "winRate": 56, "hs": 22, "matches": 20},
    "coin": 137,
    "record": {"wins": 12, "losses": 7, "win_rate": 63.2, "best_streak": 5},
    "streak_now": "현재 2연승", "agwi": 1840, "agwi_grade": "A등급",
    "achievements": 23, "achievements_total": 50,
    "attendance": 71, "attendance_streak": 9, "season": "S1",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("themes", nargs="*", help="테마 이름 (없으면 전부)")
    ap.add_argument("--out", default=os.path.join(BOT_DIR, "backups", "theme_preview"))
    args = ap.parse_args()

    names = args.themes or list(pc.ALL_THEMES)
    unknown = [n for n in names if n not in pc.ALL_THEMES]
    if unknown:
        sys.exit(f"🚨 모르는 테마: {unknown}\n   있는 것: {list(pc.ALL_THEMES)}")

    os.makedirs(args.out, exist_ok=True)
    for name in names:
        png = pc._render({**SAMPLE, "theme": name}, None)
        path = os.path.join(args.out, f"{name}.png")
        with open(path, "wb") as f:
            f.write(png)
        kind = "🎴 캐릭터" if pc.is_character(name) else "🎨 색"
        print(f"  {kind} {name:<10} {len(png)/1024:>5.0f}KB  {pc.price_of(name)}코인  → {path}")
    print(f"\n✅ {len(names)}장. 열어서 **글씨가 읽히는지** 꼭 눈으로 보세요.")


if __name__ == "__main__":
    main()
