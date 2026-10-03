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

    # /채널설정의 기능 그룹 — `/내전전적`은 프로필과 **다른 채널**을 쓰게 갈라놨어요.
    channel_cmd = next((c for c in bot.tree.get_commands() if c.name == "채널설정"), None)
    if channel_cmd is None:
        failed.append("/채널설정 명령어")
    else:
        groups = {c.value: c.name for p in channel_cmd.parameters if p.name == "기능"
                  for c in p.choices}
        print(f"\n  /채널설정 기능 {len(groups)}개: {sorted(groups)}")
        if "scrim_record" not in groups:
            failed.append("/채널설정에 내전전적 그룹(scrim_record)이 없어요")
        if "내전전적" in groups.get("profile", ""):
            failed.append("profile 그룹 설명에 아직 /내전전적이 적혀 있어요")
        if "내전전적" not in groups.get("scrim_record", ""):
            failed.append("scrim_record 그룹 설명에 /내전전적이 안 적혀 있어요")
        if len(groups) > 25:
            failed.append(f"/채널설정 선택지가 {len(groups)}개 (디스코드 한도 25개 초과)")

    # /팀짜기 뷰에 승리 보고 버튼이 붙었는지
    from cogs.team import (
        CaptainPickView, MapPickView, MatchMapView, Session, TeamSplitView,
    )
    from utils import team_balance
    view = TeamSplitView(bot)
    labels = [item.label for item in view.children]
    print(f"\n  /팀짜기 버튼: {labels}")
    for needed in ("직접 조정", "팀장", "맵", "A팀 승리", "B팀 승리"):
        if not any(needed in (l or "") for l in labels):
            failed.append(f"{needed} 버튼")
    # 디스코드 한도: 5줄까지, 한 줄에 버튼 5개까지, 드롭다운은 한 줄을 통째로 먹어요.
    # `item.row`는 자동 배치(add_item)하면 None이라 직접 세면 틀려요. discord.py의
    # 실제 레이아웃 엔진(to_components)을 돌려서 나온 줄을 검사해요.
    check_layout("/팀짜기", view, failed)

    # 🚨 영속 버튼 조건: timeout=None + 모든 버튼에 고정 custom_id.
    # 하나라도 빠지면 `bot.add_view`가 거부하거나, 재시작 뒤 버튼이 죽어요.
    if view.timeout is not None:
        failed.append(f"/팀짜기 뷰에 타임아웃이 있어요({view.timeout}초) — 영속이 아니에요")
    missing = [item.label for item in view.children if not getattr(item, "custom_id", None)]
    if missing:
        failed.append(f"custom_id가 없는 버튼: {missing}")
    ids = [item.custom_id for item in view.children]
    if len(set(ids)) != len(ids):
        failed.append(f"custom_id가 겹쳐요: {ids}")
    try:
        bot.add_view(view)
        print(f"  ✅ 영속 버튼 등록됨 (custom_id {len(ids)}개, 전부 고유)")
    except Exception as exc:
        failed.append(f"bot.add_view 실패: {type(exc).__name__}: {exc}")

    # 🚨 이 View는 봇 전체에 하나만 등록돼서 모든 팀짜기 메시지가 공유해요.
    # 그래서 편성·팀장·맵 같은 **메시지별 상태를 self에 담아두면 안 돼요.**
    # 빈 View의 속성(discord.py 내부용)과 버튼 자체는 빼고, **우리가 담은 것만** 봐요.
    baseline = set(vars(discord.ui.View(timeout=None)))
    allowed = {"_bot", "_fallback_session", "_stats_retries"}
    leaked = [
        name for name, value in vars(view).items()
        if name not in baseline and name not in allowed
        and not isinstance(value, discord.ui.Item)
    ]
    if leaked:
        failed.append(f"뷰에 메시지별 상태가 남아있어요(공유되면 섞여요): {leaked}")
    else:
        print("  ✅ 뷰가 메시지별 상태를 들고 있지 않음")

    # 하위 화면들(ephemeral)은 Session을 받아요. 가짜 세션으로 레이아웃만 봐요.
    players = [
        team_balance.Rated(key=i, label=f"P{i}", rating=10.0, tier_index=10, agwi_score=None)
        for i in range(1, 5)
    ]
    fake = Session(1, {
        "owner_id": 1, "guild_id": None, "mode": "balanced", "diff": 0.1,
        "source_label": "🎧 테스트",
        "players": [{"id": p.key, "label": p.label, "rating": p.rating,
                     "tier_index": p.tier_index} for p in players],
        "teams": [[{"id": 1, "label": "P1", "rating": 10.0, "tier_index": 10},
                   {"id": 2, "label": "P2", "rating": 10.0, "tier_index": 10}],
                  [{"id": 3, "label": "P3", "rating": 10.0, "tier_index": 10},
                   {"id": 4, "label": "P4", "rating": 10.0, "tier_index": 10}]],
    })
    check_layout("👑 팀장 화면", CaptainPickView(None, fake), failed)
    check_layout("🗺️ 맵 지정 화면", MapPickView(None, fake), failed)
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
