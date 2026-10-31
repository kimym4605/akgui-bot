# -*- coding: utf-8 -*-
"""🔊 방 패널 테스트 (2026-10-31).

디스코드에 접속하지 않아요 — 패널 구조와 **응답 규약**만 봐요.

🚨🚨 **가장 중요한 검사는 "패널이 defer하지 않는가"예요.**
   `DynamicRoomEngine`의 메서드들은 **자기 안에서** `interaction.response.defer()`를
   해요. 패널에서 미리 defer하면 `InteractionResponded`로 터져요
   (🎴 카드 패널은 정반대로 defer가 먼저여야 해요 — 섞이면 한쪽이 죽어요).

실행: python scripts/test_room_panel.py   (종료코드 0 = 전부 통과)
🚨 종료코드는 **파이프 없이** 재세요.
"""
import ast
import asyncio
import inspect
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv                 # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

import discord                                  # noqa: E402
from discord.ext import commands                # noqa: E402

from cogs.room import ROOM_KINDS                # noqa: E402
from utils import room_panel                    # noqa: E402
from utils.dynamic_room import DynamicRoomEngine    # noqa: E402

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


# engine을 가짜 bot으로 하나 만들어요(네트워크를 안 써요).
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
engine = DynamicRoomEngine(bot, ROOM_KINDS)
view = room_panel.RoomPanelView(engine, ROOM_KINDS)

print("\n[1] 🚨🚨 패널이 defer하지 않는다 (engine이 스스로 defer한다)")
src = open(os.path.join(BOT_DIR, "utils", "room_panel.py"), encoding="utf-8").read()
tree = ast.parse(src)
# engine을 부르는 콜백에 defer가 있으면 안 돼요.
ENGINE_CALLS = ("create_room", "invite", "request_join", "transfer_owner", "close_room")
offenders = []
for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
    body = ast.unparse(fn)
    calls_engine = any(f".{m}(" in body for m in ENGINE_CALLS)
    if calls_engine and "response.defer" in body:
        offenders.append(fn.name)
check(not offenders,
      "engine을 부르는 콜백에 defer가 없다", f"defer가 있는 콜백: {offenders}")

# 반대로 engine 쪽은 정말 스스로 defer하는지 — 전제가 바뀌면 이 테스트가 무의미해져요.
for m in ENGINE_CALLS:
    body = inspect.getsource(getattr(DynamicRoomEngine, m))
    check("response.defer" in body,
          f"engine.{m}가 스스로 defer한다 (전제 확인)",
          "engine이 defer를 안 하면 패널도 defer를 해야 한다")

print("\n[2] 영속 뷰 3요소")
check(view.timeout is None, "① timeout=None", str(view.timeout))
ids = [getattr(i, "custom_id", None) for i in view.children]
check(all(ids), "② 모든 항목에 custom_id", str(ids))
check(len(set(ids)) == len(ids), "custom_id가 전부 고유", str(ids))
check(all(str(i).startswith("akgui:room:") for i in ids),
      "custom_id가 akgui:room: 으로 시작", str(ids))
room_src = open(os.path.join(BOT_DIR, "cogs", "room.py"), encoding="utf-8").read()
check("self.bot.add_view(RoomPanelView(" in room_src,
      "③ cog_load에서 add_view (없으면 재시작 뒤 조용히 죽는다)")
try:
    bot.add_view(view)
    check(True, "bot.add_view가 받아들인다")
except Exception as exc:                        # noqa: BLE001
    check(False, "bot.add_view가 받아들인다", f"{type(exc).__name__}: {exc}")

print("\n[3] 레이아웃 — 디스코드 한도(5줄 · 줄당 버튼 5개)")
rows = view.to_components()
shapes = []
for i, row in enumerate(rows):
    kinds = [c.get("type") for c in row.get("components", [])]
    shapes.append(f"{i}:{len(kinds)}개")
    check(len(kinds) <= 5, f"{i}번째 줄 {len(kinds)}개 (5개 이하)")
    check(not (3 in kinds and len(kinds) > 1),
          f"{i}번째 줄에 드롭다운과 버튼이 안 섞임", str(kinds))
