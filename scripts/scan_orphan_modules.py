"""🚨 **만들었는데 아무도 안 부르는 모듈**을 찾아요 (배포 관문용).

    python scripts/scan_orphan_modules.py

## 왜 만들었나

2026-10-18에 `utils/fishing_week.py`를 만들고 `cogs/fishing.py`에 **호출을 안 걸었다.**
주간 낚시 대회는 멀쩡히 돌면서 영원히 "아무도 낚지 않았어요"를 발표했다. 테스트가
저장소 함수를 직접 불러 검증했기 때문에 이 누락을 못 잡았다.

이 저장소에서 반복되는 사고다 — `/팀짜기` 버튼이 10분 만에 꺼져서 내전 전적이 2주간
1건도 안 쌓였고, 리롤권·보호권·테마는 출시 후 실사용 0건이었다.

## 무엇을 보나

`utils/*.py`의 **쓰기 함수**(`record_*`·`add_*`·`save_*`·`set_*` 등)가 자기 모듈과
`scripts/` 밖에서 **한 번이라도 불리는지** 본다. 아무도 안 부르면 그 기능은 데이터가
영원히 안 쌓인다.

⚠️ 이건 **정적 검사**라 "불리기는 하는데 조건이 틀려서 안 쌓이는" 경우는 못 잡는다.
그건 결국 DB 건수를 세어 봐야 안다(그래서 아래에 건수도 같이 찍어 준다).
"""
import os
import re
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

# 쓰기로 보이는 함수 이름. 읽기 전용 모듈(계산·포맷)은 안 불려도 문제가 아니다.
WRITE_PREFIXES = ("record_", "add_", "save_", "set_", "put_", "mark_",
                  "give_", "grant_", "log_", "upsert_", "push_", "post_")

# 호출될 필요가 없는 것들. 늘릴 때는 **왜 괜찮은지** 한 줄 적을 것.
ALLOW = {
    # 같은 모듈의 **공개 함수가 감싸 쓰는** 내부 함수. 밖에서 직접 부르면 오히려 안 된다
    # (검증·에스크로를 건너뛰게 된다). 공개 API는 `bet_store.place_wager`.
    "bet_store.add_wager",
}


def source_of(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


util_dir = os.path.join(BOT_DIR, "utils")
cog_dir = os.path.join(BOT_DIR, "cogs")

# 호출하는 쪽 소스를 전부 합쳐 둔다(cogs + utils 서로 호출 + bot.py).
callers: dict[str, str] = {}
for d in (cog_dir, util_dir):
    for name in sorted(os.listdir(d)):
        if name.endswith(".py"):
            callers[f"{os.path.basename(d)}/{name}"] = source_of(os.path.join(d, name))
callers["bot.py"] = source_of(os.path.join(BOT_DIR, "bot.py"))

orphans: list[str] = []
checked = 0

for name in sorted(os.listdir(util_dir)):
    if not name.endswith(".py") or name.startswith("_"):
        continue
    mod = name[:-3]
    src = source_of(os.path.join(util_dir, name))

    funcs = [m.group(1) for m in re.finditer(r"^async def (\w+)|^def (\w+)", src, re.M)]
    funcs = [f for f in (m for m in re.findall(r"^(?:async )?def (\w+)", src, re.M))
             if f.startswith(WRITE_PREFIXES)]
    if not funcs:
        continue

    for func in sorted(set(funcs)):
        if f"{mod}.{func}" in ALLOW:
            continue
        checked += 1
        # 자기 모듈 밖에서 불리는가.
        #
        # 🚨 호출 형태가 셋이라 하나만 보면 **오탐이 쏟아진다**(처음에 6건 중 5건이 오탐이었다):
        #   ⒜ `fishing_week.record_catch(...)`          — 모듈째 import
        #   ⒝ `from utils.birthday_store import (\n  set_birthday,\n)` 뒤 `set_birthday(...)`
        #      → import가 **여러 줄**이라 한 줄 정규식이 못 본다
        #   ⒞ `from utils import suggestion_store as store` 뒤 `store.set_status(...)`
        #      → 별칭이라 모듈 이름이 안 나온다
        # 그래서 ⒝⒞는 "그 모듈을 import한 파일에서 `func(`가 보이면 인정"으로 잡는다.
        found = []
        for where, text in callers.items():
            if where == f"utils/{name}":
                continue
            if f"{mod}.{func}(" in text:
                found.append(where)
                continue
            imports_mod = re.search(
                rf"from utils\.{mod} import|from utils import [^\n]*\b{mod}\b", text)
            if imports_mod and re.search(rf"\b{func}\s*\(", text):
                found.append(where)
        if found:
            print(f"  ✅ {mod}.{func:24} ← {', '.join(found[:3])}")
        else:
            orphans.append(f"{mod}.{func}")
            print(f"  ❌ {mod}.{func:24} 아무도 안 불러요")

print(f"\n쓰기 함수 {checked}개를 봤어요.")

if orphans:
    print(f"\n🚨 아무도 안 부르는 쓰기 함수 {len(orphans)}개")
    for o in orphans:
        print(f"   - {o}")
    print("\n만들어만 두고 연결을 빠뜨린 것일 수 있어요. 일부러 남겨둔 거면"
          "\n이 파일의 ALLOW에 **왜 괜찮은지 한 줄과 함께** 넣어주세요.")
    sys.exit(1)

print("✅ 전부 어딘가에서 불려요.")
