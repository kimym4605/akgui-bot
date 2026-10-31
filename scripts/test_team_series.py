# -*- coding: utf-8 -*-
"""🏁 /팀짜기 다전제 테스트 (2026-11-01).

사용자 요청: *"한판 끝날때마다 다시 만들고 해야하는 수고가 있더라고 보통 3판 2선승
5판 3선승처럼 이렇게 하는데 기능을 추가해줄래?"*

디스코드에 접속하지 않아요 — 판정 로직·저장·버튼 구조·보고 흐름을 봐요.

🚨 **가장 중요한 검사는 "단판이 옛 동작과 똑같은가"예요.** `series_target=1`이면
   기존 사용자에게 보이는 변화가 **하나도 없어야** 해요.

실행: python scripts/test_team_series.py   (종료코드 0 = 통과)
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
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"

import discord                                  # noqa: E402
from discord.ext import commands                # noqa: E402

from cogs.team import Session, TeamSplitView, _build_embed   # noqa: E402
from utils import team_balance, team_store      # noqa: E402

passed, failed = [], []


def check(cond, label, detail=""):
    if cond:
        passed.append(label)
        print(f"  ✅ {label}")
    else:
        failed.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


def fake_session(target=1, wins=(0, 0)) -> Session:
    """DB 없이 Session을 만들어요."""
    players = [
        team_balance.Rated(key=i, label=f"P{i}", rating=10.0, tier_index=10,
                           agwi_score=None)
        for i in range(1, 5)
    ]
    rec = {
        "guild_id": "1", "owner_id": "1", "mode": team_store.MODE_BALANCED,
        "diff": 0.0, "source_label": "🎧 테스트",
        "players": [team_store.player_to_dict(p) for p in players],
        "teams": [[team_store.player_to_dict(p) for p in players[:2]],
                  [team_store.player_to_dict(p) for p in players[2:]]],
        "series_target": target, "wins": list(wins),
    }
    return Session(12345, rec)


print("\n[1] 🏁 선승 판정")
CASES = [
    # (목표, (A승, B승), 기대 승자)
    (1, (0, 0), None), (1, (1, 0), 0), (1, (0, 1), 1),
    (2, (1, 0), None), (2, (1, 1), None), (2, (2, 0), 0), (2, (1, 2), 1),
    (3, (2, 2), None), (3, (3, 1), 0), (3, (0, 3), 1),
]
for target, wins, want in CASES:
    s = fake_session(target, wins)
    check(s.series_winner == want,
          f"target={target} wins={wins} → {want}", f"받은 값 {s.series_winner}")

print("\n[2] 🚨 단판(target=1)은 **옛 동작과 같다**")
s1 = fake_session(1)
check(s1.series_target == 1, "기본 목표가 1이다")
check(not s1.is_series, "is_series가 False")
check(s1.series_winner is None, "0:0이면 아직 승자 없음")
s1.wins[0] += 1
check(s1.series_winner == 0, "🚨 1승이면 **즉시** 끝난다 (옛 동작)")
check(s1.total_games == 1, "최대 판수 1")
# 🚨 옛 세션 기록엔 series_target/wins가 **없다** — 그래도 단판으로 돌아야 한다
old_rec = {
    "guild_id": "1", "owner_id": "1", "mode": team_store.MODE_BALANCED,
    "diff": 0.0, "source_label": "", "players": [], "teams": [[], []],
}
old = Session(999, old_rec)
check(old.series_target == 1, "🚨 옛 기록(필드 없음)도 단판으로 읽힌다")
check(old.wins == [0, 0], "🚨 옛 기록의 점수는 0:0", str(old.wins))

print("\n[3] 🚨 깨진 저장값도 버튼을 죽이지 않는다")
# 🚨 **예외도 FAIL로 받아야 해요.** 방어를 빼면 여기서 IndexError로 테스트가 통째로
#    죽어서 실패 목록이 비고, 종료코드만 1이라 **무엇이 깨졌는지 못 알려줘요**
#    (2026-10-31 🔊 방 패널에서 같은 걸 당했어요).
for raw, want in (([], [0, 0]), ([1], [1, 0]), ([1, 2, 3], [1, 2]), (None, [0, 0])):
    rec = dict(old_rec)
    rec["wins"] = raw
    try:
        sx = Session(1, rec)
        check(sx.wins == want, f"wins={raw!r} → {want}", str(sx.wins))
    except Exception as exc:                           # noqa: BLE001
        check(False, f"wins={raw!r} → {want}",
              f"방어가 없어 {type(exc).__name__}로 터졌다: {exc}")

print("\n[4] 다전제 표시")
s2 = fake_session(2, (1, 0))
check(s2.is_series, "3판 2선승은 is_series")
check(s2.total_games == 3, "최대 3판", str(s2.total_games))
check(s2.series_label == "3판 2선승", s2.series_label)
check("1 : 0" in s2.score_text, f"점수 문구: {s2.score_text}")
s3 = fake_session(3, (0, 2))
check(s3.total_games == 5 and s3.series_label == "5판 3선승",
      f"5판 3선승: {s3.total_games}판 · {s3.series_label}")
emb = s2.embed()
check("3판 2선승" in emb.title and "(1:0)" in emb.title,
      f"embed 제목에 판수·점수: {emb.title}")
check("🏁" not in fake_session(1).embed().title,
      "🚨 단판 embed에는 🏁 표시가 **없다** (옛 모양 그대로)",
      fake_session(1).embed().title)

print("\n[5] 🚨 보고 흐름 — 중간엔 버튼을 **떼지 않는다**")
src = open(os.path.join(BOT_DIR, "cogs", "team.py"), encoding="utf-8").read()
tree = ast.parse(src)
rep = next(n for n in ast.walk(tree)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "_report")
body = ast.unparse(rep)
check("series_winner" in body, "_report가 series_winner로 끝났는지 판단한다")
check("view=self" in body, "🚨 중간 보고에서 `view=self`로 **버튼을 유지**한다")
check("view=None" in body, "시리즈가 끝나면 `view=None`으로 떼어낸다")
# 🚨 순서: 중간(view=self)이 먼저, 종료(view=None)가 나중이어야 한다
i_keep, i_drop = body.find("view=self"), body.find("view=None")
check(0 <= i_keep < i_drop,
      "🚨 '아직 안 끝남' 분기가 '끝남' 분기보다 앞에 있다",
      f"keep={i_keep} drop={i_drop}")
check("session.wins[winner_index] += 1" in body, "판마다 점수를 1 올린다")
check("record_match" in body, "🚨 경기 기록(record_match)은 **판마다** 들어간다")
check(body.count("record_match") == 1, "그 호출은 한 번뿐",
      str(body.count("record_match")))
check("session.map_name = None" in body,
      "🚨 중간 보고 뒤 맵을 비운다 (판마다 맵이 다르다)")

print("\n[6] 🚨 베팅은 **시리즈 끝에 한 번만** 정산한다 (사용자 결정)")
check("if done is not None:" in body,
      "`done`이 정해졌을 때만 _settle_bet을 부른다")
i_done = body.find("if done is not None:")
i_settle = body.find("_settle_bet")
check(0 <= i_done < i_settle,
      "🚨 그 검사가 _settle_bet보다 **앞에** 있다", f"{i_done} vs {i_settle}")
check("_settle_bet(interaction, done)" in body,
      "🚨 정산에 넘기는 승자가 **시리즈 승자(done)**다 (그 판 승자가 아니다)")
check("_has_open_bet" in body, "진행 중일 때는 '시리즈 끝에 정산' 안내만 한다")

print("\n[7] 🏁 판수 버튼")


async def _layout():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    view = TeamSplitView(bot)
    rows = view.to_components()
    ids = [str(getattr(c, "custom_id", "")) for c in view.children]
    labels = {str(getattr(c, "custom_id", "")): getattr(c, "label", "")
              for c in view.children}
    check(len(rows) <= 5, f"{len(rows)}줄 (한도 5)")
    for i, r in enumerate(rows):
        check(len(r["components"]) <= 5, f"row {i}: {len(r['components'])}개 (한도 5)")
    for t, want_label in ((1, "단판"), (2, "3판 2선승"), (3, "5판 3선승")):
        cid = f"akgui:team:series:{t}"
        check(cid in ids, f"{cid} 버튼이 있다")
        check(labels.get(cid) == want_label,
              f"  └ 라벨이 '{want_label}'", labels.get(cid, ""))
    check(len(set(ids)) == len(ids), "custom_id가 전부 고유", str(len(ids)))
    try:
        bot.add_view(view)
        check(True, "bot.add_view가 받아들인다 (영속 유지)")
    except Exception as exc:                           # noqa: BLE001
        check(False, "bot.add_view가 받아들인다", f"{type(exc).__name__}: {exc}")


asyncio.run(_layout())

print("\n[8] 🚨 첫 판을 보고한 뒤에는 판수를 못 바꾼다")
setter = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_set_series")
stxt = ast.unparse(setter)
check("sum(session.wins) > 0" in stxt, "이미 보고된 판이 있으면 막는다")
i_guard = stxt.find("sum(session.wins) > 0")
i_set = stxt.find("session.series_target = target")
check(0 <= i_guard < i_set, "🚨 그 검사가 값 변경보다 **앞에** 있다",
      f"{i_guard} vs {i_set}")

print("\n[9] 저장소가 다전제 필드를 싣는다")
store_src = open(os.path.join(BOT_DIR, "utils", "team_store.py"), encoding="utf-8").read()
for field in ('"series_target"', '"wins"', '"match_ids"'):
    check(field in store_src, f"save_session이 {field}를 저장한다")
sig = next(n for n in ast.walk(ast.parse(store_src))
           if isinstance(n, ast.FunctionDef) and n.name == "save_session")
kwonly = [a.arg for a in sig.args.kwonlyargs]
for name in ("series_target", "wins", "match_ids"):
    check(name in kwonly, f"save_session에 {name} 인자가 있다", str(kwonly))

print("\n" + "=" * 52)
print(f"통과 {len(passed)} · 실패 {len(failed)}")
if failed:
    print("\n❌ 실패 목록:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("✅ 다전제 전부 정상")
