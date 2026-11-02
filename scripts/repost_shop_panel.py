# -*- coding: utf-8 -*-
"""🪙 `#🪙｜악귀상점`의 상설 패널 임베드를 **코드에서 다시 생성해서** 제자리 수정해요.

## 왜 필요한가 — 패널은 **게시된 순간의 가격표**예요

`_panel_embed()`는 상수에서 가격을 뽑아 만들지만, 그건 **게시할 때 한 번**이에요.
`/상점패널`을 다시 치지 않으면 메시지에 박힌 옛 가격이 그대로 남아요.

🔴 2026-11-02에 `REROLL_PRICE`를 2 → 4로 올렸는데 패널엔 **"🎲 미션 리롤권 — 2코인"**이
   그대로였어요.
🚨🚨 **`scan_guides.py`가 이걸 못 잡았어요** — 그 도구는 topic·핀·본문만 보고
   **임베드 필드는 안 읽어요.** 그래서 `#🪙｜악귀상점`은 ✅로 나왔어요.
   → 가격 상수를 바꿨으면 `scan_guides`가 ✅라도 **이 스크립트를 한 번 돌릴 것.**

## 쓰는 법

    python scripts/repost_shop_panel.py          # 미리보기 (현재 vs 새 임베드 비교)
    python scripts/repost_shop_panel.py --send   # 실제 PATCH

🚨 `/상점패널`로 **새로 올리지 않아요.** 새 메시지는 맨 아래로 가고 버튼이 달린 옛
   메시지가 남아요. 제자리 PATCH면 message_id가 유지돼 버튼(영속 뷰)도 그대로 살아요.
🚨 백업을 먼저 떠요. 🚨 보낸 뒤 다시 읽어서 대조해요.
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

from cogs.akgui_shop import _panel_embed            # noqa: E402

KST = timezone(timedelta(hours=9))
CHANNEL_ID = "1564592536926818316"      # #🪙｜악귀상점


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


def _flat(embed: dict) -> list[str]:
    """임베드를 비교·출력용 줄 목록으로. 🚨 길이 합만 보면 순서가 바뀌어도 통과해요."""
    out = [f"title: {embed.get('title')}", f"desc: {embed.get('description')}"]
    for f in embed.get("fields") or []:
        out.append(f"[{f['name']}] {f['value']}")
    footer = (embed.get("footer") or {}).get("text")
    if footer:
        out.append(f"footer: {footer}")
    return out


def find_panel() -> dict:
    """패널 메시지를 찾아요. 🚨 message_id를 코드에 박지 않아요 — 재게시되면 404예요."""
    msgs = _call("GET", f"/channels/{CHANNEL_ID}/messages?limit=30")
    cands = [m for m in msgs
             if any((e.get("title") or "") == "🪙 악귀상점" for e in (m.get("embeds") or []))
             and (m.get("components") or [])]
    if len(cands) != 1:
        sys.exit(f"🚨 버튼이 달린 '🪙 악귀상점' 패널이 {len(cands)}개예요 (1개여야 해요). "
                 f"채널 메시지 {len(msgs)}개를 직접 확인하세요.")
    return cands[0]


def patch(message_id: str, embed: dict):
    """🚨 429 `code 30046`(1시간 넘은 메시지 편집 한도)면 기다렸다 다시."""
    for attempt in (1, 2, 3):
        try:
            return _call("PATCH", f"/channels/{CHANNEL_ID}/messages/{message_id}",
                         {"embeds": [embed]})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < 3:
                wait = 5.0
                try:
                    wait = float(json.loads(raw).get("retry_after") or wait)
                except Exception:                      # noqa: BLE001
                    pass
                print(f"  ⚠️ 429 — {wait:.1f}초 대기 후 재시도({attempt}/2): {raw[:160]}")
                time.sleep(wait + 1)
                continue
            sys.exit(f"🚨 PATCH 실패 {e.code}: {raw[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    fresh = _panel_embed().to_dict()
    msg = find_panel()
    old = (msg.get("embeds") or [{}])[0]

    old_lines, new_lines = _flat(old), _flat(fresh)
    if old_lines == new_lines:
        print("✅ 이미 최신이에요 — 아무것도 안 했어요.")
        return

    print(f"패널 메시지 {msg['id']}\n")
    for a, b in zip(old_lines + [""] * (len(new_lines) - len(old_lines)),
                    new_lines + [""] * (len(old_lines) - len(new_lines))):
        if a != b:
            print(f"  - {a[:110]}")
            print(f"  + {b[:110]}\n")

    if not args.send:
        print("미리보기만 했어요. 올리려면 --send 를 붙이세요.")
        return

    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BOT_DIR, "backups", f"shop_panel_{stamp}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "message.json"), "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False, indent=2)
    print(f"백업: {out}")

    patch(msg["id"], fresh)

    again = _call("GET", f"/channels/{CHANNEL_ID}/messages/{msg['id']}")
    got = (again.get("embeds") or [{}])[0]
    if _flat(got) == new_lines:
        print("✅ 다시 읽어서 줄 단위로 대조했어요 — 완전 일치.")
    else:
        sys.exit(f"🚨 반영 후 내용이 달라요. 백업({out})으로 되돌리세요.")
    # 버튼이 날아가지 않았는지도 봐요(임베드만 PATCH하면 남지만, 확인은 공짜예요).
    print(f"버튼 줄 {len(again.get('components') or [])}개 — 영속 뷰는 그대로예요.")


if __name__ == "__main__":
    main()
