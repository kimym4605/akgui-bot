"""🐟 장애보상 1차(평균값)를 **어종별 실제 가격**으로 다시 계산해 차액을 줘요 (3차).

## 1차가 왜 부족했나

`scripts/payout_lost_fish.py`는 어항이 통째로 날아간 사람에게
`잡은 마리수 × 전체 평균(1.02코인)`으로 줬어요. 어종을 알 수 없어서였죠.

🚨 **그게 전설을 1코인으로 쳐버렸어요.** 전설은 300~700조각(30~70코인)이에요.
평균값에는 전설의 기대값이 0.13%만 섞여 있어서, 실제로 전설을 잡아둔 사람은
**50배를 손해** 봤어요. 평균은 "여러 명에게 나눠줄 때" 공정하고, **한 사람의
실제 결과**를 복원할 때는 쓰면 안 돼요.

## 뭘로 복원하나 - 어항은 지워졌지만 단서 셋이 남았어요

| 단서 | 뭘 알려주나 |
|---|---|
| `best` | **가장 좋았던 1마리의 어종**(+있으면 치수). 이게 전설을 되살려요 |
| `caught` | 어항에 몇 마리 있었나 |
| `dust` | 🚨 날아간 어항의 **총 조각 % 10** |

⭐ `dust`가 왜 남아있나: 버그는 `sell_all`이 DB를 **다 고친 뒤** 호출부에서 터졌어요.
그 전에 `dust = 총조각 % 10`이 이미 쓰여 있었던 거예요. 사고 흔적이 역산 단서가 됐어요.

## 계산식

    총조각 ≈ value_pieces(best)  +  (caught-1) × (best 이하 등급의 평균)

- `best` 1마리는 **어종을 아니까** 바로 계산해요. 치수까지 남아있으면 정확한 값이에요.
- 🚨 치수가 없는 **전설**은 범위의 **최솟값(30코인)** 으로 쳐요. 중앙값(50코인)으로
  치면 유통량 940코인에 +10.5%가 한 번에 꽂혀요(`LOWBALL_GRADES` 주석 참고).
- 나머지 `caught-1`마리는 어종을 모르지만 **best보다 높은 등급일 수는 없어요**
  (`best`는 최고 등급을 기록하니까). 그래서 그 조건부 평균을 써요.
- 마지막에 **`dust`에 맞게 당겨요**: 참값은 `≡ dust (mod 10)`이어야 하니,
  추정값을 그 조건을 만족하는 가장 가까운 수로 옮겨요. 오차를 ±5조각 안으로 줄여줘요.

## 🚨 받은 것보다 적게 나오면 **회수하지 않아요**

봇 버그로 생긴 일이라 유저가 손해를 볼 이유가 없어요. 차액이 양수일 때만 줘요.

🚨 note는 `낚시판매:장애보상3`. `낚시판매`로 시작해야 경제 리포트가 낚시 발행으로 묶어요.
🚨 **두 번 돌려도 안전해요** - 이 note를 이미 받은 사람은 건너뛰어요.

## 쓰는 법

    python scripts/repay_lost_fish_exact.py            # 미리보기
    python scripts/repay_lost_fish_exact.py --apply    # 실제 지급
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
from utils.fish_data import (  # noqa: E402
    BY_KEY, COIN_PIECES, GRADE_ORDER, GRADES, pieces_of,
)
from utils.pokemon_store import _db  # noqa: E402

NOTE = "낚시판매:장애보상3"
PRIOR_NOTE = "낚시판매:장애보상"      # 1차(평균값)
APPLY = "--apply" in sys.argv

# 🚨 치수를 모르는 **전설**은 범위의 **최솟값**으로 쳐요 (사용자 결정 2026-10-17).
#
# 전설은 300~700조각(30~70코인)이라 중앙값이냐 최솟값이냐가 20코인 차이예요.
# 총 유통량이 940코인뿐인데 중앙값으로 치면 **+10.5% 인플레**가 한 번에 생겨요.
# 그래서 "모르면 유저에게 유리하게" 대신 **"모르면 보수적으로"** 를 택했어요.
#
# ⚠️ 어항이 남아있던 4명(`payout_tanks.py`)은 중앙값으로 정산했어요. 잣대가 달라진 건
#    맞지만, 그쪽은 **어종이 전부 확인된** 정산이고 이쪽은 `best` 하나로 16마리를
#    역산하는 추정이에요. 추정에 더 보수적인 값을 쓰는 건 합리적이에요.
#
# ⚠️ 이 규칙은 `best` 1마리에만 적용하는 게 아니라 **나머지 마리의 조건부 평균에도**
#    같이 적용해요(아래 `cond_mean_pieces`). 한쪽만 깎으면 같은 전설을 두 잣대로
#    재게 돼요.
LOWBALL_GRADES = {"전설"}


def value_pieces(key: str, size: int | None) -> int:
    """이 물고기를 몇 조각으로 칠 건가. **역산 전용 잣대**예요.

    치수를 아는 건 그대로 `pieces_of`로 정확히 계산해요. 모르는데 등급이
    `LOWBALL_GRADES`면 범위의 **최솟값**으로 쳐요(위 주석의 이유)."""
    grade = BY_KEY.get(key, (None, None))[0]
    if not grade:
        return 0
    if size is None and grade in LOWBALL_GRADES:
        return GRADES[grade]["pieces"][0]
    return pieces_of(key, size)


def cond_mean_pieces(best_grade: str) -> float:
    """`best_grade` **이하** 등급만 나올 때의 1마리 평균 조각.

    나머지 물고기들은 어종을 모르지만, `best`보다 높은 등급일 수는 없어요
    (`record_cast`가 최고 등급을 `best`에 적으니까요). 그 조건을 반영해요.

    ⚠️ 어종별 값은 `value_pieces(k, None)`로 평균해요. `best` 1마리와
    **같은 잣대**를 써야 둘을 더한 값이 일관돼요."""
    cap = GRADE_ORDER.index(best_grade)       # GRADE_ORDER는 높은 등급이 앞
    grades = GRADE_ORDER[cap:]
    total_w = sum(GRADES[g]["weight"] for g in grades)
    out = 0.0
    for g in grades:
        keys = [k for k, (gg, _) in BY_KEY.items() if gg == g]
        avg = sum(value_pieces(k, None) for k in keys) / len(keys)
        out += GRADES[g]["weight"] / total_w * avg
    return out


def snap_to_dust(estimate: float, dust: int, floor: int) -> int:
    """추정 조각수를 `≡ dust (mod 10)`인 가장 가까운 값으로 옮겨요.

    참값은 반드시 그 조건을 만족해요(`dust = 참값 % 10`). 공짜로 얻는 정확도예요.
    `floor`(= 아는 물고기 값)보다 작아지는 건 막아요 - 그건 불가능한 값이에요."""
    base = round(estimate)
    down = base - ((base - dust) % 10)
    up = down + 10
    best = min((down, up), key=lambda v: (abs(v - estimate), -v))
    while best < floor:
        best += 10
    return best


def main() -> int:
    fish, coin_log = _db["fish"], _db["coin_log"]

    already = {str(r["to"]) for r in coin_log.find({"note": NOTE}, {"to": 1})}

    plan, skipped = [], []
    for row in coin_log.find({"note": PRIOR_NOTE}, {"to": 1, "amount": 1}):
        uid = str(row["to"])
        if uid in already:
            skipped.append((uid, "이미 3차 보상 받음"))
            continue
        paid = int(row.get("amount", 0) or 0)
        doc = fish.find_one({"_id": uid}) or {}
        caught = int(doc.get("caught", 0) or 0)
        best = doc.get("best") or {}
        bkey = best.get("key")

        # 🚨 1차 지급 이후에 **또 낚시했다면** `best`가 날아간 어항의 물고기가
        #    아닐 수 있어요. 그러면 역산 전제가 무너지니 건너뛰어요.
        later = [r for r in coin_log.find(
            {"to": uid, "note": {"$regex": "^낚시판매"}}, {"note": 1})
            if str(r.get("note")) not in (PRIOR_NOTE, NOTE)]
        if later:
            skipped.append((uid, "1차 이후 판매 이력 있음 - 역산 불가"))
            continue
        if not bkey or bkey not in BY_KEY or not caught:
            skipped.append((uid, "best 기록이 없어 어종을 모름"))
            continue

        grade, name = BY_KEY[bkey]
        best_pieces = value_pieces(bkey, best.get("size"))
        rest = max(0, caught - 1)
        est = best_pieces + rest * cond_mean_pieces(grade)
        dust = int(doc.get("dust", 0) or 0)
        total = snap_to_dust(est, dust, best_pieces)
        coins = total // COIN_PIECES

        plan.append({
            "uid": uid, "caught": caught, "paid": paid,
            "best": f"{GRADES[grade]['emoji']} {grade} {name}"
                    + (f" {best['size']}cm" if best.get("size") else " (치수 기록 없음)"),
            "best_coins": best_pieces / COIN_PIECES,
            "est_pieces": round(est, 1), "snapped": total, "dust": dust,
            "should": coins, "top_up": max(0, coins - paid),
        })

    print("=" * 70)
    print("[미리보기 - 아무것도 바꾸지 않아요]" if not APPLY else "[실제 지급]")
    print("=" * 70)
    print(f"\n1차(평균값) 지급을 받은 사람: {len(plan) + len(skipped)}명\n")
    for p in sorted(plan, key=lambda x: -x["top_up"]):
        print(f"  {p['uid']}")
        print(f"     최고 기록  {p['best']}  = {p['best_coins']:.1f}코인")
        print(f"     {p['caught']}마리 추정 {p['est_pieces']}조각 "
              f"-> dust({p['dust']}) 맞춤 {p['snapped']}조각 = {p['should']}코인")
        print(f"     1차 지급 {p['paid']}코인  →  차액 "
              f"{'+' + str(p['top_up']) if p['top_up'] else '없음 (회수하지 않아요)'}")
    for uid, why in skipped:
        print(f"  {uid}  건너뜀 - {why}")

    total_up = sum(p["top_up"] for p in plan)
    targets = [p for p in plan if p["top_up"]]
    print(f"\n{'─' * 70}")
    print(f"지급 대상 {len(targets)}명 / 총 {total_up}코인")
    if total_up:
        supply = sum(int(d.get("coin", 0) or 0) for d in _db["coin_reset_backup"].find({})) \
            + sum(int(d.get("coin", 0) or 0) for d in _db["trainers"].find({})) \
            if "trainers" in _db.list_collection_names() else 0
        if supply:
            print(f"⚠️ 현재 총 유통량 {supply}코인 대비 +{total_up / supply * 100:.1f}%")

    if not APPLY:
        print("\n실제로 지급하려면: python scripts/repay_lost_fish_exact.py --apply")
        return 0
    if not targets:
        print("\n지급할 대상이 없어요.")
        return 0

    backup_dir = BOT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (backup_dir / f"lost_fish_exact_{stamp}.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    paid_sum = 0
    for p in targets:
        _add_sync(p["uid"], p["top_up"])
        _log_sync("add", None, p["uid"], p["top_up"], NOTE)
        fish.update_one({"_id": p["uid"]}, {"$inc": {"sold": p["top_up"]}})
        paid_sum += p["top_up"]
    print(f"\n💰 지급 완료: {len(targets)}명 / {paid_sum}코인")
    return 0


if __name__ == "__main__":
    sys.exit(main())
