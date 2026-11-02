"""🎯 새 서버 미션 3종(📅 출석 · 🎣 세 마리 낚기 · 🔞 도박)과 성인 조건부 배정 검증.
실제 DB·디스코드 없이 돌아가요.

2026-10-23에 만들었어요. 서버 미션 5종이 **균등 배정인데** 누적 완료가 통화 251건 vs
맵추천 **2건**으로 125배 갈려 있었고(실측), 갈라지는 기준이 난이도가 아니라 "미션을
몰라도 깨지는지"였어요. 그래서 사람들이 **이미 하는 활동**을 미션으로 얹었어요.

여기서 확인하는 것:
  1) 새 미션 3종의 정의 (kind=server · target)
  2) 🔞 도박 미션은 **성인이 아니면 배정 자체가 안 된다** (영구히 못 깨는 슬롯 방지)
  3) 리롤도 같은 규칙을 지킨다 - 2코인 내고 못 깨는 미션을 받으면 안 돼요
  4) `catch_fish`는 target 3이라 3마리째에만 완료된다
  5) 🚨 **`COMMAND_MISSIONS`에 넣지 않았다** - 명령어 완료 감지로는 공짜로 깨져요
  6) 🚨 **각 cog가 실제로 `mission.on_action`을 부른다** (훅 미연결 방지)
  7) `on_action`은 예외를 삼킨다 - 미션 때문에 낚시·출석이 깨지면 안 돼요
"""
import asyncio
import os
import re
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
# pokemon_store가 import 시점에 Mongo 클라이언트를 만들어요(연결은 지연돼서 안 붙어요).
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_mission_actions_test"

from utils import mission_store
from utils.mission_store import (
    ADULT_ONLY_KEYS, DAILY_MISSION_COUNT, MISSIONS, SERVER_KEYS, VALORANT_KEYS,
    COMMAND_MISSIONS, pick_missions, server_keys_for,
)

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def read(path):
    with open(os.path.join(BOT_DIR, path), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------
# 가짜 컬렉션 - mission_store가 쓰는 것만 흉내내요.
# ------------------------------------------------------------------
class FakeCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, flt, projection=None):
        doc = self.docs.get(flt["_id"])
        if doc is None:
            return None
        # picks 일치 조건(낙관적 동시성)도 흉내내요.
        if "picks" in flt and doc.get("picks") != flt["picks"]:
            return None
        if "date" in flt and doc.get("date") != flt["date"]:
            return None
        return doc

    def insert_one(self, doc):
        self.docs[doc["_id"]] = dict(doc)

    def replace_one(self, flt, doc):
        self.docs[flt["_id"]] = dict(doc)

    def update_one(self, flt, update, upsert=False):
        class Res:
            modified_count = 0
        res = Res()
        doc = self.docs.get(flt["_id"])
        if doc is None:
            return res
        # 필터 조건 검사
        if "date" in flt and doc.get("date") != flt["date"]:
            return res
        if "picks" in flt and doc.get("picks") != flt["picks"]:
            return res
        ne = flt.get("done", {})
        if isinstance(ne, dict) and "$ne" in ne and ne["$ne"] in (doc.get("done") or []):
            return res
        for key, value in (update.get("$set") or {}).items():
            target, _, leaf = key.partition(".")
            if leaf:
                doc.setdefault(target, {})[leaf] = value
            else:
                doc[target] = value
        for key, value in (update.get("$inc") or {}).items():
            target, _, leaf = key.partition(".")
            if leaf:
                bucket = doc.setdefault(target, {})
                bucket[leaf] = bucket.get(leaf, 0) + value
            else:
                doc[target] = doc.get(target, 0) + value
        for key, value in (update.get("$addToSet") or {}).items():
            bucket = doc.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
        res.modified_count = 1
        return res


fake = FakeCollection()
mission_store._missions = fake


print("1) 새 미션 3종의 정의")
for key, target in (("attend_check", 1), ("catch_fish", 3), ("play_gamble", 1)):
    info = MISSIONS.get(key)
    check(f"{key} 존재", info is not None)
    if info:
        check(f"{key} kind=server", info["kind"] == "server", info["kind"])
        check(f"{key} target={target}", info["target"] == target, str(info.get("target")))
check("서버 미션이 8종", len(SERVER_KEYS) == 8, f"{len(SERVER_KEYS)}종")
check("발로 미션은 5종 그대로", len(VALORANT_KEYS) == 5, f"{len(VALORANT_KEYS)}종")


print("\n2) 🔞 도박 미션은 성인이 아니면 배정 자체가 안 된다")
check("ADULT_ONLY_KEYS에 play_gamble", "play_gamble" in ADULT_ONLY_KEYS)
check("비성인 풀에 play_gamble 없음", "play_gamble" not in server_keys_for(False))
check("성인 풀에는 있음", "play_gamble" in server_keys_for(True))
check("비성인 풀이 7종", len(server_keys_for(False)) == 7, f"{len(server_keys_for(False))}종")

