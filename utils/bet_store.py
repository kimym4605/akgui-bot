"""내전 베팅 저장소예요.

## 왜 DB에 저장하나

베팅은 **코인을 미리 받아두는(에스크로)** 구조라, 봇이 재시작되면 판돈이 증발해요.
내전 세션(cogs/scrim.py)은 메모리에만 있어서 재시작하면 사라지는데, 베팅은 그러면 안 돼요.

## 배당 방식 (파리뮤추얼)

진 쪽에 걸린 코인을 이긴 쪽이 **건 비율대로** 나눠 가져요. 봇이 코인을 새로 찍지 않아서
서버 전체 코인 총량이 늘지 않아요(고정 배당 2배로 하면 봇이 코인을 만들어내야 해요).

- 이긴 쪽에 아무도 안 걸었으면 → **전원 환불**. 나눠줄 대상이 없는데 패자 돈만 뺏으면 안 돼요.
- 진 쪽에 아무도 안 걸었으면 → 이긴 쪽은 원금만 돌려받아요.
- 나눗셈에서 남는 코인은 **가장 많이 건 사람**에게 줘요. 그냥 버리면 코인이 사라져요.
"""
import asyncio
import logging
from datetime import datetime, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_bets = _db["bets"]

STATUS_OPEN = "open"          # 베팅 받는 중
STATUS_LOCKED = "locked"      # 마감, 경기 진행 중
STATUS_SETTLED = "settled"    # 정산 완료
STATUS_CANCELLED = "cancelled"

MIN_WAGER = 1
MAX_WAGER = 100   # 한 사람이 한 경기에 걸 수 있는 최대


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_sync(guild_id, channel_id, creator_id, captain1_id, captain2_id,
                 team1_name: str, team2_name: str, source_message_id=None) -> dict | None:
    """채널당 진행 중인 베팅은 하나뿐이에요. 이미 있으면 None."""
    existing = _bets.find_one({
        "channelId": str(channel_id),
        "status": {"$in": [STATUS_OPEN, STATUS_LOCKED]},
    })
    if existing:
        return None

    doc = {
        "guildId": str(guild_id),
        "channelId": str(channel_id),
        "createdBy": str(creator_id),
        "captains": [str(captain1_id), str(captain2_id)],
        "teamNames": [team1_name, team2_name],
        "status": STATUS_OPEN,
        "wagers": [],        # [{userId, team(1|2), amount}]
        "reports": {},       # {팀장ID: 1|2}
        "createdAt": _now_iso(),
        # `/팀짜기` 버튼으로 연 베팅이면 그 메시지 id예요. 승리 보고 버튼이 이걸 보고
        # "이 경기의 베팅이 맞는지" 확인한 뒤에 자동 정산해요. `/베팅개설`로 연 건 None이라,
        # 남의 베팅이 엉뚱하게 정산되는 일이 없어요.
        "sourceMessageId": str(source_message_id) if source_message_id else None,
    }
    result = _bets.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def _active_sync(channel_id) -> dict | None:
    return _bets.find_one({
        "channelId": str(channel_id),
        "status": {"$in": [STATUS_OPEN, STATUS_LOCKED]},
    })


def _add_wager_sync(bet_id, user_id, team: int, amount: int) -> bool:
    """베팅을 기록해요. 아직 열려있을 때만 들어가요.

    ⚠️ status 조건을 update 필터에 같이 넣어요. 조회 후 추가로 나누면 그 사이에 마감된
    베팅에 판돈이 들어갈 수 있어요(코인은 이미 빠진 뒤라 그대로 묶여버려요)."""
    result = _bets.update_one(
        {"_id": bet_id, "status": STATUS_OPEN},
        {"$push": {"wagers": {"userId": str(user_id), "team": team, "amount": amount}}},
    )
    return result.modified_count == 1


def _set_status_sync(bet_id, new_status: str, expected: str) -> bool:
    result = _bets.update_one({"_id": bet_id, "status": expected}, {"$set": {"status": new_status}})
    return result.modified_count == 1


def _report_sync(bet_id, captain_id, team: int) -> dict | None:
    """팀장의 결과 보고를 기록하고 갱신된 문서를 돌려줘요."""
    _bets.update_one(
        {"_id": bet_id, "status": STATUS_LOCKED},
        {"$set": {f"reports.{captain_id}": team}},
    )
    return _bets.find_one({"_id": bet_id})


def _get_sync(bet_id) -> dict | None:
    return _bets.find_one({"_id": bet_id})


def totals(doc: dict) -> tuple[int, int]:
    """(1팀 총액, 2팀 총액)"""
    t1 = sum(w["amount"] for w in doc.get("wagers", []) if w["team"] == 1)
    t2 = sum(w["amount"] for w in doc.get("wagers", []) if w["team"] == 2)
    return t1, t2


def user_wager(doc: dict, user_id) -> tuple[int | None, int]:
    """이 사람이 (어느 팀에, 얼마나) 걸었는지. 안 걸었으면 (None, 0)."""
    uid = str(user_id)
    mine = [w for w in doc.get("wagers", []) if w["userId"] == uid]
    if not mine:
        return None, 0
    return mine[0]["team"], sum(w["amount"] for w in mine)


