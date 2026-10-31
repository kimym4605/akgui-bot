# -*- coding: utf-8 -*-
"""🏆 내전 승리팀에게 악귀코인을 지급해요 (+ MVP 보너스).

## 왜 스크립트인가

`/팀짜기` 승리 버튼은 **베팅 정산**만 해요(파리뮤추얼 — 판돈을 이긴 쪽에 나눠주는
재분배라 총량이 안 변해요). "이긴 사람 전원에게 N코인"은 봇이 새로 찍어내는
**발행**이라 다른 얘기고, 지금 그 기능은 없어요. 운영진이 내전을 열 때마다
손으로 주는 게 현재 방식이라 이 스크립트로 처리해요.

## 🚨 note를 `베팅정산`으로 시작하면 안 돼요

`coin_ledger.classify()`가 `베팅정산*`을 **redist(재분배)** 로 분류해서
`report_economy.py`의 발행 집계에서 **통째로 빠져요**. 내전 보상은 진짜 발행이니
`내전보상:*` 으로 남겨요 — 리포트의 발행원 묶음은 `note.split(":")[0]` 이라
`내전보상` 한 줄로 모여요.

## 🚨 두 번 돌리면 두 번 지급돼요 → matchId로 막아요

낚시 보상(`payout_tanks.py`)은 어항을 비우면서 줘서 멱등이었지만, 코인 지급은
그냥 더하기라 재실행이 위험해요. 그래서 note 끝에 **경기 id 앞 8자**를 붙이고,
실행 전에 `coin_log`에서 같은 꼬리표를 찾아 **이미 줬으면 멈춰요**.

## 🚨 동명이인을 닉네임으로 고르지 마세요

2026-11-01 지급 때 서버에 `다람쥐`가 **둘**이었어요(`ram_water12` / `ram._.g`).
닉네임만 보고 골랐으면 코인이 엉뚱한 사람에게 갔을 거예요. 받는 사람은
**`scrim_matches`의 `winners` 배열**(= `/팀짜기`가 기록한 실제 승리팀)에서
가져오니 추측이 들어갈 자리가 없어요.

## 쓰는 법

    python scripts/payout_scrim.py                               # 최근 내전 미리보기
    python scripts/payout_scrim.py --mvp <유저ID> --apply        # 실제 지급
    python scripts/payout_scrim.py --match <경기_id> ...         # 특정 경기 지정
    python scripts/payout_scrim.py --win 20 --mvp-bonus 10 ...   # 금액 변경
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
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

from bson import ObjectId  # noqa: E402

from utils.coin_wallet import _add_sync, _get_balance_sync, _log_sync  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

KST = timezone(timedelta(hours=9))
NOTE_WIN = "내전보상:승리"
NOTE_MVP = "내전보상:MVP"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--match", help="scrim_matches 의 _id (없으면 가장 최근 경기)")
    p.add_argument("--mvp", help="MVP 유저 ID (없으면 MVP 보너스 생략)")
    p.add_argument("--win", type=int, default=20, help="승리 1인당 코인 (기본 20)")
    p.add_argument("--mvp-bonus", type=int, default=10, help="MVP 추가 코인 (기본 10)")
    p.add_argument("--apply", action="store_true", help="실제로 지급")
    return p.parse_args()


def main() -> int:
    a = parse_args()

    if a.match:
        doc = _db["scrim_matches"].find_one({"_id": ObjectId(a.match)})
        if not doc:
            print(f"❌ 그런 경기가 없어요: {a.match}")
            return 1
    else:
        doc = _db["scrim_matches"].find_one({}, sort=[("_id", -1)])
        if not doc:
            print("❌ 내전 기록이 하나도 없어요.")
            return 1

    winners = [str(u) for u in (doc.get("winners") or [])]
    if not winners:
        print("❌ 이 경기에 승리팀 기록이 없어요.")
        return 1

    stats = doc.get("stats") or {}
    match_id = str(stats.get("matchId") or doc["_id"])
    tail = match_id.replace("-", "")[:8]          # 중복 지급 방지 꼬리표
    when = doc["_id"].generation_time.astimezone(KST).strftime("%Y-%m-%d %H:%M")

    # 발로란트 닉네임을 붙여요 (누구인지 눈으로 확인하는 용도)
    by_uid = {str(p.get("userId")): p for p in (stats.get("players") or [])}

    if a.mvp and a.mvp not in winners:
        print(f"❌ MVP({a.mvp})가 승리팀에 없어요. 승리팀: {winners}")
        return 1

    # 🚨 이미 준 경기인지 먼저 봐요. note 꼬리표로 판정해요.
    already = list(_db["coin_log"].find({"note": {"$regex": f":{tail}$"}},
                                        {"to": 1, "amount": 1, "note": 1}))
    print("=" * 70)
    print("[미리보기 - 아무것도 바꾸지 않아요]" if not a.apply else "[실제 지급]")
    print("=" * 70)
    print(f"\n경기      {when}  ·  {doc.get('map') or '맵 미기록'}  ·  {doc.get('note') or ''}")
    print(f"matchId   {match_id}  (꼬리표 :{tail})")
    rounds = (stats.get("rounds") or {})
    if rounds:
        print(f"스코어    {rounds.get('red')} : {rounds.get('blue')}"
              f"  (이긴 팀 {stats.get('wonTeam')})")

    if already:
        print(f"\n🛑 이 경기는 **이미 지급**됐어요 ({len(already)}건 / "
              f"{sum(int(l.get('amount') or 0) for l in already)}코인).")
        for l in already:
            print(f"     {l.get('to')}  +{l.get('amount')}  {l.get('note')}")
        print("\n중복 지급을 막으려고 멈춰요. 정말 또 주려면 note 꼬리표를 바꾸세요.")
        return 1

    plan = []
    for uid in winners:
        amount = a.win + (a.mvp_bonus if uid == a.mvp else 0)
        p = by_uid.get(uid) or {}
        label = f"{p.get('name', '?')}#{p.get('tag', '?')}" if p else "(전적 미기록)"
        plan.append({
            "uid": uid, "amount": amount, "label": label,
            "mvp": uid == a.mvp, "before": _get_balance_sync(uid),
            "kda": f"{p.get('kills')}/{p.get('deaths')}/{p.get('assists')}" if p else "-",
        })

    print(f"\n승리팀 {len(plan)}명 · 총 {sum(p['amount'] for p in plan)}코인\n")
    for p in plan:
        mark = " 👑MVP" if p["mvp"] else ""
        print(f"  {p['uid']:20s} {p['label']:22s} KDA {p['kda']:>9s}"
              f"  {p['before']:4d} → {p['before'] + p['amount']:4d}코인"
              f"  (+{p['amount']}){mark}")

    if not a.apply:
        print("\n실제로 지급하려면 같은 명령에 --apply 를 붙이세요.")
        return 0

    backup_dir = BOT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"scrim_payout_{tail}_{stamp}.json"
    backup.write_text(json.dumps(
        {"match_id": match_id, "at": when, "map": doc.get("map"), "plan": plan},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n💾 백업: {backup.relative_to(BOT_DIR)}")

    paid = 0
    for p in plan:
        # 승리분과 MVP 보너스는 **따로** 기록해요. 한 줄로 합치면 리포트에서
        # "MVP 보너스가 얼마나 나갔나"를 영영 알 수 없어요.
        _add_sync(p["uid"], a.win)
        _log_sync("add", None, p["uid"], a.win, f"{NOTE_WIN}:{tail}")
        paid += a.win
        if p["mvp"]:
            _add_sync(p["uid"], a.mvp_bonus)
            _log_sync("add", None, p["uid"], a.mvp_bonus, f"{NOTE_MVP}:{tail}")
            paid += a.mvp_bonus

    print(f"💰 지급 완료: {len(plan)}명 / {paid}코인")
    print("\n[지급 후 잔액 재조회]")
    for p in plan:
        now = _get_balance_sync(p["uid"])
        want = p["before"] + p["amount"]
        ok = "✅" if now == want else f"❌ 기대 {want}"
        print(f"  {p['uid']:20s} {p['label']:22s} {now:4d}코인  {ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
