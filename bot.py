import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"

# 실행 위치와 상관없이 항상 이 파일과 같은 폴더의 .env를 찾도록 경로를 고정해요.
load_dotenv(dotenv_path=BASE_DIR / ".env")

intents = discord.Intents.default()
intents.voice_states = True  # /팀짜기 명령어가 음성채널 인원을 읽기 위해 필요해요
intents.members = True  # ⚠️ 특권 인텐트예요. 자동 역할 부여(on_member_join)를 감지하려면 필요해요.
# ⚠️ Discord 개발자 포털 > Bot 탭 > Privileged Gateway Intents 에서
#    "SERVER MEMBERS INTENT"를 반드시 켜주세요. 안 켜면 아래에서 에러가 나요.

# ------------------------------------------------------------------
# 📦 기능별 Cog 그룹 — 여기서 어떤 기능이 있는지 한눈에 볼 수 있어요.
#    새 기능을 추가하면 알맞은 그룹에 파일 이름만 추가하면 돼요.
# ------------------------------------------------------------------
COG_GROUPS: dict[str, list[str]] = {
    "🎯 발로란트 전적/정보": [
        "rank",       # 전적 조회
        "tier",       # 티어 관련
        "skin",       # 스킨 정보
        "store",      # 상점(피처드 번들) 조회
    ],
    "🤝 팀/내전": [
        "team",       # /팀짜기
        "scrim",      # /내전모집
        "map",        # /맵추천
    ],
    "🔊 랭크방/관전": [
        "rank_room",        # 즉석 생성형 랭크 통화방
        "spectator_ticket", # 관전 전용 통화방 입장권
    ],
    "🐾 포켓몬/출석": [
        "attendance",  # 출석 + 포켓몬 육성 시스템 (상점/아이템 사용은 웹사이트에서)
    ],
    "🛠️ 커뮤니티/운영": [
        "onboarding",    # 규칙 동의/온보딩
        "autorole",      # 자동 역할 부여
        "birthday",      # 생일 알림
        "adult_verify",  # 성인 인증(생년월일 자동 확인 + 매니저 승인)
        "ping",          # 핑 테스트
    ],
}


class MainBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 기술표/특성/타입/종족값/진화정보/도감번호 캐시가 하나라도 없으면
        # PokeAPI에서 전부(또는 이어서) 수집해요.
        data_dir = Path("data")
        required_files = [
            "learnsets.json", "moves.json", "abilities.json",
            "species.json", "evolution.json", "name_to_id.json",
        ]
        missing = [f for f in required_files if not (data_dir / f).exists()]

        if missing:
            print(f"📡 캐시 파일이 부족해요 ({', '.join(missing)}). PokeAPI에서 수집을 시작해요. (최대 10분 대기)", flush=True)
            from scripts.build_learnsets import main as build_learnsets
            try:
                await asyncio.wait_for(build_learnsets(), timeout=600)
                print("✅ 수집 완료!", flush=True)
            except asyncio.TimeoutError:
                print("⚠️ 수집이 10분 넘게 걸려서 중단해요. 지금까지 저장된 데이터 + 기본값으로 계속 진행해요.", flush=True)
            except Exception as e:
                print(f"⚠️ 수집 실패, 기본값으로 계속 진행해요: {e}", flush=True)

        await self._load_cogs()

        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print("✅ 슬래시 명령어를 테스트 서버에 등록했어요.", flush=True)
        else:
            await self.tree.sync()
            print("✅ 슬래시 명령어를 전역으로 등록했어요. (반영까지 최대 1시간 정도 걸려요)", flush=True)

    async def _load_cogs(self):
        listed = {name for names in COG_GROUPS.values() for name in names}
        on_disk = {f.stem for f in COGS_DIR.glob("*.py")}

        for group_name, cog_names in COG_GROUPS.items():
            print(f"\n{group_name}", flush=True)
            for name in cog_names:
                if name not in on_disk:
                    print(f"  ⚠️ 건너뜀: cogs/{name}.py 파일이 없어요.", flush=True)
                    continue
                await self.load_extension(f"cogs.{name}")
                print(f"  📦 로드: {name}", flush=True)

        # 그룹 목록에 안 적었는데 cogs 폴더에 있는 파일이 있으면 알려줘요.
        # (등록 안 하고 조용히 빠뜨리는 실수를 방지)
        unlisted = on_disk - listed
        if unlisted:
            print(f"\n⚠️ COG_GROUPS에 없는 파일들이 cogs 폴더에 있어요 (로드 안 됨): {sorted(unlisted)}", flush=True)


bot = MainBot()


@bot.event
async def on_ready():
    print(f"✅ {bot.user}(으)로 로그인 완료!")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        env_path = BASE_DIR / ".env"
        raise SystemExit(
            f"DISCORD_TOKEN이 설정되지 않았어요.\n"
            f"찾으려 한 .env 경로: {env_path}\n"
            f"이 경로에 .env 파일이 있는지, 그 안에 DISCORD_TOKEN=값 형태로 적혀있는지 확인해주세요."
        )

    try:
        bot.run(token)
    except BaseException as error:  # noqa: BLE001
        import traceback

        print("🛑 봇이 예기치 않게 종료됐어요. 아래는 원인이에요:")
        traceback.print_exc()
        raise
    else:
        print("🛑 봇이 정상적으로(예외 없이) 종료됐어요. bot.run()이 그냥 반환됐어요.")