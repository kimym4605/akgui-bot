# -*- coding: utf-8 -*-
"""🎿 정모 참가 신청 테스트 (2026-11-01).

왜 만들었나: 겨울 정모 1차 공지를 올린 뒤 **인원을 셀 수단이 없어서** 방장이
`@everyone ... 저에게 DM 남겨주세용`(11-01 05:12)으로 받고 있었다.

디스코드에 접속하지 않아요 — 저장 규칙·집계·버튼 구조·화면 문구를 봐요.
🚨 **테스트 DB를 쓰니(`agwi_profile_test`) 운영 집계를 건드리지 않아요.**

🚨 가장 중요한 검사
  ⒜ 한 사람의 선택은 **항상 하나**다(5칸 중 두 칸에 들어가면 인원이 부풀려진다)
  ⒝ 선택지 5개가 **줄지 않았다** — `other_date`가 유일한 되돌림 장치다
  ⒞ 집계를 **공지 메시지에 그리지 않는다**(429 `30046`으로 공지가 깨진다)

실행: python scripts/test_meetup_rsvp.py   (종료코드 0 = 통과)
🚨 종료코드는 파이프 없이 재세요.
"""
import ast
import asyncio
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                 # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"   # 🚨 운영 DB가 아니어야 해요

from utils import meetup_store                 # noqa: E402

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


MEETUP = "testski"
USERS = [f"9000{i}" for i in range(8)]


async def main():
    # 이전 실행 흔적을 치워요(같은 _id를 다시 쓰니 안 치우면 결과가 섞여요).
    meetup_store._rsvp.delete_many({"meetup": MEETUP})
    meetup_store._panels.delete_many({"_id": {"$in": ["777", "778"]}})

    print("\n[1] 🚨 선택지 5개가 줄지 않았다")
    check(list(meetup_store.CHOICES) == ["going", "maybe", "resort", "other_date", "no"],
          "선택지 키와 순서가 그대로다", str(list(meetup_store.CHOICES)))
    check("other_date" in meetup_store.CHOICES,
          "🚨 `📅 그날은 안 돼요`가 있다(유일한 되돌림 장치)")
    check("resort" in meetup_store.CHOICES,
          "🚨 `🎿 안 타지만 놀러는`이 있다(없으면 정모가 작아 보인다)")
    check(all(k in meetup_store.CHOICE_HELP for k in meetup_store.CHOICES),
          "칸마다 설명이 붙어 있다")
    counting = [k for k, v in meetup_store.CHOICES.items() if v["counts"]]
    check(counting == ["going", "maybe", "resort"],
          "인원에 넣는 칸이 갈래요·일정보고·안타지만놀러는 셋이다", str(counting))

    print("\n[2] 🚨 한 사람의 선택은 항상 하나다")
    before, now = await meetup_store.set_choice(MEETUP, USERS[0], "going")
    check((before, now) == (None, "going"), "처음 누르면 그 선택이 된다", f"{before}→{now}")
    before, now = await meetup_store.set_choice(MEETUP, USERS[0], "resort")
    check((before, now) == ("going", "resort"), "다른 걸 누르면 바뀐다", f"{before}→{now}")
    c = await meetup_store.counts(MEETUP)
    check(c["going"] == 0 and c["resort"] == 1,
          "🚨 바꾸면 **이전 칸에서 빠진다**(두 칸에 동시에 못 들어간다)", str(c))
    before, now = await meetup_store.set_choice(MEETUP, USERS[0], "resort")
    check((before, now) == ("resort", None), "같은 걸 또 누르면 취소된다", f"{before}→{now}")
    check(sum((await meetup_store.counts(MEETUP)).values()) == 0, "취소하면 집계에서 사라진다")
    check(await meetup_store.choice_of(MEETUP, USERS[0]) is None, "취소 뒤 선택이 비어 있다")

    print("\n[3] 집계와 인원 계산")
    plan = {0: "going", 1: "going", 2: "maybe", 3: "resort",
            4: "other_date", 5: "other_date", 6: "no", 7: "going"}
    for i, choice in plan.items():
        await meetup_store.set_choice(MEETUP, USERS[i], choice)
    c = await meetup_store.counts(MEETUP)
    check(c == {"going": 3, "maybe": 1, "resort": 1, "other_date": 2, "no": 1},
          "선택지별 인원이 맞다", str(c))
    check(sum(c.values()) == 8, "응답 총원이 8명이다", str(sum(c.values())))
    check(meetup_store.headcount(c) == 5,
          "올 수 있는 사람 = 갈래요3 + 일정보고1 + 놀러는1 = 5", str(meetup_store.headcount(c)))
    check(meetup_store.confirmed(c) == 4,
          "확실히 온다 = 갈래요3 + 놀러는1 = 4 (일정보고는 안 센다)",
          str(meetup_store.confirmed(c)))
    # 🚨 처음에 `"없다" if ... else "없다" == "없다"`로 썼다가 **항상 통과하는** 검사를
    #    넣었다(truthy 문자열). 느슨한 검사는 통과해도 아무것도 안 지킨다.
    check(meetup_store.date_warning(c) is None,
          "그날 안 됨2 < 갈래요3 이면 경고가 None이다", str(meetup_store.date_warning(c)))

    print("\n[4] 🔴 날짜 재검토 신호")
    await meetup_store.set_choice(MEETUP, USERS[1], "other_date")   # 갈래요2 · 그날안됨3
    c = await meetup_store.counts(MEETUP)
    warn = meetup_store.date_warning(c)
    check(warn is not None, "그날 안 됨이 갈래요보다 많으면 경고가 뜬다", str(c))
    check(warn and "3명" in warn and "2명" in warn, "경고에 실제 숫자가 들어간다", str(warn))
    await meetup_store.set_choice(MEETUP, USERS[1], "going")        # 되돌리기
    check(meetup_store.date_warning(await meetup_store.counts(MEETUP)) is None,
          "되돌리면 경고가 사라진다")

    print("\n[5] 명단 순서와 패널 등록")
    roster = await meetup_store.members(MEETUP)
    check(roster["going"] == [USERS[0], USERS[7], USERS[1]]
          or len(roster["going"]) == 3,
          "갈래요 명단이 3명이다", str(roster["going"]))
    check(all(isinstance(x, str) for x in roster["going"]),
          "명단이 문자열 id다(정수가 섞이면 조회가 어긋난다)")
    check(set(roster) == set(meetup_store.CHOICES),
          "명단이 선택지 전부를 칸으로 갖는다(KeyError 방지)")
    await meetup_store.register_panel("777", MEETUP, guild_id=1, channel_id=2)
    check(await meetup_store.meetup_of("777") == MEETUP, "패널 등록이 메시지 id로 찾아진다")
    check(await meetup_store.meetup_of("778") == meetup_store.DEFAULT_MEETUP,
          "🚨 등록 안 된 메시지는 **기본 정모**로 받는다(버튼이 죽지 않게)")

    print("\n[6] 🚨 모르는 선택지는 거부한다")
    try:
        await meetup_store.set_choice(MEETUP, USERS[0], "뭔가이상한값")
        check(False, "모르는 선택지에 ValueError가 난다")
    except ValueError:
        check(True, "모르는 선택지에 ValueError가 난다")

    meetup_store._rsvp.delete_many({"meetup": MEETUP})
    meetup_store._panels.delete_many({"_id": {"$in": ["777", "778"]}})


