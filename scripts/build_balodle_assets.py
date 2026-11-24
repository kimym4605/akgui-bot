# -*- coding: utf-8 -*-
"""🧩 발로들 재료(요원 이름·역할군, 스킬 목록·아이콘, 고화질 맵 그림)를 valorant-api.com에서 받아 구워요.

    python scripts/build_balodle_assets.py            # 전부
    python scripts/build_balodle_assets.py --no-images  # JSON만 (그림은 안 받아요)

## 만드는 것

- `config/balodle/agents.json`    요원키 → 이름(한글·영문)·역할군. 🚨 **손으로 적은 칸은 덮어쓰지 않아요**
  (출신·대륙·출시일·성별·별칭). 새 요원은 손입력 칸이 빈 채로 추가돼요 — 속성을 채우기 전까지는
  요원 문제의 정답 후보에서 자동으로 빠져요(스킬 문제·이름 인식에는 들어가요).
- `config/balodle/abilities.json` `"jett:E"` → 요원·키·이름(한글·영문)·아이콘 파일. 패시브는 빼요.
- `assets/valorant/balodle/abilities/<요원키>_<키>.webp`  스킬 아이콘 (흰색, 투명 배경, 256×256)
- `assets/valorant/balodle/maps/<맵키>.webp`              맵 그림 1920×1080 (5대5 맵만)

## 왜 전적 카드 재료(`build_valorant_assets.py`)와 따로 굽나

그쪽 맵 그림은 640×360이라 크게 확대하는 맵 문제에 쓰면 뭉개져요. 발로들은 8%까지 잘라
확대하니까 원본 크기가 필요해요.

🚨 `data/`에 두지 않아요 — Fly 볼륨이 가려서 배포해도 서버에 안 올라가요(프로젝트 `CLAUDE.md`).
새 요원·맵이 나오면: 이 스크립트 다시 실행 → agents.json에 속성 채우기 → 배포.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from utils import valorant_maps  # noqa: E402

CONFIG = os.path.join(BOT_DIR, "config", "balodle")
ASSETS = os.path.join(BOT_DIR, "assets", "valorant", "balodle")
API = "https://valorant-api.com/v1"
UA = {"User-Agent": "akgui-bot-asset-builder/1.0"}

# valorant-api의 슬롯 이름 → 게임 기본 키. 패시브는 문제로 내지 않아요(아이콘이 없거나 알아보기 어려워요).
SLOT_KEY = {"Grenade": "C", "Ability1": "Q", "Ability2": "E", "Ultimate": "X"}
# 손으로 채우는 칸. 스크립트는 이 칸을 **만들기만 하고 값은 건드리지 않아요.**
MANUAL_FIELDS = {"origin": "", "continent": "", "released": "", "gender": "", "aliases": []}
MAP_SIZE = (1920, 1080)
ICON_SIZE = 256
SCENE_SUFFIX = "_scene"
# 장면 그림이 그 맵 같지 않아 뺀 맵(2026-11-24 눈으로 확인). 확인되면 지워도 돼요.
SCENE_SKIP = {"Haven"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def get_json(path: str) -> list:
    return json.loads(get(f"{API}/{path}"))["data"]


def slug(name: str) -> str:
    """파일·키 이름. `KAY/O` → `kayo` (이름 그대로 쓰면 `/`가 폴더가 돼요)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_lines(path: str, data: dict):
    """항목 하나를 한 줄에 적어요 — 요원 한 명을 고치면 diff가 한 줄만 바뀌게."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = [f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}"
            for k, v in data.items()]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("{\n" + ",\n".join(rows) + "\n}\n")


def merge_agents(existing: dict, fetched: dict) -> dict:
    """받아온 이름·역할군만 갱신하고, 손입력 칸은 그대로 둬요. 원래 순서를 지키고 새 요원은 뒤에 붙여요."""
    merged = {}
    for key in list(existing) + [k for k in fetched if k not in existing]:
        row = dict(existing.get(key) or {})
        if key in fetched:
            row.update(fetched[key])          # ko · en · role 만 들어 있어요
        for field, empty in MANUAL_FIELDS.items():
            row.setdefault(field, list(empty) if isinstance(empty, list) else empty)
        merged[key] = row
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-images", action="store_true", help="JSON만 갱신하고 그림은 받지 않아요")
    args = parser.parse_args()
    if not args.no_images:
        from PIL import Image

    ko = get_json("agents?isPlayableCharacter=true&language=ko-KR")
    en = {a["uuid"]: a for a in get_json("agents?isPlayableCharacter=true&language=en-US")}

    fetched, abilities = {}, {}
    icons: list[tuple[str, str]] = []           # (파일 이름, 주소)
    for a in sorted(ko, key=lambda a: en[a["uuid"]]["displayName"]):
        e = en.get(a["uuid"])
        if not e:
            continue
        key = slug(e["displayName"])
        fetched[key] = {"ko": a["displayName"], "en": e["displayName"],
                        "role": (a.get("role") or {}).get("displayName", "")}
        en_abilities = {x["slot"]: x for x in e.get("abilities") or []}
        for ab in a.get("abilities") or []:
            letter = SLOT_KEY.get(ab.get("slot"))
            if not letter or not ab.get("displayIcon"):
                continue                          # 패시브이거나 아이콘이 없는 스킬
            fname = f"{key}_{letter.lower()}.webp"
            abilities[f"{key}:{letter}"] = {
                "agent": key, "slot": letter, "ko": ab["displayName"].strip(),
                "en": (en_abilities.get(ab["slot"]) or {}).get("displayName", "").strip(),
                "icon": fname,
            }
            icons.append((fname, ab["displayIcon"]))

    agents_path = os.path.join(CONFIG, "agents.json")
    agents = merge_agents(load(agents_path), fetched)
    dump_lines(agents_path, agents)
    dump_lines(os.path.join(CONFIG, "abilities.json"), abilities)
    blank = [k for k, v in agents.items()
             if not all(v.get(f) for f in ("origin", "continent", "released", "gender"))]
    print(f"요원 {len(agents)}명 · 스킬 {len(abilities)}개")
    if blank:
        print(f"⚠️ 속성이 빈 요원(요원 문제 정답에서 빠져요): {', '.join(blank)}")

    if args.no_images:
        return 0

    for fname, url in icons:
        im = Image.open(io.BytesIO(get(url))).convert("RGBA")
        im.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        path = os.path.join(ASSETS, "abilities", fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        im.save(path, "WEBP", lossless=True, method=6)
    print(f"스킬 아이콘 {len(icons)}개")

    # 5대5 맵만 굽어요. 같은 이름이 두 번 오는 맵(사격장)이 있어 이름으로 한 번만 받아요.
    wanted = {en_name: ko_name for en_name, ko_name in valorant_maps.EN_TO_KO.items()
              if ko_name in valorant_maps.MAPS}
    done, scenes = set(), 0
    for m in get_json("maps"):
        name = m.get("displayName")
        if name not in wanted or name in done or not m.get("splash"):
            continue
        # 🗺️ splash = 하늘에서 본 로딩 화면(`<맵>.webp`), backgroundImage = 맵 안 눈높이 장면
        #    (`<맵>_scene.webp`, 2026-11-24 추가 — 맵마다 그림이 한 장뿐이라 금방 외워졌어요).
        #    stylized·premier 배경은 backgroundImage를 어둡게 칠한 것이라 받지 않아요.
        for field, suffix in (("splash", ""), ("backgroundImage", SCENE_SUFFIX)):
            url = m.get(field)
            if not url or (suffix and name in SCENE_SKIP):
                continue
            im = Image.open(io.BytesIO(get(url))).convert("RGB")
            scale = max(MAP_SIZE[0] / im.width, MAP_SIZE[1] / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            x, y = (im.width - MAP_SIZE[0]) // 2, (im.height - MAP_SIZE[1]) // 2
            path = os.path.join(ASSETS, "maps", f"{slug(name)}{suffix}.webp")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            im.crop((x, y, x + MAP_SIZE[0], y + MAP_SIZE[1])).save(path, "WEBP", quality=86, method=6)
            scenes += bool(suffix)
        done.add(name)
    missing = sorted(set(wanted) - done)
    print(f"맵 {len(done)}개 · 장면 그림 {scenes}개"
          + (f" · ⚠️ 못 받은 맵: {', '.join(missing)}" if missing else ""))

    total = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fs in os.walk(ASSETS) for fn in fs)
    print(f"합계 {total / 1024:.0f}KB → {ASSETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