# 🚨 여러 유저·날짜를 전부 돌려봐요. 한 조합만 보면 시드 운으로 통과해요.
leaked = []
for uid in range(400):
    for date in ("2026-10-23", "2026-10-24", "2026-11-01"):
        for linked in (True, False):
            picks = pick_missions(uid, date, linked, adult=False)
            if "play_gamble" in picks:
                leaked.append((uid, date, linked))
check("비성인 2400회 배정에 🔞 미션 0건", not leaked, f"{len(leaked)}건 누출")

# 성인에게는 실제로 뽑히는지 (안 뽑히면 사실상 죽은 미션이에요)
adult_hits = sum(
    1 for uid in range(400)
    if "play_gamble" in pick_missions(uid, "2026-10-23", False, adult=True)
)
check("성인에게는 뽑힌다", adult_hits > 0, f"400명 중 {adult_hits}명")

# 하루 배정 수는 그대로여야 해요
sizes = {len(pick_missions(u, "2026-10-23", lk, a))
         for u in range(50) for lk in (True, False) for a in (True, False)}
check(f"배정 수가 항상 {DAILY_MISSION_COUNT}개", sizes == {DAILY_MISSION_COUNT}, str(sizes))

# 중복이 없어야 해요 (sample이라 당연하지만, 풀이 바뀌었으니 다시 확인)
dups = [u for u in range(200)
        for p in [pick_missions(u, "2026-10-23", True, True)] if len(set(p)) != len(p)]
check("배정에 중복 없음", not dups, f"{len(dups)}명 중복")


print("\n2-2) 🔄 연동자 배정이 발로 1 + 서버 2다 (유저 불만의 진짜 원인)")
# 2026-10-22에 `#🎯｜미션-내용`에서 두 사람이 "ㅈㄴ 어렵네 / 미션으로 받는 코인양을
# 늘려야겠다", "미션이 이상해요 / 나 언랭인데,," 라고 했어요. 둘 다 그때 배정이
# **발로 2 + 서버 1**이라, 발로를 안 하면 그날 천장이 **1코인**이었어요.
# 🚨 이 비율이 되돌아가면 그 상태가 그대로 돌아와요.
bad = []
for uid in range(300):
    for adult in (True, False):
        picks = pick_missions(uid, "2026-10-23", linked=True, adult=adult)
        v = sum(1 for k in picks if MISSIONS[k]["kind"] == "valorant")
        s = sum(1 for k in picks if MISSIONS[k]["kind"] == "server")
        if (v, s) != (1, 2):
            bad.append((uid, adult, v, s))
check("연동자는 발로 1 + 서버 2", not bad, f"{len(bad)}건 어긋남 (예: {bad[:2]})")

# 발로를 하루도 안 해도 **2개**는 깰 수 있어야 해요 (전엔 1개였어요)
reachable = min(
    sum(1 for k in pick_missions(u, "2026-10-23", True, a) if MISSIONS[k]["kind"] == "server")
    for u in range(300) for a in (True, False)
)
check("발로를 안 해도 최소 2개는 깰 수 있다", reachable >= 2, f"최소 {reachable}개")

# 비연동자는 서버 3개 그대로예요
nl = {tuple(sorted(MISSIONS[k]["kind"] for k in pick_missions(u, "2026-10-23", False, a)))
      for u in range(100) for a in (True, False)}
check("비연동자는 서버 미션 3개", nl == {("server", "server", "server")}, str(nl))


print("\n3) 비성인이 배정받은 문서에는 🔞이 없다 (ensure_today)")
fake.docs.clear()
doc = asyncio.run(mission_store.ensure_today("u_minor", linked=False, adult=False))
check("비성인 문서에 🔞 없음", "play_gamble" not in doc["picks"], str(doc["picks"]))
doc_default = asyncio.run(mission_store.ensure_today("u_default", linked=False))
check("adult 생략 시에도 🔞 없음 (안전한 기본값)",
      "play_gamble" not in doc_default["picks"], str(doc_default["picks"]))


print("\n4) 리롤도 같은 규칙을 지킨다")
# 🔞이 나올 수 있는 상황을 일부러 만들어요: 서버 미션을 거의 다 채워두고 리롤시켜요.
non_adult_pool = server_keys_for(False)
fake.docs.clear()
fake.docs["u_reroll"] = {
    "_id": "u_reroll",
    "date": mission_store.today_iso(),
    # 비성인 풀 7종 중 6종을 이미 들고 있으면, 남은 후보는 1종(= 🔞을 빼면 없음)이에요.
    "picks": non_adult_pool[:6],
    "progress": {}, "done": [],
}
new_key, reason = asyncio.run(
    mission_store.reroll("u_reroll", non_adult_pool[0], adult=False)
)
check("비성인 리롤 결과가 🔞이 아니다", new_key != "play_gamble", f"{new_key} / {reason}")
check("남은 후보가 비성인 풀 안에 있다",
      new_key is None or new_key in non_adult_pool, str(new_key))

