"""🗺️ 웹 전술판 테스트 — DB·valorant-api에 붙지 않아요(저장소와 자료를 가짜로 바꿔요)."""
import asyncio
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
sys.stdout.reconfigure(encoding="utf-8")
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

from aiohttp.test_utils import TestClient, TestServer

from cogs import tactics as cog
from utils import tactics as tc

failed: list[str] = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failed.append(name)


print("[1] 맵·요원 자료")
ko_map = {"displayName": "어센트", "displayIcon": "http://x/mini.png", "xMultiplier": 7e-05, "yMultiplier": -7e-05,
          "xScalarToAdd": 0.813895, "yScalarToAdd": 0.573242,
          "callouts": [{"regionName": "메인", "superRegionName": "A", "location": {"x": 0, "y": 0}},
                       {"regionName": "공격팀 진영 시작 지점", "superRegionName": "공격팀 진영", "location": {"x": 1000, "y": 0}}]}
m = tc.map_entry("Ascent", ko_map)
check("1m 길이 = 100 × |xMultiplier|", abs(m["unit"] - 0.007) < 1e-9, m["unit"])
check("좌표 (0,0) → 더하는 값", (m["callouts"][0]["u"], m["callouts"][0]["v"]) == (0.8139, 0.5732))
check("x가 v로 (엇갈림)", m["callouts"][1]["v"] == round(1000 * -7e-05 + 0.573242, 4))
check("콜아웃 이름 'A 메인'", m["callouts"][0]["name"] == "A 메인")
check("이미 들어 있으면 안 겹침", m["callouts"][1]["name"] == "공격팀 진영 시작 지점")

en = [{"uuid": "o", "displayName": "Omen", "displayIcon": "i", "role": {"displayName": "Controller"},
       "abilities": [{"slot": "Ability2", "displayName": "Dark Cover", "displayIcon": "e"},
                     {"slot": "Ability1", "displayName": "Paranoia", "displayIcon": "q"},
                     {"slot": "Passive", "displayName": "x", "displayIcon": None},
                     {"slot": "Ultimate", "displayName": "From the Shadows", "displayIcon": "x"},
                     {"slot": "Grenade", "displayName": "Shrouded Step", "displayIcon": "c"}]},
      {"uuid": "j", "displayName": "Jett", "displayIcon": "i", "role": {"displayName": "Duelist"},
       "abilities": [{"slot": "Grenade", "displayName": "Cloudburst", "displayIcon": "c"}]}]
ko = [{"uuid": "o", "displayName": "오멘", "role": {"displayName": "전략가"},
       "abilities": [{"slot": "Ability2", "displayName": "어둠의 장막"}, {"slot": "Ability1", "displayName": "피해망상"},
                     {"slot": "Ultimate", "displayName": "그림자 습격"}, {"slot": "Grenade", "displayName": "어둠의 발자국"}]},
      {"uuid": "j", "displayName": "제트", "role": {"displayName": "타격대"},
       "abilities": [{"slot": "Grenade", "displayName": "연막 폭발"}]}]
ag = tc.agent_entries(en, ko)
check("역할 순(전략가 먼저)", [a["name"] for a in ag] == ["오멘", "제트"])
om = ag[0]
check("스킬 Q·E·C·X 순서, 패시브 빠짐", [a["slot"] for a in om["abilities"]] == ["Q", "E", "C", "X"])
check("한국어 스킬 이름", om["abilities"][1]["name"] == "어둠의 장막")
check("연막은 원(반경)", om["abilities"][1]["shape"]["kind"] == "circle" and om["abilities"][1]["shape"]["r"] > 0)
check("모양 없는 스킬은 아이콘", om["abilities"][0]["shape"]["kind"] == "icon")
check("한국어 역할 이름", om["roleName"] == "전략가")
check("오멘 연막에 사거리(요원 기준)", om["abilities"][1]["shape"].get("range") == tc.RANGES["Dark Cover"])
check("사거리 없는 스킬엔 안 붙음", "range" not in om["abilities"][0]["shape"])
check("공용 모양 표를 안 건드림(복사본)", "range" not in tc.SHAPES["Dark Cover"])

print("[2] 저장 자료 검사")
ok = tc.clean_data({"side": "def", "scenes": [{"items": [
    {"type": "ability", "agent": "o", "slot": "E", "team": "ally", "u": 0.5, "v": 0.5},
    {"type": "ability", "agent": "v", "slot": "E", "team": "enemy", "u": 0.1, "v": 0.2, "u2": 0.3, "v2": 0.2},
    {"type": "arrow", "u": 0.1, "v": 0.1, "u2": 0.2, "v2": 0.2},
    {"type": "arrow", "u": 0.1, "v": 0.1},                       # 끝점 없음 → 버림
    {"type": "text", "u": 0.3, "v": 0.3, "text": "  " + "가" * 100},
    {"type": "text", "u": 0.3, "v": 0.3, "text": "   "},          # 빈 글 → 버림
    {"type": "hack", "u": 0.1, "v": 0.1},                          # 모르는 종류 → 버림
    {"type": "agent", "agent": "o", "u": "nan", "v": 0.2},         # 좌표 이상 → 버림
    {"type": "agent", "agent": "o", "u": 9, "v": 0.2},             # 범위 밖 → 버림
    {"type": "agent", "agent": "o", "team": "<script>", "u": 0.2, "v": 0.2, "extra": "x"},
]}]})
its = ok["scenes"][0]["items"]
check("정상 5개만 남음", len(its) == 5, len(its))
check("수비 표시 유지", ok["side"] == "def")
check("글 60자로 자름", len(its[3]["text"]) == 60)
check("팀 값은 ally/enemy만", its[4]["team"] == "ally")
check("모르는 필드는 버림", "extra" not in its[4])
check("선 스킬 끝점 유지", its[1].get("u2") == 0.3)
curve = tc.clean_data({"scenes": [{"items": [
    {"type": "ability", "agent": "h", "slot": "E", "u": 0, "v": 0, "pts": [[0.1, 0.1], [0.15, 0.2], [0.2, 0.18]]},
    {"type": "arrow", "u": 0.1, "v": 0.1, "pts": [[0.3, 0.3], [0.35, 0.4]]},
    {"type": "arrow", "u": 0.1, "v": 0.1, "u2": 0.2, "v2": 0.2, "pts": [[0.3, 0.3], ["x", 0.4]]},
    {"type": "arrow", "u": 0.1, "v": 0.1, "u2": 0.2, "v2": 0.2, "pts": [[0.3, 0.3]] * 65},
]}]})["scenes"][0]["items"]
check("곡선 점 목록 저장", curve[0].get("pts") == [[0.1, 0.1], [0.15, 0.2], [0.2, 0.18]])
check("곡선 처음·끝 = u,v / u2,v2", (curve[0]["u"], curve[0]["v2"]) == (0.1, 0.18))
check("끝점 없던 화살표도 곡선이면 살아남음", curve[1].get("u2") == 0.35)
check("이상한 점이 있으면 곡선은 버리고 직선 유지", "pts" not in curve[2] and curve[2]["u2"] == 0.2)
check("점 65개는 곡선 버림", "pts" not in curve[3])
check("장면 없으면 거절", tc.clean_data({"scenes": []}) is None)
check("너무 많으면 거절", tc.clean_data({"scenes": [{"items": [{"type": "agent", "u": .1, "v": .1}] * 301}]}) is None)
check("이상한 값 거절", tc.clean_data("x") is None and tc.clean_data({"scenes": "x"}) is None)

print("[2-1] 항목 id · 장면 sid (실시간 동기화의 기준)")
idd = tc.clean_data({"scenes": [
    {"sid": "sceneA", "items": [{"id": "keep_1", "type": "agent", "agent": "o", "u": 0.1, "v": 0.1},
                                {"id": "keep_1", "type": "agent", "agent": "o", "u": 0.2, "v": 0.2},     # 겹친 id
                                {"id": "bad id!", "type": "agent", "agent": "o", "u": 0.3, "v": 0.3},    # 이상한 id
                                {"type": "agent", "agent": "o", "u": 0.4, "v": 0.4, "rot": 1.23456, "dead": True, "me": True},
                                {"type": "agent", "agent": "o", "u": 0.4, "v": 0.4, "rot": "x", "dead": 1, "me": "yes"}]},
    {"sid": "sceneA", "items": []}, {"items": []}]})