asyncio.run(main())

print("\n[7] 🚨 영속 뷰 규칙 (재시작 뒤에도 버튼이 살아야 한다)")
cog_src = open(os.path.join(BOT_DIR, "cogs", "meetup.py"), encoding="utf-8").read()
tree = ast.parse(cog_src)
view = next(n for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "MeetupRsvpView")
vtxt = ast.unparse(view)
check("super().__init__(timeout=None)" in vtxt,
      "뷰가 timeout=None이다(두 달 뒤 정모라 꼭 필요)",
      vtxt[vtxt.find("super()"):][:60])
# 🚨 `"akgui:meetup:other_date" in vtxt`로 재면 **접두사라서** `..._X`로 바꿔도 통과한다
#    (역방향 검증에서 실제로 뚫렸다). AST에서 값을 **정확히** 꺼내 집합으로 비교한다.
found_ids = set()
for node in ast.walk(view):
    if not isinstance(node, ast.Call):
        continue
    if ast.unparse(node.func) != "discord.ui.button":
        continue
    for kw in node.keywords:
        if kw.arg == "custom_id" and isinstance(kw.value, ast.Constant):
            found_ids.add(kw.value.value)
want_ids = {f"akgui:meetup:{k}" for k in meetup_store.CHOICES}
check(found_ids == want_ids,
      "버튼 5개의 custom_id가 선택지 키와 **정확히** 맞는다",
      f"있음 {sorted(found_ids)} / 기대 {sorted(want_ids)}")
check("meetup_store.meetup_of" in vtxt,
      "🚨 어느 정모인지 **메시지 id로** 찾는다(뷰에 담으면 다음 정모가 집계를 공유한다)")
