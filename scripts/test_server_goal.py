"""🤝 서버 공동 목표 테스트 — DB·디스코드에 붙지 않아요(DB 함수를 가짜로 바꿔요)."""
import asyncio
import os
import sys
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

import discord

from cogs import server_goal as cog_mod
from utils import server_banner
from utils import server_goal as sg

failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failed.append(name)


# ------------------------------------------------------------------
print("[1] 주 계산")
check("week_key 월요일 0시는 그 주", sg.week_key(datetime(2026, 11, 23, 0, 0, 1, tzinfo=sg.KST)) == "2026-W48")
check("week_key 일요일 밤은 같은 주", sg.week_key(datetime(2026, 11, 29, 23, 59, tzinfo=sg.KST)) == "2026-W48")
check("week_start", sg.week_start("2026-W48") == datetime(2026, 11, 23, tzinfo=sg.KST))
check("week_label", sg.week_label("2026-W48") == "11/23(월) ~ 11/29(일)", sg.week_label("2026-W48"))
check("연도 넘어가는 주 비교", "2026-W52" < "2027-W01")
check("fishing_week와 같은 키", __import__("utils.fishing_week", fromlist=["x"]).week_key(
    datetime(2026, 11, 25, tzinfo=sg.KST)) == sg.week_key(datetime(2026, 11, 25, tzinfo=sg.KST)))
check("미션 완주 note가 mission cog와 같음",
      sg.MISSION_CLEAR_NOTE == __import__("cogs.mission", fromlist=["x"]).FULL_CLEAR_REASON)

print("[2] 순수 계산")
check("progress 0", sg.progress_bar(0, 12) == "░" * 12)
check("progress 넘침은 꽉 참", sg.progress_bar(30, 12) == "█" * 12)
check("progress 절반", sg.progress_bar(6, 12) == "█" * 6 + "░" * 6)
check("reached", sg.reached_keys({"mission": 12, "balodle": 14, "fishing": 99}) == ["mission", "fishing"])
check("contributors_all 합집합",
      sg.contributors_all({"mission": {"1"}, "balodle": {"1", "2"}, "fishing": {"3"}}) == {"1", "2", "3"})
check("banner_line 없음", sg.banner_line(None) is None)
check("banner_line 전부", sg.banner_line({"reached": ["a", "b", "c"], "contributors": 20}).startswith("다 같이"))
check("banner_line 이모지 없음", all(ord(c) < 0x2000 or "가" <= c <= "힣"
                                   for c in sg.banner_line({"reached": ["a"], "contributors": 3})))

print("[3] 화면")
em = cog_mod.panel_embed("2026-W48", {"mission": 5, "balodle": 15, "fishing": 3},
                         {"reached": ["mission"], "contributors": 18})
check("패널 칸 3개 + 지난주", len(em.fields) == 4)
check("달성 칸에 ✅", "✅" in em.fields[1].name and "✅" not in em.fields[0].name)
check("embed 길이 한도", len(em) < 6000)
mine = cog_mod.mine_embed("2026-W48", "7", {"mission": {"7"}, "balodle": set(), "fishing": {"7"}},
                          {"paid": {"mission": ["7"], "all": ["7"]}})
check("내 기여: 받은 코인 = 2 + 3", "**5개**" in mine.fields[0].value, mine.fields[0].value)
view = cog_mod.GoalPanelView()
check("영속 뷰 timeout=None", view.timeout is None)
check("버튼 custom_id 고정", [c.custom_id for c in view.children] == ["akgui:goal:me"])
png = server_banner.render("2026-W48", [], "다 같이 공동 목표 3/3 달성!  참여 20명")
check("배너에 결과 줄을 그려도 PNG", png[:4] == b"\x89PNG")


