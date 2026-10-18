"""📊 서버 주간 리포트 — 수치를 모아 AI가 읽을 수 있는 형태로 만들고, 요약을 받아와요.

## 왜 (2026-10-18)

지금까지 경제 점검은 `scripts/report_economy.py`를 **사람이 손으로 돌려서** 했어요.
그래서 문제가 생겨도 돌려볼 생각을 해야 알 수 있었어요(상점 구매 0건을 열흘 뒤에 발견한
적이 있어요). 주 1회 자동으로 요약이 날아오면 그 지연이 사라져요.

## 🚨 숫자는 코드가 세고, 해석만 AI가 해요

AI에게 원본 로그를 주고 "분석해줘"라고 하면 **숫자를 지어내요.** 그래서 집계는 전부
여기(`collect()`)서 파이썬으로 하고, 모델에겐 **이미 계산된 표**만 줘요. 모델이 할 일은
"이게 좋은 신호인지 나쁜 신호인지, 뭘 봐야 하는지"를 말하는 것뿐이에요.

## 🚨 `coin_log`에는 타임스탬프 필드가 없어요

`at`·`createdAt` 같은 게 없고 `_id`(ObjectId)에 생성 시각이 박혀 있어요. 기간을 자르려면
`ObjectId.from_datetime()`으로 경계값을 만들어 `_id`로 비교해야 해요.
⚠️ ObjectId의 시각 정밀도는 **초 단위**예요. 주간 집계에는 충분해요.
⚠️ 유저 필드도 종류마다 달라요 — `add`는 `to`, `spend`는 `from`이에요.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from utils import ai, coin_ledger
from utils.pokemon_store import _db

log = logging.getLogger(__name__)

FEATURE = "서버리포트"
KST = timezone(timedelta(hours=9))

_coin_log = _db["coin_log"]


def _since(days: int) -> ObjectId:
    return ObjectId.from_datetime(datetime.now(timezone.utc) - timedelta(days=days))


def _collect_sync(days: int) -> dict:
    # 🚨 분류 규칙은 `utils/coin_ledger.py` 하나뿐이에요. `scripts/report_economy.py`도
    #    같은 걸 써요. 여기서 따로 세면 두 리포트가 다른 답을 내요(실제로 그랬어요).
    entries = list(_coin_log.find({"_id": {"$gte": _since(days)}}))
    agg = coin_ledger.totals(entries)

    issue_by: Counter[str] = Counter()
    burn_by: Counter[str] = Counter()
    people: set[str] = set()

    for entry in entries:
        cls = coin_ledger.classify(entry)
        uid = coin_ledger.user_of(entry)
        if uid:
            people.add(uid)
        note = (entry.get("note") or "?").strip()
        amount = int(entry.get("amount") or 0)
        if cls == "issue":
            issue_by[note] += amount
        elif cls == "burn":
            burn_by[note] += amount

    # 🚨 지갑은 **두 컬렉션에 흩어져** 있어요. `trainers`만 보면 절반도 안 세요.
    wallets: list[int] = []
    for name in coin_ledger.WALLET_COLLECTIONS:
        wallets += [
            int(d.get("coin") or 0)
            for d in _db[name].find({"coin": {"$exists": True}}, {"coin": 1})
        ]
    wallets = [w for w in wallets if w >= 0]

    return {
        "days": days,
        "issued": agg["issued"],
        "burned": agg["burned"],
        "burn_rate": agg["burn_rate"],
        "net": agg["net"],
        "refund": agg["refund"],
        "issue_by": issue_by.most_common(8),
        "burn_by": burn_by.most_common(8),
        "gamble_bet": agg["gamble_bet"],
        "gamble_net": agg["gamble_net"],
        "active_people": len(people),
        "wallet_total": sum(wallets),
        "wallet_median": statistics.median(wallets) if wallets else 0,
        "wallet_count": len(wallets),
    }


async def collect(days: int = 7) -> dict:
    return await asyncio.to_thread(_collect_sync, days)


def render(data: dict) -> str:
    """사람도 읽고 모델도 읽는 표. **여기 없는 건 모델도 몰라요.**"""
    lines = [
        f"기간: 최근 {data['days']}일",
        f"발행: {data['issued']}코인",
        f"소각: {data['burned']}코인 (소각률 {data['burn_rate']:.1f}%)",
        f"순증: {data['net']:+}코인",
        f"활동한 사람: {data['active_people']}명",
        f"지갑: {data['wallet_count']}개 · 총 {data['wallet_total']}코인 · 중앙값 {data['wallet_median']:.0f}",
        "",
        "발행처:",
    ]
    lines += [f"  {note} {amount}코인" for note, amount in data["issue_by"]] or ["  없음"]
    lines.append("소비처:")
    lines += [f"  {note} {amount}코인" for note, amount in data["burn_by"]] or ["  없음"]
    if data["gamble_bet"]:
        lines.append(
            f"도박: 베팅 {data['gamble_bet']}코인 중 {data['gamble_net']}코인만 실제 소각"
        )
    return "\n".join(lines)


SYSTEM = """너는 디스코드 게임 서버의 운영자에게 주간 경제 리포트를 brief 하는 분석가야.
한국어 존댓말로 쓰고, 운영자 한 사람에게 보고하는 톤으로 써.

이 서버의 구조:
- 악귀코인은 출석·미션·낚시·업적으로 벌고, 상점·카드뽑기·도박·칭호로 쓴다.
- 낚시는 가장 큰 발행원이고, 낚시대(소각)를 사야 할 수 있어서 소각과 묶여 있다.
- 도박은 베팅액이 아니라 **하우스 몫만** 실제로 사라진다.

지킬 것:
- **받은 표의 숫자만** 써. 없는 수치를 지어내거나 추세를 가정하지 마
  (지난주 데이터를 안 줬으면 "늘었다/줄었다"고 말하지 마).
- 5문장 안쪽, 400자 안쪽. 문단 하나로.
- 숫자를 그대로 나열하지 마. 표는 이미 같이 보내니까, **무슨 뜻인지**만 말해.
- 눈에 띄는 것 한두 개를 짚고, 봐야 할 지점을 알려줘. 과장하지 마.
- 특별한 게 없으면 "특별한 변화 없음"이라고 담백하게 말해도 돼. 억지로 문제를 만들지 마."""


async def summarize(data: dict) -> str | None:
    """리포트 해설. 못 만들면 None(그러면 표만 보내요)."""
    if not data["issued"] and not data["burned"]:
        return None  # 집계할 활동 자체가 없으면 해설할 것도 없어요

    key = "report:" + ai.fingerprint(
        data["days"], data["issued"], data["burned"],
        data["active_people"], data["wallet_total"],
        tuple(data["issue_by"]), tuple(data["burn_by"]),
    )

    return await ai.ask(
        SYSTEM,
        f"이번 주 수치야. 운영자에게 brief 해줘.\n\n{render(data)}",
        feature=FEATURE,
        max_tokens=600,
        cache_key=key,
        cache_hours=24.0,
    )