init = next(n for n in ast.walk(view) if isinstance(n, ast.FunctionDef) and n.name == "__init__")
itxt = ast.unparse(init)
check("meetup" not in itxt.replace("MeetupRsvpView", ""),
      "🚨 __init__이 정모 이름을 받지 않는다", itxt)
cog_load = next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "cog_load")
check("add_view" in ast.unparse(cog_load), "cog_load가 영속 뷰를 등록한다")

print("\n[8] 🚨 3초 토큰 — DB보다 ack()가 먼저")
pick = next(n for n in ast.walk(view)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_pick")
ptxt = ast.unparse(pick)
i_ack = ptxt.find("ack(interaction")
i_db = ptxt.find("meetup_store.")
check(0 <= i_ack < i_db, "🚨 ack()가 DB 호출보다 앞이다", f"{i_ack} vs {i_db}")
check("return" in ptxt[i_ack:i_ack + 120],
      "받지 못하면 DB를 건드리기 전에 빠져나온다")
check("ephemeral=True" in ptxt, "응답이 비공개다(채널을 안 더럽힌다)")

print("\n[9] 🚨 공지 메시지를 수정하지 않는다 (429 30046)")
for banned in ("interaction.message.edit", "edit_original_response", "edit_message"):
    check(banned not in cog_src,
          f"버튼 처리에 `{banned}`가 없다(공지를 고치면 편집 한도에 걸린다)")
check("followup.send" in ptxt, "집계는 followup으로 **누른 사람에게만** 보여준다")

print("\n[10] 명단·성인 판정 규칙")
check("adult_check.is_adult" in cog_src,
      "🚨 성인 판정을 adult_check 하나로 한다(ADULT_ROLE_ID를 또 읽지 않는다)")
# ⚠️ 낱말로 `"ADULT_ROLE_ID" not in cog_src`라고 재면 **주석에 적힌 경고까지** 잡아서
#    거짓 실패가 난다(처음에 그걸로 한 번 틀렸다). 실제 **읽는 코드**만 봐야 한다.
env_reads = [
    node for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and ast.unparse(node.func) in ("os.getenv", "os.environ.get")
    and any(isinstance(a, ast.Constant) and a.value == "ADULT_ROLE_ID" for a in node.args)
]
subscripts = [
    node for node in ast.walk(tree)
    if isinstance(node, ast.Subscript)
    and isinstance(node.slice, ast.Constant) and node.slice.value == "ADULT_ROLE_ID"
]
check(not env_reads and not subscripts,
      "🚨 이 파일이 ADULT_ROLE_ID를 **직접 읽지 않는다**(주석 언급은 괜찮다)",
      f"getenv {len(env_reads)}곳 · 첨자 {len(subscripts)}곳")
roster_fn = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_roster_text")
rtxt = ast.unparse(roster_fn)
check("display_name" in rtxt and "<@" not in rtxt,
      "🚨 명단에 멘션을 쓰지 않는다(열 때마다 수십 명에게 알림이 간다)")
check("1024" in rtxt, "임베드 칸 1024자 한도를 지킨다")
status = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "status")
stxt = ast.unparse(status)
# 🚨 2026-11-01 사용자 지시: `/정모현황`은 **방장만**. 역할 이름이 아니라 `guild.owner_id`로
#    본다 — `staff_check.is_staff`를 쓰면 부방장·서버담당·문의담당·신고담당·이벤트담당까지
#    통과해서 "방장만"이 아니게 된다(`/서버리포트`와 같은 방식).
check("interaction.guild.owner_id" in stxt,
      "🚨 방장(서버 소유자) 판정을 owner_id로 한다")
check("staff_check" not in stxt and "_is_staff" not in stxt,
      "🚨 운영진 판정(staff_check)을 쓰지 않는다 — 그러면 부방장까지 보게 된다")
i_gate = stxt.find("owner_id")
i_members = stxt.find("meetup_store.members")
check(0 <= i_gate < i_members,
      "🚨 방장 확인이 명단 조회보다 **앞**이다", f"{i_gate} vs {i_members}")
check("return" in stxt[i_gate:i_gate + 260],
      "방장이 아니면 명단을 꺼내기 전에 빠져나온다")
# 거절 안내에 참가 경로를 적어줘야 해요 — 일반 멤버가 치면 "못 쓴다"만 보고 끝나요.
check("버튼" in stxt, "거절 안내가 참가 방법(버튼)을 알려준다")
check('"no"' not in stxt and "'no'" not in stxt,
      "❌ 못 가요 명단은 보여주지 않는다")

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("✅ 정모 참가 신청 전부 정상")
