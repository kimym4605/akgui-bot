"""`/팀짜기 인원:` 입력을 멤버로 바꾸는 파서 회귀 테스트.

실제 디스코드를 띄우지 않고, 길드/멤버 흉내만 낸 가짜 객체로 돌려요.
    python scripts/test_team_parse_members.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.team import MemberParseError, parse_members  # noqa: E402


class FakeMember:
    def __init__(self, member_id, display_name, name=None, bot=False):
        self.id = member_id
        self.display_name = display_name
        self.name = name or display_name
        self.bot = bot


class FakeGuild:
    def __init__(self, members):
        self.members = members
        self._by_id = {m.id: m for m in members}

    def get_member(self, member_id):
        return self._by_id.get(member_id)


GUILD = FakeGuild([
    FakeMember(1, "새털구름"),
    FakeMember(2, "서아"),
    FakeMember(3, "최 강"),          # 표시이름에 공백이 있는 경우
    FakeMember(4, "생명체", name="lifeform"),
    FakeMember(5, "MAYA", name="maya"),
    FakeMember(99, "악귀봇", bot=True),
])

passed = failed = 0


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


def ids(raw):
    return [m.id for m in parse_members(GUILD, raw)]


def error_of(raw):
    try:
        parse_members(GUILD, raw)
    except MemberParseError as e:
        return str(e)
    return None


print("멘션 파싱")
check("멘션 나열", ids("<@1> <@2> <@3>"), [1, 2, 3])
check("<@!id> 형태도 받음", ids("<@!1> <@2>"), [1, 2])
check("적은 순서를 지킴", ids("<@3> <@1> <@2>"), [3, 1, 2])
check("같은 사람 두 번은 한 번만", ids("<@1> <@1> <@2>"), [1, 2])
check("봇은 빠짐", ids("<@1> <@2> <@99>"), [1, 2])
check("쉼표/줄바꿈 섞여도 됨", ids("<@1>, <@2>\n<@3>"), [1, 2, 3])

print("\n이름으로 찾기 (자동완성 안 쓴 사람)")
check("표시이름", ids("새털구름, 서아"), [1, 2])
check("계정이름", ids("lifeform"), [4])
check("대소문자 무시", ids("Maya"), [5])
check("공백 품은 이름도 쉼표로 끊으면 됨", ids("최 강, 서아"), [3, 2])
check("앞에 붙은 @는 떼고 봄", ids("@새털구름"), [1])
check("멘션과 이름 섞어 쓰기", ids("<@1> 서아, 최 강"), [1, 2, 3])

print("\n못 찾은 경우")
check("모르는 이름이면 에러", error_of("없는사람") is not None, True)
check("에러에 그 이름이 담김", "`없는사람`" in (error_of("없는사람") or ""), True)
check("서버에 없는 id 멘션도 에러", error_of("<@1> <@12345>") is not None, True)
check("하나만 틀려도 전체를 막음", error_of("<@1> 없는사람") is not None, True)

print("\n빈 입력")
check("빈 문자열", ids(""), [])
check("공백/쉼표만", ids("  , , \n "), [])

print(f"\n{passed}개 통과, {failed}개 실패")
sys.exit(1 if failed else 0)
