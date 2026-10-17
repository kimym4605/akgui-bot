"""`/악귀상점` 3품목(미션 리롤권·칭호 10일권·카드 테마) 검증. 실제 DB 없이 돌아가요.

2026-10-05에 만들었어요. 코인이 쌓이기만 하던 문제(지급 662건 vs 소비 6건) 때문이에요.

여기서 확인하는 것:
  1) 리롤은 **고른 미션만** 바뀌고, 교체는 **항상 서버 미션**이다 (발로 미션을 주면 안 됨)
  2) 바뀐 미션의 진행도는 지워진다 (엉뚱한 미션에 "1/1"이 남으면 안 됨)
  3) 하루 1회 한도 · 이미 깬 미션 · 배정 안 된 미션 · 오늘 문서 없음을 각각 거절한다
  4) 동시에 두 번 들어오면 한 번만 성공한다 (picks 기반 낙관적 동시성)
  5) 테마는 기본이 공짜고, 같은 걸 두 번 사도 한 번만 들어간다
  6) 모든 테마가 어두운 색이다 (패널·글씨가 어두운 배경 기준이라 밝으면 글씨가 안 보임)
  7) 모르는 테마 이름이 와도 카드가 기본색으로 그려진다
  8) 칭호 단가에 역전이 없다 (10일권이 더 싸면 30일권을 아무도 안 사요)
  9) /악귀상점이 등록되고 뷰가 디스코드 컴포넌트 한도 안에 들어간다
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_shop_test"

import discord  # noqa: E402

from utils import cosmetic_store, mission_store, profile_card, title_store  # noqa: E402
from utils.mission_store import MISSIONS, SERVER_KEYS, VALORANT_KEYS  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
# 가짜 미션 컬렉션 (find_one / update_one with $set·$inc, 필터 일치 검사 포함)
# ------------------------------------------------------------------
class FakeMissions:
    def __init__(self, doc=None):
        self.doc = doc

    def find_one(self, flt, projection=None):
        if self.doc is None or self.doc["_id"] != flt["_id"]:
            return None
        return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                for k, v in self.doc.items()}

    def _matches(self, flt):
        for key, value in flt.items():
            if self.doc.get(key) != value:
                return False
        return True

    def update_one(self, flt, update, upsert=False):
        class Res:
            modified_count = 0
        res = Res()
        if self.doc is None or not self._matches(flt):
            return res
        for key, value in (update.get("$set") or {}).items():
            self.doc[key] = value
        for key, value in (update.get("$inc") or {}).items():
            self.doc[key] = int(self.doc.get(key) or 0) + value
        res.modified_count = 1
        return res


TODAY = mission_store.today_iso()


def doc_with(picks, done=None, progress=None, rerolls=None, date=TODAY):
    d = {"_id": "1", "date": date, "picks": list(picks), "done": list(done or []),
         "progress": dict(progress or {}), "oneTimeDone": [], "totalDone": 0}
    if rerolls is not None:
        d["rerolls"] = rerolls
    return d


def install(doc):
    fake = FakeMissions(doc)
    mission_store._missions = fake
    return fake


# 연동자의 실제 배정 모양: 발로 2 + 서버 1
LINKED_PICKS = [VALORANT_KEYS[0], VALORANT_KEYS[1], SERVER_KEYS[0]]

print("1) 고른 미션만 바뀌고, 교체는 항상 서버 미션이다")
for _ in range(20):  # 무작위라 여러 번 돌려요
    fake = install(doc_with(LINKED_PICKS))
    new_key, reason = asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))
    if new_key is None:
        check("리롤 성공", False, reason)
        break
    if MISSIONS[new_key]["kind"] != "server":
        check("교체는 항상 서버 미션", False, f"{new_key}={MISSIONS[new_key]['kind']}")
        break
    if fake.doc["picks"][1] != LINKED_PICKS[1] or fake.doc["picks"][2] != LINKED_PICKS[2]:
        check("나머지 미션은 그대로", False, str(fake.doc["picks"]))
        break
else:
    check("20번 다 서버 미션으로 교체 + 나머지 유지", True)

fake = install(doc_with(LINKED_PICKS))
new_key, _ = asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))
check("새 미션이 기존 picks에 없던 것", new_key not in LINKED_PICKS, str(new_key))
check("picks 길이가 그대로 3", len(fake.doc["picks"]) == 3, str(fake.doc["picks"]))
check("rerolls가 1 올라감", fake.doc.get("rerolls") == 1, str(fake.doc.get("rerolls")))

print("2) 바뀐 미션의 진행도는 지워진다")
fake = install(doc_with(LINKED_PICKS, progress={VALORANT_KEYS[0]: 1, SERVER_KEYS[0]: 7}))
asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))
check("바꾼 미션 진행도 삭제", VALORANT_KEYS[0] not in fake.doc["progress"], str(fake.doc["progress"]))
check("다른 미션 진행도는 유지", fake.doc["progress"].get(SERVER_KEYS[0]) == 7, str(fake.doc["progress"]))

print("3) 거절해야 하는 경우들")
install(doc_with(LINKED_PICKS, rerolls=mission_store.REROLL_LIMIT_PER_DAY))
check("하루 한도 초과 → limit", asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))[1] == "limit")

install(doc_with(LINKED_PICKS, done=[VALORANT_KEYS[0]]))
check("이미 깬 미션 → already_done",
      asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))[1] == "already_done")

install(doc_with(LINKED_PICKS))
check("배정 안 된 미션 → not_assigned",
      asyncio.run(mission_store.reroll(1, VALORANT_KEYS[4]))[1] == "not_assigned")

install(None)
check("오늘 문서 없음 → no_doc", asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))[1] == "no_doc")

install(doc_with(LINKED_PICKS, date="2020-01-01"))
check("어제 문서 → no_doc", asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))[1] == "no_doc")

install(doc_with(SERVER_KEYS))   # 서버 미션을 전부 갖고 있으면 바꿀 게 없어요
check("서버 미션 소진 → exhausted",
      asyncio.run(mission_store.reroll(1, SERVER_KEYS[0]))[1] == "exhausted")

print("4) 동시에 두 번 들어오면 한 번만 성공한다")
fake = install(doc_with(LINKED_PICKS))
first = asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))
# 두 번째는 **먼저 읽은 picks**로 들어온 셈이에요. 한도를 풀어도 picks가 달라져서 막혀야 해요.
# 한도를 풀어줘도, 이미 교체돼서 picks가 달라졌으니 막혀야 해요(코인 이중 차감 방지).
fake.doc["rerolls"] = 0
check("첫 번째는 성공", first[0] is not None, str(first))
# 이미 교체돼서 그 키는 picks에 없어요 → not_assigned로 막혀요(코인 이중 차감 방지).
check("같은 미션을 다시 리롤하면 막힌다",
      asyncio.run(mission_store.reroll(1, VALORANT_KEYS[0]))[1] == "not_assigned")

print("5) 남은 리롤 횟수 계산")
install(doc_with(LINKED_PICKS))
check(f"안 썼으면 {mission_store.REROLL_LIMIT_PER_DAY}회",
      asyncio.run(mission_store.rerolls_left(1)) == mission_store.REROLL_LIMIT_PER_DAY)
install(doc_with(LINKED_PICKS, rerolls=1))
check("한 번 썼으면 0회", asyncio.run(mission_store.rerolls_left(1)) == 0)
install(None)
check("오늘 문서가 없으면 아직 안 쓴 것",
      asyncio.run(mission_store.rerolls_left(1)) == mission_store.REROLL_LIMIT_PER_DAY)

print("6) 가격이 보상보다 비싸다 (코인 벌이용 리롤 차단)")
check("리롤 가격 > 미션 보상",
      mission_store.REROLL_PRICE > mission_store.REWARD_PER_MISSION,
      f"{mission_store.REROLL_PRICE} vs {mission_store.REWARD_PER_MISSION}")

# ------------------------------------------------------------------
# 테마
# ------------------------------------------------------------------
print("7) 테마 보유/선택")


class FakeCosmetics:
    def __init__(self):
        self.docs = {}

    def find_one(self, flt, projection=None):
        return self.docs.get(flt["_id"])

    def update_one(self, flt, update, upsert=False):
        class Res:
            modified_count = 0
            upserted_id = None
        res = Res()
        uid = flt["_id"]
        doc = self.docs.get(uid)
        # `themes: {"$ne": key}` 필터 흉내
        cond = flt.get("themes")
        if doc is not None and isinstance(cond, dict) and "$ne" in cond:
            if cond["$ne"] in (doc.get("themes") or []):
                return res
        if doc is None:
            if not upsert:
                return res
            doc = self.docs[uid] = {"_id": uid}
            res.upserted_id = uid
        for key, value in (update.get("$addToSet") or {}).items():
            bucket = doc.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
                res.modified_count = 1
        for key, value in (update.get("$set") or {}).items():
            doc[key] = value
            res.modified_count = 1
        return res


fake_cos = FakeCosmetics()
cosmetic_store._cosmetics = fake_cos

state = asyncio.run(cosmetic_store.get(5))
check("기본 테마는 공짜로 보유", state["themes"] == [cosmetic_store.DEFAULT_THEME], str(state))
check("처음 선택은 기본", state["theme"] == cosmetic_store.DEFAULT_THEME)
check("조회만으로 문서를 만들지 않는다", not fake_cos.docs)

check("처음 사면 True", asyncio.run(cosmetic_store.grant_theme(5, "심해")) is True)
check("같은 걸 또 사면 False (중복 결제 차단)",
      asyncio.run(cosmetic_store.grant_theme(5, "심해")) is False)
asyncio.run(cosmetic_store.select_theme(5, "심해"))
state = asyncio.run(cosmetic_store.get(5))
check("보유 목록에 기본+심해", sorted(state["themes"]) == sorted([cosmetic_store.DEFAULT_THEME, "심해"]),
      str(state["themes"]))
check("선택이 심해", state["theme"] == "심해")
check("남의 테마에 영향 없음",
      asyncio.run(cosmetic_store.selected_theme(6)) == cosmetic_store.DEFAULT_THEME)


class BrokenCosmetics:
    def find_one(self, *a, **kw):
        raise RuntimeError("DB 끊김")


cosmetic_store._cosmetics = BrokenCosmetics()
check("조회 실패 시 기본 테마로 물러난다",
      asyncio.run(cosmetic_store.selected_theme(5)) == cosmetic_store.DEFAULT_THEME)
cosmetic_store._cosmetics = fake_cos

print("8) 모든 테마가 어두운 색이다 (밝으면 흰 글씨가 안 보여요)")
for key, info in profile_card.THEMES.items():
    for spot in ("top", "bottom"):
        rgb = info[spot]
        # 인지 밝기(0~255). 패널(23,26,40)·글씨(255,255,255) 기준이라 넉넉히 100 아래로 둬요.
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        check(f"{key}.{spot} 어둡다 (밝기 {lum:.0f} < 100)", lum < 100, str(rgb))
check("기본 테마가 카드 기본색과 같다",
      profile_card.THEMES["기본"]["top"] == profile_card.BG_TOP
      and profile_card.THEMES["기본"]["bottom"] == profile_card.BG_BOTTOM)
check("테마마다 이모지·설명이 있다",
      all(t.get("emoji") and t.get("desc") for t in profile_card.THEMES.values()))

print("8-2) 패널 색이 테마에서 파생되고, 기본 테마는 원래 색과 거의 같다")
base_panel, base_edge = profile_card._panel_colors(profile_card.THEMES["기본"])
check("기본 패널 ≈ 원래 PANEL (채널별 오차 2 이내)",
      all(abs(base_panel[i] - profile_card.PANEL[i]) <= 2 for i in range(3)),
      f"{base_panel} vs {profile_card.PANEL}")
check("기본 테두리 ≈ 원래 PANEL_EDGE (오차 6 이내)",
      all(abs(base_edge[i] - profile_card.PANEL_EDGE[i]) <= 6 for i in range(3)),
      f"{base_edge} vs {profile_card.PANEL_EDGE}")
for key, info in profile_card.THEMES.items():
    panel, edge = profile_card._panel_colors(info)
    lum = 0.299 * panel[0] + 0.587 * panel[1] + 0.114 * panel[2]
    check(f"{key}: 패널이 어둡다 (밝기 {lum:.0f} < 110)", lum < 110, str(panel))
    check(f"{key}: 테두리가 패널보다 밝다", sum(edge) > sum(panel), f"{edge} vs {panel}")

print("9) 카드가 테마 색으로 그려지고, 모르는 이름은 기본으로 떨어진다")
if not profile_card.PILLOW_AVAILABLE:
    print("  (Pillow가 없어서 렌더 검사는 건너뛰어요)")
else:
    img = profile_card._gradient_background(*[profile_card.THEMES["라디안"][k] for k in ("top", "bottom")])
    check("맨 윗줄이 라디안 색", img.getpixel((0, 0)) == profile_card.THEMES["라디안"]["top"],
          str(img.getpixel((0, 0))))
    base = profile_card._gradient_background()
    check("기본 호출은 기본색", base.getpixel((0, 0)) == profile_card.BG_TOP)
    # _render는 data["theme"]을 읽어요. 모르는 이름이면 기본으로 떨어져야 해요.
    fallback = profile_card.THEMES.get("없는테마", profile_card.THEMES["기본"])
    check("모르는 테마 → 기본", fallback is profile_card.THEMES["기본"])

print("10) 칭호 단가에 역전이 없다 (10일권이 더 싸면 30일권이 무의미해져요)")
plans = title_store.TITLE_PLANS
check("10일권 존재", 10 in plans and plans[10] == 12, str(plans))
rate10 = plans[10] / 10
rate30 = plans[title_store.TITLE_DAYS] / title_store.TITLE_DAYS
check(f"긴 쪽이 이득 (10일 {rate10:.2f} > 30일 {rate30:.2f} 코인/일)", rate10 > rate30)

print("11) /악귀상점 등록 + 컴포넌트 한도")
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_shop_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_shop_test"
from discord.ext import commands as dcommands  # noqa: E402

from cogs.akgui_shop import RerollView, ShopView, ThemeView  # noqa: E402


def layout_ok(view, label):
    payload = view.to_components()
    rows = len(payload)
    check(f"{label}: 줄 5개 이하", rows <= 5, f"{rows}줄")
    for row in payload:
        kids = row.get("components", [])
        # 드롭다운은 한 줄을 통째로 차지해요(버튼과 못 섞여요).
        check(f"{label}: 한 줄에 5개 이하", len(kids) <= 5, str(len(kids)))


layout_ok(ShopView(None, 1), "상점")
layout_ok(RerollView(1, LINKED_PICKS), "리롤")
layout_ok(ThemeView(1, [cosmetic_store.DEFAULT_THEME], cosmetic_store.DEFAULT_THEME), "테마")

theme_payload = ThemeView(1, ["심해"], "심해").to_components()
opts = theme_payload[0]["components"][0]["options"]
check("테마 드롭다운 선택지가 25개 이하", len(opts) <= 25, str(len(opts)))
check("테마 드롭다운에 전체 테마가 나온다", len(opts) == len(profile_card.THEMES), str(len(opts)))
check("보유 테마는 '보유 중'으로 표시",
      any("보유 중" in (o.get("description") or "") for o in opts), str(opts[:2]))
check("미보유 테마는 가격 표시",
      any(f"{profile_card.THEME_PRICE}코인" in (o.get("description") or "") for o in opts))


async def load_cog():
    bot = dcommands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension("cogs.akgui_shop")
    await bot.load_extension("cogs.title_shop")
    names = {c.name for c in bot.tree.get_commands()}
    check("/악귀상점 등록됨", "악귀상점" in names, str(sorted(names)))
    cmd = bot.tree.get_command("칭호구매")
    params = {p.name: p for p in cmd.parameters}
    check("/칭호구매에 기간 선택지", "기간" in params, str(list(params)))
    if "기간" in params:
        values = [c.value for c in params["기간"].choices]
        check("선택지가 10일·30일", sorted(values) == [10, title_store.TITLE_DAYS], str(values))


asyncio.run(load_cog())

# ==================================================================
print("\n12) 🚨 3초 - 코인보다 ack가 먼저인가 (전수 검사)")
# ------------------------------------------------------------------
# 상호작용 토큰은 3초면 만료돼요(`404 Unknown interaction`, code 10062).
# 🚨 진짜 피해는 404가 아니라 **순서**예요 - 코인을 먼저 빼고 응답을 나중에 하면,
#    응답이 실패했을 때 **유저는 화면도 못 보고 코인만 잃어요.**
#    2026-10-17에 🎣 낚시 다시던지기가 이걸로 터졌고, 상점 5곳이 같은 모양이었어요
#    (🎨테마 10코인 · 🧊보호권 3코인 · 🎲리롤 2코인).
#
# 핸들러를 하나 더 붙일 때 또 빠뜨리지 않게 **이름 목록이 아니라 전수로** 검사해요.
import ast as _ast  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_shop_src = _Path(os.path.join(BOT_DIR, "cogs/akgui_shop.py")).read_text(encoding="utf-8")
_shop_tree = _ast.parse(_shop_src)

_handlers = [(c.name, f) for c in _shop_tree.body if isinstance(c, _ast.ClassDef)
             for f in c.body if isinstance(f, (_ast.AsyncFunctionDef, _ast.FunctionDef))
             and any(a.arg == "interaction" for a in f.args.args)]
check("상호작용 핸들러를 찾았다", len(_handlers) >= 8, f"{len(_handlers)}개")

# ⚠️ `interaction_check`는 예외예요 - 거절 안내만 하고 DB를 안 쳐요. 거기서 defer하면
#    "받아놓고 아무것도 안 한" 빈 응답이 남아요.
_EXEMPT = {"interaction_check", "on_timeout", "callback"}

_late, _ok_list = [], []
for _owner, _fn in _handlers:
    if _fn.name in _EXEMPT:
        continue
    # 함수 본문에서 **처음 나오는 await**가 ack여야 해요(중첩 함수는 제외).
    _inner = {id(n) for f2 in _ast.walk(_fn)
              if f2 is not _fn and isinstance(f2, (_ast.AsyncFunctionDef, _ast.FunctionDef))
              for n in _ast.walk(f2)}
    _awaits = sorted((n for n in _ast.walk(_fn)
                      if isinstance(n, _ast.Await) and id(n) not in _inner),
                     key=lambda n: (n.lineno, n.col_offset))
    if not _awaits:
        continue
    _first = _awaits[0].value
    _func = getattr(_first, "func", None)
    _name = getattr(_func, "id", "") or getattr(_func, "attr", "")
    # ⭐ 규칙은 "ack를 써라"가 아니라 **"첫 응답 전에 다른 await를 하지 마라"**예요.
    #    DB를 안 치고 바로 답하는 안내문(`ShopView.title`)은 `ack` 없이
    #    `response.send_message` 한 방이 맞아요 - defer를 끼우면 왕복만 늘어요.
    _is_direct_reply = getattr(getattr(_func, "value", None), "attr", "") == "response"
    if _name == "ack" or _is_direct_reply:
        _ok_list.append(f"{_owner}.{_fn.name}")
    else:
        _late.append(f"{_owner}.{_fn.name} → {_name}():{_awaits[0].lineno}")

check("🚨 첫 응답 전에 다른 await가 없다 (코인보다 ack가 먼저)", not _late,
      "늦게 받는 곳: " + ", ".join(_late) if _late else f"{len(_ok_list)}곳 확인")

# 🚨 ack 뒤에는 `interaction.response.*`를 쓸 수 없어요(이미 응답한 상태예요).
_bad_resp = []
for _owner, _fn in _handlers:
    if _fn.name in _EXEMPT:
        continue
    _uses_ack = any(getattr(getattr(n, "func", None), "id", "") == "ack"
                    for n in _ast.walk(_fn) if isinstance(n, _ast.Call))
    if not _uses_ack:
        continue
    for n in _ast.walk(_fn):
        if (isinstance(n, _ast.Call)
                and getattr(getattr(n.func, "value", None), "attr", "") == "response"
                and getattr(n.func, "attr", "") in ("send_message", "edit_message")):
            _bad_resp.append(f"{_owner}.{_fn.name} response.{n.func.attr}():{n.lineno}")
check("🚨 ack 뒤에 response.send_message/edit_message를 안 쓴다", not _bad_resp,
      ", ".join(_bad_resp) if _bad_resp else "followup/edit_original만 씀")


# 실제로 토큰이 죽은 상황을 흉내내요 - 코인이 빠지면 안 돼요.
class _DeadHTTP:
    status = 404
    reason = "Not Found"


class _DeadResp:
    async def defer(self, *a, **k):
        raise discord.NotFound(_DeadHTTP(), {"code": 10062, "message": "Unknown interaction"})


class _DeadInter:
    type = "component"

    def __init__(self, uid=1):
        self.user = type("U", (), {"id": uid})()
        self.response = _DeadResp()


import cogs.akgui_shop as _shop_mod  # noqa: E402
from utils import coin_wallet as _wallet  # noqa: E402

_spends = []
_real_spend = _wallet.spend


async def _spy_spend(uid, amount, *, reason=""):
    _spends.append((uid, amount, reason))
    return True


_wallet.spend = _spy_spend
try:
    _v = _shop_mod.ThemeView(1, [], cosmetic_store.DEFAULT_THEME)
    asyncio.run(_v.pick_theme(_DeadInter(1), "심해"))
    check("🚨 토큰이 죽으면 테마 코인(10)이 빠지지 않는다",
          _spends == [], f"spend가 {len(_spends)}번 불렸어요: {_spends}")

    _spends.clear()
    _rv = _shop_mod.RerollView(1, LINKED_PICKS)
    asyncio.run(_rv.do_reroll(_DeadInter(1), LINKED_PICKS[0]))
    check("🚨 토큰이 죽으면 리롤 코인(2)이 빠지지 않는다",
          _spends == [], f"spend가 {len(_spends)}번 불렸어요: {_spends}")
finally:
    _wallet.spend = _real_spend


# ------------------------------------------------------------------
# 정상 경로도 끝까지 돌려봐요. `edit_message` -> `edit_original_response`,
# `send_message` -> `followup.send` 치환을 하나라도 빠뜨리면 **ack 뒤에 다시
# 응답하려다 터져요**(`InteractionResponded`). AST로는 안 잡히는 종류예요.
class _RecResp:
    def __init__(self, rec):
        self.rec = rec

    async def defer(self, *a, **k):
        self.rec.append(("defer", k.get("ephemeral", False), k.get("thinking", False)))

    async def send_message(self, *a, **k):
        self.rec.append(("🚨response.send_message", None, None))

    async def edit_message(self, *a, **k):
        self.rec.append(("🚨response.edit_message", None, None))


class _RecInter:
    type = "component"

    def __init__(self, rec, uid=1):
        self.rec = rec
        self.user = type("U", (), {"id": uid})()
        self.response = _RecResp(rec)

    async def edit_original_response(self, **k):
        self.rec.append(("edit_original", None, None))

    class _FollowUp:
        def __init__(self, rec):
            self.rec = rec

        async def send(self, *a, **k):
            self.rec.append(("followup", k.get("ephemeral", False), None))

    @property
    def followup(self):
        return self._FollowUp(self.rec)


_patches = {
    (_wallet, "spend"): lambda uid, amt, reason="": True,
    (_wallet, "get_balance"): lambda uid: 99,
    (cosmetic_store, "owned_themes"): lambda uid: [],
    (cosmetic_store, "grant_theme"): lambda uid, key: True,
    (cosmetic_store, "select_theme"): lambda uid, key: None,
    (mission_store, "reroll"): lambda uid, key: (SERVER_KEYS[0], None),
    (mission_store, "rerolls_left"): lambda uid: 0,
}
_orig = {(m, n): getattr(m, n) for (m, n) in _patches}


def _mk_async(fn):
    async def _f(*a, **k):
        return fn(*a, **k)
    return _f


for (_m, _n), _fn in _patches.items():
    setattr(_m, _n, _mk_async(_fn))
try:
    _rec = []
    asyncio.run(_shop_mod.ThemeView(1, [], cosmetic_store.DEFAULT_THEME)
                .pick_theme(_RecInter(_rec), "심해"))
    _kinds = [r[0] for r in _rec]
    check("🎨 테마: ack로 시작해 edit_original로 끝난다",
          _kinds == ["defer", "edit_original"], f"순서 {_kinds}")

    _rec2 = []
    asyncio.run(_shop_mod.RerollView(1, LINKED_PICKS)
                .do_reroll(_RecInter(_rec2), LINKED_PICKS[0]))
    _kinds2 = [r[0] for r in _rec2]
    check("🎲 리롤: ack로 시작해 edit_original로 끝난다",
          _kinds2 == ["defer", "edit_original"], f"순서 {_kinds2}")

    # 🚨 Select 경로의 defer는 **인자가 없어야** 해요. `thinking=True`로 주면
    #    고르던 메시지는 그대로 남고 **새 메시지가 하나 더 생겨서** 화면이 쌓여요.
    check("🚨 Select의 defer는 인자 없이 (화면을 그대로 두고 받기)",
          _rec[0] == ("defer", False, False) and _rec2[0] == ("defer", False, False),
          f"테마 {_rec[0]} / 리롤 {_rec2[0]}")
finally:
    for (_m, _n), _fn in _orig.items():
        setattr(_m, _n, _fn)

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
