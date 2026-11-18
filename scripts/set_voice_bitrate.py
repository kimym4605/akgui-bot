# -*- coding: utf-8 -*-
"""🔊 서버의 음성채널 음질(bitrate)을 부스트 레벨 최대치로 올려요.

## 왜 (2026-11-15)

서버가 부스트 2레벨(256kbps 허용)이 됐는데 통화방 18개는 128kbps, 개발실·스터디카페는
64kbps 그대로였어요. 음질은 채널마다 저장된 값이라 레벨이 올라도 **저절로 안 올라가요.**
레벨이 또 바뀌면(3레벨=384kbps) 이 스크립트를 다시 돌리면 돼요 — 최대치를 서버에서 읽어요.

    python scripts/set_voice_bitrate.py          # 미리보기
    python scripts/set_voice_bitrate.py --send   # 실제 PATCH (백업 먼저)

⚠️ 부스트가 빠져서 레벨이 내려가면 디스코드가 알아서 낮춰요(이 스크립트 몫 아님).
⚠️ /방만들기로 생기는 임시 방은 `utils/dynamic_room.py`가 만들 때부터 최대치로 만들어요.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repost_shop_panel as rp  # noqa: E402  (운영봇 토큰 + User-Agent가 든 _call 재사용)

GUILD_ID = "1241914757859119184"
KST = timezone(timedelta(hours=9))
# premium_tier → 최대 음질(bps). 디스코드 기준표예요.
TIER_MAX = {0: 96_000, 1: 128_000, 2: 256_000, 3: 384_000}
VOICE_TYPES = (2,)   # 일반 음성채널만. 스테이지(13)는 음질 설정 방식이 달라 건드리지 않아요.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    guild = rp._call("GET", f"/guilds/{GUILD_ID}")
    target = TIER_MAX[int(guild.get("premium_tier") or 0)]
    feats = set(guild.get("features") or [])
    if "VIP_REGIONS" in feats:
        target = max(target, 384_000)
    print(f"부스트 {guild.get('premium_tier')}레벨 → 목표 {target // 1000}kbps\n")

    chans = rp._call("GET", f"/guilds/{GUILD_ID}/channels")
    todo = [c for c in chans if c["type"] in VOICE_TYPES and c.get("bitrate", 0) < target]
    if not todo:
        print("✅ 이미 전부 최대치예요.")
        return
    for c in todo:
        print(f"  {c['name']}: {c['bitrate'] // 1000} → {target // 1000}kbps")
    if not args.send:
        print(f"\n{len(todo)}개. 미리보기만 했어요. 올리려면 --send")
        return

    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(bot_dir, "backups", f"voice_bitrate_{stamp}.json")
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    with open(backup, "w", encoding="utf-8") as f:
        json.dump({c["id"]: {"name": c["name"], "bitrate": c["bitrate"]} for c in todo},
                  f, ensure_ascii=False, indent=2)
    print(f"\n백업: {backup}")

    ok = 0
    for c in todo:
        for attempt in (1, 2, 3):
            try:
                rp._call("PATCH", f"/channels/{c['id']}", {"bitrate": target})
                ok += 1
                break
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                if e.code == 429 and attempt < 3:
                    wait = float(json.loads(raw).get("retry_after") or 5)
                    time.sleep(wait + 0.5)
                    continue
                print(f"  🚨 {c['name']} 실패 {e.code}: {raw[:200]}")
                break
        time.sleep(0.3)

    # 다시 읽어서 대조해요.
    after = {c["id"]: c.get("bitrate") for c in rp._call("GET", f"/guilds/{GUILD_ID}/channels")}
    bad = [c["name"] for c in todo if after.get(c["id"]) != target]
    print(f"\nPATCH {ok}/{len(todo)} · 다시 읽어서 확인: "
          + ("✅ 전부 반영" if not bad else f"🚨 미반영 {bad}"))


if __name__ == "__main__":
    main()
