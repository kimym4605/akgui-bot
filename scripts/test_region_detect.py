# -*- coding: utf-8 -*-
"""🌏 계정 지역(region) 처리를 확인해요. 디스코드·실제 API 없이 돌아가요.

2026-11-03에 찾은 버그예요. 지역이 `"kr"`로 **세 군데에 따로 박혀** 있어서,
아시아(ap) 서버 계정은 `/전적`·발로 미션 자동판정·내전 KDA가 전부 조용히 실패했어요.

🚨🚨 **틀린 지역에서 두 엔드포인트가 다르게 실패해요** (실측, 같은 ap 계정 기준):

| 엔드포인트 | 틀린 지역(kr)으로 물었을 때 | 쓰는 곳 |
|---|---|---|
| `v3/mmr`     | **404** `No MMR data available for this user` | `/전적`의 티어·RR |
| `v3/matches` | **200 + 빈 목록** (에러가 아니에요)           | 미션 자동판정 · 내전 KDA |

matches 쪽이 더 고약해요. 에러가 아니라 *"오늘 경기가 없는 사람"*처럼 보여서
**로그 한 줄 없이** 발로란트 미션이 영원히 안 깨졌어요. 그래서 404만 기다리는 복구
코드는 미션 쪽에서 **한 번도 안 걸려요** — 이 테스트가 그걸 지켜요.

여기서 확인하는 것:
  1) 저장소가 지역을 저장·반환하고, **옛 데이터(지역 없음)와도 호환**된다
  2) `get_region`은 모를 때 None이다 — 'kr'로 뭉개면 고칠 기회를 영영 놓친다
  3) `set_region`이 기존 등록만 고치고, 값이 같으면 안 쓴다
  4) `detect_region`이 `data.region`을 꺼내고, 404와 일시적 실패를 가른다
  5) ⭐ 조회 지역 우선순위: 고른 값 > 등록된 값 > 기본값(kr)
  6) ⭐ 아시아 계정이 빈 결과를 받으면 **지역을 고쳐 다시 조회**하고, 그 값을 저장한다
     🚨 matches는 틀린 지역에 404가 아니라 **200 + 빈 목록**을 준다(실측). 404만
        기다리면 이 복구가 영원히 안 걸린다.
  7) 🚨 정상 경로에서는 지역 조회를 **한 번도 안 한다** (분당 30회를 전체가 나눠 씀)
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)

from utils import henrik_api, riot_account_store  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# 🚨 진짜 data/riot_accounts.json을 건드리면 안 돼요. 임시 파일로 갈아끼워요.
_tmp = Path(tempfile.mkdtemp()) / "riot_accounts.json"
riot_account_store.DATA_FILE = _tmp

ME, OTHER = 111, 222

print("1) 지역을 저장하고 돌려준다 / 옛 데이터와 호환된다")
riot_account_store.set_account(ME, "악귀", "KR1", region="ap")
check("닉네임·태그는 그대로", riot_account_store.get_account(ME) == ("악귀", "KR1"),
      str(riot_account_store.get_account(ME)))
check("지역을 돌려준다", riot_account_store.get_region(ME) == "ap",
      str(riot_account_store.get_region(ME)))

# 지역 없이 등록 = 2026-11-03 이전에 등록된 사람들의 모양
riot_account_store.set_account(OTHER, "구계정", "OLD")
check("옛 데이터도 읽힌다", riot_account_store.get_account(OTHER) == ("구계정", "OLD"))

print("2) 모르는 지역은 None이다 (기본값으로 뭉개지 않는다)")
check("지역 없으면 None", riot_account_store.get_region(OTHER) is None,
      repr(riot_account_store.get_region(OTHER)))
check("등록 자체가 없으면 None", riot_account_store.get_region(999) is None)
check("기본값 상수는 kr", riot_account_store.DEFAULT_REGION == "kr")

print("3) set_region은 기존 등록만 고친다")
check("미등록이면 False", riot_account_store.set_region(999, "ap") is False)
check("고치면 True", riot_account_store.set_region(OTHER, "ap") is True)
check("실제로 저장됐다", riot_account_store.get_region(OTHER) == "ap")
check("같은 값이면 안 쓴다(False)", riot_account_store.set_region(OTHER, "ap") is False)
check("닉네임·태그는 안 건드린다", riot_account_store.get_account(OTHER) == ("구계정", "OLD"),
      str(riot_account_store.get_account(OTHER)))


# ----------------------------------------------------------------------
# henrik_api.request를 가짜로 바꿔서, 호출 경로와 횟수를 눈으로 본다
# ----------------------------------------------------------------------
class FakeApi:
    """경로별로 정해둔 응답을 돌려주고, 어떤 경로를 몇 번 불렀는지 기록해요."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def request(self, session, path, *, headers, params=None, **kwargs):
        self.calls.append(path)
        for prefix, result in self.routes.items():
            if path.startswith(prefix):
                return result
        # 🚨 **틀린 지역의 기본 응답은 엔드포인트마다 달라요** (2026-11-03 실측):
        #    · mmr     → 404 `No MMR data available for this user`
        #    · matches → **HTTP 200 + 빈 목록** (에러가 아니라 "경기 없음"처럼 보여요)
        #    이걸 둘 다 404로 흉내내면, 실제로는 안 걸리는 복구 경로를 통과시켜요.
        if "/v3/matches/" in path:
            return 200, {"data": []}
        return 404, {"errors": [{"message": "No MMR data available for this user"}]}

    def count(self, needle):
        return sum(1 for p in self.calls if needle in p)


