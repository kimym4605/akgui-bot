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

print("\n[8] /방패널은 서버 소유자 전용")
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

print("\n" + "=" * 50)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 방 패널 전부 정상")
