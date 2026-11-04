# -*- coding: utf-8 -*-
"""🏷️ 발로란트 티어 역할 25개의 **배지 이미지와 이름**을 코드 기준으로 맞춰요.

하는 일은 두 가지예요. 둘 다 이미 맞으면 아무것도 안 해요(여러 번 돌려도 안전).
  1. 아이콘이 비어 있으면 실제 티어 배지를 붙여요.
  2. 이름이 옛 형식(`💠 다이아몬드 2`)이면 `다이아몬드 2`로 **개명**해요.

🚨 **역할을 지웠다 다시 만들지 않아요.** 삭제하면 그 역할을 달고 있던 사람들
   (2026-11-03 기준 23명)에게서 같이 떨어지고, 서열 위치도 바닥으로 내려가요.
   개명은 역할 ID·멤버·위치·아이콘을 전부 그대로 둔 채 이름만 바꿔요.

## 왜 스크립트가 따로 필요한가 — 코드는 **만들 때만** 붙였어요

`utils/tier_roles.get_or_create_tier_role()`은 역할을 **새로 만들 때**만 `display_icon`을
넣어요. 그런데 25개 역할은 **부스트 레벨 1이던 시절에 이미 다 만들어졌어요.** 그래서
`/전적`을 아무리 돌려도 기존 역할엔 아이콘이 영원히 안 붙어요(`get_or_create`가
`return role` 로 바로 빠져나가요).

🚨 **오랫동안 막혀 있던 건 코드가 아니라 서버 부스트 레벨이었어요.**
   이 서버는 `TIERLESS_BOOSTING`이라 "부스트 7개 = 레벨 2" 공식이 안 통해요.
   판단은 `GET /guilds/{id}` 의 **`features`에 `ROLE_ICONS`가 있는지**로만 해요.
   (2026-11-03 `premium_tier=2` · 부스트 10개로 해금 확인)

## 쓰는 법

    python scripts/apply_tier_role_icons.py          # 미리보기 (아무것도 안 바꿔요)
    python scripts/apply_tier_role_icons.py --send   # 실제 PATCH
    python scripts/apply_tier_role_icons.py --send --force   # 이미 있는 아이콘도 덮어써요

🚨 보낸 뒤 **다시 읽어서** 진짜 붙었는지 대조해요 (`200 ok`는 저장의 증거가 아니에요).
🚨 User-Agent가 없으면 Cloudflare 1010이 403처럼 보여요.
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

from utils.tier_roles import (                      # noqa: E402
    ENGLISH_TO_KOREAN_TIER,
    TIER_OPTIONS,
    display_name_for,
    legacy_display_name_for,
)

TIER_ICON_ENDPOINT = "https://valorant-api.com/v1/competitivetiers"
# 디스코드 역할 아이콘 업로드 한도. 실측(2026-11-03) 배지는 13~35KB라 여유가 많아요.
MAX_ICON_BYTES = 256 * 1024


def _conf() -> dict:
    """🚨 운영봇 토큰이에요. `discord-bot-starter-py/.env` 는 TEST봇 거라 쓰면 안 돼요."""
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


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "akgui-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def korean_name_for(tier_name_en: str) -> str | None:
    """'DIAMOND 2' -> '다이아몬드 2'. 이 API는 전부 대문자로 줘요."""
    parts = tier_name_en.title().split()        # 'DIAMOND 2' -> ['Diamond', '2']
    base = ENGLISH_TO_KOREAN_TIER.get(parts[0])
    if base is None:
        return None
    if base == "레디언트":
        return base
    if len(parts) > 1 and parts[1].isdigit():
        return f"{base} {parts[1]}"
    return None


def load_icons() -> dict[str, bytes]:
    """{'다이아몬드 2': png bytes} 를 만들어요. 가장 최신 세대(목록 맨 뒤)를 써요."""
    payload = json.loads(_fetch(TIER_ICON_ENDPOINT))
    seasons = payload.get("data") or []
    if not seasons:
        sys.exit("🚨 valorant-api가 빈 목록을 줬어요")
    tiers = seasons[-1].get("tiers") or []

    icons: dict[str, bytes] = {}
    for tier in tiers:
        url = tier.get("largeIcon")
        korean = korean_name_for(tier.get("tierName") or "")
        if not url or not korean:
            continue
        raw = _fetch(url)
        if len(raw) > MAX_ICON_BYTES:
            print(f"  ⚠️ {korean}: {len(raw)/1024:.0f}KB 라 한도(256KB)를 넘어요 — 건너뛰어요")
            continue
        icons[korean] = raw

    missing = [t for t in TIER_OPTIONS if t not in icons]
    if missing:
        sys.exit(f"🚨 아이콘을 못 찾은 티어가 있어요: {missing}")
    return icons


def guild_roles() -> list[dict]:
    return _call("GET", f"/guilds/{GUILD_ID}/roles")


def check_unlocked() -> None:
    guild = _call("GET", f"/guilds/{GUILD_ID}")
    features = guild.get("features") or []
    print(f"서버: premium_tier={guild.get('premium_tier')} "
          f"부스트={guild.get('premium_subscription_count')} "
          f"ROLE_ICONS={'✅' if 'ROLE_ICONS' in features else '❌'}")
    if "ROLE_ICONS" not in features:
        sys.exit("🚨 `ROLE_ICONS`가 features에 없어요. 부스트 개수가 아니라 이 값으로 판단해요 "
                 "— 지금은 역할 아이콘을 못 붙여요.")


def patch_role(role_id: str, body: dict) -> dict:
    """🚨 429면 `retry_after` 만큼 기다렸다 다시 — 연달아 때리지 않아요."""
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

    print("\n🖼️ valorant-api에서 티어 배지를 받아와요…")
    icons = load_icons()
    print(f"   {len(icons)}개 확보 "
          f"({min(len(v) for v in icons.values())/1024:.0f}~"
          f"{max(len(v) for v in icons.values())/1024:.0f}KB)")

    roles_by_name = {r["name"]: r for r in guild_roles()}

    # (역할, 보낼 body, 사람이 읽을 설명)
    todo: list[tuple[dict, dict, str]] = []
    print(f"\n{'지금 이름':<18} {'아이콘':<8} 할 일")
    for tier in TIER_OPTIONS:
        want = display_name_for(tier)
        legacy = legacy_display_name_for(tier)
        role = roles_by_name.get(want) or roles_by_name.get(legacy)
        if role is None:
            print(f"{'(없음)':<18} {'-':<8} ⏭️ '{want}' 역할이 서버에 없어요")
            continue

        body: dict = {}
        notes = []
        if role["name"] != want:
            body["name"] = want
            notes.append(f"✏️ '{role['name']}' → '{want}'")
        has_icon = bool(role.get("icon"))
        if not has_icon or args.force:
            body["icon"] = "data:image/png;base64," + base64.b64encode(icons[tier]).decode()
            notes.append("🔁 아이콘 덮어씀" if has_icon else "➕ 아이콘 붙임")

        print(f"{role['name']:<18} {('있음' if has_icon else '없음'):<8} "
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
        time.sleep(0.4)      # 역할 수정은 길드 단위 제한이 빡빡해요

    # 🚨 `200 ok`는 저장됐다는 뜻이 아니에요 — 다시 읽어서 대조해요.
    print("\n🔍 다시 읽어서 확인해요…")
    after = {r["id"]: r for r in guild_roles()}
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
