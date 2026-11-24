# -*- coding: utf-8 -*-
"""🤖 `#🤖｜봇-사용법`에 11/15~11/24에 나온 기능을 반영해요 (2026-11-24).

빠져 있던 것 / 옛 값이던 것:

| 메시지 | 고치는 것 |
|---|---|
| 🎯 발로란트 | `/발로들` 추가 (v227) |
| 🪙 악귀코인 | 카드 테마 "캐릭터" → "그림", "7종" → 색 6종 · 그림 13종, `/칭호아이콘` 추가 |
| 🎣 낚시 | `/낚시도감` 👑 왕관 (v228) |
| 🎴 프로필 | 버튼 2개 → 📋 자세히 보기 · 🎨 테마 바꾸기, `/커스텀테마` 추가, 업적 50 → 60개 |
| 🏆 주간결산 | 🖼️ 서버 배너 자동 갱신 |

일회용이에요 — 앵커가 옛 문구 그대로라 한 번 고치고 나면 다시 못 돌려요
(이미 고쳐진 자리는 "이미 반영됨"으로 건너뛰어요).

    python scripts/patch_usage_1124.py          # 미리보기만 (읽기만 해요)
    python scripts/patch_usage_1124.py --send   # 실제 PATCH (백업 → PATCH → 다시 읽어 대조)

🚨 앵커를 못 찾거나 두 번 이상 나오면 아무것도 안 보내고 멈춰요.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
sys.path.insert(0, os.path.join(BOT_DIR, "scripts"))
os.chdir(BOT_DIR)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import post_mission_list as pml                      # noqa: E402

KST = timezone(timedelta(hours=9))
CHANNEL_ID = "1532750088152289321"      # #🤖｜봇-사용법
BALODLE_CHANNEL = "1574462952457637990"  # #🧩｜발로들
DISCORD_LIMIT = 2000

# (메시지 ID, 옛 문구, 새 문구)
EDITS = [
    # 🎯 발로란트 — /맵추천 아래에 발로들
    ("1546099551809835140",
     "`/맵추천` — 맵 랜덤 추천 (원하지 않는 맵은 제외 가능)",
     "`/맵추천` — 맵 랜덤 추천 (원하지 않는 맵은 제외 가능)\n"
     f"`/발로들` — 🧩 **매일 퍼즐** · 요원 · 스킬 · 맵을 하루 한 문제씩 맞혀요 → <#{BALODLE_CHANNEL}>\n"
     "　└ 문제마다 기회 6번 · **빨리 맞힐수록** 코인을 더 받아요 (1번에 3 · 3번 안에 2 · 6번 안에 1코인)\n"
     "　└ 패널의 🔔 **알림** 버튼으로 매일 아침 새 문제 알림을 받아요"),

    # 🪙 악귀코인 — 상점 줄
    ("1546099559317508207",
     "🎨 **카드 테마**(색 15코인 · 🎴 캐릭터 25코인)",
     "🎨 **카드 테마**(색 15코인 · 🖼️ 그림 25코인)"),
    ("1546099559317508207",
     "　└ 🎨 `/프로필` 카드 배경을 바꿔요 · 7종 · 한 번 사면 **영구**라 언제든 다시 골라요",
     "　└ 🎨 `/프로필` 카드 배경을 바꿔요 · 색 6종 · 그림 13종 · 한 번 사면 **영구**예요"),
    ("1546099559317508207",
     "　└ 기간이 남았을 때 다시 사면 이어붙여져요 · `/칭호` `/칭호해제`",
     "　└ 기간이 남았을 때 다시 사면 이어붙여져요 · `/칭호` `/칭호해제`\n"
     "`/칭호아이콘` — 칭호 옆에 아이콘 · 이모지 **10코인**(바로) · 그림 **30코인**(방장 승인 후, 거절되면 환불)"),

    # 🎣 낚시 — 도감 왕관
    ("1556650613696106568",
     "`/낚시도감` — 지금까지 낚아본 물고기를 **그림**으로 모아 봐요 (못 만난 물고기는 그림자)",
     "`/낚시도감` — 지금까지 낚아본 물고기를 **그림**으로 모아 봐요 (못 만난 물고기는 그림자)\n"
     "　└ 👑 그 어종 최대 크기의 **90% 이상**을 낚으면 칸에 왕관이 붙어요"),

    # 🎴 프로필
    ("1560970516368457739",
     "　└ 🎴 **카드 배경을 좋아하는 캐릭터로** 바꿀 수 있어요 (`/악귀상점` → 카드 테마 · 25코인)",
     "　└ 🎨 **카드 배경을 그림 테마로** 바꿀 수 있어요 (`/악귀상점` → 카드 테마 · 25코인)\n"
     "　└ 🖼️ `/커스텀테마` — **내 그림**을 배경으로 (50코인 · 방장 승인 후 적용, 거절되면 환불)"),
    ("1560970516368457739",
     "　└ 카드 아래 버튼으로 **🏆 업적** · **🎯 발로란트 전적**을 바로 열어요",
     "　└ 카드 아래 **📋 자세히 보기**로 업적 · 전적 · 내전 · 음성 · 낚시 · 출석 · 코인을 열어요 (카드 주인만)\n"
     "　└ 같은 메뉴의 🎨 **테마 바꾸기**로 가진 테마끼리 **무료**로 바꿔요"),
    ("1560970516368457739",
     "`/업적` — 전체 **50개**",
     "`/업적` — 전체 **60개**"),

    # 🏆 주간결산 — 서버 배너
    ("1566004532926750754",
     "　└ 우승하면 역할이 붙어요 · **상금은 없어요**",
     "　└ 우승하면 역할이 붙어요 · **상금은 없어요**\n"
     "🖼️ **서버 배너** — 결산이 끝나면 MVP · 낚시 대회 결과로 서버 배너가 바뀌어요"),
]


def plan(contents: dict[str, str]) -> dict[str, str]:
    """메시지별 새 본문. 문제가 있으면 SystemExit."""
    new = dict(contents)
    problems = []
    for mid, old, rep in EDITS:
        text = new[mid]
        if rep in text and old != rep and text.count(old) == 1 and rep.startswith(old):
            # 덧붙이는 편집이 이미 반영된 경우
            print(f"  ↷ 이미 반영됨: {old[:40]}…")
            continue
        n = text.count(old)
        if n != 1:
            if rep in text:
                print(f"  ↷ 이미 반영됨: {old[:40]}…")
                continue
            problems.append(f"{mid}: 앵커 {n}번 — {old[:50]}")
            continue
        new[mid] = text.replace(old, rep)
    for mid, text in new.items():
        if len(text) > DISCORD_LIMIT:
            problems.append(f"{mid}: {len(text)}자 > {DISCORD_LIMIT}")
    if problems:
        print("🚨 멈춰요:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    ids = sorted({mid for mid, _, _ in EDITS})
    contents = {}
    for mid in ids:
        contents[mid] = pml._call("GET", f"/channels/{CHANNEL_ID}/messages/{mid}")["content"]
        time.sleep(1.1)

    new = plan(contents)
    changed = [mid for mid in ids if new[mid] != contents[mid]]
    for mid in ids:
        mark = "✏️" if mid in changed else "＝"
        print(f"{mark} {mid}  {len(contents[mid])} → {len(new[mid])}자")
    if not changed:
        print("고칠 게 없어요.")
        return
    if not args.send:
        for mid in changed:
            print(f"\n===== {mid} (새 본문) =====\n{new[mid]}")
        print("\n(미리보기만 했어요. 보내려면 --send)")
        return

    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(BOT_DIR, "backups", f"usage_channel_{stamp}")
    os.makedirs(bdir, exist_ok=True)
    with open(os.path.join(bdir, "before.json"), "w", encoding="utf-8") as f:
        json.dump(contents, f, ensure_ascii=False, indent=2)
    print(f"💾 백업 {bdir}")

    for mid in changed:
        pml._call("PATCH", f"/channels/{CHANNEL_ID}/messages/{mid}", {"content": new[mid]})
        time.sleep(1.1)
        again = pml._call("GET", f"/channels/{CHANNEL_ID}/messages/{mid}")["content"]
        time.sleep(1.1)
        print(("✅" if again == new[mid] else "❌ 대조 실패") + f" {mid}")


if __name__ == "__main__":
    main()