# 성인은 🔞으로도 바뀔 수 있어야 해요 (안 그러면 성인에게 후보가 하나 줄어요)
fake.docs["u_reroll_a"] = {
    "_id": "u_reroll_a",
    "date": mission_store.today_iso(),
    "picks": [k for k in SERVER_KEYS if k != "play_gamble"][:7],
    "progress": {}, "done": [],
}
new_key_a, reason_a = asyncio.run(
    mission_store.reroll("u_reroll_a", SERVER_KEYS[0], adult=True)
)
check("성인 리롤은 🔞으로 바뀔 수 있다", new_key_a == "play_gamble", f"{new_key_a} / {reason_a}")


print("\n5) catch_fish는 3마리째에만 완료된다")
fake.docs.clear()
fake.docs["u_fish"] = {
    "_id": "u_fish",
    "date": mission_store.today_iso(),
    "picks": ["catch_fish", "attend_check", "use_map"],
    "progress": {}, "done": [],
}
results = [asyncio.run(mission_store.progress("u_fish", "catch_fish")) for _ in range(4)]
check("1·2마리째는 미완료", results[0] is False and results[1] is False, str(results[:2]))
check("3마리째에 완료", results[2] is True, str(results[2]))
check("4마리째는 다시 False (코인 두 번 안 줘요)", results[3] is False, str(results[3]))
check("totalDone이 1만 올랐다", fake.docs["u_fish"].get("totalDone") == 1,
      str(fake.docs["u_fish"].get("totalDone")))

# 출석은 target 1이라 한 번에 끝나야 해요
fake.docs["u_att"] = {
    "_id": "u_att", "date": mission_store.today_iso(),
    "picks": ["attend_check"], "progress": {}, "done": [],
}
check("attend_check는 한 번에 완료",
      asyncio.run(mission_store.progress("u_att", "attend_check")) is True)

# 배정 안 된 미션은 올라가면 안 돼요
check("배정 안 된 미션은 안 올라간다",
      asyncio.run(mission_store.progress("u_att", "play_gamble")) is False)


print("\n6) 🚨 COMMAND_MISSIONS에 넣지 않았다 (명령어 감지로는 공짜로 깨져요)")
# on_app_command_completion은 명령어가 **에러 없이 끝나면** 발동해요. "낚시대가 없어요",
# "이미 출석했어요", "코인이 부족해요"도 정상 종료라 전부 완료로 잡혀요.
for cmd in ("출석", "낚시", "도박", "블랙잭", "하이로우", "슬롯"):
    check(f"COMMAND_MISSIONS에 '{cmd}' 없음", cmd not in COMMAND_MISSIONS,
          f"-> {COMMAND_MISSIONS.get(cmd)}")
for key in ("attend_check", "catch_fish", "play_gamble"):
    check(f"{key}가 명령어 감지에 매여 있지 않음", key not in COMMAND_MISSIONS.values())


print("\n7) 🚨 각 cog가 실제로 mission.on_action을 부른다 (훅 미연결 방지)")
# 전에 주간 대회 훅이 "연결했다고 생각했는데 안 돼 있던" 전례가 있어요(2026-10-18).
for path, key in (
    ("cogs/attendance.py", "attend_check"),
    ("cogs/fishing.py", "catch_fish"),
    ("cogs/casino.py", "play_gamble"),
):
    src = read(path)
    check(f"{path}가 on_action({key}) 호출",
          re.search(rf'on_action\([^)]*"{key}"', src, re.S) is not None)
    check(f"{path}가 mission을 import", "from cogs import mission" in src)

# 🎣 낚시는 **잡았을 때만** 올라야 해요 (놓친 판은 하루 횟수를 돌려받으니까요)
fsrc = read("cogs/fishing.py")
m = re.search(r'if key:\s*\n\s*await mission\.on_action', fsrc)
check("낚시 훅이 `if key:` 안에 있다 (놓친 판은 안 셈)", m is not None)

# 📅 출석은 실패 분기(`if not success: return`) **뒤**여야 해요
asrc = read("cogs/attendance.py")
i_fail = asrc.find("오늘은 이미 출석하셨어요")
i_hook = asrc.find('"attend_check"')
check("출석 훅이 '이미 출석' 분기보다 뒤에 있다", 0 < i_fail < i_hook, f"{i_fail} < {i_hook}")

# 🎰 도박은 차감(`coin_wallet.spend`) **뒤**여야 해요
csrc = read("cogs/casino.py")
i_spend = csrc.find('coin_wallet.spend(interaction.user.id, amount, reason="도박")')
i_ghook = csrc.find('"play_gamble"')
check("도박 훅이 코인 차감보다 뒤에 있다", 0 < i_spend < i_ghook, f"{i_spend} < {i_ghook}")

