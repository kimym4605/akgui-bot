"""cog 로딩 + 슬래시 명령 정의 검증. 디스코드에 접속하지 않고 확인해요."""
import asyncio
import os
import sys

BOT_DIR = r"C:\Users\user\Desktop\악귀봇프로젝트\discord-bot-starter-py"
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ["MONGODB_DB_NAME"] = "agwi_profile_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_profile_test"

import discord
from discord.ext import commands

TARGET_COGS = ["attendance", "achievement", "team", "rank", "betting", "mission", "coin"]
NEW_COMMANDS = {"프로필", "업적", "내전전적", "주간랭킹", "내전시즌"}

failed = []


async def main():
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    for name in TARGET_COGS:
        try:
            await bot.load_extension(f"cogs.{name}")
            print(f"  ✅ cogs.{name}")
        except Exception as exc:
            failed.append(name)
            print(f"  ❌ cogs.{name} → {type(exc).__name__}: {exc}")

    print("\n등록된 슬래시 명령:")
    registered = {cmd.name for cmd in bot.tree.get_commands()}
    for name in sorted(NEW_COMMANDS):
        mark = "✅" if name in registered else "❌"
        if name not in registered:
            failed.append(f"/{name}")
        print(f"  {mark} /{name}")

    # /프로필은 **본인 것만** 봐요. 남을 지정하는 옵션이 다시 생기면 잡아내요.
    profile_cmd = next((c for c in bot.tree.get_commands() if c.name == "프로필"), None)
    if profile_cmd:
        params = {p.name for p in profile_cmd.parameters}
        print(f"\n  /프로필 파라미터: {params or '없음 (본인 전용)'}")
        if params:
            failed.append(f"/프로필에 파라미터가 생겼어요: {params}")

    ach_cmd = next((c for c in bot.tree.get_commands() if c.name == "업적"), None)
    if ach_cmd:
        params = {p.name for p in ach_cmd.parameters}
        print(f"  /업적 파라미터: {params}")
        choices = next((p.choices for p in ach_cmd.parameters if p.name == "분야"), [])
        print(f"  /업적 분야 선택지: {len(choices)}개")
        from utils import achievement_data
        # 6개 = CATEGORIES(출석·코인·내전·발로란트·미션·그 외).
        # 2026-09-30 포켓몬 분야가 빠져서 7 → 6이 됐어요. 분야를 더하거나 뺄 땐
        # 이 숫자와 #🤖-봇-사용법 안내문의 업적 개수도 같이 맞춰주세요.
        if len(choices) != len(achievement_data.CATEGORIES):
            failed.append(
                f"/업적 분야 선택지 수 (선택지 {len(choices)}개 "
                f"≠ CATEGORIES {len(achievement_data.CATEGORIES)}개)"
            )

    # /팀짜기 뷰에 승리 보고 버튼이 붙었는지
    from cogs.team import TeamSplitView
    from utils import team_balance
    players = [
        team_balance.Rated(key=i, label=f"P{i}", rating=10.0, tier_index=10, agwi_score=None)
        for i in range(1, 5)
    ]
    candidates = team_balance.balanced_splits(players, limit=3)
    view = TeamSplitView(players, candidates, owner_id=1, source_label="🎧 테스트",
                         initial=(candidates[0][0], candidates[0][1]))
    labels = [item.label for item in view.children]
    print(f"\n  /팀짜기 버튼: {labels}")
    if not any("직접 조정" in (l or "") for l in labels):
        failed.append("직접 조정 버튼")
    # 한 줄에 5개까지만 들어가요. 버튼을 더 늘리면 여기서 걸려요.
    if len(view.children) > 5:
        failed.append(f"/팀짜기 버튼이 {len(view.children)}개 (한 줄 한도 초과)")
    if not any("A팀 승리" in (l or "") for l in labels):
        failed.append("A팀 승리 버튼")
    if not any("B팀 승리" in (l or "") for l in labels):
        failed.append("B팀 승리 버튼")

    # 화면에 떠 있는 편성이 승리 보고 기준과 일치하는지 (다시 섞기 후 갱신되는 부분)
    if view._current != (candidates[0][0], candidates[0][1]):
        failed.append("초기 편성 동기화")
    else:
        print("  ✅ 초기 편성이 승리 보고 기준과 일치")

    await bot.close()

    print("\n" + "=" * 50)
    if failed:
        print("❌ 실패:", ", ".join(failed))
        sys.exit(1)
    print("✅ cog 로딩 · 명령 등록 전부 정상")


asyncio.run(main())
