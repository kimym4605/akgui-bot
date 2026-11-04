# -*- coding: utf-8 -*-
"""🏷️ 포지션 역할 4개(타격대·척후대·감시자·전략가)에 **발로란트 포지션 아이콘**을 붙여요.

## 그림을 새로 만들지 않아요 — **서버에 이미 있어요**

누군가 예전에 발로란트 포지션 아이콘 4종을 **커스텀 이모지로 올려뒀는데**, 이름이 전부
`__`라 아무도 못 쓰고 있었어요. 그걸 그대로 역할 아이콘으로 옮겨 써요.

🚨 **원본은 밝은 회색(#EEE) 네모에 검은 그림**이라 그대로 쓰면 스티커처럼 붙어요.
   그래서 배경을 지우고(밝은 픽셀 = 배경) 포지션별 색을 입혀요.

⭐ **색은 눈으로 보고 정했어요.** 처음 고른 색은 라이트 테마에서 노랑·청록이 흐려져
   안 보였어요. 역할 아이콘은 **20px**로 그려지고 보는 사람 테마가 라이트일 수도
   있어서, 양쪽 바탕에 20px로 놓고 비교한 뒤 채도·명도를 낮춘 값이 아래예요.

## 쓰는 법

    python scripts/apply_position_role_icons.py          # 미리보기
    python scripts/apply_position_role_icons.py --send   # 실제 PATCH
    python scripts/apply_position_role_icons.py --send --force   # 아이콘도 덮어써요

개명(`⚔️ 타격대` -> `타격대`)도 같이 해요. 🚨 **역할을 지우지 않아요** — 지우면 그 역할을
달고 있던 사람들에게서 같이 떨어져요.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from PIL import Image                                   # noqa: E402

from utils.position_roles import (                      # noqa: E402
    POSITION_BASES,
    display_name_for,
    legacy_display_name_for,
)

# 커스텀 이모지 이름이 전부 `__`라 **이름으로는 못 고릅니다.** id로 박아둬요.
# (2026-11-03에 그림을 하나씩 크게 띄워 보고 포지션을 확인했어요)
EMOJI_BY_POSITION = {
    "타격대": "1497117313718157415",     # Duelist — 원 안의 X
    "척후대": "1497117336338169856",     # Initiator — 원 안의 번개
    "감시자": "1497117356198072451",     # Sentinel — 위를 향한 꺾쇠 두 개
    "전략가": "1497117375672090655",     # Controller — 원 안의 역삼각형
}

# 라이트·다크 양쪽에서 버티도록 눈으로 맞춘 색이에요. 더 밝게 하면 흰 배경에서 날아가요.
COLOR_BY_POSITION = {
    "타격대": (226, 48, 64),
    "척후대": (214, 146, 20),
    "감시자": (20, 160, 145),
    "전략가": (138, 86, 230),
}

# 밝은 픽셀을 배경으로 보는 경계. 원본 배경이 #EEE(238), 그림이 검정이에요.
CUTOUT_HI, CUTOUT_LO = 170, 60


def _conf() -> dict:
    """🚨 운영봇 토큰이에요. `discord-bot-starter-py/.env`는 TEST봇 거예요."""
    path = os.path.join(os.path.dirname(BOT_DIR), "운영봇_토큰_백업.env")
    conf = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.strip().partition("=")
                conf[k] = v.strip()
    for key in ("DISCORD_TOKEN", "GUILD_ID"):
        if not conf.get(key):
            sys.exit(f"🚨 {path} 에 {key}가 없어요")
    return conf


CONF = _conf()
GUILD_ID = CONF["GUILD_ID"]
HEADERS = {
    "Authorization": f"Bot {CONF['DISCORD_TOKEN']}",
    "User-Agent": "DiscordBot (https://github.com/akgui, 1.0)",
    "Content-Type": "application/json",
}


def _call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=HEADERS, method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def _cdn(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def make_icon(emoji_id: str, rgb: tuple) -> bytes:
    """커스텀 이모지에서 배경을 지우고 색을 입힌 PNG 바이트를 만들어요."""
    src = Image.open(io.BytesIO(_cdn(
        f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=128"))).convert("RGBA")
    gray = src.convert("L")
    # 어두운 픽셀일수록 불투명. 경계는 선형으로 부드럽게.
    span = CUTOUT_HI - CUTOUT_LO
    alpha = gray.point(lambda v: max(0, min(255, int((CUTOUT_HI - v) * 255 / span))))
    out = Image.new("RGBA", src.size, rgb + (255,))
    out.putalpha(alpha)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def check_unlocked() -> None:
    guild = _call("GET", f"/guilds/{GUILD_ID}")
    if "ROLE_ICONS" not in (guild.get("features") or []):
        sys.exit("🚨 `ROLE_ICONS`가 features에 없어요 — 지금은 역할 아이콘을 못 붙여요.")
    print(f"서버: premium_tier={guild.get('premium_tier')} · ROLE_ICONS ✅")


def patch_role(role_id: str, body: dict) -> dict:
    for attempt in (1, 2, 3):
        try:
            return _call("PATCH", f"/guilds/{GUILD_ID}/roles/{role_id}", body)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            if error.code == 429 and attempt < 3:
                wait = 5.0
                try:
                    wait = float(json.loads(detail).get("retry_after") or wait)
                except Exception:  # noqa: BLE001
                    pass
                print(f"    ⏳ 429 — {wait:.1f}초 기다려요")
                time.sleep(wait + 0.5)
                continue
            sys.exit(f"🚨 PATCH 실패 (HTTP {error.code}): {detail}")
    sys.exit("🚨 429가 계속돼서 포기해요")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="실제로 PATCH 해요")
    parser.add_argument("--force", action="store_true", help="이미 아이콘이 있어도 덮어써요")
    args = parser.parse_args()

    check_unlocked()
    roles_by_name = {r["name"]: r for r in _call("GET", f"/guilds/{GUILD_ID}/roles")}

    todo = []
    print(f"\n{'지금 이름':<14} {'아이콘':<8} 할 일")
    for position in POSITION_BASES:
        want = display_name_for(position)
        role = roles_by_name.get(want) or roles_by_name.get(legacy_display_name_for(position))
        if role is None:
            print(f"{'(없음)':<14} {'-':<8} ⏭️ '{want}' 역할이 서버에 없어요")
            continue

        body, notes = {}, []
        if role["name"] != want:
            body["name"] = want
            notes.append(f"✏️ '{role['name']}' → '{want}'")
        has_icon = bool(role.get("icon"))
        if not has_icon or args.force:
            raw = make_icon(EMOJI_BY_POSITION[position], COLOR_BY_POSITION[position])
            body["icon"] = "data:image/png;base64," + base64.b64encode(raw).decode()
            notes.append(f"{'🔁 아이콘 덮어씀' if has_icon else '➕ 아이콘 붙임'} ({len(raw)/1024:.0f}KB)")

        print(f"{role['name']:<14} {('있음' if has_icon else '없음'):<8} "
              f"{' · '.join(notes) if notes else '⏭️ 그대로'}")
        if body:
            todo.append((role, body, " · ".join(notes)))

    if not todo:
        print("\n✅ 바꿀 게 없어요.")
        return
    if not args.send:
        print(f"\n미리보기예요. {len(todo)}개를 바꾸려면 --send 를 붙이세요.")
        return

    print(f"\n🚀 {len(todo)}개를 고쳐요…")
    for role, body, notes in todo:
        patch_role(role["id"], body)
        print(f"   ✅ {notes}")
        time.sleep(0.4)

    # 🚨 `200 ok`는 저장의 증거가 아니에요 — 다시 읽어서 대조해요.
    print("\n🔍 다시 읽어서 확인해요…")
    after = {r["id"]: r for r in _call("GET", f"/guilds/{GUILD_ID}/roles")}
    bad = []
    for role, body, _ in todo:
        now = after.get(role["id"]) or {}
        if "name" in body and now.get("name") != body["name"]:
            bad.append(f"{role['name']}: 이름이 {now.get('name')!r} 그대로")
        if "icon" in body and not now.get("icon"):
            bad.append(f"{now.get('name', role['name'])}: 아이콘이 안 보임")
    if bad:
        sys.exit("🚨 PATCH는 성공했는데 반영이 안 됐어요:\n  " + "\n  ".join(bad))
    print(f"✅ {len(todo)}개 전부 반영된 걸 확인했어요.")


if __name__ == "__main__":
    main()