_real_request = henrik_api.request

print("4) detect_region이 data.region을 꺼내고, 404와 일시적 실패를 가른다")
fake = FakeApi({"/valorant/v1/account": (200, {"data": {"region": "ap"}})})
henrik_api.request = fake.request
region, status = asyncio.run(henrik_api.detect_region(None, {}, "악귀", "KR1"))
check("지역을 꺼낸다", (region, status) == ("ap", 200), f"{region} {status}")
check("v1/account 경로로 물었다", fake.count("/valorant/v1/account") == 1, str(fake.calls))

fake = FakeApi({"/valorant/v1/account": (404, {"errors": [{"message": "not found"}]})})
henrik_api.request = fake.request
region, status = asyncio.run(henrik_api.detect_region(None, {}, "없는", "계정"))
check("404는 region=None + status=404", (region, status) == (None, 404), f"{region} {status}")

fake = FakeApi({"/valorant/v1/account": (429, {})})
henrik_api.request = fake.request
region, status = asyncio.run(henrik_api.detect_region(None, {}, "악귀", "KR1"))
check("429도 region=None이지만 status가 다르다 (영구 실패 아님)",
      (region, status) == (None, 429), f"{region} {status}")

fake = FakeApi({"/valorant/v1/account": (200, {"data": {}})})
henrik_api.request = fake.request
region, _ = asyncio.run(henrik_api.detect_region(None, {}, "악귀", "KR1"))
check("200인데 region이 비면 None", region is None, repr(region))

henrik_api.request = _real_request

print("5) ⭐ 조회 지역 우선순위: 고른 값 > 등록된 값 > 기본값")
# `cogs/rank.py`가 쓰는 식과 **같은 식**이에요. 여기서 깨지면 거기서도 깨져요.
def resolve(picked, user_id):
    return picked or (riot_account_store.get_region(user_id)
                      or riot_account_store.DEFAULT_REGION)

riot_account_store.set_account(ME, "악귀", "KR1", region="ap")
check("고른 값이 1순위", resolve("na", ME) == "na", resolve("na", ME))
check("안 고르면 등록된 값", resolve(None, ME) == "ap", resolve(None, ME))
riot_account_store.set_account(ME, "악귀", "KR1")        # 지역 없는 상태로 되돌림
check("둘 다 없으면 kr", resolve(None, ME) == "kr", resolve(None, ME))

print("6) ⭐ 틀린 지역(200+빈 목록) → 지역을 고쳐 다시 조회하고, 저장까지 한다")
# 🚨 흐름을 흉내내지 않고 **`cogs/mission.py`의 진짜 함수**를 불러요. 흉내내면 그 안에
#    생긴 버그를 못 잡아요(테스트는 통과하는데 봇은 고장난 상태가 돼요).
os.environ.setdefault("HENRIKDEV_API_KEY", "테스트용-가짜키")
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
from cogs.mission import Mission  # noqa: E402


class FakeSelf:
    """`_fetch_recent_matches`가 self에서 쓰는 건 `_get_session()` 하나뿐이에요."""

    async def _get_session(self):
        return None


async def lookup(user_id, api):
    """진짜 `Mission._fetch_recent_matches`를 호출해요. 지역은 등록값에서 나와요."""
    _, status = await Mission._fetch_recent_matches(
        FakeSelf(), "악귀", "KR1", user_id=user_id
    )
    # 마지막으로 찌른 matches 경로에서 "어느 지역을 썼는지"를 읽어요.
    used = [p for p in api.calls if "/v3/matches/" in p]
    region = used[-1].split("/v3/matches/")[1].split("/")[0] if used else None
    return region, status


