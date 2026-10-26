"""🟡 레전드 홍보 + 🥈 부방장 멘션 검증 (2026-10-27). 실제 DB·디스코드 없이 돌아가요.

`test_card_gacha_flow.py`가 "돈이 오가는 순서"를 본다면, 여기는 **레전드가 나왔을 때
누가 어디서 알게 되는지**를 봐요.

🚨 왜 따로 만들었나: 이 기능은 **0.5%짜리 경로**예요. 손으로 확인하려면 평균 200장
(약 667코인)을 뽑아야 해서 실서버에서 눈으로 볼 수가 없어요. 조건을 직접 만들어
돌려보지 않으면 **배포하고 몇 주 뒤에야 안 되는 걸 알게 돼요**(그 전례가 많아요
-> [[feedback_wire_the_hook_not_just_the_store]]).

여기서 확인하는 것:
  1) 레전드가 없으면 뽑기방에 아무것도 안 보낸다 (평소 뽑기를 시끄럽게 만들지 않기)
  2) 다른 채널에서 뽑은 레전드는 **뽑기방에 홍보**된다 (카드 그림까지)
  3) 🚨 **뽑기방에서 공개로 뽑아도 홍보는 올라간다** — 그림만 생략한다
  4) 나쁜말악귀면 🥈 부방장을 멘션한다 — `allowed_mentions.roles`에도 그 역할만 들어간다
  5) 멘션 대상은 👑 방장이 아니다 (`방장` ⊂ `부방장` 부분일치 함정)
  6) 🥈 부방장 역할이 없어도 홍보는 올라간다 (멘션만 빠진다)
  7) 뽑기방을 못 찾으면 조용히 넘어간다
  8) 홍보가 터져도 `do_pull`은 성공으로 끝난다 (코인은 나갔고 카드는 들어갔으니까)
  9) 뽑은 사람에게는 핑이 안 간다 (`allowed_mentions.users` 꺼짐)

🚨 3)이 이 파일에서 가장 중요한 검사예요. 처음엔 "공개로 뽑았으면 결과가 이미 보이니
홍보를 건너뛴다"고 만들었는데, 그 전제(`/출석`의 🎴 버튼으로 뽑으면 본인에게만 보인다)는
**2026-10-17에 그 버튼이 제거되면서 사라졌어요.** 지금 뽑기는 거의 전부 뽑기방 공개
뽑기라, 건너뛰기를 두면 이 기능이 **한 번도 안 터져요.** 그 회귀를 여기서 막아요.
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_card_test"

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def run(coro):
    return asyncio.run(coro)


import cogs.card_gacha as gacha  # noqa: E402
from utils.card_data import BY_KEY  # noqa: E402

CARD_CHANNEL = 999_000_111
OTHER_CHANNEL = 555_000_222


# ------------------------------------------------------------------
# 가짜 디스코드
# ------------------------------------------------------------------
class FakeRole:
    def __init__(self, role_id, name):
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"


class FakeChannel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.sent = []

    async def send(self, content=None, *, embed=None, file=None, allowed_mentions=None):
        self.sent.append({"content": content, "embed": embed, "file": file,
                          "allowed_mentions": allowed_mentions})


class FakeGuild:
    def __init__(self, roles, channel):
        self.roles = roles
        self._channel = channel

    def get_channel(self, channel_id):
        return self._channel if self._channel and channel_id == self._channel.id else None


class FakeUser:
    id = 12345
    mention = "<@12345>"


class FakeInteraction:
    def __init__(self, channel_id, guild):
        self.user = FakeUser()
        self.guild = guild
        self.channel_id = channel_id
        self.channel = type("Ch", (), {"parent_id": None})()


def make(roles=("👑 방장", "🥈 부방장"), channel_id=CARD_CHANNEL, with_channel=True):
    """(interaction, 뽑기방) 한 쌍을 만들어요. `channel_id`는 **뽑은 장소**예요."""
    role_objs = [FakeRole(100 + i, name) for i, name in enumerate(roles)]
    card_channel = FakeChannel(CARD_CHANNEL) if with_channel else None
    guild = FakeGuild(role_objs, card_channel)
    return FakeInteraction(channel_id, guild), card_channel


def card(key, *, pity=False, is_new=True):
    grade, name = BY_KEY[key]   # BY_KEY는 {key: (등급, 이름)} 튜플이에요
    return {"key": key, "grade": grade, "name": name,
            "is_new": is_new, "pity": pity}


SUMMARY = {"per_grade": {"레전드": {"owned": 3, "total": 13}},
           "owned": 20, "total": 83, "cards": 40}

# 채널 지정을 가짜로 끼워넣어요(실제로는 /채널설정 또는 CARD_CHANNEL_ID secret이에요).
gacha.get_allowed_channel_id = lambda group, env=None, fallback_group=None: CARD_CHANNEL


# 이미지는 이 테스트의 관심사가 아니에요.
async def no_image(drawn):
    return None


gacha.card_render.render_pull = no_image


# ------------------------------------------------------------------
print("🟡 레전드 홍보 검증")
print()

print("[1] 레전드가 없으면 조용하다")
inter, ch = make(channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("n19"), card("e08")],
                          shown_publicly=False, summary=SUMMARY))
check("일반·에픽만 뽑으면 뽑기방에 아무것도 안 간다", len(ch.sent) == 0, f"{len(ch.sent)}건")

print()
print("[2] 다른 채널에서 뽑은 레전드는 뽑기방에 홍보된다")
inter, ch = make(channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("l06")], shown_publicly=False, summary=SUMMARY))
check("홍보가 1건 간다", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    embed = ch.sent[0]["embed"]
    check("임베드에 카드 이름이 있다", embed is not None and "수호악귀" in embed.title,
          getattr(embed, "title", None))
    check("뽑은 사람을 멘션으로 적는다",
          embed is not None and "<@12345>" in (embed.description or ""))
    check("레전드 도감 진행도가 들어간다",
          any(f.name == "레전드 도감" for f in (embed.fields if embed else [])))
    check("일반 레전드는 content(멘션 줄)가 없다", ch.sent[0]["content"] is None,
          str(ch.sent[0]["content"]))

print()
print("[3] 🚨 뽑기방에서 공개로 뽑아도 홍보는 올라간다 (그림만 생략)")
print("    - 지금 뽑기의 거의 전부가 이 경로예요. 건너뛰면 기능이 안 터져요.")
inter, ch = make(channel_id=CARD_CHANNEL)
run(gacha.announce_legend(inter, [card("l06")], shown_publicly=True, summary=SUMMARY))
check("공개 뽑기에서도 홍보가 간다", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    embed = ch.sent[0]["embed"]
    check("임베드는 그대로 있다", embed is not None and "수호악귀" in embed.title)
    check("같은 그림을 두 번 안 띄운다", ch.sent[0]["file"] is None
          and embed.image.url is None, str(embed.image.url))

print()
print("[3-1] 다른 채널(본인에게만 보인 뽑기)에서는 그림까지 붙는다")
inter, ch = make(channel_id=OTHER_CHANNEL)


async def with_image(drawn):
    return b"PNG"


gacha.card_render.render_pull = with_image
run(gacha.announce_legend(inter, [card("l06")], shown_publicly=False, summary=SUMMARY))
check("그림이 첨부된다", bool(ch.sent) and ch.sent[0]["file"] is not None)
if ch.sent:
    check("임베드가 그 그림을 가리킨다",
          (ch.sent[0]["embed"].image.url or "").startswith("attachment://"),
          str(ch.sent[0]["embed"].image.url))
gacha.card_render.render_pull = no_image

print()
print("[4] 나쁜말악귀 -> 🥈 부방장 멘션")
inter, ch = make(channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("l02")], shown_publicly=False, summary=SUMMARY))
check("홍보가 1건 간다", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    content = ch.sent[0]["content"] or ""
    mentions = ch.sent[0]["allowed_mentions"]
    vice = next(r for r in inter.guild.roles if r.name == "🥈 부방장")
    check("content에 부방장 역할 멘션이 들어간다", vice.mention in content, content)
    check("나쁜말악귀라고 알려준다", "나쁜말악귀" in content, content)
    check("allowed_mentions.roles에 부방장만 있다",
          mentions is not None and list(getattr(mentions, "roles", []) or []) == [vice],
          str(getattr(mentions, "roles", None)))
    check("[10] 뽑은 사람에게는 핑이 안 간다",
          mentions is not None and mentions.users is False, str(mentions.users))
    check("@everyone은 안 쏜다",
          mentions is not None and mentions.everyone is False, str(mentions.everyone))
    check("임베드도 같이 간다", ch.sent[0]["embed"] is not None)

print()
print("[5] 뽑기방 공개 뽑기 + 나쁜말악귀 -> 멘션도 같이 간다")
inter, ch = make(channel_id=CARD_CHANNEL)
run(gacha.announce_legend(inter, [card("l02")], shown_publicly=True, summary=SUMMARY))
check("한 건만 간다", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    check("멘션이 들어있다", "<@&" in (ch.sent[0]["content"] or ""),
          str(ch.sent[0]["content"]))
    check("임베드도 같이 간다", ch.sent[0]["embed"] is not None)

print()
print("[6] 👑 방장을 멘션하지 않는다 (`방장` ⊂ `부방장` 부분일치 함정)")
inter, ch = make(roles=("👑 방장",), channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("l02")], shown_publicly=False, summary=SUMMARY))
check("홍보는 간다", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    check("방장만 있는 서버에선 멘션을 안 붙인다", ch.sent[0]["content"] is None,
          str(ch.sent[0]["content"]))

print()
print("[7] 🥈 부방장 역할이 없어도 홍보는 올라간다")
inter, ch = make(roles=(), channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("l02")], shown_publicly=False, summary=SUMMARY))
check("역할이 없어도 홍보 1건", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    check("멘션만 빠진다", ch.sent[0]["content"] is None, str(ch.sent[0]["content"]))

print()
print("[8] 뽑기방을 못 찾으면 조용히 넘어간다")
inter, ch = make(channel_id=OTHER_CHANNEL, with_channel=False)
try:
    run(gacha.announce_legend(inter, [card("l02")], shown_publicly=False, summary=SUMMARY))
    check("예외 없이 넘어간다", True)
except Exception as exc:  # noqa: BLE001
    check("예외 없이 넘어간다", False, repr(exc))

print()
print("[8-1] DM(guild=None)에서도 안 터진다")
inter = FakeInteraction(OTHER_CHANNEL, None)
try:
    run(gacha.announce_legend(inter, [card("l02")], shown_publicly=False, summary=SUMMARY))
    check("예외 없이 넘어간다", True)
except Exception as exc:  # noqa: BLE001
    check("예외 없이 넘어간다", False, repr(exc))

print()
print("[8-2] 천장으로 나온 레전드는 ⭐천장이라고 적어준다")
inter, ch = make(channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("l06", pity=True)], shown_publicly=False,
                          summary=SUMMARY))
check("천장 표시가 들어간다",
      bool(ch.sent) and any(f.name == "천장" for f in ch.sent[0]["embed"].fields))

print()
print("[8-3] 한 번에 레전드 2장이면 둘 다 적는다")
inter, ch = make(channel_id=OTHER_CHANNEL)
run(gacha.announce_legend(inter, [card("l06"), card("l02")], shown_publicly=False,
                          summary=SUMMARY))
if ch.sent:
    embed, content = ch.sent[0]["embed"], ch.sent[0]["content"] or ""
    check("제목이 '2장'이다", "2장" in embed.title, embed.title)
    check("둘 다 이름이 들어간다",
          "수호악귀" in embed.description and "나쁜말악귀" in embed.description)
    check("섞여 있어도 부방장 멘션은 붙는다", "<@&" in content, content)

print()
print("[9] 홍보가 터져도 do_pull은 성공으로 끝난다")


class FakeWallet:
    def __init__(self, balance=100):
        self.balance = balance
        self.log = []

    async def spend(self, user_id, amount, *, reason=""):
        if self.balance < amount:
            return False
        self.balance -= amount
        self.log.append(("spend", amount, reason))
        return True

    async def add(self, user_id, amount, *, reason=""):
        self.balance += amount
        self.log.append(("add", amount, reason))
        return self.balance

    async def get_balance(self, user_id):
        return self.balance


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, *, embed=None, file=None, view=None,
                   ephemeral=False):
        self.sent.append({"content": content, "embed": embed, "ephemeral": ephemeral})


wallet = FakeWallet(100)
gacha.coin_wallet = wallet


async def fake_pull(user_id, n=3):
    return [card("l02")]


async def fake_get(user_id):
    return {"counts": {"l02": 1}, "draws": 1, "since_legend": 0}


gacha.card_store.pull = fake_pull
gacha.card_store.get_collection = fake_get

inter, ch = make(channel_id=OTHER_CHANNEL)
inter.followup = FakeFollowup()


async def boom(*args, **kwargs):
    raise RuntimeError("홍보 실패 재현")


real_announce = gacha.announce_legend
gacha.announce_legend = boom
try:
    run(gacha.do_pull(inter, ephemeral=True))
    check("홍보가 터져도 do_pull이 예외를 안 올린다", True)
except Exception as exc:  # noqa: BLE001
    check("홍보가 터져도 do_pull이 예외를 안 올린다", False, repr(exc))
finally:
    gacha.announce_legend = real_announce
check("결과는 유저에게 그대로 갔다", len(inter.followup.sent) == 1,
      f"{len(inter.followup.sent)}건")
check("코인 환불은 일어나지 않았다",
      [k for k, *_ in wallet.log] == ["spend"], str(wallet.log))

print()
print("[9-1] 정상 경로: do_pull이 홍보까지 이어서 보낸다 (배선 검증)")
wallet2 = FakeWallet(100)
gacha.coin_wallet = wallet2
inter, ch = make(channel_id=OTHER_CHANNEL)
inter.followup = FakeFollowup()
run(gacha.do_pull(inter, ephemeral=True))
check("유저에게 결과가 갔다", len(inter.followup.sent) == 1, f"{len(inter.followup.sent)}건")
check("뽑기방에 홍보가 갔다", len(ch.sent) == 1, f"{len(ch.sent)}건")
if ch.sent:
    check("부방장 멘션까지 붙었다", "<@&" in (ch.sent[0]["content"] or ""),
          str(ch.sent[0]["content"]))

# ⚠️ 새 섹션은 **이 요약 블록 위**에 넣으세요. 아래에 붙이면 FAIL이 집계되지 않아
#    종료코드가 0으로 나오고 배포 관문이 거짓 통과해요
#    -> [[feedback_handrolled_test_summary_at_end]]
print()
print("=" * 60)
if failures:
    print(f"❌ {len(failures)}건 실패")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