# ------------------------------------------------------------------
# 정산: DB를 메모리로 흉내 내요
# ------------------------------------------------------------------
class FakeDB:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.ppl: dict[str, dict] = {}
        self.coins: list[tuple] = []
        self.posts: list[str] = []

    def doc(self, week):
        return self.docs.setdefault(week, {"_id": week, "paid": {}, "reached": {}})

    async def people(self, week):
        return {k: set(v) for k, v in self.ppl.get(week, {}).items()}

    async def get_state(self, week):
        d = self.doc(week)
        return {"paid": {k: list(v) for k, v in d["paid"].items()}, "closed": d.get("closed")}

    async def claim(self, week, key, uid):
        lst = self.doc(week)["paid"].setdefault(key, [])
        if uid in lst:
            return False
        lst.append(uid)
        return True

    async def mark_reached(self, week, key):
        d = self.doc(week)
        field = "all_reached" if key == sg.ALL_KEY else key
        if field in d["reached"]:
            return False
        d["reached"][field] = True
        return True

    async def close_week(self, week):
        d = self.doc(week)
        if d.get("closed"):
            return False
        d["closed"] = True
        return True

    async def save_summary(self, week, counts, contributors):
        self.doc(week)["summary"] = {"counts": counts, "contributors": contributors,
                                     "reached": sg.reached_keys(counts)}

    async def summary(self, week):
        return self.doc(week).get("summary")

    async def add(self, uid, amount, *, reason=""):
        self.coins.append((str(uid), amount, reason))
        return 0


fake = FakeDB()
for name in ("people", "get_state", "claim", "mark_reached", "close_week", "save_summary", "summary"):
    setattr(sg, name, getattr(fake, name))
cog_mod.coin_wallet.add = fake.add


class FakeBot:
    def get_channel(self, _):
        return None


cog = cog_mod.ServerGoal.__new__(cog_mod.ServerGoal)
cog.bot = FakeBot()
cog._panel_sig = None


async def _post(text):
    fake.posts.append(text)
cog._post = _post

W = "2026-W48"
U = [str(i) for i in range(1, 21)]


async def run_settle():
    print("[4] 정산")
    # 미션 11명(미달), 발로들 15명(달성), 낚시 3명
    fake.ppl[W] = {"mission": U[:11], "balodle": U[:15], "fishing": U[:3]}
    await cog.settle(W, announce=True)
    check("발로들 15명에게 2코인", sorted(c[0] for c in fake.coins) == sorted(U[:15])
          and all(c[1] == 2 for c in fake.coins))
    check("reason 형식", fake.coins[0][2] == f"공동목표:{W}:balodle", fake.coins[0][2])
    check("달성 글 1개", len(fake.posts) == 1 and "발로들" in fake.posts[0])

    n = len(fake.coins)
    await cog.settle(W, announce=True)
    check("다시 돌려도 두 번 안 줌", len(fake.coins) == n)
    check("달성 글도 한 번만", len(fake.posts) == 1)

    fake.ppl[W]["balodle"] = U[:16]          # 달성 뒤 한 명 더
    await cog.settle(W, announce=True)
    check("달성 뒤 참여한 사람도 받음", fake.coins[-1][:2] == (U[15], 2))
    check("그때는 글 안 올림", len(fake.posts) == 1)

    fake.ppl[W] = {"mission": U[:12], "balodle": U[:16], "fishing": U[4:19]}   # 세 칸 다
    fake.coins.clear()
    await cog.settle(W, announce=True)
    bonus = [c for c in fake.coins if c[2].endswith(":all")]
    everyone = set(U[:12]) | set(U[:16]) | set(U[4:19])
    check("전부 달성 보너스는 참여자 전원에게 3코인",
          {c[0] for c in bonus} == everyone and all(c[1] == 3 for c in bonus), str(len(bonus)))
    mission = [c for c in fake.coins if c[2].endswith(":mission")]
    check("미션 칸 12명 지급", len(mission) == 12)
    check("발로들은 이미 받아서 다시 안 줌", not [c for c in fake.coins if c[2].endswith(":balodle")])
    check("미션·낚시·전부 달성 글 3개 더", len(fake.posts) == 4, str(fake.posts))

    print("[5] 지난주 마감")
    real = sg.previous_week_key
    sg.previous_week_key = lambda when=None: W
    fake.posts.clear()
    await cog.close_previous()
    check("마감 결과 글 1개", len(fake.posts) == 1 and "3/3 달성" in fake.posts[0], str(fake.posts))
    check("요약 저장", fake.docs[W]["summary"]["contributors"] == len(everyone))
    await cog.close_previous()
    check("마감은 한 번만", len(fake.posts) == 1)
    sg.previous_week_key = lambda when=None: "2026-W47"
    fake.posts.clear()
    await cog.close_previous()
    check("기능 전 주(W47)는 정산·발표 안 함", not fake.posts and "2026-W47" not in fake.docs)
    sg.previous_week_key = real


asyncio.run(run_settle())

print()
if failed:
    print(f"❌ 실패 {len(failed)}개: {failed}")
    sys.exit(1)
print("✅ 서버 공동 목표 테스트 전부 통과")
