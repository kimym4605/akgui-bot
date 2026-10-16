"""🐟 판매 버그로 **사라진** 물고기를 추정 정산해요 (장애 보상 2차).

## 무슨 일이 있었나

2026-10-17, `/물고기판매`가 `ValueError: too many values to unpack`로 죽었어요
(`sell_all`이 3개 값을 돌려주게 바뀌었는데 호출부가 2개만 받았어요).

🚨 **문제는 터진 위치예요.** `sell_all`은 DB에서 **어항을 먼저 비운 뒤** 값을 돌려줘요.
예외는 그걸 *받는* 쪽에서 났으니, 어항은 이미 비워졌고 코인 지급만 실행되지 않았어요.
= 코드 주석에 "최악"이라고 적어둔 바로 그 상태(물고기만 사라지고 코인은 없음)예요.

`scripts/payout_tanks.py`는 **어항에 남아있던** 사람만 정산했어요. 이미 날아간 사람은
어항이 비어 있어서 대상에서 빠졌어요. 이 스크립트가 그들을 보상해요.

## 🚨 정확한 복구는 불가능해요

어항 내용(어종·치수)이 지워져서 **얼마치였는지 알 수 없어요.** 그래서
`잡은 마리수 × 1마리 평균값`으로 추정 지급해요. 평균이라 운 좋았던 사람은 덜 받고
나빴던 사람은 더 받지만, 데이터가 없는 상황에서 가장 공정한 근사예요.

대상 조건: **잡은 적이 있는데(caught>0) · 어항이 비었고 · 낚시판매로 받은 코인이 0인** 사람.

🚨 note는 `낚시판매:장애보상`이에요. `낚시판매`로 시작해야 경제 리포트의 발행 출처
집계에서 낚시로 잡혀요(리포트는 `:` 앞을 기준으로 묶어요).

🚨 **두 번 돌려도 안전해요.** 이미 이 note로 받은 사람은 건너뛰어요.

## 쓰는 법

    python scripts/payout_lost_fish.py            # 미리보기
    python scripts/payout_lost_fish.py --apply    # 실제 지급
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

for candidate in (BOT_DIR.parent / "운영봇_토큰_백업.env", BOT_DIR / ".env"):
    if candidate.is_file():
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

from utils.coin_wallet import _add_sync, _log_sync  # noqa: E402
from utils.fish_data import COIN_PIECES, expected_pieces_per_cast  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

NOTE = "낚시판매:장애보상"
APPLY = "--apply" in sys.argv


def main() -> int:
    fish, coin_log = _db["fish"], _db["coin_log"]
    ev = expected_pieces_per_cast()

    already = {str(l["to"]) for l in coin_log.find({"note": NOTE}, {"to": 1})}

    plan = []
    for doc in fish.find({}):
        uid = str(doc["_id"])
        caught = int(doc.get("caught", 0) or 0)
        tank_n = sum(len(v) if isinstance(v, list) else int(v or 0)
                     for v in (doc.get("tank") or {}).values())
        got = sum(l["amount"] for l in
                  coin_log.find({"to": uid, "note": {"$regex": "^낚시판매"}}, {"amount": 1}))
        if caught and tank_n == 0 and got == 0 and uid not in already:
            coins = round(caught * ev) // COIN_PIECES
            if coins:
                plan.append({"uid": uid, "caught": caught, "coins": coins})

    print("=" * 62)
    print("[미리보기 - 아무것도 바꾸지 않아요]" if not APPLY else "[실제 지급]")
    print("=" * 62)
    print(f"\n1마리 평균 {ev / COIN_PIECES:.2f}코인으로 추정해요")
    print(f"대상: {len(plan)}명 / 총 {sum(p['coins'] for p in plan)}코인")
    if already:
        print(f"건너뜀: {len(already)}명 (이미 보상받음)")
    print()
    for p in sorted(plan, key=lambda x: -x["coins"]):
        print(f"  {p['uid']:20s} {p['caught']:3d}마리 잃음 → {p['coins']:3d}코인")

    if not APPLY:
        print("\n실제로 지급하려면: python scripts/payout_lost_fish.py --apply")
        return 0

    if not plan:
        print("\n지급할 대상이 없어요.")
        return 0

    backup_dir = BOT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (backup_dir / f"lost_fish_payout_{stamp}.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    paid = 0
    for p in plan:
        _add_sync(p["uid"], p["coins"])
        _log_sync("add", None, p["uid"], p["coins"], NOTE)
        fish.update_one({"_id": p["uid"]}, {"$inc": {"sold": p["coins"]}})
        paid += p["coins"]
    print(f"\n💰 지급 완료: {len(plan)}명 / {paid}코인")
    return 0


if __name__ == "__main__":
    sys.exit(main())
