"""🐟 어항에 든 물고기를 전부 코인으로 바꿔 지급해요 (장애 보상용).

## 왜 필요했나

2026-10-17, 치수 시스템을 넣으면서 `fishing_store.sell_all()`이 3개 값
(tank, coins, dust)을 돌려주게 바뀌었는데 `cogs/fishing.py`의 `/물고기판매`가
**2개만 받고 있었어요**. `ValueError: too many values to unpack`로 판매가 통째로
죽었고, 유저들은 어항에 물고기를 쌓아둔 채 팔 수가 없었어요.

코드는 고쳤지만, 그동안 못 판 물고기를 **직접 정산해서** 돌려줘요.

## 하는 일

1. `fish` 컬렉션의 모든 어항을 읽어 값(조각)을 계산
2. 사람별로 `조각 // 10` 코인을 지급하고 **나머지는 `dust`로 남겨요**
   (`sell_all`과 똑같은 규칙이라 손해도 이득도 없어요)
3. 어항을 비우고 `sold` 누적에 반영

🚨 note는 **`낚시판매`** 로 남겨요. 평소 판매와 같은 경로로 집계돼야
`scripts/report_economy.py`의 낚시 발행량이 맞아요. 별도 이름을 쓰면 '기타'로 빠져요.

🚨 **두 번 돌려도 안전해요.** 어항을 비우면서 지급하니 두 번째엔 줄 게 없어요.

## 쓰는 법

    python scripts/payout_tanks.py            # 미리보기
    python scripts/payout_tanks.py --apply    # 실제 지급
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

# 운영 DB에 붙어요. 로컬 .env는 **테스트봇**이라 값이 다를 수 있어서 운영 백업을 우선해요.
for candidate in (BOT_DIR.parent / "운영봇_토큰_백업.env", BOT_DIR / ".env"):
    if candidate.is_file():
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

from utils.coin_wallet import _add_sync, _log_sync, _uid  # noqa: E402
from utils.fish_data import BY_KEY, COIN_PIECES  # noqa: E402
from utils.fishing_store import _normalize_tank, tank_pieces  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

NOTE = "낚시판매"
APPLY = "--apply" in sys.argv


def main() -> int:
    fish = _db["fish"]
    docs = list(fish.find({}))

    plan = []
    for doc in docs:
        tank = _normalize_tank(doc.get("tank") or {})
        if not tank:
            continue
        pieces = tank_pieces(tank) + int(doc.get("dust", 0) or 0)
        coins, dust = divmod(pieces, COIN_PIECES)
        plan.append({
            "uid": str(doc["_id"]),
            "tank": tank,
            "n": sum(len(v) for v in tank.values()),
            "pieces": pieces, "coins": coins, "dust": dust,
        })

    print("=" * 62)
    print("[미리보기 - 아무것도 바꾸지 않아요]" if not APPLY else "[실제 지급]")
    print("=" * 62)
    print(f"\n어항에 물고기가 있는 사람: {len(plan)}명")
    print(f"총 지급 코인: {sum(p['coins'] for p in plan)}코인\n")
    for p in sorted(plan, key=lambda x: -x["coins"]):
        top = ", ".join(
            f"{BY_KEY[k][1]}×{len(v)}" for k, v in sorted(
                p["tank"].items(), key=lambda kv: -len(kv[1]))[:3])
        print(f"  {p['uid']:20s} {p['n']:3d}마리 → {p['coins']:3d}코인"
              f" (+{p['dust']}조각 이월)   {top}")

    if not APPLY:
        print("\n실제로 지급하려면: python scripts/payout_tanks.py --apply")
        return 0

    backup_dir = BOT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"tanks_before_payout_{stamp}.json"
    backup.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(f"\n💾 백업: {backup.relative_to(BOT_DIR)}")

    paid = 0
    for p in plan:
        uid = p["uid"]
        # 🚨 **어항을 먼저 비우고** 코인을 줘요. 반대로 하면 중간에 죽었을 때
        #    코인은 받았는데 물고기도 남아있어서 두 번 받을 수 있어요.
        fish.update_one({"_id": uid},
                        {"$set": {"tank": {}, "dust": p["dust"]},
                         "$inc": {"sold": p["coins"]}})
        if p["coins"]:
            _add_sync(uid, p["coins"])
            _log_sync("add", None, uid, p["coins"], NOTE)
            paid += p["coins"]
    print(f"💰 지급 완료: {len(plan)}명 / {paid}코인")
    print("\n✅ 끝났어요. `python scripts/report_economy.py`로 확인해보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
