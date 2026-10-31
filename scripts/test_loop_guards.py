# -*- coding: utf-8 -*-
"""🔁 `@tasks.loop` 전부에 **error 핸들러**가 있는지 지켜요 (2026-11-01 신설).

## 왜 — **예외 하나에 영구 정지한다**

`discord.ext.tasks`의 루프는 예외가 올라오면 **그냥 끝나요.** 로그 한 줄 말고는
티가 안 나고, 다시 켜주는 사람도 없어요. 그래서:

- 🎤 `flush_voice`가 멈추면 **통화 미션이 조용히 죽어요**(서버 미션 완료 1위예요)
- 🏷️ `expire_titles`가 멈추면 **만료된 칭호를 공짜로 계속 쓰게** 돼요(기간제 상품!)
- 🎂 `birthday_check`가 멈추면 생일 축하가 안 올라와요

2026-11-01에 로그에서 정체불명 `aiohttp TimeoutError` 1건을 보고 전수 조사하니
**루프 11개 중 3개에 핸들러가 없었어요.** 디스코드 API 호출도 aiohttp라 어느 루프에서든
타임아웃이 날 수 있어요.

🚨 **그래서 숫자를 박지 않아요** — 루프를 새로 만들면 자동으로 검사 대상이 돼요.
   (`test_bet_team_flow`가 버튼 수를 8로 박아뒀다가 거짓 실패를 낸 걸 같은 날 고쳤어요)

실행: python scripts/test_loop_guards.py   (종료코드 0 = 통과)
"""
import ast
import os
import re
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


# 🚨 경로를 정규화해요 — `BOT_DIR`가 `scripts/..` 꼴이면 제외 조건이 전부 참이 돼서
#    **아무 파일도 안 보고 "전부 통과"**가 나와요(같은 날 안내문 스캐너에서 당했어요).
BASE = os.path.abspath(BOT_DIR)
SKIP_DIRS = {".git", "__pycache__", "scripts", ".venv"}

loops: list[tuple[str, str]] = []     # (파일, 루프 이름)
handlers: set[tuple[str, str]] = set()
restarts: dict[tuple[str, str], str] = {}

for root, dirs, files in os.walk(BASE):
    rel = os.path.relpath(root, BASE)
    if any(part in SKIP_DIRS for part in rel.split(os.sep)):
        continue
    for fn in sorted(files):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(root, fn)
        label = os.path.relpath(path, BASE)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except Exception as exc:                       # noqa: BLE001
            check(False, f"{label} 파싱", f"{type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                dd = ast.unparse(dec)
                if "tasks.loop" in dd:
                    loops.append((label, node.name))
                m = re.match(r"(\w+)\.error$", dd)
                if m:
                    handlers.add((label, m.group(1)))
                    restarts[(label, m.group(1))] = ast.unparse(node)

print(f"\n[1] `@tasks.loop` {len(loops)}개를 찾았어요")
check(len(loops) >= 10, f"루프가 {len(loops)}개 (10개 이상이어야 정상)",
      "walk가 파일을 못 봤을 수 있어요")

print("\n[2] 🚨 루프마다 `@<loop>.error` 핸들러가 있다")
for label, name in sorted(loops):
    check((label, name) in handlers, f"{label} :: {name}",
          "예외 하나에 영구 정지해요 — @{}.error 를 추가하세요".format(name))

print("\n[3] 🚨 핸들러가 **다시 켜준다** (`restart()`)")
for label, name in sorted(loops):
    body = restarts.get((label, name))
    if body is None:
        continue        # [2]에서 이미 실패로 잡혔어요
    check(f"{name}.restart()" in body.replace("self.", ""),
          f"{label} :: {name} → restart() 호출",
          "로그만 찍고 안 켜면 멈춘 채로 남아요")

print("\n[4] 🚨 핸들러가 **무엇이 멈췄는지** 로그에 남긴다")
for label, name in sorted(loops):
    body = restarts.get((label, name))
    if body is None:
        continue
    check("log.error" in body or "log.warning" in body,
          f"{label} :: {name} → 로그를 남긴다",
          "조용히 재시작하면 멈춘 사실을 영영 모릅니다")

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print(f"✅ 루프 {len(loops)}개 전부 보호됨")