check(len(rows) <= 5, f"{len(rows)}줄 (5줄 이하)", str(shapes))
print(f"     레이아웃: {len(rows)}줄 ({', '.join(shapes)})")

print("\n[4] 🚨 방 종류를 손으로 늘어놓지 않는다 (ROOM_KINDS에서 만든다)")
new_btns = [i for i in view.children if str(getattr(i, "custom_id", "")).startswith("akgui:room:new:")]
check(len(new_btns) == len(ROOM_KINDS),
      f"종류 버튼이 {len(ROOM_KINDS)}개 (ROOM_KINDS와 같다)", str(len(new_btns)))
for key, cfg in ROOM_KINDS.items():
    btn = next((b for b in new_btns if b.custom_id.endswith(f":{key}")), None)
    check(btn is not None and btn.label == cfg["label"],
          f"{cfg['emoji']} {cfg['label']} 버튼이 라벨까지 일치",
          f"{btn.label if btn else '없음'} vs {cfg['label']}")
panel_fn = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "panel_embed")
ptxt = ast.unparse(panel_fn)
check("room_kinds" in ptxt, "패널 설명도 ROOM_KINDS에서 만든다")
for cfg in ROOM_KINDS.values():
    check(cfg["label"] not in ptxt, f"설명에 '{cfg['label']}'을 손으로 안 박았다")
# 🚨 choice_name은 label을 이미 품고 있어서 그대로 쓰면 이름이 두 번 나온다
#    ("랭크방 - 랭크방 (게임 랭크용)"). 2026-10-31 게시 미리보기에서 잡았다.
rendered = room_panel.panel_embed(ROOM_KINDS).description
for cfg in ROOM_KINDS.values():
    check(rendered.count(cfg["label"]) == 1,
          f"'{cfg['label']}'이 설명에 한 번만 나온다",
          f"{rendered.count(cfg['label'])}번")

print("\n[5] 관리 버튼 — 사람을 골라야 하는 것은 UserSelect로 받는다")
labels = {i.custom_id: getattr(i, "label", "") for i in view.children}
for cid in ("akgui:room:invite", "akgui:room:request",
            "akgui:room:transfer", "akgui:room:close", "akgui:room:options"):
    check(cid in labels, f"{cid} 버튼이 있다")
pick = room_panel._PickMemberView(engine, "invite", "테스트")
check(any(isinstance(i, discord.ui.UserSelect) for i in pick.children),
      "초대/신청/넘기기는 UserSelect를 띄운다")
check(pick.timeout is not None,
      "그 뷰는 **일회용**이다 (영속이 아니라 self에 상태를 담아도 안전)", str(pick.timeout))

print("\n[6] ⚙️ 상세 설정 — 종류를 안 고르면 engine을 부르지 않는다")
opts = room_panel._OptionsView(engine, ROOM_KINDS)
check(opts.kind is None, "처음엔 종류가 안 골라져 있다")
create_fn = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "create")
ctxt = ast.unparse(create_fn)
check("if self.kind is None" in ctxt,
      "🚨 종류가 None이면 막는다 (안 막으면 KeyError로 터진다)")
idx_guard = ctxt.find("self.kind is None")
idx_call = ctxt.find("create_room")
check(0 <= idx_guard < idx_call, "그 검사가 engine 호출보다 **앞에** 있다",
      f"guard={idx_guard} call={idx_call}")
check(len(room_panel.CAPACITY_CHOICES) + 1 <= 25,
      f"정원 드롭다운 {len(room_panel.CAPACITY_CHOICES) + 1}개 (한도 25개 안)")
sel = next(i for i in opts.children if isinstance(i, discord.ui.Select)
           and "인원" in (i.placeholder or ""))
check(any(o.value == "0" for o in sel.options), "무제한 선택지가 있다")

