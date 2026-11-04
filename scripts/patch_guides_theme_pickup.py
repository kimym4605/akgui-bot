# -*- coding: utf-8 -*-
"""📮 테마 요청 **줍기** 경로를 안내문에 반영해요 (2026-11-04).

## 왜 필요한가

요청 창구를 📮 모달 하나에서 **그림 올리면 줍기**로 넓혔어요. 그런데 안내문이 그걸
모르면 넓힌 길이 안 보여요 — **같은 사고가 네 번 났어요.**
→ [[feedback_sync_discord_guides_after_deploy]]

## 고치는 곳 두 군데

| 채널 | 옛 상태 | 왜 거짓/부족인가 |
|---|---|---|
| `#🎴｜프로필` 핀 | 테마 얘기가 **한 줄도 없다** | 기능이 사는 채널이 그 기능을 안 적어뒀어요. 🎨 색·🎴 캐릭터·📮 요청이 전부 빠져 있어요 |
| `#🤖｜봇-사용법` | `📮 … 그 화면에서 **요청**하면` | 이제 **그림을 올리는 쪽이 주 경로**예요(모달은 보조) |

🚨 **`scan_guides.py`는 이 둘을 못 잡아요.** 그 스캐너는 **숫자**만 대조해서,
   문장이 낡은 건 보이지 않아요(프로필 채널은 지금도 `✅`로 나와요).

## 쓰는 법

    python scripts/patch_guides_theme_pickup.py          # 미리보기
    python scripts/patch_guides_theme_pickup.py --send   # 실제 PATCH

🚨 **1시간 넘은 메시지는 편집 한도(429 `30046`)가 있어요.** 백업 먼저 · 2000자 가드 ·
   429는 `retry_after`만큼 기다렸다 **세 번까지만** · 보낸 뒤 다시 읽어 대조해요.
   연달아 PATCH를 쏘지 마세요. → [[feedback_pokemon_bot_usage_channel_update]]
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
    CHARACTER_THEME_PRICE, COLOR_THEME_PRICE,
)

KST = timezone(timedelta(hours=9))
DISCORD_LIMIT = 2000

PROFILE_CHANNEL = "1554515180191228067"   # #🎴｜프로필
USAGE_CHANNEL = "1532750088152289321"     # #🤖｜봇-사용법
MVP_CHANNEL = "1561312462903578688"       # #🏆｜주간결산 (핀 마지막 줄에 이미 있어요)

# 🚨 **값은 상수에서 가져와요.** 손으로 적으면 가격을 바꿀 때 안내문만 거짓이 돼요
#    (11-02 미션 보상에서 같은 모양의 버그를 네 군데서 걷어냈어요).
_THEME_BLOCK = (
    "\n`/악귀상점` → 🎨 **카드 테마**\n"
    f"프로필 카드 배경을 바꿔요 — 색 **{COLOR_THEME_PRICE}코인** · "
    f"🎴 캐릭터 그림 **{CHARACTER_THEME_PRICE}코인**. 한 번 사면 영구히 남아요.\n"
    "\n📮 **원하는 캐릭터가 없으면 이 채널에 그림을 올려주세요.**\n"
    "봇이 그 글에 📮 를 달아줘요 — **누르면 그대로 요청**이 돼요. "
    "말로 적어도 되고(`우사기 테마 넣어주세요`), 테마 화면의 📮 버튼도 같은 자리로 가요.\n"
)

_MVP_LINE = f"\n📌 🏅 **주간 MVP**는 월요일마다 <#{MVP_CHANNEL}> 에서 발표돼요."

_USAGE_OLD = "　└ 📮 원하는 캐릭터가 없으면 그 화면에서 **요청**하면 방장이 넣어줘요"
_USAGE_NEW = (f"　└ 📮 원하는 캐릭터가 없으면 <#{PROFILE_CHANNEL}> 에 "
              "**그림을 올리면** 봇이 📮 를 달아줘요 (누르면 요청)")

# (채널, 옛 문구, 새 문구) — 앵커가 1곳이 아니면 아무것도 안 하고 멈춰요.
REPLACEMENTS = [
    (PROFILE_CHANNEL, _MVP_LINE, _THEME_BLOCK + _MVP_LINE),
    (USAGE_CHANNEL, _USAGE_OLD, _USAGE_NEW),
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


def _fetch(channel_id: str) -> list:
    """최근 글 **과 핀**을 합쳐서 돌려줘요.

    🚨 **핀을 따로 읽어야 해요.** `#🎴｜프로필`의 사용법 핀은 10-04 글인데 그 뒤로
    업적 알림이 수십 개 쌓여서 `limit=50` 밖으로 밀렸어요. 최근 글만 보던 첫 판이
    `앵커가 0곳`으로 **거짓 실패**를 냈어요(같은 함정을 패널 테스트에서 겪었어요).
    """
    rows = list(_call("GET", f"/channels/{channel_id}/messages?limit=50") or [])
    seen = {m["id"] for m in rows}

    pins = _call("GET", f"/channels/{channel_id}/pins")
    # ⚠️ 새 핀 API는 `{"items": [{"message": {...}}]}`이고 옛 API는 배열이에요.
    items = pins.get("items") if isinstance(pins, dict) else (pins or [])
    for entry in items or []:
        m = entry.get("message", entry)
        if m.get("id") and m["id"] not in seen:
            rows.append(m)
            seen.add(m["id"])
    return rows


def patch(channel_id: str, message_id: str, content: str):
    """🚨 429 `code 30046`(1시간 넘은 메시지 편집 한도)면 기다렸다 다시. 세 번까지만."""
    for attempt in (1, 2, 3):
        try:
            return _call("PATCH", f"/channels/{channel_id}/messages/{message_id}",
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

    me = _call("GET", "/users/@me")
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BOT_DIR, "backups", f"guides_theme_pickup_{stamp}")

    cache: dict[str, list] = {}
    for channel_id, _, _ in REPLACEMENTS:
        if channel_id not in cache:
            cache[channel_id] = _fetch(channel_id)
            print(f"#{channel_id}: 메시지 {len(cache[channel_id])}개를 읽었어요")

    if args.send:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"백업: {out}")
    print()

    planned, already = [], 0
    for channel_id, anchor, new in REPLACEMENTS:
        msgs = cache[channel_id]
        hits = [m for m in msgs if anchor in (m.get("content") or "")]
        done = [m for m in msgs if new in (m.get("content") or "")]
        if not hits and done:
            print(f"✅ 이미 반영됨 — {anchor.strip()[:40]}…")
            already += 1
            continue
        if len(hits) != 1:
            sys.exit(f"🚨 앵커가 {len(hits)}곳에서 발견됐어요 (1곳이어야 해요): "
                     f"{anchor.strip()[:60]!r}")
        # 🚨 **봇이 쓴 글만 PATCH할 수 있어요.** 사람 글이면 400이 아니라 403이 나요.
        if (hits[0].get("author") or {}).get("id") != me["id"]:
            sys.exit(f"🚨 {hits[0]['id']} 은 봇 글이 아니에요 — 손으로 고쳐야 해요")
        planned.append((channel_id, hits[0], anchor, new))

    by_msg: dict[tuple, list] = {}
    for channel_id, m, anchor, new in planned:
        by_msg.setdefault((channel_id, m["id"]), []).append((m, anchor, new))

    applied = 0
    for (channel_id, mid), items in by_msg.items():
        body = items[0][0].get("content") or ""
        before = len(body)
        for _, anchor, new in items:
            body = body.replace(anchor, new)
        print(f"── #{channel_id} / {mid}: {before}자 → {len(body)}자")
        for _, anchor, new in items:
            print(f"  - {anchor.strip()[:70]}…\n  + {new.strip()[:70]}…")
        if len(body) > DISCORD_LIMIT:
            sys.exit(f"🚨 {len(body)}자로 한도({DISCORD_LIMIT})를 넘어요. 재배분이 필요해요.")
        if not args.send:
            continue
        patch(channel_id, mid, body)
        again = _call("GET", f"/channels/{channel_id}/messages/{mid}")
        if (again.get("content") or "") != body:
            sys.exit(f"🚨 {mid}: 반영 후 내용이 달라요. 백업({out})으로 되돌리세요.")
        print("  ✅ 다시 읽어서 대조 완료 — 완전 일치")
        applied += 1

    if not args.send:
        print(f"\n미리보기만 했어요(치환 {len(planned)}건 · 이미 반영 {already}건). "
              "실제로 고치려면 --send")
    else:
        print(f"\n✅ 메시지 {applied}개 수정 · 이미 반영 {already}건")


if __name__ == "__main__":
    main()