def compute_payouts(doc: dict, winner: int) -> tuple[dict[str, int], bool]:
    """({유저ID: 받을 코인}, 전원환불여부)를 계산해요.

    이긴 쪽에 아무도 안 걸었으면 나눠줄 기준이 없어서 전원 환불이에요."""
    wagers = doc.get("wagers", [])
    win_total, lose_total = (totals(doc) if winner == 1 else totals(doc)[::-1])

    if win_total <= 0:
        # 전원 환불: 각자 건 만큼 그대로
        refunds: dict[str, int] = {}
        for w in wagers:
            refunds[w["userId"]] = refunds.get(w["userId"], 0) + w["amount"]
        return refunds, True

    payouts: dict[str, int] = {}
    winners = [w for w in wagers if w["team"] == winner]
    distributed = 0
    for w in winners:
        # 원금 + 진 쪽 판돈에서 내 지분만큼
        share = lose_total * w["amount"] // win_total
        payouts[w["userId"]] = payouts.get(w["userId"], 0) + w["amount"] + share
        distributed += share

    # 나눗셈에서 버려진 코인은 가장 많이 건 사람에게 몰아줘요(그냥 두면 코인이 사라져요).
    leftover = lose_total - distributed
    if leftover > 0 and winners:
        top = max(winners, key=lambda w: w["amount"])
        payouts[top["userId"]] = payouts.get(top["userId"], 0) + leftover

    return payouts, False


# ------------------------------------------------------------------
# 공개 API - 전부 async예요
# ------------------------------------------------------------------
async def create(guild_id, channel_id, creator_id, captain1_id, captain2_id, team1_name, team2_name,
                 source_message_id=None):
    return await asyncio.to_thread(
        _create_sync, guild_id, channel_id, creator_id, captain1_id, captain2_id,
        team1_name, team2_name, source_message_id,
    )


def team_name(doc: dict, team: int) -> str:
    return doc["teamNames"][team - 1]


async def place_wager(doc: dict, user_id, team: int, amount: int) -> tuple[bool, str]:
    """코인을 걸어요. `(성공여부, 안내문)`을 돌려줘요.

    `/베팅` 명령어와 `/팀짜기`의 🎲 버튼이 **둘 다 이 함수를 써요.** 검증과 에스크로가
    두 벌이 되면 한쪽만 고치는 사고가 나거든요.
    """
    if doc["status"] != STATUS_OPEN:
        return False, "이미 마감된 베팅이에요."
    if not (MIN_WAGER <= amount <= MAX_WAGER):
        return False, f"{MIN_WAGER}~{MAX_WAGER}개 사이로 걸어주세요."

    # 이미 건 팀과 다른 팀에는 못 걸어요(양쪽에 걸면 무조건 이득이라 베팅이 아니게 돼요).
    my_team, my_total = user_wager(doc, user_id)
    if my_team is not None and my_team != team:
        return False, f"이미 **{team_name(doc, my_team)}**에 {my_total}개를 걸었어요. 양쪽에는 못 걸어요."
    if my_total + amount > MAX_WAGER:
        return False, f"한 경기에 최대 {MAX_WAGER}개까지예요. (지금까지 {my_total}개)"

    from utils import coin_wallet

    # ⚠️ 코인부터 빼요(에스크로). 기록을 먼저 남기면 잔액이 모자란 베팅이 들어가요.
    if not await coin_wallet.spend(user_id, amount, reason="내전베팅"):
        balance = await coin_wallet.get_balance(user_id)
        return False, f"악귀코인이 부족해요. 지금 **{balance}개** 갖고 있어요."

    if not await add_wager(doc["_id"], user_id, team, amount):
        # 그 찰나에 마감됐어요. 코인을 돌려줘요.
        await coin_wallet.add(user_id, amount, reason="베팅 마감으로 환불")
        return False, "방금 베팅이 마감돼서 취소했어요. 코인은 돌려드렸어요."

    return True, f"**{team_name(doc, team)}**에 **{amount}코인**을 걸었어요!"


async def settle(bet_id, winner: int, *, expected: str) -> tuple[dict[str, int], bool] | None:
    """베팅을 정산하고 코인을 지급해요. 이미 정산됐으면 None.

    ⚠️ **상태를 먼저 settled로 바꾼 뒤에 지급해요.** 두 사람이 동시에 정산을 돌리면
    (양 팀장이 `/베팅결과`를 같이 누르거나, 승리 보고 버튼이 겹치면) 지급이 두 번 나가요.
    상태 전환이 실패하면 그 자리에서 멈춰요.

    `/베팅결과`(팀장 보고)와 `/팀짜기` 승리 버튼이 **둘 다 이 함수를 써요.** 지급 로직이
    두 벌이 되면 한쪽만 고치는 사고가 나거든요.
    """
    if not await set_status(bet_id, STATUS_SETTLED, expected):
        return None

    doc = await get(bet_id)
    if doc is None:
        return None

    payouts, refunded = compute_payouts(doc, winner)

    # 순환 import를 피하려고 여기서 불러와요(coin_wallet은 pokemon_store를 쓰고, 이 파일도 그래요).
    from utils import coin_wallet

    for user_id, amount in payouts.items():
        await coin_wallet.add(user_id, amount, reason=f"베팅정산:{'환불' if refunded else '승리'}")
    log.info("🎲 베팅 정산: bet=%s winner=%s refunded=%s payouts=%s",
             bet_id, winner, refunded, payouts)
    return payouts, refunded


async def active(channel_id) -> dict | None:
    return await asyncio.to_thread(_active_sync, channel_id)


async def get(bet_id) -> dict | None:
    return await asyncio.to_thread(_get_sync, bet_id)


async def add_wager(bet_id, user_id, team: int, amount: int) -> bool:
    return await asyncio.to_thread(_add_wager_sync, bet_id, user_id, team, amount)


async def set_status(bet_id, new_status: str, expected: str) -> bool:
    return await asyncio.to_thread(_set_status_sync, bet_id, new_status, expected)


async def report(bet_id, captain_id, team: int) -> dict | None:
    return await asyncio.to_thread(_report_sync, bet_id, captain_id, team)
