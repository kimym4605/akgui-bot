# -*- coding: utf-8 -*-
"""🏅 희귀도 차등을 `#🤖｜봇-사용법`에 반영해요 (2026-11-02).

## 고치는 곳 3군데

| 옛 문구 | 새 문구 | 왜 |
|---|---|---|
| `🎲 **미션 리롤권**(2코인)` | `(4코인)` | 리롤 가격이 2→4로 올랐어요 |
| `오늘의 미션 3개, 하나 깰 때마다 1개` | 희귀도만큼 | 보상이 1코인 고정이 아니에요 |
| `/악귀상점` (2코인부터 쓸 수 있어요) | `3코인부터` | 2코인짜리(리롤권)가 없어졌어요 → 최저가는 🪝 소형 낚시대 |

🚨 **`scan_guides.py`는 이 셋을 못 잡았어요.** `#🤖｜봇-사용법`은 여러 기능을 한 글에
   담아서 '전역 숫자 집합'으로 보는데, `2`와 `1`이 다른 상수에도 있어서 전부 통과했어요.
   → 이 채널은 **숫자 대조로는 못 막아요.** 상수를 바꿨으면 눈으로 훑을 것.

## 쓰는 법

    python scripts/patch_usage_mission_rarity.py          # 미리보기
    python scripts/patch_usage_mission_rarity.py --send   # 실제 PATCH

🚨 앵커를 못 찾으면 **아무것도 안 하고 멈춰요**(전문을 다시 쓰다 다른 데를 건드리는 사고 방지).
🚨 이미 반영돼 있으면 건너뛰어요 — 여러 번 돌려도 안전해요.
🚨 보내기 전에 백업을 떠요. 2026-10-31에 429로 메시지가 깨졌을 때 백업으로 복구했어요.
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

from utils.fish_data import SMALL_ROD_PRICE          # noqa: E402
from utils.mission_store import (                    # noqa: E402
    DAILY_MISSION_COUNT, MAX_DAILY_REWARD, RARITY, REROLL_PRICE,
)

KST = timezone(timedelta(hours=9))
CHANNEL_ID = "1532750088152289321"      # #🤖｜봇-사용법
MISSION_CHANNEL = "1546034268550070364"  # #🎯｜미션-내용 (전체 목록 링크)
DISCORD_LIMIT = 2000

_RARITY_SHORT = " · ".join(f"{r['emoji']}{r['label']} {r['reward']}" for r in RARITY.values())

# (앵커, 새 문구). 🚨 앵커는 **옛 값이 박힌 그 줄**이라야 해요 — 짧게 잡으면 엉뚱한 데가 바뀌어요.
REPLACEMENTS = [
    (
        "🎲 **미션 리롤권**(2코인)",
        f"🎲 **미션 리롤권**({REROLL_PRICE}코인)",
    ),
    (
        f"`/미션` — 오늘의 미션 {DAILY_MISSION_COUNT}개, 하나 깰 때마다 1개 "
        f"→ 전체 목록은 <#{MISSION_CHANNEL}>",
        f"`/미션` — 오늘의 미션 {DAILY_MISSION_COUNT}개 · 깬 미션의 **희귀도만큼** 코인 "
        f"({_RARITY_SHORT}코인 · 하루 최대 {MAX_DAILY_REWARD}코인) "
        f"→ 전체 목록은 <#{MISSION_CHANNEL}>",
    ),
    (
        "`/악귀상점` (2코인부터 쓸 수 있어요)",
        f"`/악귀상점` ({SMALL_ROD_PRICE}코인부터 쓸 수 있어요)",
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
    """🚨 429 `code 30046`(1시간 넘은 메시지 편집 한도)면 기다렸다 한 번 더."""
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
                print(f"  ⚠️ 429 — {wait:.1f}초 대기 후 재시도({attempt}/2): {raw[:160]}")
                time.sleep(wait + 1)
                continue
            sys.exit(f"🚨 PATCH 실패 {e.code}: {raw[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    msgs = _call("GET", f"/channels/{CHANNEL_ID}/messages?limit=30")
    print(f"메시지 {len(msgs)}개를 읽었어요\n")

    # 백업은 **고치기 전에** 전부 떠둬요.
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BOT_DIR, "backups", f"usage_channel_{stamp}")
    if args.send:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False, indent=2)
        print(f"백업: {out}\n")

    planned, applied, already = [], 0, 0
    for anchor, new in REPLACEMENTS:
        hits = [m for m in msgs if anchor in (m.get("content") or "")]
        done = [m for m in msgs if new in (m.get("content") or "")]
        if not hits and done:
            print(f"✅ 이미 반영됨 — {anchor[:40]}…")
            already += 1
            continue
        if len(hits) != 1:
            # 🚨 앵커를 못 찾았거나 여러 곳에 있으면 **멈춰요.** 추측해서 고치면 사고예요.
            sys.exit(f"🚨 앵커가 {len(hits)}곳에서 발견됐어요 (1곳이어야 해요): {anchor!r}")
        planned.append((hits[0], anchor, new))

    # 한 메시지에 여러 치환이 들어갈 수 있으니 메시지별로 모아서 한 번만 PATCH해요
    # (그래야 429 횟수를 아껴요).
    by_msg: dict[str, list] = {}
    for m, anchor, new in planned:
        by_msg.setdefault(m["id"], []).append((m, anchor, new))

    for mid, items in by_msg.items():
        body = items[0][0].get("content") or ""
        for _, anchor, new in items:
            body = body.replace(anchor, new)
            print(f"  - {anchor[:50]}…\n  + {new[:50]}…")
        old_len = len(items[0][0].get("content") or "")
        print(f"\n메시지 {mid}: {old_len}자 → {len(body)}자")
        # 🚨 2000자를 넘으면 PATCH가 실패해요. 넘으면 보내지 않아요.
        if len(body) > DISCORD_LIMIT:
            sys.exit(f"🚨 {len(body)}자로 한도({DISCORD_LIMIT})를 넘어요. 재배분이 필요해요.")
        if not args.send:
            continue
        patch(mid, body)
        again = _call("GET", f"/channels/{CHANNEL_ID}/messages/{mid}")
        if (again.get("content") or "") != body:
            sys.exit(f"🚨 {mid}: 반영 후 내용이 달라요. 백업({out})으로 되돌리세요.")
        print(f"  ✅ 다시 읽어서 대조 완료 — 완전 일치")
        applied += 1

    if not args.send:
        print(f"\n미리보기만 했어요(치환 {len(planned)}건 · 이미 반영 {already}건). "
              f"올리려면 --send 를 붙이세요.")
    else:
        print(f"\n✅ 메시지 {applied}개 수정 · 이미 반영 {already}건")


if __name__ == "__main__":
    main()