print("\n[7] 🚨 모달을 쓰지 않는다 (모달엔 드롭다운이 안 들어간다)")
# 🚨 **글자로 찾으면 안 돼요** — docstring에 "모달(`send_modal`)로는 못 해요"라고
#    적어둔 설명이 걸려서 **거짓 실패**가 났어요(2026-10-31에 실제로 당했어요).
#    반대 방향 사고(글자 검사가 docstring에 걸려 **거짓 통과**)도 전례가 있어요.
#    → [[feedback_loose_assertions_false_pass]] ③
#    그래서 **AST로 실제 호출만** 봐요.
modal_calls = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == "send_modal"]
modal_classes = [n.name for n in ast.walk(tree)
                 if isinstance(n, ast.ClassDef)
                 and any("Modal" in ast.unparse(b) for b in n.bases)]
check(not modal_calls and not modal_classes,
      "send_modal 호출도 Modal 클래스도 없다 — 종류를 글자로 받으면 오타가 바로 실패가 된다",
      f"호출 {len(modal_calls)}개 · 클래스 {modal_classes}")

print("\n[8] ⭐ 채널별 패널 — 그 종류만 보여준다 (2026-10-31 사용자 결정)")
for key, cfg in ROOM_KINDS.items():
    one = room_panel.RoomPanelView(engine, ROOM_KINDS, [key])
    news = [i for i in one.children
            if str(getattr(i, "custom_id", "")).startswith("akgui:room:new:")]
    check(len(news) == 1 and news[0].custom_id.endswith(f":{key}"),
          f"{cfg['emoji']} {cfg['label']} 패널에 종류 버튼이 1개뿐",
          str([n.custom_id for n in news]))
    # 🚨 관리 버튼은 어느 패널에나 있어야 한다 — 자기 방 관리는 종류와 무관하다.
    ids = {str(getattr(i, "custom_id", "")) for i in one.children}
    for need in ("akgui:room:invite", "akgui:room:request",
                 "akgui:room:transfer", "akgui:room:close", "akgui:room:options"):
        check(need in ids, f"  └ {need}도 함께 있다")
    # 종류가 하나면 ⚙️가 그 종류를 미리 물고 있어야 한다(단계가 하나 줄어든다)
    check(one.preset == key, f"  └ ⚙️ preset이 {key}로 잡힌다", str(one.preset))
    opts = room_panel._OptionsView(engine, ROOM_KINDS, preset_kind=key)
    check(opts.kind == key, "  └ 그 옵션 뷰는 종류가 이미 정해져 있다", str(opts.kind))
    check(not any(isinstance(i, discord.ui.Select) and "어떤 방" in (i.placeholder or "")
                  for i in opts.children),
          "  └ 종류 드롭다운을 안 띄운다")
    emb = room_panel.panel_embed(ROOM_KINDS, [key]).title
    check(cfg["label"] in emb, f"  └ 제목이 '{cfg['label']}'을 말한다", emb)

print("\n[8-b] 🚨 전체 패널(kinds=None)은 그대로 전부 보여준다")
allv = room_panel.RoomPanelView(engine, ROOM_KINDS, None)
news = [i for i in allv.children
        if str(getattr(i, "custom_id", "")).startswith("akgui:room:new:")]
check(len(news) == len(ROOM_KINDS), f"종류 버튼 {len(ROOM_KINDS)}개", str(len(news)))
check(allv.preset is None, "전체 패널은 preset이 없다 (⚙️에서 종류를 고른다)")
check(room_panel._OptionsView(engine, ROOM_KINDS).kind is None,
      "그 옵션 뷰는 종류가 비어 있다")

print("\n[8-c] 🚨 없는 종류 키는 걸러낸다 (오타가 '버튼 없는 패널'로 배포되면 안 된다)")
# 🚨 **예외도 FAIL로 받아야 한다.** 필터를 빼면 여기서 KeyError로 테스트가 통째로
#    죽어서 뒤 검사가 하나도 안 돌았다(2026-10-31 역방향 확인에서 드러났다).
#    종료코드는 1이지만 실패 목록이 비어 "무엇이 깨졌는지"를 알려주지 못한다.
try:
    bad = room_panel.RoomPanelView(engine, ROOM_KINDS, ["rank", "없는종류"])
    news = [i for i in bad.children
            if str(getattr(i, "custom_id", "")).startswith("akgui:room:new:")]
    check(len(news) == 1, "모르는 키는 버리고 아는 것만 만든다",
          str([n.custom_id for n in news]))