# 판정 기준이 한 벌인지 (미션은 받았는데 명령어가 막히면 최악이에요)
check("casino가 adult_check에 위임", "_is_adult = adult_check.is_adult" in csrc)
check("casino에 ADULT_ROLE_ID 상수가 남아있지 않다", "ADULT_ROLE_ID" not in csrc)


print("\n8) on_action은 예외를 삼킨다 (미션 때문에 낚시·출석이 깨지면 안 돼요)")
from cogs import mission as mission_cog


class Boom:
    def find_one(self, *a, **k):
        raise RuntimeError("DB가 터졌어요")

    def insert_one(self, *a, **k):
        raise RuntimeError("DB가 터졌어요")


mission_store._missions = Boom()
try:
    asyncio.run(mission_cog.on_action(123, "catch_fish", None, None))
    check("store가 터져도 예외가 안 올라온다", True)
except Exception as exc:  # noqa: BLE001
    check("store가 터져도 예외가 안 올라온다", False, repr(exc))
mission_store._missions = fake

# 모듈 함수로 뽑혔는지 (다른 cog가 import해서 쓰는 구조의 전제)
check("mission.complete가 모듈 함수", callable(getattr(mission_cog, "complete", None)))
check("mission.on_action이 모듈 함수", callable(getattr(mission_cog, "on_action", None)))


print("\n9) ⭐ 호출부를 **실제로 실행**해서 진행도가 오르는지 (문자열 검사로는 못 잡는 것)")
# 🚨 7)은 "소스에 호출이 적혀 있다"까지만 봐요. 그런데 `on_action`은 **예외를 삼켜요**.
#    둘이 겹치면 훅이 조용히 실패해도 완료가 0건으로만 보이고, "아무도 안 해서 0건"인지
#    "버그로 0건"인지 구분이 안 돼요. 전에 주간 대회 훅이 정확히 그랬어요(2026-10-18).
#    그래서 여기서는 **진짜 함수를 불러서** 가짜 DB의 진행도가 변했는지 확인해요.
import discord

from utils import coin_wallet, notify_prefs, riot_account_store

granted = []          # coin_wallet.add 호출 기록
sent = []             # 채널 알림 기록


def _mk_async(fn):
    async def _f(*a, **k):
        return fn(*a, **k)
    return _f


# 🚨 스텁은 **미션 경로 밖**만 덮어요. `on_action -> ensure_today -> progress -> complete`는
#    실제 코드가 돌아야 의미가 있어요(스텁을 크게 잡으면 그 안의 버그를 못 잡아요).
def _patch_outside_mission():
    coin_wallet.add = _mk_async(lambda uid, amount, reason=None: granted.append((str(uid), amount, reason)) or 99)
    coin_wallet.get_balance = _mk_async(lambda uid: 0)   # 실패 안내문이 읽어요
    notify_prefs.is_enabled = _mk_async(lambda uid, kind: True)
    riot_account_store.get_account = lambda uid: None   # 비연동자로 둬요


_patch_outside_mission()


class FakeChannel:
    async def send(self, content=None, **kw):
        sent.append(content)


class FakeInter:
    """미션 훅이 쓰는 것만 - `user.id` · `channel`. user는 Member가 아니라 비성인이에요."""

    def __init__(self, uid):
        self.user = type("U", (), {"id": uid, "bot": False})()
        self.channel = FakeChannel()
        self.followup = type("F", (), {"send": _mk_async(lambda *a, **k: None)})()
        self.response = type("R", (), {
            "defer": _mk_async(lambda *a, **k: None),
            "send_message": _mk_async(lambda *a, **k: None),
        })()

    async def edit_original_response(self, **kw):
        return None


def install_doc(uid, picks, done=None, progress=None):
    fake.docs[str(uid)] = {
        "_id": str(uid), "date": mission_store.today_iso(),
        "picks": list(picks), "progress": dict(progress or {}), "done": list(done or []),
    }


def prog_of(uid, key):
    return fake.docs[str(uid)].get("progress", {}).get(key, 0)


def done_of(uid):
    return fake.docs[str(uid)].get("done", [])


# ── 🎰 도박: take_bet (게임 4종의 공통 입구) ────────────────────────────
from cogs import casino as casino_cog
from utils import casino_store

install_doc(9001, ["play_gamble", "use_map", "use_rank"])
granted.clear(); sent.clear()
casino_store.bet_limit_today = _mk_async(lambda uid: (5, 0))
casino_store.try_wager = _mk_async(lambda uid, amt: (True, amt))
casino_store.refund_wager = _mk_async(lambda uid, amt: None)
coin_wallet.spend = _mk_async(lambda uid, amt, reason=None: True)

