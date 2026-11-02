# -*- coding: utf-8 -*-
"""🎴 캐릭터 카드 테마를 `#🤖｜봇-사용법`에 반영해요 (2026-11-03).

## 고치는 곳

| 옛 문구 | 왜 거짓인가 |
|---|---|
| `🎨 **카드 테마**(15코인)` | 캐릭터 테마는 **25코인**이에요. 한 값만 적으면 고르는 쪽에 따라 거짓이 돼요 |
| `/프로필` 설명 | 그림 배경과 📮 요청 창구가 생긴 걸 모르면 아무도 안 써요 |

🚨 **`scan_guides.py`는 이걸 못 잡아요.** 이 채널은 `SCOPES`가 `None`이라 전역 숫자
   집합으로 보는데 `15`가 다른 상수(카드 테마 값 자체)에도 있어서 그대로 통과해요.
   → 가격 상수를 바꿨으면 이 채널은 **눈으로** 훑어야 해요.

## 쓰는 법

    python scripts/patch_usage_card_themes.py          # 미리보기
    python scripts/patch_usage_card_themes.py --send   # 실제 PATCH

🚨 앵커를 못 찾으면 아무것도 안 하고 멈춰요. 이미 반영됐으면 건너뛰어요(여러 번 안전).
🚨 백업 먼저 · 2000자 가드 · 429 재시도 · 보낸 뒤 재대조까지 합니다.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                      # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from utils.profile_card import (                    # noqa: E402
    CHARACTER_THEME_PRICE, CHARACTER_THEMES, COLOR_THEME_PRICE,
)

KST = timezone(timedelta(hours=9))
CHANNEL_ID = "1532750088152289321"      # #🤖｜봇-사용법
DISCORD_LIMIT = 2000

_theme_item = (f"🎨 **카드 테마**(색 {COLOR_THEME_PRICE}코인 · "
               f"🎴 캐릭터 {CHARACTER_THEME_PRICE}코인)")

REPLACEMENTS = [
    (f"🎨 **카드 테마**({COLOR_THEME_PRICE}코인)", _theme_item),
    (
        "`/프로필` — **악귀 프로필 카드** 한 장 "
        "(티어 · 발로란트 전적 · 칭호 · 코인 · 내전 전적 · 최고 연승 · 악귀력 · 업적)",
        "`/프로필` — **악귀 프로필 카드** 한 장 "
        "(티어 · 발로란트 전적 · 칭호 · 코인 · 내전 전적 · 최고 연승 · 악귀력 · 업적)\n"
        f"　└ 🎴 **카드 배경을 좋아하는 캐릭터로** 바꿀 수 있어요 "
        f"(`/악귀상점` → 카드 테마 · {CHARACTER_THEME_PRICE}코인)\n"
        "　└ 📮 원하는 캐릭터가 없으면 그 화면에서 **요청**하면 방장이 넣어줘요",
    ),
]


def _headers() -> dict:
    path = os.path.join(os.path.dirname(BOT_DIR), "운영봇_토큰_백업.env")
    conf = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.strip().partition("=")
                conf[k] = v
    if not conf.get("DISCORD_TOKEN"):
        sys.exit(f"🚨 {path} 에 DISCORD_TOKEN이 없어요")
    return {
        # 🚨 User-Agent가 없으면 Cloudflare 1010이 403처럼 보여요.
        "Authorization": f"Bot {conf['DISCORD_TOKEN']}",
        "User-Agent": "DiscordBot (https://github.com/akgui, 1.0)",
        "Content-Type": "application/json",
    }


def _call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=_headers(), method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def patch(message_id: str, content: str):
    """🚨 429 `code 30046`(1시간 넘은 메시지 편집 한도)면 기다렸다 다시."""
    for attempt in (1, 2, 3):
        try:
            return _call("PATCH", f"/channels/{CHANNEL_ID}/messages/{message_id}",
                         {"content": content})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < 3:
                wait = 5.0
                try:
                    wait = float(json.loads(raw).get("retry_after") or wait)
                except Exception:                      # noqa: BLE001
                    pass
                print(f"  ⚠️ 429 — {wait:.1f}초 대기 후 재시도({attempt}/2)")
                time.sleep(wait + 1)
                continue
            sys.exit(f"🚨 PATCH 실패 {e.code}: {raw[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    if not CHARACTER_THEMES:
        sys.exit("🚨 캐릭터 테마가 하나도 없어요. 먼저 그림을 넣고 "
                 "`python scripts/check_card_themes.py`로 확인하세요.")

    msgs = _call("GET", f"/channels/{CHANNEL_ID}/messages?limit=30")
    print(f"메시지 {len(msgs)}개를 읽었어요\n")

    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BOT_DIR, "backups", f"usage_channel_{stamp}")
    if args.send:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False, indent=2)
        print(f"백업: {out}\n")

    planned, already = [], 0
    for anchor, new in REPLACEMENTS:
        hits = [m for m in msgs if anchor in (m.get("content") or "")]
        done = [m for m in msgs if new in (m.get("content") or "")]
        if not hits and done:
            print(f"✅ 이미 반영됨 — {anchor[:40]}…")
            already += 1
            continue
        if len(hits) != 1:
            sys.exit(f"🚨 앵커가 {len(hits)}곳에서 발견됐어요 (1곳이어야 해요): {anchor!r}")
        planned.append((hits[0], anchor, new))

    by_msg: dict[str, list] = {}
    for m, anchor, new in planned:
        by_msg.setdefault(m["id"], []).append((m, anchor, new))

    applied = 0
    for mid, items in by_msg.items():
        body = items[0][0].get("content") or ""
        for _, anchor, new in items:
            body = body.replace(anchor, new)
            print(f"  - {anchor[:60]}…\n  + {new[:60]}…")
        print(f"\n메시지 {mid}: {len(items[0][0].get('content') or '')}자 → {len(body)}자")
        if len(body) > DISCORD_LIMIT:
            sys.exit(f"🚨 {len(body)}자로 한도({DISCORD_LIMIT})를 넘어요. 재배분이 필요해요.")
        if not args.send:
            continue
        patch(mid, body)
        again = _call("GET", f"/channels/{CHANNEL_ID}/messages/{mid}")
        if (again.get("content") or "") != body:
            sys.exit(f"🚨 {mid}: 반영 후 내용이 달라요. 백업({out})으로 되돌리세요.")
        print("  ✅ 다시 읽어서 대조 완료 — 완전 일치")
        applied += 1

    if not args.send:
        print(f"\n미리보기만 했어요(치환 {len(planned)}건 · 이미 반영 {already}건).")
    else:
        print(f"\n✅ 메시지 {applied}개 수정 · 이미 반영 {already}건")


if __name__ == "__main__":
    main()
