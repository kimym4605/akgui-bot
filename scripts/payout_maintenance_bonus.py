"""🎁 서버 멤버 전원에게 악귀코인을 똑같이 지급해요 (점검·장애 보상용).

## 왜 만들었나

2026-11-05 보안 점검으로 봇이 DB에 못 붙어 출석·미션·코인 기능이 한동안 먹통이었어요.
사용자 요청으로 **서버의 사람 멤버 전원(봇 제외)에게 20코인씩** 보상해요.

## 규칙

- 대상: 디스코드 길드 멤버 중 `bot`이 아닌 사람 전원 (DB에 지갑이 없어도 새로 생겨요)
- 지급: `coin_wallet._add_sync` — 트레이너면 trainers, 아니면 지갑(coin_reset_backup)
- 기록: `coin_log`에 `kind="add"`, note=`NOTE` → `report_economy.py`에서 **발행(issue)**으로 잡혀요
- 🚨 **두 번 돌려도 안전해요.** 같은 note로 이미 받은 사람은 건너뛰어요.

## 쓰는 법

    python scripts/payout_maintenance_bonus.py            # 미리보기
    python scripts/payout_maintenance_bonus.py --apply    # 실제 지급
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

# 운영 DB·운영봇 토큰. 로컬 .env는 TEST봇이라 운영 백업을 우선해요.
for candidate in (BOT_DIR.parent / "운영봇_토큰_백업.env", BOT_DIR / ".env"):
    if candidate.is_file():
        for line in candidate.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

from utils.coin_wallet import _add_sync, _coin_log, _log_sync  # noqa: E402

AMOUNT = 20
NOTE = "점검보상:20261105"
APPLY = "--apply" in sys.argv

HEADERS = {
    "Authorization": f"Bot {os.environ['DISCORD_TOKEN']}",
    "User-Agent": "DiscordBot (https://github.com/akgui, 1.0)",
}


def guild_humans() -> list[dict]:
    gid = os.environ["GUILD_ID"]
    out, after = [], "0"
    while True:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/guilds/{gid}/members?limit=1000&after={after}",
            headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.load(r)
        if not page:
            break
        out.extend(page)
        after = page[-1]["user"]["id"]
        if len(page) < 1000:
            break
        time.sleep(0.5)
    return [m for m in out if not m["user"].get("bot")]


def main() -> int:
    humans = guild_humans()
    already = {str(d["to"]) for d in _coin_log.find({"kind": "add", "note": NOTE}, {"to": 1})}
    todo = [m for m in humans if m["user"]["id"] not in already]

    print("=" * 50)
    print("[실제 지급]" if APPLY else "[미리보기 - 아무것도 바꾸지 않아요]")
    print("=" * 50)
    print(f"사람 멤버: {len(humans)}명 · 이미 받음: {len(humans) - len(todo)}명")
    print(f"이번 지급: {len(todo)}명 × {AMOUNT}코인 = {len(todo) * AMOUNT}코인 (note={NOTE})")

    if not APPLY:
        print("\n실제로 지급하려면: python scripts/payout_maintenance_bonus.py --apply")
        return 0

    paid = 0
    for m in todo:
        uid = m["user"]["id"]
        _add_sync(uid, AMOUNT)
        _log_sync("add", None, uid, AMOUNT, NOTE)
        paid += 1
    print(f"\n💰 지급 완료: {paid}명 / {paid * AMOUNT}코인")
    return 0


if __name__ == "__main__":
    sys.exit(main())