except Exception as exc:                        # noqa: BLE001
    check(False, "모르는 키는 버리고 아는 것만 만든다",
          f"걸러내지 않아 {type(exc).__name__}로 터졌다: {exc}")
try:
    check(room_panel.panel_embed(ROOM_KINDS, ["rank", "없는종류"]).title.count("랭크방") == 1,
          "설명도 아는 종류만 쓴다")
except Exception as exc:                        # noqa: BLE001
    check(False, "설명도 아는 종류만 쓴다", f"{type(exc).__name__}로 터졌다: {exc}")

print("\n[8-d] /방패널의 `종류` 옵션이 실제로 패널에 전달된다")
room_tree = ast.parse(room_src)
panel_cmd_fn = next((n for n in ast.walk(room_tree)
                     if isinstance(n, ast.AsyncFunctionDef) and n.name == "panel"), None)
ptxt2 = ast.unparse(panel_cmd_fn) if panel_cmd_fn else ""
check("종류" in ptxt2 and "kinds" in ptxt2,
      "종류 파라미터를 받아 kinds로 넘긴다")
# 🚨 `RoomPanelView(..., kinds)`만 보면 **`kinds = None`으로 바꿔치기한 걸 못 잡는다**
#    (역방향 확인에서 드러났다). kinds가 **종류에서 나온다**는 것까지 봐야 한다.
kinds_assign = [n for n in ast.walk(panel_cmd_fn or ast.Module(body=[], type_ignores=[]))
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "kinds" for t in n.targets)]
check(bool(kinds_assign) and all("종류" in ast.unparse(n.value) for n in kinds_assign),
      "🚨 kinds를 **`종류`에서 만든다** (상수로 박으면 옵션이 죽는다)",
      str([ast.unparse(n.value) for n in kinds_assign]))
check("RoomPanelView(self.engine, ROOM_KINDS, kinds)" in ptxt2,
      "🚨 패널 생성에 kinds를 **넘긴다** (안 넘기면 늘 전체가 올라간다)", ptxt2[-200:])
check("panel_embed(ROOM_KINDS, kinds)" in ptxt2,
      "🚨 설명에도 kinds를 넘긴다 (버튼은 1개인데 설명만 4종이 되면 거짓이 된다)")
check(any(isinstance(d, ast.Call) and "choices" in ast.unparse(d)
          for d in (panel_cmd_fn.decorator_list if panel_cmd_fn else [])),
      "종류는 **선택지(choices)**로 받는다 — 글자로 받으면 오타가 바로 실패가 된다")

print("\n[9] /방패널은 서버 소유자 전용")
panel_cmd = next((n for n in ast.walk(ast.parse(room_src))
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "panel"), None)
check(panel_cmd is not None, "panel 명령어가 있다")
if panel_cmd:
    txt = ast.unparse(panel_cmd)
    check("guild.owner_id" in txt, "소유자 검사가 있다")
    i_guard = txt.find("owner_id")
    i_send = txt.find("channel.send")
    check(0 <= i_guard < i_send, "소유자 검사가 게시보다 **앞에** 있다",
          f"guard={i_guard} send={i_send}")

# 🚨 새 섹션은 **반드시 이 요약 블록보다 위에.** 아래에 붙이면 FAIL이 찍혀도
#    sys.exit(1)을 이미 지나쳐서 **종료코드가 0**이 돼요(10-31에 당했어요).
print("\n[10] 🚨 한 채널에 **두 종류**를 같이 올릴 수 있다 (🏆프리미어 합치기)")
# 🏆프리미어방은 45일간 방 생성 122건 중 0건이고 사람이 "프리미어"를 쓴 글도 0건이라
# 전용 채널을 지우고 **랭크 채널 패널에 버튼만 얹었어요**(2026-11-01 사용자 결정).
two = room_panel.RoomPanelView(engine, ROOM_KINDS, ["rank", "premier"])
creates = [it for it in two.children
           if getattr(it, "custom_id", "").startswith("akgui:room:new:")]
