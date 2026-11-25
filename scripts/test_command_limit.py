"""전역 슬래시 명령어 한도(100개) 검사 — 운영과 같은 순서로 **모든** cog를 실어서 세요. 디스코드에는 안 붙어요.

🚨 2026-11-26 사고: 전역 명령어가 **딱 100개**인 상태에서 `/내작전판`·`/작전판패널`을 더해 102개가 됐고,
   배포하자마자 봇이 시작하다가 꺼졌어요(`CommandLimitReached` → 운영 봇 정지).
   `test_cog_load.py`는 일부 cog만 실어서 못 잡았어요. 그래서 여기서는 `bot.py`의 `COG_GROUPS`를 전부 실어요.

- 로컬 PC에는 `tzdata`(Asia/Seoul)와 `yt_dlp`가 없어서 cog 4개가 안 실려요. 세는 데는 필요 없으니 흉내만 내요.
- 한도는 **전역 슬래시(chat input) 100개**. 그룹(`/도박 ...`)은 하위 명령이 몇 개든 1개로 쳐요.
  우클릭 메뉴는 따로 세요(종류별 5개).
- 🚨 새 기능은 명령어를 늘리지 말고 **기존 명령어의 옵션·그룹·패널 버튼**으로 넣어 주세요.

    python scripts/test_command_limit.py        # 단독 실행. `test_cog_load.py`도 이걸 불러요.
"""
import asyncio
import os
import sys
import types
from datetime import timedelta, timezone
from unittest.mock import MagicMock

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"     # 운영 DB를 건드리지 않아요
os.environ["BIRTHDAY_DB_NAME"] = "agwi_profile_test"
os.environ["PORT"] = "0"                                 # 작전판 웹 서버: 빈 포트 아무거나(다른 테스트와 안 겹치게)

LIMIT = 100          # 디스코드 전역 슬래시 명령어 한도
MENU_LIMIT = 5       # 우클릭 메뉴(메시지·사용자) 종류별 한도

# ---- 로컬에 없는 것 흉내 (세는 데는 필요 없어요) ----
import zoneinfo  # noqa: E402

try:
    zoneinfo.ZoneInfo("Asia/Seoul")
except zoneinfo.ZoneInfoNotFoundError:
    _RealZone = zoneinfo.ZoneInfo

    def _zone(key):
        try:
            return _RealZone(key)
        except zoneinfo.ZoneInfoNotFoundError:
            return timezone(timedelta(hours=9), key)     # 서버는 전부 KST만 써요

    zoneinfo.ZoneInfo = _zone

try:
    import yt_dlp  # noqa: F401
except ModuleNotFoundError:
    _fake = types.ModuleType("yt_dlp")
    _fake.YoutubeDL = MagicMock()
    _fake.utils = MagicMock()
    _fake.version = types.SimpleNamespace(__version__="없음(테스트)")
    sys.modules["yt_dlp"] = _fake
    sys.modules["yt_dlp.utils"] = _fake.utils

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402


async def main() -> int:
    import bot as bot_module            # `COG_GROUPS`만 읽어요(봇을 켜지 않아요)

    names = [name for group in bot_module.COG_GROUPS.values() for name in group]
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    def slash():
        return {c.name for c in bot.tree.get_commands(type=discord.AppCommandType.chat_input)}

    per, broken = {}, []
    for name in names:
        before = slash()
        try:
            await bot.load_extension(f"cogs.{name}")
        except Exception as exc:  # noqa: BLE001
            cause = exc.__cause__ or exc
            broken.append(f"{name} → {type(cause).__name__}: {str(cause)[:150]}")
            continue
        added = sorted(slash() - before)
        if added:
            per[name] = added

    total = len(slash())
    menus = {
        "메시지 우클릭": len(bot.tree.get_commands(type=discord.AppCommandType.message)),
        "사용자 우클릭": len(bot.tree.get_commands(type=discord.AppCommandType.user)),
    }
    for name, added in sorted(per.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(added):2d}  {name:16s} " + " ".join("/" + x for x in added))
    print(f"\n전역 슬래시 명령어: {total}개 / 한도 {LIMIT}개 (남은 자리 {LIMIT - total}개) · cog {len(names)}개")
    print("우클릭 메뉴: " + ", ".join(f"{k} {v}개" for k, v in menus.items()) + f" / 한도 각 {MENU_LIMIT}개")

    ok = True
    for line in broken:
        ok = False
        print(f"❌ cog를 못 실었어요: {line}")
    if total > LIMIT:
        ok = False
        print(f"❌ 전역 슬래시 명령어가 {total}개예요 — 한도 {LIMIT}개를 넘으면 봇이 시작하다가 꺼져요.")
    for kind, n in menus.items():
        if n > MENU_LIMIT:
            ok = False
            print(f"❌ {kind} 메뉴가 {n}개예요 (한도 {MENU_LIMIT}개).")
    if ok:
        print("✅ 명령어 한도 안이에요" + (" — 🚨 남은 자리가 없어요. 새 명령어는 못 늘려요." if total == LIMIT else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    finally:
        sys.stdout.flush()
        os._exit(code)      # 실어 둔 cog들의 반복 작업·웹 서버를 기다리지 않고 바로 끝내요
