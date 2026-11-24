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

print("[3] 웹 경로")
store: dict = {}


async def fake_create(uid, map_key, title, channel_id=None):
    vid, tok = f"v{len(store)}", f"tok{len(store)}"
    store[vid] = {"_id": vid, "edit_hash": tc._hash(tok), "map": map_key, "title": title,
                  "uid": str(uid), "channel": str(channel_id) if channel_id else None,
                  "data": {"scenes": [{"title": "", "items": []}], "side": "atk"}}
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


async def fake_maps(s):
    return {"ascent": m}


async def fake_agents(s):
    return ag

tc.create_board, tc.get_board, tc.save_board = fake_create, fake_get, fake_save
tc.maps, tc.agents = fake_maps, fake_agents


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