ii = idd["scenes"][0]["items"]
check("쓸 수 있는 id·sid는 그대로", ii[0]["id"] == "keep_1" and idd["scenes"][0]["sid"] == "sceneA")
check("겹치거나 이상한 id는 새로 붙임", len({x["id"] for x in ii}) == 5 and all(tc._valid_id(x["id"]) for x in ii))
check("겹친·없는 sid도 새로 붙임", len({s["sid"] for s in idd["scenes"]}) == 3)
check("경기 장면 요원 값(시선·처치·나) 유지", ii[3].get("rot") == 1.235 and ii[3].get("dead") is True and ii[3].get("me") is True)
check("이상한 값은 버림", not {"rot", "dead", "me"} & set(ii[4]))
old = {"scenes": [{"title": "", "items": [{"type": "agent", "u": 0.1, "v": 0.1}]}], "side": "atk"}
check("예전 판에 id를 붙임(한 번만)", tc.ensure_ids(old) is True and tc.ensure_ids(old) is False
      and tc._valid_id(old["scenes"][0]["sid"]) and tc._valid_id(old["scenes"][0]["items"][0]["id"]))

print("[2-2] 실시간 연산 (apply_op)")


def fresh():
    return {"title": "제목", "notes": [], "data": {"side": "atk", "scenes": [
        {"sid": "s1", "title": "", "items": [{"id": "a1", "type": "agent", "agent": "o", "team": "ally", "u": 0.1, "v": 0.1}]}]}}


st = fresh()
new_item = {"id": "b2", "type": "text", "text": "여기", "team": "enemy", "u": 0.5, "v": 0.5, "hack": 1}
r = tc.apply_op(st, {"t": "add", "sid": "s1", "item": new_item})
check("추가: 정리된 연산을 돌려줌", r and r["t"] == "add" and "hack" not in r["item"] and len(st["data"]["scenes"][0]["items"]) == 2)
check("같은 추가가 또 오면 바뀐 것 없음(NOOP)", tc.apply_op(st, {"t": "add", "sid": "s1", "item": new_item}) is tc.NOOP
      and len(st["data"]["scenes"][0]["items"]) == 2)
r = tc.apply_op(st, {"t": "upd", "sid": "s1", "item": {**new_item, "u": 0.6}})
check("고치기", r and r["t"] == "upd" and st["data"]["scenes"][0]["items"][1]["u"] == 0.6)
check("없는 항목 고치기는 NOOP(남이 먼저 지움)", tc.apply_op(st, {"t": "upd", "sid": "s1", "item": {**new_item, "id": "zz"}}) is tc.NOOP)
check("지우기 → 또 지우면 NOOP", tc.apply_op(st, {"t": "del", "sid": "s1", "id": "b2"})["t"] == "del"
      and tc.apply_op(st, {"t": "del", "sid": "s1", "id": "b2"}) is tc.NOOP)
check("없는 장면의 연산은 NOOP", tc.apply_op(st, {"t": "add", "sid": "nope", "item": new_item}) is tc.NOOP)
check("id 없는 항목·모르는 종류·이상한 값은 거절", tc.apply_op(st, {"t": "add", "sid": "s1", "item": {"type": "agent", "u": 0, "v": 0}}) is None
      and tc.apply_op(st, {"t": "hack"}) is None and tc.apply_op(st, "x") is None
      and tc.apply_op(st, {"t": "add", "sid": "s1", "item": {"id": "q", "type": "agent", "u": 9, "v": 0}}) is None)
check("마지막 장면은 못 지움(거절)", tc.apply_op(st, {"t": "sdel", "sid": "s1"}) is None)
r = tc.apply_op(st, {"t": "sadd", "after": "s1", "scene": {"sid": "s2", "title": "둘째", "items": [
    {"id": "c3", "type": "agent", "agent": "j", "u": 0.3, "v": 0.3}]}})
check("장면 추가(뒤에)", r and [s["sid"] for s in st["data"]["scenes"]] == ["s1", "s2"])
check("같은 장면 추가가 또 오면 NOOP", tc.apply_op(st, {"t": "sadd", "after": "s1", "scene": {"sid": "s2", "items": []}}) is tc.NOOP)
tc.apply_op(st, {"t": "sadd", "after": None, "scene": {"sid": "s0", "items": []}})
tc.apply_op(st, {"t": "sadd", "after": "없는장면", "scene": {"sid": "s9", "items": []}})
check("after 없으면 맨 앞, 모르는 장면이면 맨 뒤", [s["sid"] for s in st["data"]["scenes"]] == ["s0", "s1", "s2", "s9"])
check("장면 제목", tc.apply_op(st, {"t": "stitle", "sid": "s2", "title": "가" * 99})["title"] == "가" * 40
      and tc.apply_op(st, {"t": "stitle", "sid": "s2", "title": "가" * 40}) is tc.NOOP)
r = tc.apply_op(st, {"t": "meta", "title": "  새 제목  ", "side": "def"})
check("제목·공수", r == {"t": "meta", "title": "새 제목", "side": "def"} and st["title"] == "새 제목" and st["data"]["side"] == "def")
check("같은 값이면 NOOP, 이상한 공수는 무시", tc.apply_op(st, {"t": "meta", "title": "새 제목", "side": "x"}) is tc.NOOP)
st["notes"] = [{"id": "n1", "sid": "s2", "u": 0, "v": 0, "text": "x", "uid": "5"}, {"id": "n2", "sid": "s1", "u": 0, "v": 0, "text": "y", "uid": "5"}]
tc.apply_op(st, {"t": "sdel", "sid": "s2"})
check("장면을 지우면 그 장면의 메모도 같이", [n["id"] for n in st["notes"]] == ["n2"] and tc.apply_op(st, {"t": "sdel", "sid": "s2"}) is tc.NOOP)
full = fresh()
for i in range(tc.MAX_SCENES - 1):
    tc.apply_op(full, {"t": "sadd", "after": "s1", "scene": {"sid": f"x{i}", "items": []}})
check("장면 10개 넘으면 거절", len(full["data"]["scenes"]) == 10
      and tc.apply_op(full, {"t": "sadd", "after": "s1", "scene": {"sid": "more", "items": []}}) is None)
full["data"]["scenes"][0]["items"] = [{"id": f"k{i}", "type": "agent", "agent": "o", "team": "ally", "u": 0.1, "v": 0.1} for i in range(tc.MAX_ITEMS)]
check("항목 300개 넘으면 거절", tc.apply_op(full, {"t": "add", "sid": "s1", "item": {"id": "over", "type": "agent", "u": 0.1, "v": 0.1}}) is None)

# 브라우저(board.html applyOps)와 서버(apply_op)가 같은 결과를 내는지 — node가 만든 사례로 맞춰 봐요
import json
import shutil
import subprocess

