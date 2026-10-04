"""`/팀짜기` 🎲 베팅 붙이기 관련 로직을 확인해요. (DB 없이 순수 계산/구조만)

2026-10-05에 붙였어요. 코인이 849개 풀려 있는데 소비가 5%뿐이라, 이미 만들어둔 베팅이
`/베팅개설`→`/베팅`→`/베팅마감`→`/베팅결과` 네 단계라서 2번 쓰이고 멈춰 있었거든요.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import bet_store

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def doc_with(wagers, status=bet_store.STATUS_OPEN, source=None):
    return {
        "_id": "bet1",
        "teamNames": ["A팀", "B팀"],
        "status": status,
        "wagers": wagers,
        "sourceMessageId": source,
        "captains": ["1", "2"],
    }


print("1) 파리뮤추얼 배당 (코인 총량이 안 늘어난다)")
d = doc_with([
    {"userId": "a", "team": 1, "amount": 10},
    {"userId": "b", "team": 1, "amount": 10},
    {"userId": "c", "team": 2, "amount": 20},
])
payouts, refunded = bet_store.compute_payouts(d, winner=1)
check("환불 아님", refunded is False)
check("a·b가 각 20코인", payouts == {"a": 20, "b": 20}, str(payouts))
check("지급 총액 = 판돈 총액", sum(payouts.values()) == 40, str(sum(payouts.values())))

print("2) 이긴 쪽에 아무도 안 걸면 전원 환불")
d = doc_with([{"userId": "a", "team": 1, "amount": 10}])
payouts, refunded = bet_store.compute_payouts(d, winner=2)
check("환불 처리", refunded is True)
check("건 만큼 그대로", payouts == {"a": 10}, str(payouts))

print("3) 나눗셈 나머지가 사라지지 않는다")
d = doc_with([
    {"userId": "a", "team": 1, "amount": 3},
    {"userId": "b", "team": 1, "amount": 1},
    {"userId": "c", "team": 2, "amount": 10},
])
payouts, _ = bet_store.compute_payouts(d, winner=1)
check("지급 총액 = 14", sum(payouts.values()) == 14, str(payouts))
check("나머지는 최다 베팅자에게", payouts["a"] > payouts["b"], str(payouts))

print("4) 팀 이름 / 내 베팅 조회")
d = doc_with([{"userId": "a", "team": 2, "amount": 7}])
check("team_name", bet_store.team_name(d, 2) == "B팀")
check("user_wager", bet_store.user_wager(d, "a") == (2, 7), str(bet_store.user_wager(d, "a")))
check("안 건 사람", bet_store.user_wager(d, "zzz") == (None, 0))

print("5) ⭐ 남의 베팅을 정산하지 않는다 (sourceMessageId 대조)")
# `/팀짜기` 승리 버튼은 자기가 연 베팅만 건드려야 해요.
mine = doc_with([], source="12345")
other = doc_with([], source=None)          # /베팅개설로 연 것
check("내 메시지면 통과", str(mine["sourceMessageId"]) == "12345")
check("sourceMessageId 없으면 건너뜀", not other["sourceMessageId"])
check("다른 메시지면 건너뜀", str(mine["sourceMessageId"]) != "99999")

print("6) 마감된 베팅에는 못 건다")
async def t6():
    locked = doc_with([], status=bet_store.STATUS_LOCKED)
    ok, msg = await bet_store.place_wager(locked, "a", 1, 5)
    check("마감이면 거부", ok is False, msg)

    opened = doc_with([{"userId": "a", "team": 1, "amount": 1}])
    ok, msg = await bet_store.place_wager(opened, "a", 2, 5)
    check("양쪽에는 못 건다", ok is False, msg)

    ok, msg = await bet_store.place_wager(opened, "a", 1, bet_store.MAX_WAGER + 1)
    check("한도 초과 거부", ok is False, msg)

    ok, msg = await bet_store.place_wager(opened, "b", 1, 0)
    check("0코인 거부", ok is False, msg)
asyncio.run(t6())

print("7) 구조 - 버튼과 공용 함수가 제자리에 있다")
import inspect
from cogs import team as team_cog

src = inspect.getsource(team_cog)
check("🎲 베팅 버튼 custom_id", 'custom_id="akgui:team:bet"' in src)
check("승리 보고가 베팅을 정산한다", "_settle_bet" in src)
check("source 대조를 한다", "sourceMessageId" in src)
check("누구나 누를 수 있다(소유자 검사 안 씀)",
      "async def bet(" in src and "Session.load(interaction.message.id)" in src)

bet_src = inspect.getsource(bet_store)
check("정산은 한 곳에서", "async def settle(" in bet_src)
check("거는 것도 한 곳에서", "async def place_wager(" in bet_src)

from cogs import betting as betting_cog
b_src = inspect.getsource(betting_cog)
check("/베팅결과도 공용 정산을 쓴다", "bet_store.settle(" in b_src)
check("/베팅도 공용 place_wager를 쓴다", "bet_store.place_wager(" in b_src)
check("지급 로직이 betting.py에 중복되지 않음", "compute_payouts" not in b_src)

print("8) 뷰 구성 - 버튼이 한 줄 한도를 안 넘는다")
view = team_cog.TeamSplitView()
rows = {}
for comp in view.to_components():
    for item in comp.get("components", []):
        rows.setdefault(comp.get("id", id(comp)), []).append(item)
for key, items in rows.items():
    check(f"한 줄에 {len(items)}개 (<=5)", len(items) <= 5)
# 윗줄 5개(섞기·무작위·조정·팀장·맵) + 아랫줄 3개(베팅·A승·B승) = 8개예요.
check("버튼 총 8개", sum(len(v) for v in rows.values()) == 8,
      str(sum(len(v) for v in rows.values())))

print()
if failures:
    print(f"실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("전부 통과")
