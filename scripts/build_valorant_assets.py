# -*- coding: utf-8 -*-
"""🎨 전적 카드 재료(요원 얼굴 · 맵 그림 · 티어 엠블럼)를 valorant-api.com에서 받아 `assets/valorant/`에 구워요.

    python scripts/build_valorant_assets.py

## 왜 미리 굽나 (2026-11-23)

전적 카드는 경기 알림마다 그려져요. 그때마다 그림을 내려받으면 느리고, 그 사이트가 잠깐
죽으면 카드가 통째로 안 나와요. 그래서 **배포에 같이 실어요.** 새 요원·맵이 나오면 이걸
다시 돌리고 배포하면 돼요(없는 요원은 카드에서 이니셜 원으로 물러나요).

valorant-api.com은 인증 없는 공개 정적 데이터예요(티어 아이콘은 이미 `cogs/rank.py`가 같은 곳에서 받아요).

## 만드는 것

- `agents/<이름>.webp` — 128×128 얼굴 (displayIcon)
- `maps/<이름>.webp`   — 640×360 맵 그림 (splash를 줄여서)
- `tiers/<번호>.webp`  — 128×128 티어 엠블럼 (최신 시즌 largeIcon)
- `index.json`         — HenrikDev가 주는 이름 → 파일 이름

🚨 파일 이름은 **소문자 영문**으로 만들어요(`KAY/O` → `kayo`). 이름 그대로 쓰면 `/`가 폴더가 돼요.
"""
import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BOT_DIR, "assets", "valorant")
UA = {"User-Agent": "akgui-bot-asset-builder/1.0"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def save(img: Image.Image, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "WEBP", quality=88, method=6)


def main():
    index = {"agents": {}, "maps": {}, "tiers": {}}

    agents = json.loads(get("https://valorant-api.com/v1/agents?isPlayableCharacter=true"))["data"]
    for a in agents:
        name, url = a.get("displayName"), a.get("displayIcon")
        if not name or not url:
            continue
        im = Image.open(io.BytesIO(get(url))).convert("RGBA").resize((128, 128), Image.LANCZOS)
        save(im, os.path.join(OUT, "agents", f"{slug(name)}.webp"))
        index["agents"][name] = slug(name)
    print(f"요원 {len(index['agents'])}명")

    maps = json.loads(get("https://valorant-api.com/v1/maps"))["data"]
    for m in maps:
        name, url = m.get("displayName"), m.get("splash")
        if not name or not url:
            continue
        im = Image.open(io.BytesIO(get(url))).convert("RGB")
        scale = max(640 / im.width, 360 / im.height)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        x, y = (im.width - 640) // 2, (im.height - 360) // 2
        save(im.crop((x, y, x + 640, y + 360)), os.path.join(OUT, "maps", f"{slug(name)}.webp"))
        index["maps"][name] = slug(name)
    print(f"맵 {len(index['maps'])}개")

    seasons = json.loads(get("https://valorant-api.com/v1/competitivetiers"))["data"]
    for t in (seasons[-1].get("tiers") or []):
        url = t.get("largeIcon")
        if not url:
            continue
        im = Image.open(io.BytesIO(get(url))).convert("RGBA").resize((128, 128), Image.LANCZOS)
        save(im, os.path.join(OUT, "tiers", f"{t['tier']}.webp"))
        index["tiers"][str(t["tier"])] = t.get("tierName", "")
    print(f"티어 {len(index['tiers'])}개")

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    total = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fs in os.walk(OUT) for fn in fs)
    print(f"합계 {total / 1024:.0f}KB → {OUT}")


if __name__ == "__main__":
    sys.exit(main())