if shutil.which("node"):
    dump = subprocess.run(["node", os.path.join("scripts", "test_tactics_sync.js"), "--dump"],
                          capture_output=True, text=True, encoding="utf-8")
    cases = json.loads(dump.stdout) if dump.returncode == 0 else []

    def canon(state):
        return {"title": state["title"], "side": state["data"]["side"], "scenes": [
            {"sid": s["sid"], "title": s.get("title") or "",
             "items": sorted(json.dumps(it, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for it in s["items"])}
            for s in state["data"]["scenes"]]}

    diff = 0
    for case in cases:
        state = {"title": case["base"]["title"], "notes": [],
                 "data": {"side": case["base"]["side"], "scenes": case["base"]["scenes"]}}
        for op in case["ops"]:
            tc.apply_op(state, op)
        if canon(state) != case["result"]:
            diff += 1
    check(f"브라우저 applyOps와 서버 apply_op 결과가 같음 ({len(cases)}사례)", cases and diff == 0, f"{diff}개 다름")
else:
    print("  ⏭️ node가 없어 브라우저·서버 맞춰 보기는 건너뜀")

print("[2-3] 링크 — 편집 토큰 · 개인 통행증")
check("편집 토큰은 보기ID로 언제나 같은 값", tc.edit_token_for("abc") == tc.edit_token_for("abc") != tc.edit_token_for("abd")
      and len(tc.edit_token_for("abc")) == 24)
p_c = tc.make_pass("board1", 777, "c")
check("통행증: 맞는 판에서만 통과", tc.check_pass("board1", p_c) == ("777", "c") and tc.check_pass("board2", p_c) is None)
head = p_c.split(".")
check("역할을 바꿔치면 거절", tc.check_pass("board1", ".".join([head[0], "f", head[2], head[3]])) is None)
check("사람을 바꿔치면 거절", tc.check_pass("board1", ".".join(["778", head[1], head[2], head[3]])) is None)
check("만료를 늘려도 거절", tc.check_pass("board1", ".".join([head[0], head[1], "ffffffff", head[3]])) is None)
check("이상한 값 거절", all(tc.check_pass("board1", x) is None for x in ("", "a.b.c.d", None, "1.c.zz.sig", "x" * 200)))
ttl = dict(tc.PASS_TTL)
tc.PASS_TTL["c"] = -10
check("지난 통행증은 거절", tc.check_pass("board1", tc.make_pass("board1", 777, "c")) is None)
tc.PASS_TTL.update(ttl)
check("by(짧은 서명)는 사람마다 다르고 ID가 안 보임", tc.by_of(777) == tc.by_of("777") != tc.by_of(778) and "777" not in tc.by_of(777)
      and tc.by_of(None) == "")

print("[2-4] 💬 메모 핀")
ns = fresh()
n1 = tc.add_note(ns, {"id": "n1", "sid": "s1", "u": 0.2, "v": 0.3, "text": "  여기서   연막\n먼저  "}, 42, "철수")
check("메모 남기기(공백 정리)", n1 and n1["text"] == "여기서 연막 먼저" and n1["uid"] == "42" and n1["name"] == "철수")
check("같은 id·없는 장면·빈 글·id 없음은 거절", all(tc.add_note(ns, x, 42, "철수") is None for x in (
    {"id": "n1", "sid": "s1", "u": 0.2, "v": 0.3, "text": "또"}, {"id": "n2", "sid": "없음", "u": 0.2, "v": 0.3, "text": "x"},
    {"id": "n3", "sid": "s1", "u": 0.2, "v": 0.3, "text": "   "}, {"sid": "s1", "u": 0.2, "v": 0.3, "text": "x"}, "x")))
check("120자로 자름", len(tc.add_note(ns, {"id": "n4", "sid": "s1", "u": 0, "v": 0, "text": "가" * 300}, 42, "철수")["text"]) == 120)
out = tc.note_out(n1)
check("브라우저로는 디스코드 ID 대신 by만", "uid" not in out and out["by"] == tc.by_of(42) and "42" not in json.dumps(out))
check("남의 메모는 못 지움, 내 것은 지움", tc.del_note(ns, "n1", 43) is False and tc.del_note(ns, "n1", 42) is True)
check("판 주인은 누구 것이든 지움", tc.del_note(ns, "n4", 1, anyone=True) is True and ns["notes"] == [])
for i in range(tc.MAX_NOTES):
    tc.add_note(ns, {"id": f"m{i}", "sid": "s1", "u": 0, "v": 0, "text": "x"}, 42, "철수")
check("판 하나에 60개까지", len(ns["notes"]) == 60 and tc.add_note(ns, {"id": "last", "sid": "s1", "u": 0, "v": 0, "text": "x"}, 42, "철수") is None)
check("복사본 제목", tc.fork_title("A 공격") == "A 공격 수정안" and tc.fork_title("A 공격 수정안") == "A 공격 수정안"
      and len(tc.fork_title("가" * 40)) == 40)

print("[3] 웹 경로")
store: dict = {}


made_count = 0


async def fake_create(uid, map_key, title, channel_id=None, data=None, extra=None):
    global made_count
    made_count += 1                      # 지운 뒤에도 겹치지 않게 번호는 계속 올라가요
    vid = f"view{made_count:03d}"
    tok = tc.edit_token_for(vid)
    store[vid] = {"_id": vid, "edit_hash": tc._hash(tok), "map": map_key, "title": title,
                  "uid": str(uid), "channel": str(channel_id) if channel_id else None,
                  "data": data or {"scenes": [{"title": "", "items": []}], "side": "atk"}, "notes": []}
    store[vid].update(extra or {})
    return vid, tok


async def fake_get(*, view_id=None, edit_token=None):
    if edit_token:
        return next((d for d in store.values() if d["edit_hash"] == tc._hash(edit_token)), None)
    return store.get(view_id)


async def fake_save(token, data, title=None):
    d = await fake_get(edit_token=token)
    if not d:
        return False
    d["data"] = data
    if title is not None:
        d["title"] = title
    return True


saved: list[str] = []


async def fake_save_state(view_id, state):
    """실시간 방이 저장할 때 — 판·제목·메모를 통째로."""
    d = store.get(view_id)
    if not d:
        return False
    d["data"], d["title"], d["notes"] = state["data"], state["title"], state["notes"]
    saved.append(view_id)
    return True


async def fake_maps(s):
    return {"ascent": m}


async def fake_agents(s):
    return ag

tc.create_board, tc.get_board, tc.save_board, tc.save_state = fake_create, fake_get, fake_save, fake_save_state
tc.maps, tc.agents = fake_maps, fake_agents


async def recv(ws, kind, timeout=2.0):
    """그 종류(t)의 메시지가 올 때까지 읽어요(다른 종류는 넘겨요). 안 오면 None."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while True:
        left = end - loop.time()
        if left <= 0:
            return None
        try:
            msg = await asyncio.wait_for(ws.receive(), left)
        except asyncio.TimeoutError:
            return None
        if msg.type.name != "TEXT":
            return None
        j = json.loads(msg.data)
        if j.get("t") == kind:
            return j


async def quiet(ws, kind, timeout=0.3):
    """그 종류의 메시지가 **안 오는지**."""
    return await recv(ws, kind, timeout) is None


async def run():
    vid, tok = await fake_create(1, "ascent", "A 공격")
    page = cog.read_page()
    check("화면 파일 읽힘", "<svg" in page and "/api/meta" in page)
    async with TestClient(TestServer(cog.build_web_app(page, lambda: None))) as c:
        r = await c.get(f"/e/{tok}")
        check("편집 화면 200", r.status == 200 and "text/html" in r.headers["Content-Type"])
        check("검색 노출 막음", r.headers.get("X-Robots-Tag") == "noindex")
        r = await c.get("/api/meta"); j = await r.json()
        check("자료: 맵·요원", "ascent" in j["maps"] and len(j["agents"]) == 2)
        r = await c.get(f"/api/board/e/{tok}"); j = await r.json()
        check("편집 링크로 판 받기", r.status == 200 and j["editable"] and j["view"] == vid and j["map"] == "ascent")
        r = await c.get(f"/api/board/v/{vid}"); j = await r.json()
        check("보기 링크는 편집 불가 표시", r.status == 200 and j["editable"] is False)
        check("보기 응답에 편집 토큰 없음", tok not in await r.text())
        r = await c.get("/api/board/e/없는토큰")
        check("없는 편집 링크 404", r.status == 404)
        body = {"title": "A 공격 연막", "data": {"side": "atk", "scenes": [{"items": [
            {"type": "ability", "agent": "o", "slot": "E", "team": "ally", "u": 0.4, "v": 0.4}]}]}}
        r = await c.post(f"/api/board/e/{tok}", json=body)
        check("저장 200", r.status == 200, await r.text())
        r = await c.post(f"/api/board/e/{tok}", json=body)
        check("1초 안에 또 저장하면 429", r.status == 429)
        r = await c.get(f"/api/board/v/{vid}"); j = await r.json()
        check("저장한 게 보기 링크에 보임", j["title"] == "A 공격 연막" and len(j["data"]["scenes"][0]["items"]) == 1)
        r = await c.post(f"/api/board/e/{vid}", json=body)
        check("보기 ID로는 저장 못 함(404)", r.status == 404)
        r = await c.post("/api/board/e/tok-other", data=b"not json", headers={"Content-Type": "application/json"})
        check("JSON 아니면 400", r.status == 400)
        r = await c.post("/api/board/e/tok-big", data=b"x" * (300 * 1024))
        check("256KB 넘으면 거절(413)", r.status == 413)
        r = await c.get("/healthz")
        check("healthz", r.status == 200)
        r = await c.post(f"/api/board/e/{tok}/post")
        check("올릴 곳(poster) 없으면 503", r.status == 503)

    # 📤 올리기 경로 — 가짜 poster
    posted = []

    async def poster(doc):
        posted.append(doc["_id"])
        return (False, "실패 연습") if len(posted) == 1 else (True, "#작전 에 1장 올렸어요")

    async with TestClient(TestServer(cog.build_web_app(page, lambda: None, poster=poster))) as c:
        r = await c.post(f"/api/board/e/{tok}/post"); j = await r.json()
        check("올리기 실패는 400 + 안내", r.status == 400 and j["error"] == "실패 연습")
        r = await c.post(f"/api/board/e/{tok}/post"); j = await r.json()
        check("실패한 뒤엔 바로 다시 시도 가능 → 성공", r.status == 200 and j["ok"] and "올렸어요" in j["message"])
        r = await c.post(f"/api/board/e/{tok}/post"); j = await r.json()
        check("성공 뒤 30초 안엔 429", r.status == 429 and "초 뒤" in j["error"])
        r = await c.post(f"/api/board/v/{vid}/post")
        check("보기 링크로는 못 올림", r.status in (404, 405))
        r = await c.post("/api/board/e/없는토큰/post")
        check("없는 편집 링크 404", r.status == 404)
        r = await c.post(f"/api/board/e/{tok}/invite")
        check("초대할 곳(inviter) 없으면 503", r.status == 503)

    print("[3-1] 👥 실시간 — 같이 보기·같이 그리기·피드백")
    from utils import tactics_live as tl
    tl.NOTE_GAP = 0.0          # 테스트에선 메모를 연달아 남겨요
    tl.SAVE_DELAY = 0.05
    noted = []
    hub = tl.Hub(on_note=lambda room, note: noted.append((room.view_id, note["uid"], note["text"])))

    async def namer(uid):
        return {"1": "주인", "20": "친구", "30": "코치"}.get(str(uid), "멤버")

    invited = []

    async def inviter(doc):
        invited.append(doc["_id"])
        return True, "#작전 에 초대 글을 올렸어요"

    lv, ltok = await fake_create(1, "ascent", "같이 그리는 판", 555)
    pass_c, pass_f = tc.make_pass(lv, 20, "c"), tc.make_pass(lv, 30, "f")
    app = cog.build_web_app(page, lambda: None, poster=poster, inviter=inviter, namer=namer, hub=hub)
    async with TestClient(TestServer(app)) as c:
        r = await c.get(f"/c/{lv}/{pass_c}")
        check("같이 그리기 화면 200", r.status == 200 and "text/html" in r.headers["Content-Type"])
        r = await c.get(f"/api/board/c/{lv}/{pass_c}"); j = await r.json()
        check("같이 그리기 통행증: 고칠 수 있음", r.status == 200 and j["role"] == "c" and j["editable"] is True and j["by"] == tc.by_of(20))
        r = await c.get(f"/api/board/f/{lv}/{pass_f}"); j = await r.json()
        check("피드백 통행증: 못 고침(메모만)", r.status == 200 and j["role"] == "f" and j["editable"] is False)
        check("응답에 편집 토큰·디스코드 ID 없음", ltok not in await r.text() and '"uid"' not in await r.text())
        r = await c.get(f"/api/board/c/{lv}/{pass_f}")
        check("피드백 통행증으로 같이 그리기 경로는 404", r.status == 404)
        r = await c.get(f"/api/board/f/{lv}/{tc.make_pass('다른판', 30, 'f')}")
        check("다른 판의 통행증은 404", r.status == 404)
        r = await c.get(f"/ws/c/{lv}/위조.c.ffff.sig")
        check("위조 통행증은 연결 전에 404", r.status == 404)
        r = await c.get("/ws/v/없는판")
        check("없는 판은 연결 전에 404", r.status == 404)

        we = await c.ws_connect(f"/ws/e/{ltok}")
        i_e = await recv(we, "init")
        check("주인 연결: init(역할 e·이름)", i_e and i_e["me"]["role"] == "e" and i_e["me"]["name"] == "주인" and i_e["reset"] is False)
        sid = i_e["data"]["scenes"][0]["sid"]
        check("예전 판에도 장면 sid가 붙어 옴", tc._valid_id(sid))
        wc = await c.ws_connect(f"/ws/c/{lv}/{pass_c}")
        i_c = await recv(wc, "init")
        check("같이 그리는 사람: init + 참가자 2명", i_c and i_c["me"]["role"] == "c" and i_c["me"]["name"] == "친구" and len(i_c["who"]) == 2)
        w = await recv(we, "who")
        check("먼저 있던 사람에게 참가 알림", w and [p["name"] for p in w["list"]] == ["주인", "친구"])
        wf = await c.ws_connect(f"/ws/f/{lv}/{pass_f}")
        i_f = await recv(wf, "init")
        wv = await c.ws_connect(f"/ws/v/{lv}")
        i_v = await recv(wv, "init")
        check("보기 링크: 이름 없이 보는 사람 수만", i_v and i_v["me"]["role"] == "v" and i_v["viewers"] == 1 and len(i_v["who"]) == 3)
        check("참가자 목록에 디스코드 ID 없음", "uid" not in json.dumps(i_v) and '"20"' not in json.dumps(i_v))

        item = {"id": "it1", "type": "ability", "agent": "o", "slot": "E", "team": "ally", "u": 0.4, "v": 0.4}
        await we.send_json({"t": "ops", "n": 1, "ops": [{"t": "add", "sid": sid, "item": item}]})
        a = await recv(we, "ack")
        o_c, o_f, o_v = await recv(wc, "ops"), await recv(wf, "ops"), await recv(wv, "ops")
        check("주인이 놓으면 본인은 확인(ack)만", a == {"t": "ack", "n": 1})
        check("다른 사람 모두에게 바로 보임", all(o and o["ops"][0]["item"]["id"] == "it1" for o in (o_c, o_f, o_v)))
        await wc.send_json({"t": "ops", "n": 1, "ops": [{"t": "upd", "sid": sid, "item": {**item, "u": 0.7}}]})
        o_e = await recv(we, "ops")
        check("같이 그리는 사람이 고친 것도 주인에게 보임", o_e and o_e["ops"][0]["t"] == "upd" and o_e["ops"][0]["item"]["u"] == 0.7)
        await recv(wc, "ack")
        for w2 in (wf, wv):       # 지금까지 온 것 비우기
            await recv(w2, "ops")
        await wv.send_json({"t": "ops", "n": 1, "ops": [{"t": "del", "sid": sid, "id": "it1"}]})
        await wf.send_json({"t": "ops", "n": 1, "ops": [{"t": "del", "sid": sid, "id": "it1"}]})
        check("보기·피드백 링크는 못 고침", await quiet(we, "ops") and len(hub.room(lv).state["data"]["scenes"][0]["items"]) == 1)
        r = await c.get(f"/api/board/v/{lv}"); j = await r.json()
        check("저장 전에도 보기 링크는 최신 상태", j["data"]["scenes"][0]["items"][0]["u"] == 0.7)
        await asyncio.sleep(0.25)
        check("잠시 뒤 자동 저장", store[lv]["data"]["scenes"][0]["items"][0]["u"] == 0.7 and lv in saved)

        await we.send_json({"t": "ops", "n": 2, "ops": [{"t": "add", "sid": sid, "item": {"type": "agent", "u": 0.1, "v": 0.1}}]})
        re_ = await recv(we, "init")
        check("거절된 연산 → 보낸 사람 화면을 서버 상태로(reset)", re_ and re_["reset"] is True and len(re_["data"]["scenes"][0]["items"]) == 1)
        await we.send_str("이건 JSON이 아님")
        await we.send_json({"t": "ops", "n": 3, "ops": [{"t": "stitle", "sid": sid, "title": "진입"}]})
        check("이상한 메시지가 와도 연결은 그대로", (await recv(we, "ack")) == {"t": "ack", "n": 3})

        await wf.send_json({"t": "nadd", "note": {"id": "note1", "sid": sid, "u": 0.3, "v": 0.3, "text": "여기 연막 먼저"}})
        n_all = [await recv(x, "nadd") for x in (we, wc, wf, wv)]
        check("피드백 메모는 모두에게(쓴 사람 포함)", all(n and n["note"]["text"] == "여기 연막 먼저" and n["note"]["name"] == "코치" for n in n_all))
        check("메모에 디스코드 ID 대신 by", "uid" not in n_all[0]["note"] and n_all[0]["note"]["by"] == i_f["me"]["by"])
        check("남이 남기면 주인에게 알릴 거리(on_note)", noted == [(lv, "30", "여기 연막 먼저")])
        await we.send_json({"t": "nadd", "note": {"id": "note2", "sid": sid, "u": 0.3, "v": 0.3, "text": "내 메모"}})
        for x in (we, wc, wf, wv):
            await recv(x, "nadd")
        check("주인이 자기 판에 남긴 메모는 알리지 않음", len(noted) == 1)
        await wv.send_json({"t": "nadd", "note": {"id": "note3", "sid": sid, "u": 0.3, "v": 0.3, "text": "익명"}})
        check("보기 링크로는 메모 못 남김", await quiet(we, "nadd") and len(hub.room(lv).state["notes"]) == 2)
        await wc.send_json({"t": "ndel", "id": "note1"})
        check("남의 메모는 못 지움", await quiet(we, "ndel") and len(hub.room(lv).state["notes"]) == 2)
        await wf.send_json({"t": "ndel", "id": "note1"})
        d1 = await recv(we, "ndel")
        await we.send_json({"t": "ndel", "id": "note2"})
        d2 = [await recv(wv, "ndel"), await recv(wv, "ndel")]
        check("쓴 사람은 자기 메모를 지움", d1 == {"t": "ndel", "id": "note1"} and d2[1] == {"t": "ndel", "id": "note2"}
              and hub.room(lv).state["notes"] == [])

        await wc.send_json({"t": "ping", "u": 0.5, "v": 0.5})
        pg = [await recv(x, "ping") for x in (we, wf, wv)]
        check("핑은 다른 사람에게만", all(p and p["u"] == 0.5 for p in pg) and await quiet(wc, "ping"))
        await wv.send_json({"t": "ping", "u": 0.5, "v": 0.5})
        check("보기 링크는 핑 못 보냄", await quiet(we, "ping"))
        await we.send_json({"t": "at", "sid": sid})
        at = await recv(wv, "at")
        check("장면 넘김 알림(따라가기)", at and at["sid"] == sid)

        # 실시간이 끊긴 주인의 통째 저장 → 열려 있는 화면 모두 다시 받음
        body2 = {"title": "통째 저장", "data": {"side": "def", "scenes": [{"sid": sid, "items": []}]}}
        r = await c.post(f"/api/board/e/{ltok}", json=body2)
        ri = await recv(wv, "init")
        check("통째 저장이 오면 모두 reset", r.status == 200 and ri and ri["reset"] is True and ri["title"] == "통째 저장"
              and ri["data"]["scenes"][0]["items"] == [])
        r = await c.post(f"/api/board/e/{ltok}/invite"); j = await r.json()
        check("초대 글 올리기", r.status == 200 and j["ok"] and invited == [lv])
        r = await c.post(f"/api/board/e/{ltok}/invite")
        check("초대 글은 60초에 한 번", r.status == 429)
        r = await c.post(f"/api/board/e/{ltok}/post")
        check("빈 판이 아닌지 등은 poster가 판단(연결됨)", r.status in (200, 400))

        await wf.close(); await wc.close(); await wv.close()
        bye = await recv(we, "who")
        check("나가면 참가자 목록이 줄어듦", bye is not None)
        saved.clear()
        await we.send_json({"t": "ops", "n": 9, "ops": [{"t": "meta", "title": "마지막 제목"}]})
        await recv(we, "ack")
        await we.close()
        await asyncio.sleep(0.2)
        check("마지막 사람이 나가면 저장하고 방을 없앰", store[lv]["title"] == "마지막 제목" and hub.room(lv) is None and hub.count == 0)

        # 지워진 판: 모두 내보내고(4404) 다시 붙지 않게
        wd = await c.ws_connect(f"/ws/v/{lv}")
        await recv(wd, "init")
        await hub.close_room(lv, save=False)
        msg = await asyncio.wait_for(wd.receive(), 2)
        check("판이 지워지면 4404로 닫힘", msg.type.name in ("CLOSE", "CLOSING", "CLOSED") and wd.close_code == 4404)

        # 방이 꽉 참
        old_max = tl.MAX_ROOM_CONNS
        tl.MAX_ROOM_CONNS = 1
        w1 = await c.ws_connect(f"/ws/v/{lv}")
        await recv(w1, "init")
        w2 = await c.ws_connect(f"/ws/v/{lv}")
        msg = await asyncio.wait_for(w2.receive(), 2)
        check("방이 꽉 차면 1013으로 닫힘", w2.close_code == 1013)
        tl.MAX_ROOM_CONNS = old_max
        await w1.close()
    check("서버가 내려갈 때 열린 방 정리", hub.count == 0)

    print("[3-2] 🎬 경기 장면")
    from utils import tactics_match as tm

    def loc(p, team, x, y, rot=0.5):
        return {"player_puuid": p, "player_team": team, "location": {"x": x, "y": y}, "view_radians": rot}

    match = {
        "metadata": {"map": "Ascent", "mode": "Competitive", "matchid": "m-1", "game_start": 1795000000, "rounds_played": 3},
        "players": {"all_players": [
            {"puuid": "me", "name": "악귀", "tag": "KR1", "team": "Red", "character": "Omen"},
            {"puuid": "mate", "name": "B", "tag": "2", "team": "Red", "character": "Jett"},
            {"puuid": "foe", "name": "C", "tag": "3", "team": "Blue", "character": "Jett"},
            {"puuid": "new", "name": "D", "tag": "4", "team": "Blue", "character": "아직 없는 요원"}]},
        "teams": {"red": {"has_won": True, "rounds_won": 13, "rounds_lost": 7}, "blue": {"has_won": False}},
        "rounds": [
            {"winning_team": "Red", "end_type": "Eliminated",
             "plant_events": {"plant_location": {"x": 100, "y": 200}, "planted_by": {"team": "Red"}, "plant_site": "A",
                              "plant_time_in_round": 30000}},
            {"winning_team": "Blue", "end_type": "Round timer expired",
             "plant_events": {"plant_location": None, "planted_by": None, "plant_site": None, "plant_time_in_round": None}},
            {"winning_team": "Red", "end_type": "Bomb defused", "plant_events": None}],
        "kills": [
            {"round": 0, "kill_time_in_round": 45000, "killer_puuid": "foe", "victim_puuid": "me",
             "victim_death_location": {"x": 1500, "y": 2500}, "player_locations_on_kill": [
                 loc("foe", "Blue", 1000, 2000, 2.0), loc("mate", "Red", -500, 300)]},
            {"round": 0, "kill_time_in_round": 12000, "killer_puuid": "me", "victim_puuid": "new",
             "victim_death_location": {"x": 900, "y": 800}, "player_locations_on_kill": [
                 loc("me", "Red", 400, 500, 1.234567), loc("mate", "Red", -500, 300), loc("foe", "Blue", 1000, 2000)]},
            {"round": 9, "kill_time_in_round": 1, "killer_puuid": "me", "victim_puuid": "foe",
             "victim_death_location": {"x": 0, "y": 0}, "player_locations_on_kill": []},       # 없는 라운드 → 버림
            {"round": 2, "kill_time_in_round": 1, "killer_puuid": "me", "victim_puuid": "foe",
             "victim_death_location": None, "player_locations_on_kill": []}]}                  # 위치 없음 → 버림
    sm = tm.summarize(match, "악귀", "kr1")
    check("경기 요약(대소문자 무시로 내 계정 찾음)", sm and sm["map"] == "Ascent" and sm["me"] == "me" and sm["team"] == "Red"
          and sm["won"] is True and sm["score"] == (13, 7) and sm["agent"] == "Omen")
    check("킬은 라운드별·시간순, 이상한 건 버림", [k["t"] for k in sm["rounds"][0]["kills"]] == [12000, 45000]
          and sm["rounds"][1]["kills"] == [] and sm["rounds"][2]["kills"] == [])
    check("남의 계정 이름이면 None", tm.summarize(match, "없는사람", "KR1") is None)
    check("요약이 원본보다 훨씬 작음(통째로 안 들고 있음)", "player_locations_on_kill" not in json.dumps(sm))
    rs = tm.round_stats(sm, 0)
    check("라운드 한 줄 값", rs == {"won": True, "end": "전멸", "site": "A", "kills": 2, "my_kills": 1, "died": True}, rs)
    check("공격팀은 설치한 팀(없으면 가까운 라운드)", tm.attacker_team(sm, 0) == "Red" and tm.attacker_team(sm, 2) == "Red")
    made = tm.round_scenes(sm, 0, m, ag)
    check("킬마다 장면 하나", made is not None and len(made[0]["scenes"]) == 2 and made[1] == "atk")
    sc1, sc2 = made[0]["scenes"]
    check("장면 제목: 시각 + 누가→누구", sc1["title"] == "0:12 오멘→?" and sc2["title"] == "0:45 제트→오멘", (sc1["title"], sc2["title"]))
    mine = [it for it in sc1["items"] if it.get("me")]
    check("내 위치에 '나' 표시 + 시선", len(mine) == 1 and mine[0]["rot"] == 1.235 and mine[0]["team"] == "ally"
          and (mine[0]["u"], mine[0]["v"]) == tc.to_uv(m, {"x": 400, "y": 500}))
    check("적은 enemy, 아군은 ally", sorted(it["team"] for it in sc1["items"] if it["type"] == "agent") == ["ally", "ally", "enemy"])
    check("모르는 요원(신규)은 건너뜀 — 터지지 않음", not any(it.get("dead") for it in sc1["items"]))
    dead = [it for it in sc2["items"] if it.get("dead")]
    check("죽은 사람은 죽은 자리에 처치 표시", len(dead) == 1 and dead[0].get("me") is True and "rot" not in dead[0]
          and (dead[0]["u"], dead[0]["v"]) == tc.to_uv(m, {"x": 1500, "y": 2500}))
    arrows = [it for it in sc2["items"] if it["type"] == "arrow"]
    check("처치자 → 피해자 화살표(적 색)", len(arrows) == 1 and arrows[0]["team"] == "enemy" and (arrows[0]["u2"], arrows[0]["v2"]) == (dead[0]["u"], dead[0]["v"]))
    check("설치 뒤 장면에만 스파이크 표시", not any(it["type"] == "text" for it in sc1["items"])
          and [it["text"] for it in sc2["items"] if it["type"] == "text"] == ["스파이크"])
    check("만든 장면은 저장 검사를 그대로 통과(id·sid 있음)", tc.clean_data(made[0]) == made[0])
    check("킬 없는 라운드·없는 라운드는 None", tm.round_scenes(sm, 1, m, ag) is None and tm.round_scenes(sm, 99, m, ag) is None)
    many = {**sm, "rounds": [{**sm["rounds"][0], "kills": sm["rounds"][0]["kills"] * 8}]}
    check("장면은 10개까지", len(tm.round_scenes(many, 0, m, ag)[0]["scenes"]) == 10)
    blue = tm.summarize(match, "C", "3")
    check("상대 팀 입장에선 수비", tm.round_scenes(blue, 0, m, ag)[1] == "def")

    print("[3-3] 디스코드 버튼")
    import re as _re
    for act in ("fb", "fork", "join"):
        b = cog.BoardButton(act, "Ab_-cdEFgh1")
        mt = _re.fullmatch(cog.BoardButton.__discord_ui_compiled_template__, b.item.custom_id)
        if not (mt and mt["act"] == act and mt["vid"] == "Ab_-cdEFgh1"):
            check(f"올린 글 버튼 custom_id ({act})", False, b.item.custom_id)
            break
    else:
        check("올린 글 버튼 custom_id가 다시 읽힘(재시작 뒤에도 동작)", True)
    import secrets as _secrets
    check("실제 보기ID 모양도 맞음", all(_re.fullmatch(cog.BoardButton.__discord_ui_compiled_template__,
                                               f"akgui:tac:fb:{_secrets.token_urlsafe(8)}") for _ in range(200)))
    pv = cog.TacticsPanelView()
    check("패널 버튼 4개 · 꺼지지 않음", pv.timeout is None and sorted(x.custom_id for x in pv.children) == [
        "akgui:tac:lib", "akgui:tac:match", "akgui:tac:mine", "akgui:tac:new"])
    lvw = cog.links_view("viewid", "edittoken")
    check("링크 버튼", [x.url for x in lvw.children] == [f"{cog.BASE_URL}/e/edittoken", f"{cog.BASE_URL}/v/viewid"])

    print("[3-4] 디스코드 흐름 (가짜 상호작용 — 디스코드에 안 붙어요)")
    from utils import tactics_render as _tr

    async def _no_images(session, urls):
        return {}
    _tr.fetch_images = _no_images
    from datetime import datetime, timezone
    from types import SimpleNamespace

    async def fake_count(uid):
        return sum(1 for d in store.values() if d["uid"] == str(uid))

    async def fake_list(uid, limit=25):
        return [d for d in store.values() if d["uid"] == str(uid)][:limit]

    async def fake_reissue(view_id, uid):
        d = store.get(view_id)
        return tc.edit_token_for(view_id) if d and d["uid"] == str(uid) else None

    async def fake_shared_counts():
        out = {}
        for d in store.values():
            if d.get("shared_at"):
                out[d["map"]] = out.get(d["map"], 0) + 1
        return out

    async def fake_list_shared(map_key, limit=25):
        return [d for d in store.values() if d.get("shared_at") and d["map"] == map_key][:limit]

    async def fake_set_shared(view_id, channel_id, message_id):
        store[view_id]["shared_at"] = datetime.now(timezone.utc)
        store[view_id]["post"] = {"channel": str(channel_id), "msg": str(message_id)}

    async def fake_unshare(view_id, uid):
        return store[view_id].pop("shared_at", None) is not None

    async def fake_delete(view_id, uid):
        d = store.get(view_id)
        if d and d["uid"] == str(uid):
            del store[view_id]
            return True
        return False

    tc.count_boards, tc.list_boards, tc.reissue_edit_token = fake_count, fake_list, fake_reissue
    tc.shared_counts, tc.list_shared, tc.set_shared = fake_shared_counts, fake_list_shared, fake_set_shared
    tc.unshare, tc.delete_board = fake_unshare, fake_delete

    class FakeChannel:
        id, name, mention = 555, "작전", "#작전"

        def __init__(self):
            self.sent = []

        async def send(self, content=None, **kw):
            self.sent.append((content, kw))
            return SimpleNamespace(id=9000 + len(self.sent))

    class FakeIt:
        """상호작용 흉내 — 무엇을 보냈는지만 모아요."""

        def __init__(self, uid):
            self.user = SimpleNamespace(id=uid)
            self.channel_id, self.guild_id, self.channel = 555, 777, None
            self.out = []
            self.followup = SimpleNamespace(send=self._followup)
            self.response = SimpleNamespace(defer=self._defer)

        async def _defer(self, **kw):
            return None

        async def _followup(self, content=None, **kw):
            self.out.append({"content": content, **kw})

        async def edit_original_response(self, **kw):
            self.out.append(kw)

        @property
        def last(self):
            return self.out[-1]

    def urls_of(view):
        return [x.url for x in view.children if getattr(x, "url", None)]

    def button(view, label):
        return next(x for x in view.children if getattr(x, "label", None) == label)

    def ids_of(view):
        return [x.custom_id for x in view.children if getattr(x, "custom_id", None) and x.custom_id.startswith("akgui:")]

    chan = FakeChannel()
    bot = SimpleNamespace(guilds=[], get_user=lambda uid: None, get_channel=lambda cid: None)
    inst = cog.Tactics(bot)
    inst._text_channel = lambda cid: chan if cid else None
    before = set(store)

    it = FakeIt(1)
    await inst.show_new(it)
    check("새 작전판: 맵 고르기 화면", "맵" in it.last["content"] and isinstance(it.last["view"], cog.PickView))
    await it.last["view"].on_pick(it, "ascent")
    made_id = (set(store) - before).pop()
    check("맵을 고르면 판이 생기고 편집·보기 링크", urls_of(it.last["view"]) == [
        f"{cog.BASE_URL}/e/{tc.edit_token_for(made_id)}", f"{cog.BASE_URL}/v/{made_id}"] and store[made_id]["channel"] == "555")
    await inst.create_and_reply(it, "없는맵", None, edit=False)
    check("없는 맵은 안내만", "못 찾았어요" in it.last["content"])
    old_cap = tc.MAX_BOARDS_PER_USER
    tc.MAX_BOARDS_PER_USER = 1
    n_before = len(store)
    await inst.create_and_reply(it, "ascent", None, edit=False)
    check("한 사람 한도를 넘으면 안 만듦", len(store) == n_before and "까지" in it.last["content"])
    tc.MAX_BOARDS_PER_USER = old_cap

    store[made_id]["data"] = tc.clean_data({"scenes": [{"items": [
        {"type": "ability", "agent": "o", "slot": "E", "team": "ally", "u": 0.4, "v": 0.4}]}]})
    ok_post, msg_post = await inst.post_board(store[made_id])
    content, kw = chan.sent[-1]
    check("📤 올리기: 그림 + 버튼(보기·피드백·복사) + 모음에 실림", ok_post and len(kw["files"]) == 1 and "<@1>" in content
          and ids_of(kw["view"]) == [f"akgui:tac:fb:{made_id}", f"akgui:tac:fork:{made_id}"]
          and urls_of(kw["view"]) == [f"{cog.BASE_URL}/v/{made_id}"] and store[made_id].get("shared_at") is not None, msg_post)
    check("올린 글은 아무도 부르지 않음(멘션 꺼짐)", kw["allowed_mentions"].users is False and kw["allowed_mentions"].everyone is False)
    empty_id, _ = await fake_create(1, "ascent", "빈 판", 555)
    ok_e, msg_e = await inst.post_board(store[empty_id])
    check("빈 판은 안 올림", ok_e is False and "빈 작전판" in msg_e)
    ok_n, msg_n = await inst.post_board({**store[made_id], "channel": None})
    check("올릴 채널이 없으면 안내", ok_n is False and "채널" in msg_n)

    it2 = FakeIt(20)
    await inst.act_feedback(it2, made_id)
    fb_url = urls_of(it2.last["view"])[0]
    check("피드백 버튼: 누른 사람의 개인 링크", fb_url.startswith(f"{cog.BASE_URL}/f/{made_id}/")
          and tc.check_pass(made_id, fb_url.rsplit("/", 1)[1]) == ("20", "f") and it2.last["ephemeral"] is True)
    await inst.act_join(it2, made_id)
    j_url = urls_of(it2.last["view"])[0]
    check("같이 그리기 버튼: 12시간 개인 링크", tc.check_pass(made_id, j_url.rsplit("/", 1)[1]) == ("20", "c") and "/c/" in j_url)
    it1 = FakeIt(1)
    await inst.act_feedback(it1, made_id)
    check("만든 사람이 누르면 편집 링크", urls_of(it1.last["view"])[0] == f"{cog.BASE_URL}/e/{tc.edit_token_for(made_id)}")
    await inst.act_feedback(it2, "없는판아이디")
    check("지워진 판의 버튼은 안내만", "지워진" in it2.last["content"])
    n_before = set(store)
    await inst.act_fork(it2, made_id)
    fork_id = (set(store) - n_before).pop()
    fk = store[fork_id]
    check("복사해서 고치기: 내 판으로 복사(원본 표시, 메모는 안 따라감)", fk["uid"] == "20" and fk["forked_from"] == made_id
          and fk["forked_uid"] == "1" and fk["title"].endswith("수정안") and fk["notes"] == []
          and len(fk["data"]["scenes"][0]["items"]) == 1 and fk["data"] is not store[made_id]["data"])
    await inst.post_board(fk)
    check("수정안을 올리면 누구 판의 수정안인지 표시", "수정안" in chan.sent[-1][0] and "<@1>" in chan.sent[-1][0] and "<@20>" in chan.sent[-1][0])

    await inst.show_mine(it)
    opts = it.last["view"].children[0].options
    check("내 작전판: 내 것만 목록에", {o.value for o in opts} == {k for k, d in store.items() if d["uid"] == "1"} and fork_id not in {o.value for o in opts})
    await it.last["view"].on_pick(it, made_id)
    dv = it.last["view"]
    check("내 작전판 상세: 편집 링크 다시 받기", urls_of(dv)[0] == f"{cog.BASE_URL}/e/{tc.edit_token_for(made_id)}"
          and "모음에 실려" in it.last["embed"].description)
    await inst.mine_detail(it2, made_id)
    check("남의 판은 편집 링크를 못 받음", "없는 작전판" in (it2.last.get("content") or ""))
    n_sent = len(chan.sent)
    await button(dv, "같이 그리기 초대").callback(it)
    check("같이 그리기 초대 글(버튼 포함)", len(chan.sent) == n_sent + 1 and ids_of(chan.sent[-1][1]["view"]) == [f"akgui:tac:join:{made_id}"])
    ok_i, msg_i = await inst.post_invite(store[made_id])
    check("초대 글은 60초에 한 번", ok_i is False and "초 뒤" in msg_i)
    await button(dv, "모음에서 내리기").callback(it)
    check("모음에서 내리기", "shared_at" not in store[made_id] and "내렸어요" in it.last["embed"].description)
    await button(it.last["view"], "삭제").callback(it)
    check("삭제는 한 번 더 물어봄", made_id in store and "지울까요" in it.last["content"])
    await button(it.last["view"], "취소").callback(it)
    check("취소하면 그대로", made_id in store and it.last["embed"] is not None)
    await button(it.last["view"], "삭제").callback(it)
    await button(it.last["view"], "정말 삭제").callback(it)
    check("정말 삭제하면 지워지고 목록으로", made_id not in store and "내 작전판" in (it.last.get("content") or ""))

    await inst.show_library(it2)
    lib_opts = it2.last["view"].children[0].options
    check("작전 모음: 맵별 개수", [o.label for o in lib_opts] == ["어센트 (1)"], [o.label for o in lib_opts])
    await it2.last["view"].on_pick(it2, "ascent")
    check("모음 → 그 맵의 작전 목록", [o.value for o in it2.last["view"].children[0].options] == [fork_id])
    await it2.last["view"].on_pick(it2, fork_id)
    check("모음 상세: 보기·올린 글·피드백·복사", ids_of(it2.last["view"]) == [f"akgui:tac:fb:{fork_id}", f"akgui:tac:fork:{fork_id}"]
          and urls_of(it2.last["view"])[0] == f"{cog.BASE_URL}/v/{fork_id}" and "discord.com/channels/777/555/" in urls_of(it2.last["view"])[1])
    store[fork_id].pop("shared_at")
    await inst.show_library(it2)
    check("올라온 게 없으면 안내", "아직 올라온 작전이 없어요" in it2.last["content"])

    # 💬 메모 알림(올린 글에 답글)
    store[fork_id]["post"] = {"channel": "555", "msg": "9001"}
    n_sent = len(chan.sent)
    await inst._announce_note(fork_id, "20", "수정안", {"name": "코치*", "text": "여기 @everyone 연막", "uid": "30"})
    content, kw = chan.sent[-1]
    check("메모 알림: 만든 사람만 부르고 올린 글에 답글", len(chan.sent) == n_sent + 1 and "<@20>" in content and "코치\\*" in content
          and kw["reference"].message_id == 9001 and kw["allowed_mentions"].everyone is False
          and [u.id for u in kw["allowed_mentions"].users] == [20])
    fake_room = SimpleNamespace(view_id=fork_id, owner="20", state={"title": "수정안"})
    inst.note_posted(fake_room, {"uid": "30", "name": "코치", "text": "첫 메모"})
    inst.note_posted(fake_room, {"uid": "30", "name": "코치", "text": "둘째 메모"})
    await asyncio.sleep(0.05)
    check("같은 사람·같은 판은 10분에 한 번만 알림", len(chan.sent) == n_sent + 2)

    # 🎬 내 경기 장면
    os.environ["HENRIKDEV_API_KEY"] = "test-key"
    calls = []

    async def fake_henrik(session, path, *, headers, params=None, cache_ttl=60, **kw):
        calls.append((path, params, cache_ttl))
        return 200, {"data": [match, "이상한 값", {**match, "metadata": {**match["metadata"], "map": "없는맵"}}]}

    cog.henrik_api.request = fake_henrik
    cog.riot_account_store.get_account = lambda uid: ("악귀", "KR1") if uid == 1 else None
    cog.riot_account_store.get_region = lambda uid: None
    await inst.show_matches(it2)
    check("계정 연동이 없으면 안내", "계정등록" in it2.last["content"])
    await inst.show_matches(it)
    mo = it.last["view"].children[0].options
    check("경기 목록: 맵·모드·점수·승패 (모르는 맵은 빠짐)", len(mo) == 1 and mo[0].label == "어센트 · 경쟁 · 13:7 승" and "오멘" in mo[0].description, [o.label for o in mo])
    check("전적은 공용 창구로, 캐시에 안 남김", calls == [("/valorant/v3/matches/kr/악귀/KR1", {"size": cog.MATCH_SIZE}, 0)], calls)
    await it.last["view"].on_pick(it, "0")
    ro = it.last["view"].children[0].options
    check("라운드 목록: 킬 있는 라운드만", [o.value for o in ro] == ["0"] and ro[0].label == "1라운드 · 승 · 전멸 · A 설치"
          and ro[0].description == "킬 2번 · 내 킬 1 · 내가 죽음", [(o.label, o.description) for o in ro])
    n_before = set(store)
    await it.last["view"].on_pick(it, "0")
    mid = (set(store) - n_before).pop()
    check("라운드를 고르면 장면이 든 판이 생김", store[mid]["title"] == "어센트 1라운드 복기" and len(store[mid]["data"]["scenes"]) == 2
          and store[mid]["source"] == {"match": "m-1", "round": 0} and len(urls_of(it.last["view"])) == 2)

    async def henrik_429(session, path, **kw):
        return 429, {cog.henrik_api.RETRY_AFTER_KEY: 42}
    cog.henrik_api.request = henrik_429
    await inst.show_matches(it)
    check("전적 서버가 바쁘면 몇 초 뒤인지 안내", "42초" in it.last["content"])
    check("이름 찾기: 모르는 사람은 '멤버'", await inst.member_name("abc") == "멤버" and await inst.member_name(12345) == "멤버")

    # `/작전판`(맵 없이) 메뉴 — 명령어를 늘리지 않으려고(전역 100개 한도) 내 작전판·패널 박기를 여기 모았어요
    def labels(view):
        return [x.label for x in view.children]

    import discord

    class FakeText(discord.TextChannel):       # isinstance 검사만 지나가면 돼요
        def __init__(self):
            self.sent, self.id = [], 555

        @property
        def mention(self):
            return "#작전"

        async def send(self, content=None, **kw):
            self.sent.append((content, kw))
            return SimpleNamespace(id=7000 + len(self.sent))

    panel_store = {}
    cog.settings_store.get_setting = lambda key: panel_store.get(key)
    cog.settings_store.set_setting = lambda key, value: panel_store.__setitem__(key, value)
    it_m = FakeIt(20)
    it_m.guild = SimpleNamespace(owner_id=1)
    await inst.show_menu(it_m)
    check("/작전판 메뉴: 버튼 4개 (소유자가 아니면 패널 박기 없음)", labels(it_m.last["view"]) == ["새 작전판", "내 작전판", "작전 모음", "내 경기 장면"]
          and it_m.last["ephemeral"] is True and it_m.last["embed"] is not None, labels(it_m.last["view"]))
    it_o = FakeIt(1)
    it_o.guild = SimpleNamespace(owner_id=1)
    it_o.channel = FakeText()
    await inst.show_menu(it_o)
    check("서버 소유자에게만 📌 패널 박기", labels(it_o.last["view"])[-1] == "이 채널에 패널 박기" and len(it_o.last["view"].children) == 5)
    await button(it_o.last["view"], "내 작전판").callback(it_o)
    check("메뉴의 내 작전판 버튼이 목록을 엶", isinstance(it_o.last.get("view"), cog.PickView) or "작전판" in (it_o.last.get("content") or ""))
    await inst.post_panel(it_o)
    p_content, p_kw = it_o.channel.sent[-1]
    check("패널 박기: 상설 패널(버튼 4개)을 올리고 위치를 기억", ids_of(p_kw["view"]) == ["akgui:tac:new", "akgui:tac:mine", "akgui:tac:lib", "akgui:tac:match"]
          and panel_store[cog.KEY_PANEL] == {"channel": 555, "message": 7001} and "올렸어요" in it_o.last["content"])
    it_m.channel = FakeText()
    await inst.post_panel(it_m)
    check("소유자가 아니면 패널을 못 올림", it_m.channel.sent == [] and "소유자만" in it_m.last["content"])
    board_cmd = inst.board
    check("슬래시 명령어는 /작전판 하나, 맵은 비워도 됨", [c.name for c in inst.get_app_commands()] == ["작전판"]
          and not next(p for p in board_cmd.parameters if p.name == "맵").required)

    print("[4] 그림 그리기")
    from utils import tactics_render as tr

    async def no_images(session, urls):
        return {}
    tr.fetch_images = no_images
    agents_by = {a["id"]: a for a in ag}
    # 하버 만조(곡선) 흉내를 위해 오멘 Q에 path 모양을 잠시 씌워요
    items = [
        {"type": "ability", "agent": "o", "slot": "E", "team": "ally", "u": 0.5, "v": 0.5},
        {"type": "ability", "agent": "o", "slot": "E", "team": "enemy", "u": 0.2, "v": 0.2, "u2": 0.3, "v2": 0.35,
         "pts": [[0.2, 0.2], [0.25, 0.3], [0.3, 0.35]]},
        {"type": "ability", "agent": "o", "slot": "Q", "team": "ally", "u": 0.6, "v": 0.6},
        {"type": "agent", "agent": "o", "team": "ally", "u": 0.4, "v": 0.7},
        {"type": "arrow", "team": "ally", "u": 0.1, "v": 0.9, "u2": 0.3, "v2": 0.8, "pts": [[0.1, 0.9], [0.2, 0.95], [0.3, 0.8]]},
        {"type": "text", "team": "enemy", "u": 0.5, "v": 0.1, "text": "여기 연막 🔥 두 개"},
        {"type": "ability", "agent": "없는요원", "slot": "Q", "team": "ally", "u": 0.7, "v": 0.7},
    ]
    jpg = tr.render_scene(mapinfo=m, agents=agents_by, images={}, items=items, title="A 공격 🗺️", subtitle="어센트 · 공격")
    check("그림이 JPEG", jpg[:3] == b"\xff\xd8\xff" and len(jpg) > 10_000)
    from PIL import Image
    import io as _io
    im = Image.open(_io.BytesIO(jpg))
    check("크기 1000×1064", im.size == (1000, 1000 + tr.HEAD_PX), im.size)
    check("이모지는 걸러냄", tr._clean("여기 연막 🔥 두 개") == "여기 연막  두 개")
    check("곡선 점은 촘촘히", len(tr.smooth_points([[0, 0], [0.5, 0.5], [1, 0]])) > 10)
    plain = [{"type": "agent", "agent": "o", "team": "ally", "u": 0.5, "v": 0.5}]
    base_img = Image.open(_io.BytesIO(tr.render_scene(mapinfo=m, agents=agents_by, images={}, items=plain, title="t")))

    def changed_px(extra):
        im2 = Image.open(_io.BytesIO(tr.render_scene(mapinfo=m, agents=agents_by, images={}, title="t",
                                                     items=[{**plain[0], **extra}])))
        from PIL import ImageChops
        box = ImageChops.difference(base_img.convert("RGB"), im2.convert("RGB")).point(lambda p: 255 if p > 40 else 0).getbbox()
        return box
    check("경기 장면: 시선 화살촉이 그려짐", changed_px({"rot": 0.0}) is not None)
    check("경기 장면: '나' 테두리가 그려짐", changed_px({"me": True}) is not None)
    check("경기 장면: 처치 표시가 그려짐", changed_px({"dead": True}) is not None)
    up = changed_px({"rot": 0.0})          # rot 0 → 시선 (sin0, −cos0) = 위쪽
    check("시선 0은 위쪽", up is not None and up[3] <= 500 + tr.HEAD_PX, up)

    doc = {"_id": vid, "map": "ascent", "title": "A 공격", "uid": "1",
           "data": {"side": "def", "scenes": [{"title": "진입 전", "items": items}, {"title": "", "items": []},
                                              {"title": "설치 후", "items": items[:2]}]}}
    imgs = await cog.render_board_images(None, doc)
    check("빈 장면은 건너뛰고 2장", [n for n, _ in imgs] == ["tactics_1.jpg", "tactics_3.jpg"], [n for n, _ in imgs])
    doc["map"] = "없는맵"
    check("없는 맵이면 0장", await cog.render_board_images(None, doc) == [])


asyncio.run(run())

print()
if failed:
    print(f"❌ 실패 {len(failed)}개: {failed}")
    sys.exit(1)
print("✅ 웹 전술판 테스트 전부 통과")
