# -*- coding: utf-8 -*-
"""🔫 계정 관련 명령어 둘이 **서로를 안내하는지** 지켜요 (2026-10-31 신설).

## 왜 필요한가

`/티어 계정삭제`와 `/오상쿠키삭제`는 **이름이 비슷한데 지우는 게 다릅니다**:

| 명령어 | 지우는 것 | 저장소 |
|---|---|---|
| `/티어 계정삭제` | 전적·티어 역할용 **닉네임#태그 연동** (23명 사용) | `riot_accounts.json` |
| `/오상쿠키삭제` | **/오상 로그인 쿠키** | `riot_sessions.json` |

2026-10-26에 유저(◡̈)가 `#❓봇에게-질문`에 **"발로란트 등록계정 해제"**라고만 적고
어느 쪽인지 몰라 사람에게 물었어요. 그래서 양쪽 설명·응답에서 **서로를 안내**하게
고쳤고(2026-10-31), 이 테스트가 그게 유지되는지 봐요.

🚨 **둘을 하나로 합치지 마세요.** 데이터가 달라서, 합치면 한쪽을 지우려던 사람이
   다른 쪽까지 지운 줄 알거나 그 반대가 돼요.

실행: python scripts/test_account_commands.py   (종료코드 0 = 통과)
"""
import ast
import os
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


def find_cmd(tree: ast.Module, name: str):
    """`@app_commands.command(name="…")` 가 붙은 함수를 찾아요."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            txt = ast.unparse(dec)
            if "app_commands.command" in txt and f'name=\'{name}\'' in txt.replace('"', "'"):
                return node, txt
    return None, ""


tier_src = open(os.path.join(BOT_DIR, "cogs", "tier.py"), encoding="utf-8").read()
shop_src = open(os.path.join(BOT_DIR, "cogs", "myshop.py"), encoding="utf-8").read()
tier_tree, shop_tree = ast.parse(tier_src), ast.parse(shop_src)

print("\n[1] 두 명령어가 **둘 다 살아 있다** (합치지 않았다)")
del_acc, del_acc_dec = find_cmd(tier_tree, "계정삭제")
del_ck, del_ck_dec = find_cmd(shop_tree, "오상쿠키삭제")
check(del_acc is not None, "/티어 계정삭제 가 있다")
check(del_ck is not None, "/오상쿠키삭제 가 있다")
reg, reg_dec = find_cmd(tier_tree, "계정등록")
check(reg is not None, "/티어 계정등록 가 있다")

print("\n[2] 🚨 서로 **다른 저장소**를 건드린다 (합쳐지지 않았다)")
acc_body = ast.unparse(del_acc) if del_acc else ""
ck_body = ast.unparse(del_ck) if del_ck else ""
check("delete_account" in acc_body,
      "/티어 계정삭제 → delete_account (riot_accounts)", acc_body[:80])
check("riot_session_store" in ck_body,
      "/오상쿠키삭제 → riot_session_store (riot_sessions)", ck_body[:80])
check("riot_session_store" not in acc_body,
      "🚨 /티어 계정삭제가 쿠키를 건드리지 않는다")
check("delete_account(" not in ck_body,
      "🚨 /오상쿠키삭제가 계정 연동을 건드리지 않는다")

print("\n[3] ⭐ 설명(description)이 서로를 구분해준다")
check("오상" in del_acc_dec,
      "/티어 계정삭제 설명에 `/오상`을 언급", del_acc_dec[:120])
check("전적" in del_ck_dec or "티어" in del_ck_dec,
      "/오상쿠키삭제 설명에 전적·티어를 언급", del_ck_dec[:120])
check("오상" in reg_dec, "/티어 계정등록 설명도 `/오상`과 구분", reg_dec[:120])

print("\n[4] ⭐ 응답에서 **다른 쪽 명령어 이름**을 알려준다")
check("오상쿠키삭제" in acc_body,
      "/티어 계정삭제 응답이 `/오상쿠키삭제`를 가리킨다")
check("계정삭제" in ck_body,
      "/오상쿠키삭제 응답이 `/티어 계정삭제`를 가리킨다")
# 🚨 "없을 때"도 안내해야 해요 — 엉뚱한 명령어를 쓴 사람이 바로 그 경로예요.
check(acc_body.count("tail") >= 3,
      "/티어 계정삭제: 성공·실패 **양쪽** 응답에 안내가 붙는다",
      f"tail 사용 {acc_body.count('tail')}회")
check(ck_body.count("tail") >= 3,
      "/오상쿠키삭제: 쿠키 없음·하나·여러개 **전부**에 안내가 붙는다",
      f"tail 사용 {ck_body.count('tail')}회")

print("\n[5] 🚨 혼동의 근원 — `/오상` 쪽 화면이 '계정'만 말하지 않는다")
check("로그인 쿠키 지우기" in shop_src,
      "여러 계정 선택 화면 제목이 **로그인 쿠키**임을 밝힌다")

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("✅ 계정 명령어 구분·교차 안내 정상")
