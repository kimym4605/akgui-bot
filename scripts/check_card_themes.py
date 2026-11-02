# -*- coding: utf-8 -*-
"""🎴 캐릭터 카드 테마를 **양방향으로** 대조해요 (2026-11-03).

## 쓰는 법 — 캐릭터를 추가하는 전체 절차

1. 그림을 `assets/card_themes/` 에 넣어요 (권장 **1000x560 PNG**)
2. `python scripts/check_card_themes.py` — 등록 안 된 그림을 찾아
   **붙여넣을 JSON 줄**을 그대로 뽑아줘요
3. 그 줄을 `assets/card_themes/themes.json` 에 넣어요
4. 다시 돌려서 ✅ 인지 보고, `python scripts/preview_card_theme.py <이름>` 으로
   **카드를 실제로 뽑아** 글씨가 읽히는지 눈으로 봐요
5. 배포하면 상점에 떠요

## 🚨 왜 양방향인가

**목록에만 있고 그림이 없으면** 그 테마는 기본 배경으로 그려져요 —
**25코인을 받고 아무 일도 안 일어나요.** (로더가 그런 항목을 빼긴 하지만,
빠졌다는 걸 사람이 알아야 고치죠.)
**그림만 있고 목록에 없으면** 넣어놓고 안 파는 거예요. 둘 다 사람이 알아야 해요.
⭐ `scripts/scan_guides.py`를 양방향으로 만들고 나서야 누락을 잡았던 것과 같은 이유예요.

종료코드: 문제가 있으면 1 (배포 관문에 넣을 수 있어요).
"""
import json
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from utils import card_theme_assets as cta          # noqa: E402

problems = []


def main() -> int:
    print(f"폴더: {cta.THEME_DIR}")
    if not cta.THEME_DIR.exists():
        print("  (아직 폴더가 없어요 — 캐릭터 테마 0종, 색 테마만 팔려요)")
        return 0

    images = sorted(p for p in cta.THEME_DIR.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    entries = cta._load_manifest()
    listed = {str(e.get("image") or ""): e for e in entries}
    loaded = cta.load()

    print(f"\n그림 {len(images)}개 · 목록 {len(entries)}줄 · 실제로 팔리는 테마 {len(loaded)}종\n")

    # ── ① 목록에 있는데 못 쓰는 것 (돈만 받고 안 바뀌는 상품) ──────────
    print("① 목록 → 그림")
    for entry in entries:
        key = str(entry.get("key") or "?")
        image = str(entry.get("image") or "")
        path = cta.THEME_DIR / image
        if not image:
            print(f"  ❌ {key}: image가 비었어요")
            problems.append(key)
        elif not path.exists():
            print(f"  ❌ {key}: 그림이 없어요 ({image}) — 상점에서 빠져요")
            problems.append(key)
        else:
            why = cta._validate(path)
            if why:
                print(f"  ❌ {key}: {why}")
                problems.append(key)
            elif key not in loaded:
                print(f"  ❌ {key}: 알 수 없는 이유로 안 불려요")
                problems.append(key)
            else:
                from PIL import Image
                with Image.open(path) as im:
                    size = f"{im.size[0]}x{im.size[1]}"
                note = "" if size == "1000x560" else f"  ⚠️ 권장 1000x560 (지금 {size})"
                top = loaded[key]["top"]
                print(f"  ✅ {key} ({image}, {size}) 패널색 {top}{note}")
    if not entries:
        print("  (목록이 비어 있어요)")

    # ── ② 그림만 있고 목록에 없는 것 (넣어놓고 안 파는 것) ─────────────
    print("\n② 그림 → 목록")
    orphans = [p for p in images if p.name not in listed]
    if not orphans:
        print("  ✅ 전부 등록돼 있어요")
    for path in orphans:
        why = cta._validate(path)
        print(f"  ⚠️ {path.name}: 목록에 없어요 — 아래 줄을 themes.json에 넣으세요"
              + (f"  (단 먼저 고칠 것: {why})" if why else ""))
        snippet = {
            "key": path.stem,
            "emoji": "🎴",
            "desc": f"{path.stem} 테마",
            "image": path.name,
        }
        for line in json.dumps(snippet, ensure_ascii=False, indent=2).splitlines():
            print(f"      {line}")

    # ── ③ 이름 충돌 (색 테마가 이겨서 그림이 안 나와요) ────────────────
    print("\n③ 색 테마와 이름이 겹치나")
    from utils.profile_card import THEMES
    clash = sorted(set(loaded) & set(THEMES))
    if clash:
        # 🚨 `ALL_THEMES`는 색 테마를 나중에 덮어써요(기존 구매자 보호). 그래서
        #    이름이 겹치면 **그림이 절대 안 나와요** — 사람이 알아야 고쳐요.
        print(f"  ❌ 겹쳐요: {clash} — 색 테마가 이겨서 그림이 안 나와요. 이름을 바꾸세요")
        problems.extend(clash)
    else:
        print("  ✅ 겹치는 이름 없어요")

    print("\n" + "=" * 50)
    if problems:
        print(f"❌ 고칠 것 {len(problems)}건: {sorted(set(problems))}")
        return 1
    print(f"✅ 캐릭터 테마 {len(loaded)}종 전부 정상"
          + (f" · 등록 대기 {len(orphans)}개" if orphans else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