ok, err, limited = asyncio.run(casino_cog.take_bet(FakeInter(9001), 1))
check("🎰 베팅이 성립하면 도박 미션이 완료된다",
      ok is True and "play_gamble" in done_of(9001), f"ok={ok} done={done_of(9001)}")
check("🎰 코인이 실제로 지급됐다", any(g[0] == "9001" for g in granted), str(granted))
check("🎰 완료 알림이 채널로 갔다", any("한 판 걸어보기" in (s or "") for s in sent), str(sent))

# 🚨 **잔액 부족으로 못 걸었으면 올라가면 안 돼요** (= COMMAND_MISSIONS를 피한 이유)
install_doc(9002, ["play_gamble", "use_map", "use_rank"])
coin_wallet.spend = _mk_async(lambda uid, amt, reason=None: False)
ok2, _, _ = asyncio.run(casino_cog.take_bet(FakeInter(9002), 1))
check("🚨 잔액이 부족해 못 걸면 미션이 안 올라간다",
      ok2 is False and "play_gamble" not in done_of(9002), f"ok={ok2} done={done_of(9002)}")

# 🚨 한 판 한도를 넘겨도 올라가면 안 돼요
install_doc(9003, ["play_gamble", "use_map", "use_rank"])
coin_wallet.spend = _mk_async(lambda uid, amt, reason=None: True)
ok3, _, _ = asyncio.run(casino_cog.take_bet(FakeInter(9003), 999))
check("🚨 한도를 넘겨 거절되면 미션이 안 올라간다",
      ok3 is False and "play_gamble" not in done_of(9003), f"ok={ok3} done={done_of(9003)}")

# 🚨 하루 베팅 한도를 다 썼을 때도
install_doc(9004, ["play_gamble", "use_map", "use_rank"])
casino_store.try_wager = _mk_async(lambda uid, amt: (False, 20))
casino_store.state_today = _mk_async(lambda uid: (20, 20))
ok4, _, _ = asyncio.run(casino_cog.take_bet(FakeInter(9004), 1))
check("🚨 하루 한도를 다 썼으면 미션이 안 올라간다",
      ok4 is False and "play_gamble" not in done_of(9004), f"ok={ok4} done={done_of(9004)}")


# ── 📅 출석: /출석 핸들러 ──────────────────────────────────────────────
from cogs import attendance as attend_cog
from utils import attend_service

cog = attend_cog.Attendance.__new__(attend_cog.Attendance)
handler = attend_cog.Attendance.do_attend.callback

install_doc(9101, ["attend_check", "use_map", "use_rank"])
granted.clear()
attend_service.attend = _mk_async(lambda uid: (True, {
    "coin": 10, "coinGain": 1, "streak": 3, "streakBonus": 0, "weeklyBonus": 0,
}))
asyncio.run(handler(cog, FakeInter(9101)))
check("📅 출석에 성공하면 출석 미션이 완료된다",
      "attend_check" in done_of(9101), str(done_of(9101)))

# 🚨 **이미 출석한 사람이 다시 쳐도** 명령어는 정상 종료돼요 - 그때 올라가면 공짜 1코인이에요
install_doc(9102, ["attend_check", "use_map", "use_rank"])
attend_service.attend = _mk_async(lambda uid: (False, {"coin": 10, "streak": 3}))
asyncio.run(handler(cog, FakeInter(9102)))
check("🚨 이미 출석했으면 미션이 안 올라간다 (공짜 완료 방지)",
      "attend_check" not in done_of(9102), str(done_of(9102)))


# ── 🎣 낚시: finish_cast ──────────────────────────────────────────────
from cogs import fishing as fishing_cog
from utils import fishing_store

fishing_store.record_cast = _mk_async(lambda uid, key, size=None: None)
fishing_store.give_back_rod = _mk_async(lambda uid: None)
fishing_store.get = _mk_async(lambda uid: {"tank": {}, "pieces": 0, "dust": 0,
                                           "casts": 0, "caught": 0, "sold": 0, "best": None})
fishing_store.cast_quota = _mk_async(lambda uid: (1, 20))   # 남은 캐스트 안내문이 읽어요
SOME_FISH = next(iter(fishing_cog.BY_KEY))


class FakeView:
    def __init__(self, result, caught=None):
        self.result = result
        self.caught = caught
        self.size = fishing_cog.fish_data.SIZE_BY_KEY[caught][0] if caught else None
        self.rod_left = 5

    def stop(self):
        pass


install_doc(9201, ["catch_fish", "use_map", "use_rank"])
asyncio.run(fishing_cog.finish_cast(FakeInter(9201), FakeView("ok", SOME_FISH)))
check("🎣 한 마리 낚으면 진행도가 1 오른다", prog_of(9201, "catch_fish") == 1,
      str(prog_of(9201, "catch_fish")))

