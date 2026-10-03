"""`/팀짜기`의 👑 팀장 지정과 `/팀보기`(마지막 편성 저장)의 회귀 테스트.

    python scripts/test_team_captain_store.py

실제 파일을 건드리지 않게 team_store의 저장 경로를 임시 디렉터리로 바꿔치기해서 돌려요.
(운영 중인 봇은 이 파일을 `data/last_teams.json`에 쓰고 있어요)
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import team_balance, team_store  # noqa: E402

# ⚠️ cogs.team을 가져오기 전에 경로를 바꿔둬요(가져오는 순간 모듈 상수가 굳어요).
_tmp = tempfile.TemporaryDirectory()
team_store.DATA_DIR = Path(_tmp.name)
team_store.FILE_PATH = Path(_tmp.name) / "last_teams.json"

from cogs.team import (  # noqa: E402
    _build_embed,
    _team_lines,
    _when_text,
    keep_valid_captains,
    random_captains,
)

passed = failed = 0


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


def player(key, rating, **kwargs):
    return team_balance.Rated(
        key=key, label=f"P{key}", rating=rating, tier_index=int(rating), **kwargs
    )


A = [player(1, 12), player(2, 10), player(3, 8)]
B = [player(4, 11), player(5, 9), player(6, 7)]

print("팀장 유효성 (keep_valid_captains)")
check("양쪽 다 제 팀에 있으면 그대로", keep_valid_captains(A, B, (1, 4)), (1, 4))
check("A팀장이 그 팀에 없으면 비움", keep_valid_captains(A, B, (99, 4)), (None, 4))
check("B팀장이 그 팀에 없으면 비움", keep_valid_captains(A, B, (1, 99)), (1, None))
check("반대편으로 넘어간 팀장은 승격되지 않고 비움",
      keep_valid_captains(A, B, (4, 1)), (None, None))
check("None은 그대로 None", keep_valid_captains(A, B, (None, None)), (None, None))
check("빈 팀이면 비움", keep_valid_captains([], B, (1, 4)), (None, 4))

print("\n맞교환 뒤 팀장 (🔀 직접 조정 시나리오)")
from cogs.team import swap_players  # noqa: E402
# P1(A팀장)과 P4(B팀장)를 맞교환하면 둘 다 반대편으로 가므로 양쪽이 비어야 해요.
new_a, new_b = swap_players(A, B, A[0], B[0])
check("팀장끼리 맞교환하면 양쪽 다 비움",
      keep_valid_captains(new_a, new_b, (1, 4)), (None, None))
# 팀장이 아닌 사람끼리 바꾸면 팀장은 그대로 남아야 해요.
new_a, new_b = swap_players(A, B, A[2], B[2])
check("팀장이 아닌 사람끼리 바꾸면 팀장 유지",
      keep_valid_captains(new_a, new_b, (1, 4)), (1, 4))

print("\n무작위 팀장 뽑기 (random_captains)")
for _ in range(50):
    a_cap, b_cap = random_captains(A, B)
    if a_cap not in {p.key for p in A} or b_cap not in {p.key for p in B}:
        check("항상 자기 팀에서 뽑힘", (a_cap, b_cap), "자기 팀 안의 id")
        break
else:
    check("항상 자기 팀에서 뽑힘 (50회)", True, True)
check("빈 팀은 None", random_captains([], B)[0], None)
check("양쪽 다 비면 (None, None)", random_captains([], []), (None, None))

print("\n명단 표시 (_team_lines)")
lines = _team_lines(A, 2)
check("팀장이 맨 위로 올라감", lines.splitlines()[0].startswith("👑 "), True)
check("팀장 이름이 맞음", "P2" in lines.splitlines()[0], True)
check("팀장 아닌 줄엔 👑이 없음", "👑" in lines.splitlines()[1], False)
check("인원이 안 줄어듦", len(lines.splitlines()), 3)
check("팀장을 안 정하면 아무도 👑이 아님", "👑" in _team_lines(A, None), False)
check("팀장이 그 팀에 없으면 무시", "👑" in _team_lines(A, 99), False)
check("빈 팀은 '-'", _team_lines([], None), "-")

print("\n임베드 (모드별 제목/실력차)")
embed = _build_embed(A, B, 0.33, mode=team_store.MODE_BALANCED, source_label="🎧 테스트방")
check("균형 제목", embed.title, "🎯 팀 나누기 (실력 균형)")
check("실력 차이 칸이 있음", any(f.name == "⚖️ 실력 차이" for f in embed.fields), True)
embed = _build_embed(A, B, 2.0, mode=team_store.MODE_RANDOM, source_label="x")
check("랜덤 제목", embed.title, "🎲 팀 나누기 (완전 랜덤)")
check("랜덤은 실력 차이를 안 보여줌",
      any(f.name == "⚖️ 실력 차이" for f in embed.fields), False)
embed = _build_embed(A, B, 1.0, mode=team_store.MODE_MANUAL, source_label="x")
check("직접 조정 제목", embed.title, "✏️ 팀 나누기 (직접 조정)")
embed = _build_embed(A, B, None, mode=team_store.MODE_BALANCED, source_label="x")
check("diff가 None이면 실력 차이 칸 생략",
      any(f.name == "⚖️ 실력 차이" for f in embed.fields), False)
embed = _build_embed([], B, None, mode=team_store.MODE_BALANCED, source_label="x")
check("한 팀이 비어도 안 터짐 (0으로 나누기 방지)", embed.fields[0].name, "🅰️ 팀 A (0명)")
embed = _build_embed(A, B, 0.5, mode=team_store.MODE_BALANCED, source_label="x",
                     captains=(1, 4))
check("팀장이 임베드에 반영됨", embed.fields[0].value.splitlines()[0].startswith("👑 "), True)

print("\n맵 표시")
embed = _build_embed(A, B, 0.5, mode=team_store.MODE_BALANCED, source_label="x",
                     map_name="어센트")
check("맵이 제목에 붙음", embed.title.endswith("· 🗺️ 어센트"), True)
check("모드 제목도 남아있음", embed.title.startswith("🎯 팀 나누기"), True)
embed = _build_embed(A, B, 0.5, mode=team_store.MODE_BALANCED, source_label="x")
check("맵이 없으면 제목에 안 붙음", "🗺️" in embed.title, False)

def save(message_id, *, guild=777, team_a=A, team_b=B, mode=team_store.MODE_BALANCED,
         diff=0.33, label="🎧 테스트방", captains=(None, None), map_name=None,
         url=None, winner=None, reported=False, match_id=None, players=None):
    team_store.save_session(
        message_id, guild_id=guild, owner_id=1,
        players=players if players is not None else A + B,
        team_a=team_a, team_b=team_b, mode=mode, diff=diff, source_label=label,
        captains=captains, map_name=map_name, message_url=url, winner=winner,
        reported=reported, match_id=match_id,
    )


print("\n저장·조회 (team_store — 메시지별 세션)")
check("처음엔 아무것도 없음", team_store.get_session(1001), None)
save(1001, captains=(2, 5), map_name="어센트", url="https://discord.com/x")
record = team_store.get_session(1001)
check("저장된 모드", record["mode"], team_store.MODE_BALANCED)
check("저장된 맵", record["map"], "어센트")
check("저장된 실력 차이", record["diff"], 0.33)
check("저장된 팀장", team_store.load_captains(record), (2, 5))
check("저장된 링크", record["message_url"], "https://discord.com/x")
check("저장된 주인", record["owner_id"], 1)
check("보고 전이면 reported=False", record["reported"], False)
loaded_a, loaded_b = team_store.load_teams(record)
check("A팀 명단 복원", [p.label for p in loaded_a], ["P1", "P2", "P3"])
check("B팀 명단 복원", [p.label for p in loaded_b], ["P4", "P5", "P6"])
check("티어가 살아있음", [p.tier_index for p in loaded_a], [12, 10, 8])
check("rating이 살아있음", loaded_a[0].rating, 12.0)
check("전체 명단도 복원 (다시 섞기에 필요해요)",
      [p.label for p in team_store.load_players(record)],
      ["P1", "P2", "P3", "P4", "P5", "P6"])
check("다른 메시지는 영향 없음", team_store.get_session(1002), None)

print("\n메시지가 여러 개여도 각각 따로 살아있어요 (영속 버튼의 핵심)")
save(1002, team_a=B, team_b=A, mode=team_store.MODE_MANUAL, diff=1.5, map_name="펄")
check("1001은 그대로", team_store.get_session(1001)["map"], "어센트")
check("1002는 따로", team_store.get_session(1002)["map"], "펄")
check("두 세션이 다 남음", len(team_store._load_all()), 2)
check("같은 서버면 최신 것을 돌려줌 (/팀보기)",
      team_store.latest_for_guild(777)["map"], "펄")
save(1003, guild=888, map_name="바인드")
check("다른 서버는 섞이지 않음", team_store.latest_for_guild(888)["map"], "바인드")
check("기록 없는 서버는 None", team_store.latest_for_guild(999), None)

print("\n같은 메시지를 다시 저장하면 덮어써요")
save(1001, map_name="로터스", winner=1, reported=True, match_id="m-9")
record = team_store.get_session(1001)
check("맵이 바뀜", record["map"], "로터스")
check("승자 기록", record["winner"], 1)
check("보고 표시", record["reported"], True)
check("경기 id 기록", record["match_id"], "m-9")
check("세션 수는 그대로", len(team_store._load_all()), 3)

print("\n못 재는 실력차(inf)는 저장하지 않아요 (JSON이 깨지면 안 돼요)")
save(1004, team_a=A, team_b=[], diff=team_balance.imbalance(A, []))
raw = team_store.FILE_PATH.read_text(encoding="utf-8")
check("inf가 파일에 안 들어감", "Infinity" in raw, False)
check("diff는 None으로 저장", team_store.get_session(1004)["diff"], None)
import json  # noqa: E402
check("표준 JSON으로 다시 읽힘", isinstance(json.loads(raw), dict), True)

print("\n서버를 나간 사람 (id로 이름을 못 찾는 경우)")
check("저장해둔 이름을 그대로 씀",
      team_store.player_from_dict({"id": 42}).label, "42")
check("이름이 있으면 그걸 씀",
      team_store.player_from_dict({"id": 42, "label": "탈주닌자"}).label, "탈주닌자")
check("rating이 없으면 기본 티어로",
      team_store.player_from_dict({"id": 42}).rating,
      float(team_balance.FALLBACK_TIER_INDEX))

print("\n깨진 기록도 명령어를 죽이지 않아요")
check("teams가 없으면 빈 두 팀", team_store.load_teams({}), ([], []))
check("teams가 한 칸만 있으면 채워줌",
      team_store.load_teams({"teams": [[{"id": 1, "label": "P1"}]]})[1], [])
check("captains가 없으면 (None, None)", team_store.load_captains({}), (None, None))

print("\n지우기")
team_store.delete_session(1004)
check("지워짐", team_store.get_session(1004), None)
team_store.delete_session(1004)  # 두 번 지워도 안 터져야 해요.
check("없는 걸 지워도 조용히 넘어감", team_store.get_session(1004), None)

print("\n오래된 세션 정리 (prune) — 파일이 무한정 안 커지게")
old = team_store._load_all()
old["9999"] = {**old["1001"],
               "saved_at": (datetime.now(team_store.KST)
                            - timedelta(days=team_store.SESSION_TTL_DAYS + 1)
                            ).isoformat(timespec="seconds")}
team_store._save_all(old)
check("넣자마자는 보임", team_store.get_session(9999) is not None, True)
removed = team_store.prune()
check("오래된 걸 지움", removed, 1)
check("정말 사라짐", team_store.get_session(9999), None)
check("최근 것은 남음", team_store.get_session(1001) is not None, True)
check("지울 게 없으면 0", team_store.prune(), 0)

# 개수 상한도 지켜지는지 (MAX_SESSIONS를 잠깐 낮춰서 봐요)
real_max = team_store.MAX_SESSIONS
team_store.MAX_SESSIONS = 2
save(2001, map_name="A")
save(2002, map_name="B")
save(2003, map_name="C")
check("상한을 넘지 않음", len(team_store._load_all()) <= 2, True)
check("가장 최근 것은 남아있음", team_store.get_session(2003) is not None, True)
team_store.MAX_SESSIONS = real_max

print("\n시각 표시 (_when_text)")
now = datetime.now(team_store.KST)
check("오늘", _when_text(now.isoformat(timespec="seconds")), f"오늘 {now:%H:%M}")
yesterday = now - timedelta(days=1)
check("어제", _when_text(yesterday.isoformat(timespec="seconds")),
      f"어제 {yesterday:%H:%M}")
old = now - timedelta(days=5)
check("그 이전은 날짜로", _when_text(old.isoformat(timespec="seconds")),
      f"{old.month}월 {old.day}일 {old:%H:%M}")
check("없으면 안내문", _when_text(None), "언제인지 모르는 시점")
check("깨진 값이어도 안 터짐", _when_text("어제쯤"), "언제인지 모르는 시점")

_tmp.cleanup()
print(f"\n{passed}개 통과, {failed}개 실패")
sys.exit(1 if failed else 0)
