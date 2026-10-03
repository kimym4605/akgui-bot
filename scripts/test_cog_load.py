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
NEW_COMMANDS = {"프로필", "업적", "내전전적", "주간랭킹", "내전시즌", "팀짜기", "팀보기"}

failed = []

# 디스코드 컴포넌트 타입 번호예요. 2 = 버튼, 3 = 드롭다운(문자열 Select).
_BUTTON, _SELECT = 2, 3
# 한 메시지에 줄은 5개까지, 한 줄에 버튼은 5개까지예요.
_MAX_ROWS, _MAX_PER_ROW = 5, 5


def check_layout(label, view, failed):
    """View가 디스코드 컴포넌트 한도 안에 들어가는지 확인해요.

    `item.row`를 직접 세면 안 돼요 - `add_item`으로 자동 배치하면 None이고, 줄은
    discord.py가 보낼 때 정해요. 그래서 실제 레이아웃 엔진을 돌려서 결과를 봐요."""
    rows = view.to_components()
    shapes = []
    for index, row in enumerate(rows):
        kinds = [c.get("type") for c in row.get("components", [])]
        shapes.append(f"{index}:{len(kinds)}개")
        if len(kinds) > _MAX_PER_ROW:
            failed.append(f"{label} {index}번째 줄에 {len(kinds)}개 (한 줄 {_MAX_PER_ROW}개 초과)")
        # 드롭다운은 한 줄을 통째로 먹어요. 같은 줄에 버튼이 섞이면 디스코드가 거절해요.
        if _SELECT in kinds and len(kinds) > 1:
            failed.append(f"{label} {index}번째 줄에 드롭다운과 다른 항목이 섞임")
    if len(rows) > _MAX_ROWS:
        failed.append(f"{label}이 {len(rows)}줄 ({_MAX_ROWS}줄 초과)")
    print(f"  {label} 레이아웃: {len(rows)}줄 ({', '.join(shapes)})")


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
    from cogs.team import CaptainPickView, MapPickView, MatchMapView, TeamSplitView
    from utils import team_balance, team_store
    players = [
        team_balance.Rated(key=i, label=f"P{i}", rating=10.0, tier_index=10, agwi_score=None)
        for i in range(1, 5)
    ]
    candidates = team_balance.balanced_splits(players, limit=3)
    view = TeamSplitView(
        players, candidates, owner_id=1, guild_id=None, source_label="🎧 테스트",
        initial=(candidates[0][0], candidates[0][1]),
        mode=team_store.MODE_BALANCED, diff=candidates[0][2],
    )
    labels = [item.label for item in view.children]
    print(f"\n  /팀짜기 버튼: {labels}")
    for needed in ("직접 조정", "팀장", "맵", "A팀 승리", "B팀 승리"):
        if not any(needed in (l or "") for l in labels):
            failed.append(f"{needed} 버튼")
    # 디스코드 한도: 5줄까지, 한 줄에 버튼 5개까지, 드롭다운은 한 줄을 통째로 먹어요.
    # `item.row`는 자동 배치(add_item)하면 None이라 직접 세면 틀려요. discord.py의
    # 실제 레이아웃 엔진(to_components)을 돌려서 나온 줄을 검사해요.
    check_layout("/팀짜기", view, failed)

    # 화면에 떠 있는 편성이 승리 보고 기준과 일치하는지 (다시 섞기 후 갱신되는 부분)
    if view._current != (candidates[0][0], candidates[0][1]):
        failed.append("초기 편성 동기화")
    else:
        print("  ✅ 초기 편성이 승리 보고 기준과 일치")

    # 👑 팀장 화면도 디스코드 한도 안에 들어가는지 (드롭다운 2개 + 버튼 3개)
    check_layout("👑 팀장 화면", CaptainPickView(view), failed)
    # 🗺️ 맵 화면 2종 (경기 전 지정 / 승리 보고 뒤 채워넣기)
    check_layout("🗺️ 맵 지정 화면", MapPickView(view), failed)
    check_layout("🗺️ 보고 후 맵 화면", MatchMapView("x" * 24, 1, "요약"), failed)
    # 맵 드롭다운이 25개 한도를 넘지 않는지 (맵이 늘어나면 여기서 걸려요)
    from utils import valorant_maps
    if len(valorant_maps.MAPS) > valorant_maps.MAX_SELECT_OPTIONS:
        failed.append(
            f"맵이 {len(valorant_maps.MAPS)}개 (드롭다운 한도 "
            f"{valorant_maps.MAX_SELECT_OPTIONS}개 초과 — 목록이 잘려요)"
        )
    else:
        print(f"  ✅ 맵 {len(valorant_maps.MAPS)}개 (드롭다운 한도 안)")

    await bot.close()

    print("\n" + "=" * 50)
    if failed:
        print("❌ 실패:", ", ".join(failed))
        sys.exit(1)
    print("✅ cog 로딩 · 명령 등록 전부 정상")


asyncio.run(main())