# 🚨 놓친 판은 하루 횟수를 돌려받으니 **안 세는 게** 맞아요
asyncio.run(fishing_cog.finish_cast(FakeInter(9201), FakeView("early")))
asyncio.run(fishing_cog.finish_cast(FakeInter(9201), FakeView("afk")))
check("🚨 놓친 판(early·afk)은 진행도를 올리지 않는다", prog_of(9201, "catch_fish") == 1,
      str(prog_of(9201, "catch_fish")))

# 3마리째에 완료 + 코인
granted.clear()
asyncio.run(fishing_cog.finish_cast(FakeInter(9201), FakeView("ok", SOME_FISH)))
check("🎣 2마리째는 아직 미완료", "catch_fish" not in done_of(9201), str(done_of(9201)))
asyncio.run(fishing_cog.finish_cast(FakeInter(9201), FakeView("ok", SOME_FISH)))
check("🎣 3마리째에 완료되고 코인이 지급된다",
      "catch_fish" in done_of(9201) and any(g[0] == "9201" for g in granted),
      f"done={done_of(9201)} granted={granted}")

# 4마리째엔 코인이 또 가면 안 돼요
granted.clear()
asyncio.run(fishing_cog.finish_cast(FakeInter(9201), FakeView("ok", SOME_FISH)))
check("🚨 4마리째엔 코인이 다시 지급되지 않는다", not granted, str(granted))

# 배정 안 된 사람은 낚아도 아무 일 없어야 해요
install_doc(9202, ["use_map", "use_rank", "use_myshop"])
granted.clear()
asyncio.run(fishing_cog.finish_cast(FakeInter(9202), FakeView("ok", SOME_FISH)))
check("낚시 미션이 배정 안 된 사람은 낚아도 코인이 없다",
      not granted and not done_of(9202), f"granted={granted} done={done_of(9202)}")


# ==================================================================
# 🔊 "방 만들기" 미션이 **버튼 경로에서도** 올라가는지 (2026-10-31)
#
# 🚨🚨 전엔 `COMMAND_MISSIONS`(= `/방만들기` 명령어 완료)로 잡았는데, 같은 날 🔊 방
#    패널 **버튼**을 만들면서 그 경로가 끊겼어요 — 버튼은 슬래시 명령어가 아니라서
#    `on_app_command_completion`이 안 떠요. 오늘 8명 배정·**완료 0건**이 그 신호였어요.
# → 이제 `dynamic_room.create_room`이 **실제로 만든 뒤** 직접 올려요.
# ==================================================================
import ast as _ast                                   # noqa: E402

print("\n🔊 방 만들기 미션 배선")
_dr_src = open(os.path.join(BOT_DIR, "utils", "dynamic_room.py"), encoding="utf-8").read()
_dr = _ast.parse(_dr_src)
_fn = next((n for n in _ast.walk(_dr)
            if isinstance(n, _ast.AsyncFunctionDef) and n.name == "create_room"), None)
check("dynamic_room.create_room이 있다", _fn is not None)
_body = _ast.unparse(_fn) if _fn else ""
# 🚨 `ast.unparse`는 문자열을 **단일 인용부호**로 내요(`'create_room'`). 이중으로
#    찾으면 호출이 있는데도 FAIL이 나요(2026-10-31에 실제로 당했어요).
#    그래서 인용부호를 벗긴 뒤 찾아요.
_body_q = _body.replace('"', "'")
check("🚨 create_room 미션을 **직접** 올린다 (버튼 경로도 커버)",
      "'create_room'" in _body_q and "on_action" in _body_q,
      "on_action(..., 'create_room', ...) 호출이 없어요")
check("🚨 그 호출이 **딱 한 번**이다 (두 번이면 미션이 두 배로 올라가요)",
      _body.count("on_action") == 1, f"{_body.count('on_action')}번")
# 🚨 방을 **만든 뒤**여야 해요. 앞에 두면 실패했는데도 미션이 깨져요.
_i_create = _body.find("create_voice_channel")
_i_hook = _body.find("on_action")
check("🚨 방을 실제로 만든 **뒤**에 올린다",
      0 <= _i_create < _i_hook, f"create_voice_channel={_i_create} on_action={_i_hook}")
# 🚨 COMMAND_MISSIONS에 다시 들어가면 명령어 경로에서 **두 번** 올라가요.
check("🚨 COMMAND_MISSIONS에 '방만들기'가 없다 (중복 호출 방지)",
      "방만들기" not in mission_store.COMMAND_MISSIONS,
      f"{sorted(mission_store.COMMAND_MISSIONS)}")
check("   └ 명령어로만 쓰는 것들은 그대로 남아 있다",
      {"오상", "전적", "맵추천"} <= set(mission_store.COMMAND_MISSIONS),
      f"{sorted(mission_store.COMMAND_MISSIONS)}")


