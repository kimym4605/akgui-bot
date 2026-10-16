"""🎴 카드 전체 회수 + 뽑기에 쓴 코인 전액 환불 (테스트 기간 정리용).

2026-10-17에 확률을 3차 조정(레어 30->20, 에픽 5->3)하면서, 그 전까지의 뽑기를
**테스트로 보고 전부 되돌리기로** 했어요(사용자 지시).

## 하는 일

1. `cards` 컬렉션을 **파일로 백업**한 뒤 전부 지워요(보유 카드 + 천장 카운터).
2. `coin_log`에서 **뽑기에 실제로 쓴 코인**을 사람별로 계산해 돌려줘요.

## 🚨 환불액 계산

`쓴 코인 = (kind=spend 이고 note가 '카드뽑기'로 시작) 의 합`
`이미 돌려준 코인 = (kind=add 이고 note가 '카드뽑기:환불'로 시작) 의 합`
→ **실환불 = 쓴 것 - 이미 돌려준 것**

이미 돌려준 걸 빼지 않으면(동시 실행에 밀려 자동 환불된 건이 있어요) **두 번 돌려주게**
돼요. 지금은 그런 건이 0건이지만 계산에서 빼두는 게 맞아요.

## 🚨 환불 note를 `카드뽑기:환불`로 시작하는 이유

`scripts/report_economy.py`가 `REFUND_ADD`(= `카드뽑기:환불`로 시작)를 **발행이 아니라
환불로** 분류해요. 다른 이름을 쓰면 이 환불이 전부 '코인 발행'으로 잡혀서 발행량이
부풀고 소각률이 엉터리가 돼요.

## 🚨 두 번 돌려도 안전한가

네. 이미 `카드뽑기:환불(테스트초기화)` 로그가 있는 사람은 건너뛰어요.

## 쓰는 법

    python scripts/reset_cards_refund.py            # 미리보기 (아무것도 안 바꿔요)
    python scripts/reset_cards_refund.py --apply    # 실제로 실행
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

# 운영 DB에 붙어요. 로컬 .env는 **테스트봇**이라 MONGODB_URI가 다를 수 있어서
# 운영 토큰 백업 파일을 우선으로 읽어요(reference_akgui_bot_prod_access).
for candidate in (BOT_DIR.parent / "운영봇_토큰_백업.env", BOT_DIR / ".env"):
    if candidate.is_file():
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

from utils.coin_wallet import _add_sync, _log_sync, _uid  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

REFUND_NOTE = "카드뽑기:환불(테스트초기화)"
SPEND_PREFIX = "카드뽑기"
REFUND_PREFIX = "카드뽑기:환불"

APPLY = "--apply" in sys.argv


def main() -> int:
    cards = _db["cards"]
    coin_log = _db["coin_log"]

    # ---------- 1. 뽑기 소비·기환불 집계 ----------
    spent: dict[str, int] = {}
    already: dict[str, int] = {}
    done: set[str] = set()

    for entry in coin_log.find({"note": {"$regex": f"^{SPEND_PREFIX}"}},
                               {"kind": 1, "note": 1, "amount": 1, "from": 1, "to": 1}):
        note = entry.get("note") or ""
        amount = int(entry.get("amount") or 0)
        if entry.get("kind") == "spend":
            uid = _uid(entry.get("from"))
            spent[uid] = spent.get(uid, 0) + amount
        elif entry.get("kind") == "add" and note.startswith(REFUND_PREFIX):
            uid = _uid(entry.get("to"))
            already[uid] = already.get(uid, 0) + amount
            if note == REFUND_NOTE:
                done.add(uid)      # 이미 이 스크립트로 돌려준 사람

    plan = {}
    for uid, total in spent.items():
        if uid in done:
            continue
        net = total - already.get(uid, 0)
        if net > 0:
            plan[uid] = net

    card_docs = list(cards.find({}))
    total_cards = sum(int(d.get("draws", 0) or 0) for d in card_docs)

    print(f"{'=' * 62}")
    print(f"{'[미리보기 - 아무것도 바꾸지 않아요]' if not APPLY else '[실제 실행]'}")
    print(f"{'=' * 62}")
    print(f"\n회수할 도감: {len(card_docs)}명 / 누적 {total_cards}장")
    print(f"환불 대상  : {len(plan)}명 / 총 {sum(plan.values())}코인")
    if done:
        print(f"건너뜀     : {len(done)}명 (이미 이 스크립트로 환불받음)")
    print()
    for uid, amount in sorted(plan.items(), key=lambda kv: -kv[1]):
        owned = next((d for d in card_docs if str(d.get("_id")) == uid), None)
        n = sum((owned or {}).get("counts", {}).values())
        prev = already.get(uid, 0)
        tail = f" (이미 {prev} 환불받아 제외)" if prev else ""
        print(f"  {uid:20s} {amount:4d}코인 환불 · 카드 {n:3d}장 회수{tail}")

    if not APPLY:
        print("\n실제로 실행하려면: python scripts/reset_cards_refund.py --apply")
        return 0

    # ---------- 2. 백업 ----------
    backup_dir = BOT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"cards_before_reset_{stamp}.json"
    backup.write_text(
        json.dumps(
            {"cards": card_docs, "refund_plan": plan, "already_refunded": already},
            ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\n💾 백업: {backup.relative_to(BOT_DIR)}")

    # ---------- 3. 환불 ----------
    # ⚠️ 환불을 **먼저** 해요. 카드를 먼저 지우고 중간에 죽으면 "카드도 없고 코인도 없는"
    #    최악이 돼요. 반대 순서면 최악이라도 "코인은 돌려받았는데 카드가 남아있는" 상태라
    #    다시 돌리면 정리돼요(이미 환불한 사람은 건너뛰니까요).
    refunded = 0
    for uid, amount in plan.items():
        _add_sync(uid, amount)
        _log_sync("add", None, uid, amount, REFUND_NOTE)
        refunded += amount
    print(f"💰 환불 완료: {len(plan)}명 / {refunded}코인")

    # ---------- 4. 카드 회수 ----------
    result = cards.delete_many({})
    print(f"🎴 도감 회수: {result.deleted_count}개 문서 삭제")

    print("\n✅ 끝났어요. `python scripts/report_economy.py`로 확인해보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