check(len(creates) == 2, f"만들기 버튼이 2개 ({len(creates)}개)")
check({it.custom_id for it in creates} ==
      {"akgui:room:new:rank", "akgui:room:new:premier"},
      "랭크·프리미어 버튼이 맞게 들어갔다",
      str(sorted(it.custom_id for it in creates)))
# 🚨 `row`는 안 박으면 None이에요 — 실제 배치는 직렬화할 때 계산돼요.
comp = two.to_components()
check(all(len(r.get("components", [])) <= 5 for r in comp),
      f"줄마다 5개 한도 안 ({[len(r.get('components', [])) for r in comp]})")
check(len(comp) <= 5, f"5줄 한도 안 ({len(comp)}줄)")
# 관리 버튼(초대·신청·넘기기·닫기)은 그대로 있어야 해요
for cid in ("akgui:room:options", "akgui:room:invite", "akgui:room:request",
            "akgui:room:transfer", "akgui:room:close"):
    check(any(getattr(it, "custom_id", "") == cid for it in two.children),
          f"관리 버튼 {cid} 가 남아있다")
# 종류가 둘이면 ⚙️가 종류를 **물어봐야** 해요(하나일 때만 미리 넣어줘요)
check(two.preset is None, "두 종류면 preset이 없다 (⚙️가 종류를 물어본다)")
check(room_panel.RoomPanelView(engine, ROOM_KINDS, ["rank"]).preset == "rank",
      "한 종류면 preset이 그 종류다")
# 임베드도 두 종류를 **둘 다** 설명해야 해요
emb = room_panel.panel_embed(ROOM_KINDS, ["rank", "premier"])
body = emb.description or ""
for k in ("rank", "premier"):
    check(ROOM_KINDS[k]["label"] in body,
          f"임베드가 {ROOM_KINDS[k]['label']}을 설명한다")
check(ROOM_KINDS["scrim"]["label"] not in body,
      "안 고른 ⚔️내전방은 설명에 없다 (사용자가 따로 두라고 했어요)")
# 🚨 같은 걸 두 번 고르면 버튼이 두 개 생기면 안 돼요
dup = room_panel.RoomPanelView(engine, ROOM_KINDS, ["rank", "rank"])
check(len([it for it in dup.children
           if getattr(it, "custom_id", "").startswith("akgui:room:new:")]) == 1,
      "같은 종류를 두 번 줘도 버튼은 1개")
# 명령어 쪽도 중복을 거르는지 (dict.fromkeys)
room_src_2 = open(os.path.join(BOT_DIR, "cogs", "room.py"), encoding="utf-8").read()
panel_txt = ast.unparse(next(n for n in ast.walk(ast.parse(room_src_2))
                             if isinstance(n, ast.AsyncFunctionDef)
                             and n.name == "panel"))
check("종류2" in panel_txt, "/방패널이 `종류2`를 받는다")
check("fromkeys" in panel_txt, "중복을 거른다 (dict.fromkeys)")

# 🚨 **파라미터마다** choices가 붙어야 해요. "choices 데코레이터가 있나"만 보면
#    `종류2`에서 빼먹은 걸 못 잡아요(역방향 확인 D에서 드러났어요). 선택지가 없으면
#    디스코드가 **자유 입력**으로 받아서, 오타가 조용히 "버튼 없는 패널"이 돼요.
#    숫자나 이름을 박지 않으니 `종류3`을 더해도 자동으로 검사 대상이 돼요.
_panel_fn = next(n for n in ast.walk(ast.parse(room_src_2))
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "panel")
_params = [a.arg for a in _panel_fn.args.args
           if a.arg not in ("self", "interaction")]
_choice_kw = set()
for _d in _panel_fn.decorator_list:
    if isinstance(_d, ast.Call) and ast.unparse(_d.func).endswith("choices"):
        _choice_kw |= {k.arg for k in _d.keywords if k.arg}
check(bool(_params), f"방패널 파라미터를 찾았다: {_params}")
for _p in _params:
    check(_p in _choice_kw, f"`{_p}` 가 선택지(choices)로 받는다",
          f"choices에 있는 것: {sorted(_choice_kw)}")

print("\n" + "=" * 50)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 방 패널 전부 정상")
