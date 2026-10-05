"""연속 출석 개편 검증 (🧊 보호권 · 📅 주간 보너스 · 🔥 구간 보너스 · 🏆 순위). DB 없이 돌아가요.

2026-10-05 실측에서 나온 문제를 고친 거예요: 연속일 중앙값 1일, 7일 이상 4명,
그리고 **누적 41회인데 연속 3일**인 사람들(한 번 놓쳐서 0으로 리셋).

여기서 확인하는 것:
  1) 보호권은 **딱 하루 빠진 경우만** 살린다 (이틀 이상은 못 살림 = 연속의 의미 유지)
  2) 첫 출석·연속 0인 사람에게는 보호권이 안 쓰인다 (살릴 연속이 없는데 소모되면 손해)
  3) 어제 출석했으면 보호권 없이 그냥 이어진다 (멀쩡한데 소모하면 안 됨)
  4) 구간 보너스: 7일↑ +1, 30일↑ +2 (경계값에서 정확히 바뀐다)
  5) 주간 보너스: 7의 배수인 날만, 반복해서 나온다 (업적은 평생 1회라 그걸 메우는 역할)
  6) 보호권 보유 상한이 지켜지고, 없는데 쓰려 하면 실패한다 (음수 방지)
  7) 순위표는 **살아있는 연속만** 올린다 (한 달 전 42일 기록이 1등으로 남으면 안 됨)
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_attend_test"

from utils import attend_service, inventory_store  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()


def iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


print("1) 보호권은 딱 하루 빠진 경우만 살린다")
check("어제 출석 → 보호 필요 없음", attend_service.can_protect(iso(1), 5) is False)
check("이틀 전 출석(하루 빠짐) → 살릴 수 있음", attend_service.can_protect(iso(2), 5) is True)
check("사흘 전 출석(이틀 빠짐) → 못 살림", attend_service.can_protect(iso(3), 5) is False)
check("일주일 전 → 못 살림", attend_service.can_protect(iso(7), 42) is False)
check("기록 없음 → 못 살림", attend_service.can_protect(None, 0) is False)
check("연속 0 → 못 살림(살릴 게 없어요)", attend_service.can_protect(iso(2), 0) is False)

print("2) _next_streak가 보호 여부에 맞게 계산한다")
check("어제 출석 → +1", attend_service._next_streak(iso(1), 5) == 6)
check("하루 빠짐 + 보호 없음 → 1로 리셋", attend_service._next_streak(iso(2), 5) == 1)
check("하루 빠짐 + 보호 → 이어짐", attend_service._next_streak(iso(2), 5, protected=True) == 6)
check("이틀 빠짐 + 보호해도 리셋",
      attend_service._next_streak(iso(3), 5, protected=True) == 1)
check("첫 출석 → 1", attend_service._next_streak(None, 0) == 1)
check("첫 출석은 보호를 줘도 1", attend_service._next_streak(None, 0, protected=True) == 1)

print("3) 구간 보너스 (7일↑ +1, 30일↑ +2)")
cases = [(1, 0), (6, 0), (7, 1), (8, 1), (29, 1), (30, 2), (42, 2), (100, 2)]
for streak, expected in cases:
    got = attend_service.streak_bonus(streak)
    check(f"연속 {streak}일 → +{expected}", got == expected, f"실제 +{got}")
check("0일은 보너스 없음", attend_service.streak_bonus(0) == 0)

print("4) 주간 보너스 (7의 배수마다, 반복)")
for streak in (7, 14, 21, 28, 35, 42):
    check(f"연속 {streak}일 → +{attend_service.WEEKLY_BONUS_COIN}",
          attend_service.weekly_bonus(streak) == attend_service.WEEKLY_BONUS_COIN)
for streak in (1, 6, 8, 13, 29, 41):
    check(f"연속 {streak}일 → 없음", attend_service.weekly_bonus(streak) == 0)
check("0일은 없음 (0 % 7 == 0 함정)", attend_service.weekly_bonus(0) == 0)

print("5) 하루 최대 지급액이 예상대로다 (코인 발행량 계산의 근거)")
def total(streak):
    return 1 + attend_service.streak_bonus(streak) + attend_service.weekly_bonus(streak)
check("1일차 = 1코인", total(1) == 1, str(total(1)))
check("7일차 = 1+1+3 = 5코인", total(7) == 5, str(total(7)))
check("10일차 = 2코인", total(10) == 2, str(total(10)))
check("30일차 = 1+2 = 3코인 (30은 7의 배수가 아니에요)", total(30) == 3, str(total(30)))
check("35일차 = 1+2+3 = 6코인", total(35) == 6, str(total(35)))
check("평상시 상한은 3코인", max(total(s) for s in range(1, 200) if s % 7) == 3)

# ------------------------------------------------------------------
print("6) 보호권 보유량 (상한·음수 방지)")


class FakeInventory:
    def __init__(self):
        self.docs = {}

    def find_one(self, flt, projection=None):
        return self.docs.get(flt["_id"])

    def _ok(self, doc, flt):
        for key, cond in flt.items():
            if key in ("_id", "$or"):
                continue
            value = (doc or {}).get(key)
            if isinstance(cond, dict):
                if "$gte" in cond and not (isinstance(value, int) and value >= cond["$gte"]):
                    return False
                if "$lt" in cond and not (isinstance(value, int) and value < cond["$lt"]):
                    return False
            elif value != cond:
                return False
        if "$or" in flt:
            if not any(self._ok(doc, {**clause, "_id": flt["_id"]})
                       if "$exists" not in str(clause) else
                       (list(clause.values())[0].get("$exists") is False
                        and list(clause)[0] not in (doc or {}))
                       for clause in flt["$or"]):
                return False
        return True

    def update_one(self, flt, update, upsert=False):
        class Res:
            modified_count = 0
            upserted_id = None
        res = Res()
        uid = flt["_id"]
        doc = self.docs.get(uid)
        if doc is None:
            if not upsert:
                return res
            doc = self.docs[uid] = {"_id": uid}
            res.upserted_id = uid
        elif not self._ok(doc, flt):
            return res
        for key, value in (update.get("$inc") or {}).items():
            doc[key] = int(doc.get(key) or 0) + value
            res.modified_count = 1
        return res

    def find_one_and_update(self, flt, update, return_document=None):
        uid = flt["_id"]
        doc = self.docs.get(uid)
        if doc is None or not self._ok(doc, flt):
            return None
        for key, value in (update.get("$inc") or {}).items():
            doc[key] = int(doc.get(key) or 0) + value
        return doc


inventory_store._inventory = FakeInventory()

check("처음엔 0장", asyncio.run(inventory_store.protect_count(9)) == 0)
check("없는데 쓰면 실패", asyncio.run(inventory_store.consume_protect(9)) is False)
check("1장 지급 성공", asyncio.run(inventory_store.grant_protect(9)) is True)
check("보유 1장", asyncio.run(inventory_store.protect_count(9)) == 1)
check("2장까지 지급 성공", asyncio.run(inventory_store.grant_protect(9)) is True)
check("보유 2장", asyncio.run(inventory_store.protect_count(9)) == inventory_store.PROTECT_MAX)
check("상한 넘으면 지급 거절", asyncio.run(inventory_store.grant_protect(9)) is False)
check("상한을 안 넘었다", asyncio.run(inventory_store.protect_count(9)) == inventory_store.PROTECT_MAX)
check("쓰면 1장 줄어듦",
      asyncio.run(inventory_store.consume_protect(9)) is True
      and asyncio.run(inventory_store.protect_count(9)) == inventory_store.PROTECT_MAX - 1)
asyncio.run(inventory_store.consume_protect(9))
check("다 쓰면 0장", asyncio.run(inventory_store.protect_count(9)) == 0)
check("0장에서 또 쓰면 실패(음수 안 됨)",
      asyncio.run(inventory_store.consume_protect(9)) is False
      and asyncio.run(inventory_store.protect_count(9)) == 0)
asyncio.run(inventory_store.refund_protect(9))
check("환불은 1장 되돌림", asyncio.run(inventory_store.protect_count(9)) == 1)
check("남의 보호권에 영향 없음", asyncio.run(inventory_store.protect_count(10)) == 0)


class BrokenInventory:
    def find_one(self, *a, **kw):
        raise RuntimeError("DB 끊김")


inventory_store._inventory = BrokenInventory()
check("조회 실패 시 0장으로 본다 (거짓으로 연속을 잇지 않게)",
      asyncio.run(inventory_store.protect_count(9)) == 0)
inventory_store._inventory = FakeInventory()

# ------------------------------------------------------------------
print("7) 순위표는 살아있는 연속만 올린다")


class FakeCol:
    def __init__(self, docs):
        self.docs = docs

    def find(self, flt, projection=None):
        return iter(self.docs)


attend_service._trainers = FakeCol([
    {"_id": "a", "attendanceStreak": 42, "attendance": 42, "lastAttendanceDate": iso(0)},
    {"_id": "b", "attendanceStreak": 99, "attendance": 99, "lastAttendanceDate": iso(30)},
    {"_id": "c", "attendanceStreak": 13, "attendance": 41, "lastAttendanceDate": iso(1)},
])
attend_service._guest = FakeCol([
    {"_id": "d", "attendanceStreak": 20, "attendance": 25, "lastAttendanceDate": iso(2)},
    {"_id": "e", "attendanceStreak": 1, "attendance": 3, "lastAttendanceDate": iso(0)},
])

data = asyncio.run(attend_service.rankings(limit=10))
streak_ids = [r[0] for r in data["streak"]]
check("한 달 전 99일 기록은 연속 순위에서 빠진다", "b" not in streak_ids, str(streak_ids))
check("오늘·어제 출석자는 올라간다", streak_ids[:2] == ["a", "c"], str(streak_ids))
check("이틀 전 출석자는 '위험'으로 간다",
      [r[0] for r in data["risky"]] == ["d"], str(data["risky"]))
check("오늘 출석 여부 표시", data["streak"][0][2] is True and data["streak"][1][2] is False,
      str(data["streak"][:2]))
check("누적 순위는 안 온 사람도 포함(99회가 1등)",
      [r[0] for r in data["total"]][:2] == ["b", "a"], str(data["total"][:3]))
check("누적 순위에 5명 전원", len(data["total"]) == 5, str(len(data["total"])))

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
