"""🪙 코인 로그 한 줄을 **발행/소각/재분배/도박/환불** 중 무엇으로 셀지 정하는 규칙.

## 왜 모듈로 뺐나 (2026-10-18)

이 규칙은 원래 `scripts/report_economy.py` 안에만 있었어요. 그런데 `/서버리포트`가
생기면서 같은 규칙을 두 번 쓰게 됐고, 복제본이 **다른 답을 냈어요** — 처음 돌렸을 때
한쪽은 "소각률 95.6%", 다른 쪽은 "80.9%"였어요. 원인은 환불 제외를 빠뜨린 것이었고요.

경제 수치는 **한 소스에서만** 나와야 해요. 운영 판단의 근거라서, 두 화면이 다른 숫자를
말하면 어느 쪽도 믿을 수 없게 돼요. 그래서 규칙을 여기로 옮기고 둘 다 이걸 import해요.

🚨 **여기를 고치면 두 리포트가 같이 바뀌어요.** 그게 의도예요.
   `scripts/test_server_report.py`가 두 집계가 일치하는지 검사해요.

## 왜 이렇게 분류하나

- **재분배**(`내전베팅` ↔ `베팅정산:*`, 송금): 유저 사이를 오갈 뿐 총량이 안 변해요.
  양쪽에서 빼지 않으면 **송금 한 번이 소각 한 번으로** 잡혀요.
- **도박**(`도박` ↔ `도박 당첨`/`환불`/`버그 보상`): 나갔다가 **일부만** 돌아와요.
  베팅 총액이 아니라 **차액(하우스 몫)만** 소각이에요. 엣지가 ~9%라 148코인이 돌아도
  27코인만 사라져요. "많이 쓴다"와 "많이 태운다"는 다른 얘기예요.
- **환불**(`카드뽑기:환불`): 되돌린 거래라 **아예 없던 일**이에요. 발행도 소각도 아니고,
  짝이 되는 spend까지 소각에서 빼야 해요. 안 그러면 발행·소각이 **둘 다** 부풀어요.

⚠️ `도박 당첨`이 `도박`으로도 시작해요. 그래서 **add/spend를 먼저 보고** 갈라요.
⚠️ `coin_log`의 유저 필드는 종류마다 달라요 — `add`는 `to`, `spend`는 `from`이에요.
⚠️ 시각 필드가 없어요. `_id`(ObjectId)에 생성 시각이 박혀 있어요.
"""
from __future__ import annotations

from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

# 나갔다가 그대로 돌아오는 재분배 (파리뮤추얼). 총량 불변이라 양쪽에서 빼요.
REDIST_SPEND = ("내전베팅",)
REDIST_ADD = ("베팅정산",)
# 나갔다가 일부만 돌아와요. 차액(하우스 몫)만 소각이에요.
GAMBLE_SPEND = ("도박",)
GAMBLE_ADD = ("도박 당첨", "도박 환불", "도박 버그 보상")
# 되돌린 거래 — 소각도 발행도 아니에요.
REFUND_ADD = ("카드뽑기:환불",)

# 지갑 잔액이 흩어져 있는 컬렉션. 🚨 `trainers`만 보면 절반도 안 세요
# (2026-10-18 실측: trainers만 21개 / 실제 58개).
WALLET_COLLECTIONS = ("trainers", "coin_reset_backup")


def classify(entry: dict) -> str:
    """로그 한 줄 → issue / burn / gamble_bet / gamble_back / redist / refund / transfer."""
    note = entry.get("note") or ""
    kind = entry.get("kind")

    # 🚨 유저 사이를 오간 코인은 발행도 소각도 아니에요. 이 분기가 없으면 맨 아래
    #    `burn`으로 떨어져 **송금이 통째로 소각으로** 집계돼요.
    if kind == "transfer":
        return "transfer"

    if kind == "add":
        if note.startswith(GAMBLE_ADD):
            return "gamble_back"
        if note.startswith(REDIST_ADD):
            return "redist"
        # ⚠️ 환불은 반드시 issue보다 **먼저** 걸러요.
        if note.startswith(REFUND_ADD):
            return "refund"
        return "issue"

    if note.startswith(GAMBLE_SPEND):
        return "gamble_bet"
    if note.startswith(REDIST_SPEND):
        return "redist"
    return "burn"


def user_of(entry: dict) -> str | None:
    """이 기록의 주인. ⚠️ `add`는 `to`, `spend`는 `from`이에요."""
    uid = entry.get("to") if entry.get("kind") == "add" else entry.get("from")
    return str(uid) if uid else None


def kst_of(oid) -> "datetime":  # noqa: F821
    """`coin_log`에는 시각 필드가 없어요. ObjectId 앞 4바이트에서 꺼내요."""
    return oid.generation_time.astimezone(KST)


def totals(entries: list[dict]) -> dict:
    """발행·소각·도박을 한 번에 집계해요. **두 리포트가 같은 답을 내는 지점이에요.**

    `burn`에서 환불액을 빼는 이유: 환불은 짝이 되는 spend를 되돌린 거라
    그 spend도 소각이 아니에요.
    """
    acc = {k: 0 for k in
           ("issue", "burn", "gamble_bet", "gamble_back", "redist", "refund", "transfer")}
    for entry in entries:
        acc[classify(entry)] += int(entry.get("amount") or 0)

    # 도박은 하우스 몫만 사라져요. 유저가 이득을 본 구간이면 소각 0이에요(음수 아님).
    gamble_net = max(0, acc["gamble_bet"] - acc["gamble_back"])
    net_burn = max(0, acc["burn"] - acc["refund"]) + gamble_net
    issued = acc["issue"]

    return {
        **acc,
        "gamble_net": gamble_net,
        "issued": issued,
        "burned": net_burn,
        "burn_rate": (net_burn / issued * 100) if issued else 0.0,
        "net": issued - net_burn,
    }
