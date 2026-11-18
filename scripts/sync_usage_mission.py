# -*- coding: utf-8 -*-
"""🤖 `#🤖｜봇-사용법`의 미션·전적 줄을 **코드 값으로 다시 맞춰요** (2026-11-18).

## 왜 또 스크립트인가 — 일회용 패치는 다음 번에 못 써요

`patch_usage_mission_rarity.py`(11/02)는 **옛 문구를 글자 그대로** 앵커로 잡았어요
(`"🎲 **미션 리롤권**(2코인)"`). 그래서 한 번 쓰고 나면 다시 못 돌려요 — 앵커가 사라지니까요.
실제로 2026-11-15에 보상을 🟢2 · 🔵5 · 🟣8로, 리롤권을 6코인으로 올렸을 때 이 채널은
**아무도 안 고쳤고**, 11/18까지 사흘 동안 이렇게 적혀 있었어요:

    🎲 미션 리롤권(4코인)                                   ← 실제 6코인
    (🟢흔함 1 · 🔵보통 3 · 🟣드묾 5코인 · 하루 최대 15코인)   ← 실제 2 · 5 · 8 · 최대 26

`scan_guides.py`도 못 잡았어요(그 채널용 검사 문구가 실제 글과 달라서 한 번도 안 걸렸어요 —
같은 날 고쳤어요).

→ 그래서 **숫자가 뭐든 그 자리를 찾는 정규식**으로 잡고, 새 문구는 **코드 상수에서** 만들어요.
   미션 보상·리롤 가격을 바꾼 뒤엔 이걸 그냥 다시 돌리면 돼요(같으면 아무것도 안 해요).

## 고치는 자리 3곳

| 자리 | 무엇 |
|---|---|
| `🎲 **미션 리롤권**(N코인)` | `REROLL_PRICE` |
| `` `/미션` — 오늘의 미션 N개 · … (…) `` | 희귀도별 보상 · `MAX_DAILY_REWARD` |
| `` `/전적` — … `` 바로 아랫줄 | `모드: 일반전만` 안내 한 줄 (없으면 넣고, 있으면 맞춰요) |

## 쓰는 법

    python scripts/sync_usage_mission.py            # 미리보기만 (읽기 1번, 아무것도 안 고침)
    python scripts/sync_usage_mission.py --send     # 실제 PATCH

🚨 자리를 못 찾거나 **두 군데 이상**이면 아무것도 안 하고 멈춰요(추측해서 고치면 사고예요).
🚨 보내기 전에 백업을 떠요(`backups/usage_channel_<stamp>/`).
🚨 PATCH 뒤에 **다시 읽어서** 글자까지 대조해요. 사이사이 쉬어요(운영 봇과 같은 토큰이에요).
🚨 `#🤖｜봇-사용법`은 기능 안내만 적는 곳이에요 — 패치노트는 `#봇업데이트`로.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
sys.path.insert(0, os.path.join(BOT_DIR, "scripts"))
os.chdir(BOT_DIR)

# 운영 토큰 + User-Agent를 붙이는 `_call`을 그대로 써요(같은 걸 세 번째로 복사하지 않으려고요).
import post_mission_list as pml                      # noqa: E402
from utils.mission_store import (                    # noqa: E402
    DAILY_MISSION_COUNT, MAX_DAILY_REWARD, RARITY, REROLL_PRICE,
)

KST = timezone(timedelta(hours=9))
CHANNEL_ID = "1532750088152289321"      # #🤖｜봇-사용법
DISCORD_LIMIT = 2000
PAUSE = 1.5                              # 요청 사이 쉬는 시간(초)

_RARITY_SHORT = " · ".join(f"{r['emoji']}{r['label']} {r['reward']}" for r in RARITY.values())
RANK_MODE_LINE = "　└ `모드`를 **일반전만**으로 고르면 일반전 기록만 모아 봐요 (기본은 경쟁전 우선)\n"

# (이름, 그 자리를 찾는 정규식, 새 문구를 만드는 함수(match → str))
# 🚨 정규식은 **숫자를 `\d+`로** 잡아요. 옛 값을 글자로 적으면 다음에 못 써요(위 설명).
RULES = [
    (
        "리롤권 값",
        re.compile(r"🎲 \*\*미션 리롤권\*\*\(\d+코인\)"),
        lambda m: f"🎲 **미션 리롤권**({REROLL_PRICE}코인)",
    ),
    (
        "미션 보상 줄",
        re.compile(r"`/미션` — 오늘의 미션 \d+개 · 깬 미션의 \*\*희귀도만큼\*\* 코인 \([^)\n]*\)"),
        lambda m: (f"`/미션` — 오늘의 미션 {DAILY_MISSION_COUNT}개 · 깬 미션의 **희귀도만큼** 코인 "
                   f"({_RARITY_SHORT}코인 · 하루 최대 {MAX_DAILY_REWARD}코인)"),
    ),
    (
        "전적 모드 안내",
        # `/전적` 줄 + (이미 있으면) 그 아래 '일반전만' 줄까지 한 덩어리로 잡아요.
        re.compile(r"(`/전적` — [^\n]*\n)(　└ [^\n]*일반전만[^\n]*\n)?"),
        lambda m: m.group(1) + RANK_MODE_LINE,
    ),
]


def plan(msgs: list) -> tuple[dict, int]:
    """메시지별 새 본문을 만들어요. ({message_id: (옛, 새, [바뀐 것])}, 이미 맞는 수)"""
    new_body = {m["id"]: (m.get("content") or "") for m in msgs}
    changes: dict[str, list] = {}
    already = 0
    for name, pattern, build in RULES:
        hits = [(m["id"], mt) for m in msgs for mt in pattern.finditer(m.get("content") or "")]
        if len(hits) != 1:
            sys.exit(f"🚨 '{name}' 자리가 {len(hits)}곳이에요 (1곳이어야 해요). "
                     f"글이 바뀌었으면 정규식을 고치세요: {pattern.pattern}")
        mid, mt = hits[0]
        old, new = mt.group(0), build(mt)
        if old == new:
            print(f"  ✅ {name} — 이미 맞아요")
            already += 1
            continue
        if new_body[mid].count(old) != 1:
            sys.exit(f"🚨 '{name}'의 옛 문구가 그 글에 {new_body[mid].count(old)}번 나와요. 멈춰요.")
        new_body[mid] = new_body[mid].replace(old, new)
        changes.setdefault(mid, []).append((name, old, new))
    out = {}
    for m in msgs:
        if m["id"] in changes:
            out[m["id"]] = (m.get("content") or "", new_body[m["id"]], changes[m["id"]])
    return out, already


def patch(message_id: str, content: str):
    """🚨 429(1시간 넘은 메시지 편집 한도 `30046` 포함)면 `retry_after`만큼 기다렸다 **한 번만** 더."""
    for attempt in (1, 2):
        try:
            return pml._call("PATCH", f"/channels/{CHANNEL_ID}/messages/{message_id}",
                             {"content": content})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt == 1:
                wait = 5.0
                try:
                    wait = float(json.loads(raw).get("retry_after") or wait)
                except Exception:                      # noqa: BLE001
                    pass
                print(f"  ⚠️ 429 — {wait:.1f}초 기다렸다 한 번 더 할게요: {raw[:160]}")
                time.sleep(wait + 1)
                continue
            sys.exit(f"🚨 PATCH 실패 {e.code}: {raw[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="실제로 PATCH해요 (없으면 미리보기)")
    args = ap.parse_args()

    msgs = pml._call("GET", f"/channels/{CHANNEL_ID}/messages?limit=30")
    print(f"메시지 {len(msgs)}개를 읽었어요\n")

    planned, already = plan(msgs)
    for mid, (old, new, items) in planned.items():
        print(f"\n메시지 {mid}: {len(old)}자 → {len(new)}자")
        for name, a, b in items:
            print(f"  [{name}]")
            for line in a.rstrip("\n").split("\n"):
                print(f"    - {line}")
            for line in b.rstrip("\n").split("\n"):
                print(f"    + {line}")
        # 🚨 2000자를 넘으면 PATCH가 그냥 실패해요. 하나라도 넘으면 **아무것도 안 보내요.**
        if len(new) > DISCORD_LIMIT:
            sys.exit(f"🚨 {len(new)}자로 한도({DISCORD_LIMIT})를 넘어요. 글을 나눠야 해요.")

    if not planned:
        print("\n✅ 전부 코드와 같아요 — 고칠 게 없어요.")
        return
    if not args.send:
        print(f"\n미리보기만 했어요(고칠 글 {len(planned)}개 · 이미 맞는 자리 {already}곳). "
              f"올리려면 --send 를 붙이세요.")
        return

    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BOT_DIR, "backups", f"usage_channel_{stamp}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "messages.json"), "w", encoding="utf-8") as f:
        json.dump(msgs, f, ensure_ascii=False, indent=2)
    print(f"\n백업: {out}")

    for mid, (_old, new, _items) in planned.items():
        time.sleep(PAUSE)
        patch(mid, new)
        time.sleep(PAUSE)
        again = pml._call("GET", f"/channels/{CHANNEL_ID}/messages/{mid}")
        if (again.get("content") or "") != new:
            sys.exit(f"🚨 {mid}: 반영 후 내용이 달라요. 백업({out})으로 되돌릴지 확인하세요.")
        print(f"  ✅ {mid} — 다시 읽어서 대조했어요, 완전 일치")
    print(f"\n✅ 글 {len(planned)}개를 고쳤어요.")


if __name__ == "__main__":
    main()