fake = FakeApi({
    "/valorant/v3/matches/ap/": (200, {"data": [{"ok": True}]}),
    "/valorant/v1/account": (200, {"data": {"region": "ap"}}),
    # kr은 등록 안 함 → FakeApi 기본값인 "200 + 빈 목록"이 나와요 (실제와 같은 모양)
})
henrik_api.request = fake.request
region, status = asyncio.run(lookup(ME, fake))
check("ap로 다시 조회해 성공", (region, status) == ("ap", 200), f"{region} {status}")
check("kr로 먼저 찔러봤다(빈 목록을 받았다)", fake.count("/matches/kr/") == 1, str(fake.calls))
check("지역을 알아봤다", fake.count("/valorant/v1/account") == 1, str(fake.calls))
check("⭐ 고친 지역을 저장했다", riot_account_store.get_region(ME) == "ap",
      repr(riot_account_store.get_region(ME)))

print("7) 🚨 두 번째부터는 지역 조회를 안 한다 (호출 한도를 더 안 깎는다)")
fake2 = FakeApi({
    "/valorant/v3/matches/ap/": (200, {"data": [{"ok": True}]}),
    "/valorant/v1/account": (200, {"data": {"region": "ap"}}),
})
henrik_api.request = fake2.request
region, status = asyncio.run(lookup(ME, fake2))
check("바로 ap로 간다", (region, status) == ("ap", 200), f"{region} {status}")
check("kr은 아예 안 찔러본다", fake2.count("/matches/kr/") == 0, str(fake2.calls))
check("⭐ 지역 조회가 0회", fake2.count("/valorant/v1/account") == 0, str(fake2.calls))
check("호출이 딱 1회", len(fake2.calls) == 1, str(fake2.calls))

print("   그리고 한국 계정은 원래부터 추가 호출이 없어야 해요")
riot_account_store.set_account(OTHER, "한국", "KR1", region="kr")
fake3 = FakeApi({"/valorant/v3/matches/kr/": (200, {"data": []})})
henrik_api.request = fake3.request
region, status = asyncio.run(lookup(OTHER, fake3))
check("kr 계정은 한 번에 끝난다", (region, status) == ("kr", 200) and len(fake3.calls) == 1,
      f"{region} {status} {fake3.calls}")

henrik_api.request = _real_request

print("8) 🚨 한국 사람이 그냥 안 한 날도 **딱 한 번만** 물어본다")
# 여기가 한도 사고가 날 자리예요. 빈 목록마다 지역을 물어보면, 안 한 사람 1명당
# 하루 48번(30분마다) 헛호출이 나가요. 25명이면 하루 1,200회 — 분당 30회 한도가 터져요.
# 그래서 "지역을 아직 모르는 사람"에게만 묻고, **알아낸 값이 kr이어도 저장**해서 빠져나와요.
IDLE = 333
riot_account_store.set_account(IDLE, "안한사람", "KR1")      # 지역 모름
fake4 = FakeApi({"/valorant/v1/account": (200, {"data": {"region": "kr"}})})
henrik_api.request = fake4.request
asyncio.run(lookup(IDLE, fake4))
check("처음엔 한 번 물어본다", fake4.count("/valorant/v1/account") == 1, str(fake4.calls))
check("⭐ kr이어도 저장해둔다", riot_account_store.get_region(IDLE) == "kr",
      repr(riot_account_store.get_region(IDLE)))
check("같은 지역이라 재조회는 안 한다", fake4.count("/matches/") == 1, str(fake4.calls))

fake5 = FakeApi({"/valorant/v1/account": (200, {"data": {"region": "kr"}})})
henrik_api.request = fake5.request
asyncio.run(lookup(IDLE, fake5))
check("⭐ 다음부터는 안 물어본다", fake5.count("/valorant/v1/account") == 0, str(fake5.calls))
check("호출이 딱 1회", len(fake5.calls) == 1, str(fake5.calls))

print("   지역을 못 알아내면(429) 저장하지 않고 다음에 다시 시도한다")
LATER = 444
riot_account_store.set_account(LATER, "나중에", "KR1")
fake6 = FakeApi({"/valorant/v1/account": (429, {})})
henrik_api.request = fake6.request
asyncio.run(lookup(LATER, fake6))
check("429면 저장 안 함", riot_account_store.get_region(LATER) is None,
      repr(riot_account_store.get_region(LATER)))

henrik_api.request = _real_request

print()
if failures:
    print(f"❌ 실패 {len(failures)}건: {failures}")
    sys.exit(1)
print("✅ 전부 통과")
