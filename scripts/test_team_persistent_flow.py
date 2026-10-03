"""`/팀짜기` 영속 버튼의 전체 흐름을 디스코드 없이 돌려봐요.

    python scripts/test_team_persistent_flow.py

진짜로 확인하려는 것: **버튼 콜백이 저장소에서 상태를 읽고 써서, 봇이 재시작된 뒤에도
이어서 동작하는가.** 저장소 단위 테스트로는 이 배선을 못 잡아요.

가짜 Interaction/Message로 콜백을 직접 부르고, 중간에 **View를 새로 만들어**(= 봇 재시작)
같은 메시지의 버튼이 계속 먹는지 봐요.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_map_test"

from utils import team_balance, team_store  # noqa: E402

# ⚠️ cogs.team을 가져오기 전에 저장 경로를 임시 디렉터리로 바꿔요(운영 data/를 건드리면 안 됨).
_tmp = tempfile.TemporaryDirectory()
team_store.DATA_DIR = Path(_tmp.name)
team_store.FILE_PATH = Path(_tmp.name) / "team_sessions.json"

from cogs.team import Session, TeamSplitView  # noqa: E402

passed = failed = 0
MESSAGE_ID = 555001
OWNER = 11


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


# ── 가짜 디스코드 객체 ────────────────────────────────────────────
class FakeMessage:
    def __init__(self, message_id):
        self.id = message_id
        self.jump_url = f"https://discord.com/x/{message_id}"
        self.embeds = []
        self.view_removed = False
        self.edits = 0

    async def edit(self, **kwargs):
        self.edits += 1
        if "embed" in kwargs:
            self.embeds = [kwargs["embed"]]
        if "view" in kwargs and kwargs["view"] is None:
            self.view_removed = True


class FakeResponse:
    def __init__(self):
        self.messages = []       # send_message로 나간 것들
        self.edited = []         # edit_message로 고친 것들
        self.deferred = False

    async def send_message(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})

    async def edit_message(self, **kwargs):
        self.edited.append(kwargs)

    async def defer(self):
        self.deferred = True

    async def send(self, content=None, **kwargs):
        """followup.send 흉내예요. `wait=True`면 메시지를 돌려줘야 해요."""
        self.messages.append({"content": content, **kwargs})
        return FakeMessage(900000 + len(self.messages))


class FakeInteraction:
    def __init__(self, user_id, message):
        self.user = type("U", (), {"id": user_id, "display_name": "테스터"})()
        self.message = message
        self.guild_id = 777
        self.guild = None
        self.response = FakeResponse()
        self.followup = FakeResponse()


def players_of(n):
    return [
        team_balance.Rated(key=i, label=f"P{i}", rating=float(20 - i), tier_index=20 - i)
        for i in range(1, n + 1)
    ]


async def press(view, name, user_id=OWNER, message=None):
    """버튼을 누른 것처럼 콜백을 부르고, 그때의 interaction을 돌려줘요."""
    interaction = FakeInteraction(user_id, message)
    item = getattr(view, name)
    await item.callback(interaction)
    return interaction


async def main():
    message = FakeMessage(MESSAGE_ID)
    people = players_of(6)
    team_a, team_b, diff = team_balance.balanced_splits(people, limit=1)[0]

    print("팀짜기 직후 세션 저장")
    team_store.save_session(
        MESSAGE_ID, guild_id=777, owner_id=OWNER, players=people,
        team_a=team_a, team_b=team_b, mode=team_store.MODE_BALANCED, diff=diff,
        source_label="🎧 테스트방", message_url=message.jump_url,
    )
    check("세션이 저장됨", team_store.get_session(MESSAGE_ID) is not None, True)

    view = TeamSplitView(bot=None)

    print("\n남이 누르면 막혀요")
    stranger = await press(view, "reshuffle", user_id=999, message=message)
    check("안내가 나감", "실행한 사람만" in (stranger.response.messages[0]["content"] or ""), True)
    check("비공개로", stranger.response.messages[0].get("ephemeral"), True)
    check("편성은 안 바뀜",
          [p.label for p in Session.load(MESSAGE_ID).team_a], [p.label for p in team_a])

    print("\n🔄 다시 섞기")
    before = {p.key for p in Session.load(MESSAGE_ID).team_a}
    await press(view, "reshuffle", message=message)
    after = Session.load(MESSAGE_ID)
    check("A팀이 바뀜", {p.key for p in after.team_a} != before, True)
    check("인원은 그대로", len(after.team_a) + len(after.team_b), 6)
    check("모드가 균형", after.mode, team_store.MODE_BALANCED)
    check("아무도 사라지지 않음",
          sorted(p.key for p in after.team_a + after.team_b), [1, 2, 3, 4, 5, 6])

    print("\n🎲 완전 랜덤")
    await press(view, "pure_random", message=message)
    rand = Session.load(MESSAGE_ID)
    check("모드가 랜덤", rand.mode, team_store.MODE_RANDOM)
    check("인원 유지", len(rand.team_a) + len(rand.team_b), 6)

    print("\n🔁 봇 재시작 (View를 새로 만들어도 같은 메시지가 먹어야 해요)")
    view = TeamSplitView(bot=None)   # ← 재시작 흉내: 상태를 하나도 안 물려받아요
    await press(view, "reshuffle", message=message)
    restored = Session.load(MESSAGE_ID)
    check("재시작 뒤에도 편성이 바뀜", restored.mode, team_store.MODE_BALANCED)
    check("명단이 보존됨",
          sorted(p.key for p in restored.team_a + restored.team_b), [1, 2, 3, 4, 5, 6])
    check("전체 명단(players)도 남아있음", len(restored.players), 6)

    print("\n👑 팀장 (하위 화면이 본 메시지를 고쳐요)")
    from cogs.team import CaptainPickView
    captain_view = CaptainPickView(message, Session.load(MESSAGE_ID))
    edits_before = message.edits
    interaction = FakeInteraction(OWNER, message)
    await captain_view.roll.callback(interaction)
    with_captains = Session.load(MESSAGE_ID)
    check("팀장이 양쪽에 생김",
          all(c is not None for c in with_captains.captains), True)
    check("팀장이 각자 제 팀에 있음",
          (with_captains.captains[0] in {p.key for p in with_captains.team_a},
           with_captains.captains[1] in {p.key for p in with_captains.team_b}),
          (True, True))
    check("본 메시지를 고쳤음", message.edits > edits_before, True)
    check("임베드에 👑이 보임", "👑" in message.embeds[0].fields[0].value, True)

    print("\n🗺️ 맵")
    from cogs.team import MapPickView
    map_view = MapPickView(message, Session.load(MESSAGE_ID))
    await map_view.on_map_chosen(FakeInteraction(OWNER, message), "어센트")
    check("맵이 저장됨", Session.load(MESSAGE_ID).map_name, "어센트")
    check("제목에 맵이 붙음", "어센트" in message.embeds[0].title, True)

    print("\n🔄 다시 섞어도 맵은 남고 팀장은 지워져요")
    await press(view, "reshuffle", message=message)
    after_shuffle = Session.load(MESSAGE_ID)
    check("맵 유지", after_shuffle.map_name, "어센트")
    check("팀장 초기화", after_shuffle.captains, (None, None))

    print("\n🅰️ 승리 보고")
    from utils import scrim_record_store
    scrim_record_store._matches.delete_many({"note": {"$regex": "테스트방"}})
    reported = await press(view, "report_a", message=message)
    check("defer했음", reported.response.deferred, True)
    done = Session.load(MESSAGE_ID)
    check("보고 표시", done.reported, True)
    check("승자 기록", done.winner, 0)
    check("경기 id 기록", bool(done.match_id), True)
    check("버튼을 떼어냄", message.view_removed, True)
    check("결과 메시지가 나감", len(reported.followup.messages) >= 1, True)
    saved = scrim_record_store._matches.find_one({"note": {"$regex": "테스트방"}})
    check("DB에 경기가 들어감", saved is not None, True)
    check("맵도 같이 들어감", saved["map"], "어센트")
    check("승자 인원", len(saved["winners"]), len(done.team_a))

    print("\n보고 뒤에는 편성을 못 바꿔요")
    locked = await press(view, "reshuffle", message=message)
    check("안내가 나감",
          "이미 결과가 기록" in (locked.response.messages[0]["content"] or ""), True)
    check("편성이 그대로",
          sorted(p.key for p in Session.load(MESSAGE_ID).team_a),
          sorted(p.key for p in done.team_a))

    print("\n기록이 사라진 메시지를 누르면 안내해요")
    team_store.delete_session(MESSAGE_ID)
    gone = await press(view, "manual_adjust", message=message)
    check("안내가 나감", "기록이 없어요" in (gone.response.messages[0]["content"] or ""), True)
    check("터지지 않음", True, True)

    print("\n폴백 aiohttp 세션 정리 (안 닫으면 종료할 때 경고가 나요)")
    check("세션을 만들어 썼음", view._fallback_session is not None, True)
    await view.close_session()
    check("닫혔음", view._fallback_session.closed, True)
    await view.close_session()  # 두 번 불러도 안 터져야 해요.

    scrim_record_store._matches.delete_many({"note": {"$regex": "테스트방"}})
    scrim_record_store._records.delete_many({"userId": {"$in": [str(i) for i in range(1, 7)]}})
    _tmp.cleanup()
    print(f"\n{passed}개 통과, {failed}개 실패")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
