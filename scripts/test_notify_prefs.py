"""`/알림설정`(개인별 알림 끄기) 검증. 실제 DB·디스코드 없이 돌아가요.

2026-10-05에 만들었어요. "미션을 깨면 알림이 떠서 방해된다"는 이야기가 나와서요.

여기서 확인하는 것:
  1) notify_prefs 저장 규칙 - 기본은 전부 켜짐, 끈 것만 목록으로 남는다
  2) 알림 종류를 나중에 추가해도 기존 유저는 켜진 상태다 (off-list 설계의 핵심)
  3) DB가 흔들리면 "보내는 쪽"으로 기운다 (코인 지급 안내가 조용히 사라지면 분쟁이 돼요)
  4) 미션 알림이 실제로 막히는지 - 채널 알림/자동판정 DM 둘 다
  5) 켜진 사람에게 가는 채널 알림은 핑을 쏘지 않는다 (allowed_mentions)
  6) /알림설정 화면이 디스코드 컴포넌트 한도 안에 들어가고 버튼이 토글된다
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
# pokemon_store가 import 시점에 Mongo 클라이언트를 만들어요(연결은 지연돼서 안 붙어요).
# 혹시라도 실제로 붙는 일이 없게 테스트 DB 이름을 박아둬요.
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_notify_test"

import discord

from utils import notify_prefs

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
# 가짜 컬렉션 - find_one / update_one($pull, $addToSet, upsert)만 흉내내요.
# ------------------------------------------------------------------
class FakeCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.writes = 0

    def find_one(self, flt, projection=None):
        return self.docs.get(flt["_id"])

    def update_one(self, flt, update, upsert=False):
        self.writes += 1
        uid = flt["_id"]
        doc = self.docs.get(uid)
        if doc is None:
            if not upsert:
                return  # 문서가 없으면 $pull은 아무 일도 안 해야 해요.
            doc = self.docs[uid] = {"_id": uid}
        for key, value in (update.get("$addToSet") or {}).items():
            bucket = doc.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
        for key, value in (update.get("$pull") or {}).items():
            doc[key] = [v for v in (doc.get(key) or []) if v != value]


fake = FakeCollection()
notify_prefs._prefs = fake

print("1) 아무 설정도 안 한 사람은 전부 켜짐")
states = asyncio.run(notify_prefs.get_all(1))
check("알림 종류가 3개", len(states) == 3, str(sorted(states)))
check("전부 True", all(states.values()), str(states))
check("조회만으로 문서를 만들지 않는다", fake.writes == 0 and not fake.docs)

print("2) 하나를 끄면 그것만 꺼진다")
asyncio.run(notify_prefs.set_enabled(1, "mission_dm", False))
states = asyncio.run(notify_prefs.get_all(1))
check("mission_dm 꺼짐", states["mission_dm"] is False)
check("나머지는 그대로 켜짐", states["mission_channel"] and states["wishlist_dm"], str(states))
check("is_enabled도 같은 답", asyncio.run(notify_prefs.is_enabled(1, "mission_dm")) is False)
check("끈 것만 저장된다", fake.docs["1"]["off"] == ["mission_dm"], str(fake.docs["1"]))

print("3) 두 번 꺼도 중복으로 쌓이지 않고, 다시 켜면 목록에서 빠진다")
asyncio.run(notify_prefs.set_enabled(1, "mission_dm", False))
check("중복 없음", fake.docs["1"]["off"] == ["mission_dm"], str(fake.docs["1"]))
asyncio.run(notify_prefs.set_enabled(1, "mission_dm", True))
check("다시 켜짐", asyncio.run(notify_prefs.is_enabled(1, "mission_dm")) is True)
check("목록이 비었다", fake.docs["1"]["off"] == [], str(fake.docs["1"]))

print("4) 남의 설정에 영향이 없다")
asyncio.run(notify_prefs.set_enabled(1, "wishlist_dm", False))
check("1번은 꺼짐", asyncio.run(notify_prefs.is_enabled(1, "wishlist_dm")) is False)
check("2번은 켜짐", asyncio.run(notify_prefs.is_enabled(2, "wishlist_dm")) is True)

print("5) 알림 종류를 나중에 추가해도 기존 유저는 켜진 상태다")
# 이게 off-list로 저장하는 이유예요. 켠 목록으로 담으면 새 알림이 전원 꺼진 채 시작해요.
notify_prefs.NOTIFY_KINDS["새알림_테스트"] = {"emoji": "🆕", "title": "새 알림", "desc": "테스트용"}
try:
    check("기존 유저도 새 알림은 켜짐", asyncio.run(notify_prefs.is_enabled(1, "새알림_테스트")) is True)
    check("화면에도 4개가 뜬다", len(asyncio.run(notify_prefs.get_all(1))) == 4)
finally:
    del notify_prefs.NOTIFY_KINDS["새알림_테스트"]

print("6) DB가 흔들리면 보내는 쪽으로 기운다")


class BrokenCollection:
    def find_one(self, *a, **kw):
        raise RuntimeError("DB 끊김")


notify_prefs._prefs = BrokenCollection()
check("조회 실패 시 True", asyncio.run(notify_prefs.is_enabled(1, "mission_dm")) is True)
notify_prefs._prefs = fake

# ------------------------------------------------------------------
# 미션 알림이 실제로 막히는지
# ------------------------------------------------------------------
print("7) 미션 채널 알림 / 자동판정 DM 차단")

from cogs import mission as mission_cog  # noqa: E402
from utils import coin_wallet, mission_store  # noqa: E402


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class FakeUser:
    def __init__(self):
        self.dms = []

    async def send(self, content=None, **kwargs):
        self.dms.append(content)


class FakeBot:
    def __init__(self, user):
        self._user = user

    def get_user(self, user_id):
        return self._user


fake_user = FakeUser()
# __init__이 tasks.loop을 start()하면 이벤트 루프가 필요해요. 알림 함수만 보면 되니 건너뛰어요.
cog = mission_cog.Mission.__new__(mission_cog.Mission)
cog.bot = FakeBot(fake_user)

# 코인 지급·진행도 저장은 DB를 타니까 통째로 가짜로 바꿔요.
mission_store.progress = lambda *a, **kw: _async(True)
coin_wallet.add = lambda *a, **kw: _async(7)
coin_wallet.get_balance = lambda *a, **kw: _async(7)
mission_cog.mission_store.progress = mission_store.progress
mission_cog.coin_wallet.add = coin_wallet.add
mission_cog.coin_wallet.get_balance = coin_wallet.get_balance


async def _async(value):
    return value


asyncio.run(notify_prefs.set_enabled(10, "mission_channel", True))
ch = FakeChannel()
asyncio.run(cog._complete(10, "use_rank", ch))
check("켠 사람에겐 채널 알림이 간다", len(ch.sent) == 1, str(ch.sent))
if ch.sent:
    mentions = ch.sent[0][1].get("allowed_mentions")
    check(
        "핑은 안 쏜다 (allowed_mentions.none)",
        mentions is not None and mentions.users is False,
        repr(mentions),
    )

asyncio.run(notify_prefs.set_enabled(11, "mission_channel", False))
ch2 = FakeChannel()
asyncio.run(cog._complete(11, "use_rank", ch2))
check("끈 사람에겐 채널 알림이 안 간다", ch2.sent == [], str(ch2.sent))

asyncio.run(notify_prefs.set_enabled(12, "mission_dm", False))
asyncio.run(cog._notify_auto_complete(12, ["val_play"]))
check("끈 사람에겐 자동판정 DM이 안 간다", fake_user.dms == [], str(fake_user.dms))

asyncio.run(cog._notify_auto_complete(13, ["val_play"]))
check("켠 사람에겐 자동판정 DM이 간다", len(fake_user.dms) == 1, str(fake_user.dms))

print("8) 계정을 못 찾았다는 안내는 설정과 무관하게 간다")
fake_user.dms.clear()
asyncio.run(cog._notify_account_missing(12))  # 12번은 위에서 mission_dm을 껐어요
check("안내 DM은 그대로 간다", len(fake_user.dms) == 1, str(fake_user.dms))

# ------------------------------------------------------------------
# 화면
# ------------------------------------------------------------------
print("9) /알림설정 화면")

from cogs.notify import NotifySettingsView, _build_embed  # noqa: E402

states = {"mission_channel": True, "mission_dm": False, "wishlist_dm": True}
view = NotifySettingsView(10, states)
payload = view.to_components()
rows = len(payload)
buttons = [c for row in payload for c in row.get("components", [])]
check("버튼이 알림 종류 수만큼", len(buttons) == len(notify_prefs.NOTIFY_KINDS), str(len(buttons)))
check("줄 수가 5줄 이하", rows <= 5, f"{rows}줄")
check("한 줄에 5개 이하", all(len(row.get("components", [])) <= 5 for row in payload))
labels = [c.get("label", "") for c in buttons]
check("켠 것은 '켜짐'으로 보인다", any("켜짐" in label for label in labels), str(labels))
check("끈 것은 '꺼짐'으로 보인다", any("꺼짐" in label for label in labels), str(labels))
check(
    "켜짐은 초록 / 꺼짐은 회색",
    sorted(c["style"] for c in buttons) == sorted([
        discord.ButtonStyle.success.value, discord.ButtonStyle.secondary.value,
        discord.ButtonStyle.success.value,
    ]),
    str([c["style"] for c in buttons]),
)

embed = _build_embed(states)
check("임베드 필드가 알림 종류 수만큼", len(embed.fields) == len(notify_prefs.NOTIFY_KINDS))
check("꺼진 항목이 제목에 표시된다", any("🔕" in f.name for f in embed.fields))
check("켜진 항목이 제목에 표시된다", any("🔔" in f.name for f in embed.fields))

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