# ==================================================================
# 🚨🚨 서버 미션 **8종 전부** 훅이 걸려 있는지 (2026-10-31)
#
# ⭐ **오늘 사고의 재발 방지다.** `create_room` 훅이 끊긴 걸 "어려운 미션"으로 오진할
#    뻔했고, 실측(8명 배정·0건)이 아니었으면 몰랐다. 훅이 없으면 그 미션은 **영원히
#    0건**이고, 로그도 에러도 안 남아서 유저 신고로만 드러난다.
#
# 🚨 훅은 두 가지 모양 중 하나다:
#    ⒜ `COMMAND_MISSIONS` 표 (슬래시 명령어 완료 — **버튼은 안 잡힌다**)
#    ⒝ 소스에서 `on_action("<key>", ...)` / `progress("<key>", ...)` 직접 호출
#    ⒝ 쪽이 안전하다. 명령어를 패널 버튼으로 꺼낼 거면 **반드시 ⒝로 옮길 것.**
# ==================================================================
print("\n🎯 서버 미션 8종 훅 전수 검사")
import ast as _ast2                                  # noqa: E402

_found: dict[str, list[str]] = {}
# 🚨 **경로를 정규화해야 한다.** `BOT_DIR`는 `scripts/..` 꼴이라 그대로 walk하면
#    모든 하위 경로에 `scripts`가 들어가서 **제외 조건이 전부 참**이 된다 → 아무 파일도
#    안 보고 "훅이 없다"는 **거짓 FAIL** 5건이 났다(2026-10-31에 실제로 당했다).
_BASE = os.path.abspath(BOT_DIR)
for _root, _dirs, _files in os.walk(_BASE):
    _rel = os.path.relpath(_root, _BASE)
    if any(s in _rel.split(os.sep) for s in (".git", "__pycache__", "scripts", ".venv")):
        continue
    for _fn in _files:
        if not _fn.endswith(".py"):
            continue
        _path = os.path.join(_root, _fn)
        try:
            _tree = _ast2.parse(open(_path, encoding="utf-8").read())
        except Exception:  # noqa: BLE001
            continue
        for _node in _ast2.walk(_tree):
            if not isinstance(_node, _ast2.Call):
                continue
            _name = getattr(_node.func, "attr", "") or getattr(_node.func, "id", "")
            if _name not in ("on_action", "progress", "complete", "_complete"):
                continue
            for _a in _node.args:
                if isinstance(_a, _ast2.Constant) and _a.value in mission_store.MISSIONS:
                    _found.setdefault(_a.value, []).append(
                        f"{os.path.basename(_path)}:{_node.lineno}")
for _cmd, _key in mission_store.COMMAND_MISSIONS.items():
    _found.setdefault(_key, []).append(f"COMMAND_MISSIONS['{_cmd}']")

for _key in mission_store.SERVER_KEYS:
    _where = _found.get(_key) or []
    check(f"   {_key}: 훅이 있다 ({', '.join(_where) if _where else '없음'})",
          bool(_where),
          "훅이 없으면 이 미션은 영원히 0건이에요 — on_action으로 올려주세요")


# ==================================================================
# 🏅 희귀도별 보상 (2026-11-02)
# ==================================================================
print("\n🏅 희귀도별 보상")

check("미션 13종 전부에 유효한 희귀도가 있다",
      all(MISSIONS[k].get("rarity") in mission_store.RARITY for k in MISSIONS),
      str({k: MISSIONS[k].get("rarity") for k in MISSIONS
           if MISSIONS[k].get("rarity") not in mission_store.RARITY}))

# 🚨 **아무도 전보다 적게 받으면 안 돼요.** 차등을 넣은 건 올려주려던 것이지
#    누군가를 깎으려던 게 아니에요. 옛 고정 보상은 1코인이었어요.
_min_reward = min(mission_store.reward_of(k) for k in MISSIONS)
check(f"최저 보상이 옛 고정값(1코인) 이상 — {_min_reward}코인", _min_reward >= 1,
      f"{ {k: mission_store.reward_of(k) for k in MISSIONS if mission_store.reward_of(k) < 1} }")

# ⭐⭐ **희귀도가 실측과 어긋나지 않는지 본다.** 아래는 2026-11-02에 `coin_log`로 잰
#    14일 완료율이에요. 풀 안에서는 배정 확률이 균등해서 그대로 비교할 수 있어요.
# 🚨 티어를 바꾸고 싶으면 **먼저 다시 재세요.** 느낌으로 바꾸면 여기서 FAIL이 나요 —
#    실제로 "학살자 15킬은 어려우니 비싸게"가 숫자와 **반대**였어요(68%로 쉬운 쪽).
# 🚨 풀을 섞어서 비교하면 안 돼요(발로 5종 vs 서버 8종은 분모가 달라요).
RATE_2026_11_02 = {
    "voice_together": 83, "use_myshop": 42, "attend_check": 42, "use_rank": 34,
    "play_gamble": 34,  # 🔞라 배정 분모를 절반으로 보정한 값
    "catch_fish": 28, "use_map": 28, "create_room": 25,
    "val_kd1": 87, "val_win": 79, "val_play": 71, "val_kills15": 68, "val_comp": 65,
}
check("실측 표가 미션 13종을 전부 덮는다",
      set(RATE_2026_11_02) == set(MISSIONS),
      f"빠짐 {sorted(set(MISSIONS) - set(RATE_2026_11_02))} / "
      f"잉여 {sorted(set(RATE_2026_11_02) - set(MISSIONS))}")

for _pool, _pname in ((SERVER_KEYS, "서버"), (VALORANT_KEYS, "발로")):
    _bad = []
    for _a in _pool:
        for _b in _pool:
            # 완료율이 더 높은(= 더 쉬운) 미션이 **더 많이 주면** 모순이에요.
            if RATE_2026_11_02[_a] > RATE_2026_11_02[_b] and \
                    mission_store.reward_of(_a) > mission_store.reward_of(_b):
                _bad.append(f"{_a}({RATE_2026_11_02[_a]}%,{mission_store.reward_of(_a)}코인)"
                            f">{_b}({RATE_2026_11_02[_b]}%,{mission_store.reward_of(_b)}코인)")
    check(f"{_pname} 풀: 쉬운 미션이 더 많이 주는 역전이 없다", not _bad, "; ".join(_bad))

# ⭐ **실행 검증.** 문자열 검사로는 "지급액이 고정값으로 박혀 있다"를 못 잡아요.
#    실제로 `complete()`를 불러서 **가짜 지갑에 들어온 금액**이 희귀도와 같은지 봐요.
#    (2026-10-31에 '소스에 호출이 있다'까지만 보고 끊긴 훅을 놓친 전례가 있어요.)
_by_rarity = {}
for _k in SERVER_KEYS:
    _by_rarity.setdefault(MISSIONS[_k]["rarity"], _k)
check("서버 미션에 희귀도 3종이 다 있다 (실행 검증 표본)",
      set(_by_rarity) == set(mission_store.RARITY), str(_by_rarity))

for _rar, _key in sorted(_by_rarity.items(), key=lambda kv: mission_store.RARITY[kv[0]]["reward"]):
    _uid = 9700 + mission_store.RARITY[_rar]["reward"]
    _want = mission_store.RARITY[_rar]["reward"]
    install_doc(_uid, [_key, "voice_together", "use_rank"][:3])
    # target이 3인 미션(세 마리 낚기)은 한 번에 안 깨지니 진행도를 미리 채워둬요.
    _need = MISSIONS[_key]["target"]
    if _need > 1:
        install_doc(_uid, [_key, "voice_together", "use_rank"],
                    progress={_key: _need - 1})
    granted.clear(); sent.clear()
    asyncio.run(mission_cog.complete(_uid, _key, FakeChannel()))
    _amounts = [g[1] for g in granted if g[0] == str(_uid)]
    check(f"   {_rar}({_want}코인) {_key} → 지갑에 {_amounts}",
          _amounts == [_want], f"기대 [{_want}] · 지급 {_amounts}")
    check(f"   {_rar} 알림 문구에 +{_want}개가 적힌다",
          any(f"+{_want}개" in (s or "") for s in sent), str(sent))

# 🚨 **합계는 `len(keys) * 고정값`이 아니라 키별 합이어야 해요.** 발로 자동판정 DM과
#    `/미션` 요약이 그 방식으로 세고 있었어요(전엔 보상이 같아서 우연히 맞았어요).
_mix = [_by_rarity["common"], _by_rarity["rare"]]
check("total_reward가 희귀도별로 더한다",
      mission_store.total_reward(_mix)
      == mission_store.reward_of(_mix[0]) + mission_store.reward_of(_mix[1]),
      f"{_mix} → {mission_store.total_reward(_mix)}")
check("🚨 total_reward가 '개수 × 최저보상'과 다르다 (고정 지급 회귀 탐지)",
      mission_store.total_reward(_mix) != len(_mix) * _min_reward,
      f"{mission_store.total_reward(_mix)} vs {len(_mix) * _min_reward}")

# 🚨 옛 상수가 되살아나면 "전부 1코인"으로 조용히 돌아가요.
check("🚨 REWARD_PER_MISSION 상수가 되살아나지 않았다",
      not hasattr(mission_store, "REWARD_PER_MISSION"),
      "희귀도별 reward_of()로 대체됐어요 — 고정 상수를 다시 만들지 마세요")


# ==================================================================
# 🚨 요약은 **맨 마지막**이어야 해요. 뒤에 섹션을 붙이면 그 FAIL이 집계되지 않아
#    종료코드가 0으로 나오고 배포 관문이 그냥 통과해요 (2026-10-19에 실제로 그랬어요).
# ==================================================================
print("\n" + "=" * 50)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 새 미션 3종 · 성인 조건부 배정 · 훅 연결 전부 정상")
