import asyncio
import faulthandler
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"

# 실행 위치와 상관없이 항상 이 파일과 같은 폴더의 .env를 찾도록 경로를 고정해요.
load_dotenv(dotenv_path=BASE_DIR / ".env")


# ------------------------------------------------------------------
# 📝 로깅 설정
#
# 예전엔 전부 print()였어요. 2026-09-04에 봇이 먹통이 됐을 때, 로그에 레벨도
# 타임스탬프도 없어서 "언제부터 이상했는지"를 눈으로 훑어 찾아야 했어요.
# 이제 시각(한국시간)·레벨·모듈이 같이 찍혀서 grep으로 걸러낼 수 있어요.
# ------------------------------------------------------------------
KST = timezone(timedelta(hours=9), "KST")


class _KstFormatter(logging.Formatter):
    """Fly 로그가 UTC라 헷갈려서, 앱 로그만이라도 한국시간으로 찍어요."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, KST)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def _setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _KstFormatter("[%(asctime)s KST] [%(levelname)-8s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    # discord.py는 기본적으로 자체 핸들러를 붙이는데, 위 설정과 중복 출력돼요.
    # 루트로 올려보내서 형식을 하나로 통일해요.
    logging.getLogger("discord").propagate = True
    # 게이트웨이 heartbeat 경고는 사고 진단의 핵심이라 반드시 보이게 유지해요.
    logging.getLogger("discord.gateway").setLevel(logging.INFO)


_setup_logging()
log = logging.getLogger("akgui")

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
        "store",      # 상점(피처드 번들) 조회 - 로그인 불필요
        "myshop",     # /오상 - 개인 오늘의 상점, ⚠️본인 라이엇 로그인 필요(비공식 방식)
        "vp",         # /vp계산 - 목표 VP를 채우는 가장 싼 충전 조합
    ],
    "🤝 팀/내전": [
        "team",       # /팀짜기
        "scrim",      # /내전모집
        "map",        # /맵추천
    ],
    "🔊 즉석 생성형 통화방": [
        "room",             # /방만들기 (랭크방/폐관수련방/프리미어방 등)
    ],
    "🎤 노래방": [
        "music",            # 노래방 음성채널 유튜브 음악 재생
    ],
    "🐾 포켓몬/출석": [
        "attendance",    # 출석 + 포켓몬 육성 시스템 (상점/아이템 사용은 웹사이트에서)
        "daycare_voice",  # 키우미집 알 생성/부화 진행도를 음성채널 잔류 시간으로 채움
    ],
    "🛠️ 커뮤니티/운영": [
        "onboarding",    # 규칙 동의/온보딩
        "autorole",      # 자동 역할 부여
        "birthday",      # 생일 알림
        "adult_verify",  # 성인 인증(생년월일 자동 확인 + 매니저 승인)
        "ping",          # 핑 테스트
    ],
}


# ------------------------------------------------------------------
# 🐕 이벤트 루프 워치독
#
# 2026-09-04 사고: 머신은 계속 `started`인데 봇의 asyncio 이벤트 루프가 통째로
# 멈춰서(heartbeat blocked → 로그 무음 37분) 디스코드에선 오프라인이나 다름없는
# 상태가 몇 시간 방치됐다. Fly에 헬스체크가 없어 자동 복구도 안 됐다.
#
# 구조:
#   - `_beat_loop()` : 이벤트 루프 위에서 5초마다 타임스탬프를 갱신하는 코루틴.
#     루프가 막히면 이 갱신이 자동으로 멈춘다 = 그게 곧 탐지 신호다.
#   - `_watchdog_thread()` : **이벤트 루프와 무관한 별도 데몬 스레드.**
#     루프가 아무리 막혀도 이 스레드는 계속 돈다(블로킹은 GIL을 놓으므로).
#     갱신이 STALL_LIMIT초 넘게 멈추면 전 스레드 스택을 덤프하고 프로세스를 죽인다.
#     → Fly의 재시작 정책이 새 머신을 띄운다.
#
# ⚠️ 굳이 스택 덤프까지 남기는 이유: 이번 사고는 재시작하는 순간 로그 버퍼가 날아가
#    범인을 못 찾았다. 다음 재발 때는 죽기 직전 스택이 로그에 남아야 원인을 잡는다.
# ------------------------------------------------------------------
WATCHDOG_STALL_LIMIT = float(os.getenv("WATCHDOG_STALL_SECONDS", "120"))
WATCHDOG_CHECK_INTERVAL = 10.0
_BEAT_INTERVAL = 5.0

_last_beat = time.monotonic()
_watchdog_armed = False  # 로그인(READY) 전까지는 무장하지 않아요


async def _beat_loop(bot: commands.Bot):
    """이벤트 루프가 살아있다는 걸 알리는 심장박동. 루프가 막히면 같이 멈춰요."""
    global _last_beat, _watchdog_armed

    # 부팅 중엔(PokeAPI 캐시 수집 등 최대 10분) 오탐으로 죽이면 안 되니
    # 로그인 완료 뒤에 무장해요.
    await bot.wait_until_ready()
    _last_beat = time.monotonic()
    _watchdog_armed = True
    log.info("🐕 워치독 무장 완료 (이벤트 루프가 %.0f초 이상 멈추면 프로세스를 재시작해요)", WATCHDOG_STALL_LIMIT)

    while True:
        _last_beat = time.monotonic()
        await asyncio.sleep(_BEAT_INTERVAL)


def _watchdog_thread():
    """이벤트 루프와 독립된 감시 스레드. 루프가 죽어도 이 스레드는 살아있어요."""
    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)

        if not _watchdog_armed:
            continue

        stalled_for = time.monotonic() - _last_beat
        if stalled_for < WATCHDOG_STALL_LIMIT:
            continue

        # ⚠️ 여기서는 일부러 logging도 print도 안 써요.
        # 둘 다 내부에 락이 있어서, 만약 멈춰버린 스레드가 그 락을 쥔 채로 굳었다면
        # 워치독까지 같이 멈춰버려요. 하필 "모든 게 멈췄을 때 동작해야 하는 코드"라
        # 락이 없는 os.write(fd, ...)로 직접 씁니다.
        message = (
            f"\n🚨 워치독: 이벤트 루프가 {stalled_for:.0f}초째 멈춰 있어요. "
            f"(한계 {WATCHDOG_STALL_LIMIT:.0f}초) 스택을 남기고 프로세스를 재시작할게요.\n"
        )
        try:
            os.write(2, message.encode("utf-8", "replace"))
        except OSError:
            pass

        # 모든 스레드의 스택 = 다음 재발 때 원인을 잡을 유일한 단서.
        # faulthandler도 fd에 직접 쓰기 때문에 락에 걸리지 않아요.
        try:
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        except Exception:  # noqa: BLE001
            try:
                os.write(2, b"watchdog: stack dump failed\n")
            except OSError:
                pass

        # 루프가 죽어 있으니 정상 종료(bot.close())를 기대할 수 없어요. 즉시 강제 종료.
        os._exit(1)


class MainBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 심장박동은 부팅 초반에 띄워둬요. (내부에서 wait_until_ready로 대기)
        asyncio.create_task(_beat_loop(self))

        # 기술표/특성/타입/종족값/진화정보/도감번호 캐시가 하나라도 없으면
        # PokeAPI에서 전부(또는 이어서) 수집해요.
        data_dir = Path("data")
        required_files = [
            "learnsets.json", "moves.json", "abilities.json",
            "species.json", "evolution.json", "name_to_id.json",
        ]
        missing = [f for f in required_files if not (data_dir / f).exists()]

        if missing:
            log.info("📡 캐시 파일이 부족해요 (%s). PokeAPI에서 수집을 시작해요. (최대 10분 대기)", ", ".join(missing))
            from scripts.build_learnsets import main as build_learnsets
            try:
                await asyncio.wait_for(build_learnsets(), timeout=600)
                log.info("✅ 수집 완료!")
            except asyncio.TimeoutError:
                log.warning("⚠️ 수집이 10분 넘게 걸려서 중단해요. 지금까지 저장된 데이터 + 기본값으로 계속 진행해요.")
            except Exception as e:
                log.warning("⚠️ 수집 실패, 기본값으로 계속 진행해요: %s", e)

        await self._load_cogs()

        # DB 설정이 틀렸으면 첫 /출석 때가 아니라 지금 알아채는 게 나아요.
        from utils.pokemon_store import ping_db

        if await ping_db():
            log.info("🗄️ MongoDB 연결 확인")
        else:
            log.warning("🗄️ MongoDB에 연결하지 못했어요. 포켓몬/출석 기능이 실패할 수 있어요.")

        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("✅ 슬래시 명령어를 테스트 서버에 등록했어요.")
        else:
            await self.tree.sync()
            log.info("✅ 슬래시 명령어를 전역으로 등록했어요. (반영까지 최대 1시간 정도 걸려요)")

    async def _load_cogs(self):
        listed = {name for names in COG_GROUPS.values() for name in names}
        on_disk = {f.stem for f in COGS_DIR.glob("*.py")}

        for group_name, cog_names in COG_GROUPS.items():
            log.info("%s", group_name)
            for name in cog_names:
                if name not in on_disk:
                    log.warning("  ⚠️ 건너뜀: cogs/%s.py 파일이 없어요.", name)
                    continue
                await self.load_extension(f"cogs.{name}")
                log.info("  📦 로드: %s", name)

        # 그룹 목록에 안 적었는데 cogs 폴더에 있는 파일이 있으면 알려줘요.
        # (등록 안 하고 조용히 빠뜨리는 실수를 방지)
        unlisted = on_disk - listed
        if unlisted:
            log.warning("⚠️ COG_GROUPS에 없는 파일들이 cogs 폴더에 있어요 (로드 안 됨): %s", sorted(unlisted))


bot = MainBot()


@bot.event
async def on_ready():
    log.info("✅ %s(으)로 로그인 완료!", bot.user)


# ------------------------------------------------------------------
# 🧯 전역 에러 핸들러
#
# 예전엔 이게 없어서, 슬래시 명령 안에서 예외가 나면 유저 화면엔 디스코드가 띄우는
# "애플리케이션이 응답하지 않았습니다"만 뜨고 끝이었어요. 무슨 일이 났는지도,
# 어느 명령이 터졌는지도 안 남았죠.
# 이제 (1) 유저에게 사람 말로 알려주고 (2) 스택을 로그에 남겨요.
# ------------------------------------------------------------------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    original = getattr(error, "original", error)
    command_name = interaction.command.qualified_name if interaction.command else "(알 수 없음)"

    # 채널 제한 등 "의도된 거절"은 각 명령이 이미 안내 메시지를 보냈어요. 조용히 넘어가요.
    if isinstance(error, discord.app_commands.CheckFailure):
        return

    if isinstance(original, asyncio.TimeoutError):
        message = "⏱️ 처리 시간이 너무 오래 걸려서 중단했어요. 잠시 후 다시 시도해주세요."
        log.warning("[/%s] 시간 초과 (user=%s)", command_name, interaction.user)
    else:
        message = "⚠️ 명령을 처리하다가 오류가 났어요. 계속 그러면 관리자에게 알려주세요."
        log.exception("[/%s] 처리 중 예외 (user=%s)", command_name, interaction.user, exc_info=original)

    # 이미 응답했는지에 따라 보내는 방법이 달라요. 여기서 또 터지면 로그만 남기고 끝냅니다.
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException as e:
        log.warning("[/%s] 오류 안내 메시지 전송마저 실패: %s", command_name, e)


@bot.event
async def on_error(event_method: str, *args, **kwargs):
    """슬래시 명령이 아닌 이벤트 리스너(on_voice_state_update 등)에서 난 예외."""
    log.exception("이벤트 처리 중 예외: %s", event_method)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        env_path = BASE_DIR / ".env"
        raise SystemExit(
            f"DISCORD_TOKEN이 설정되지 않았어요.\n"
            f"찾으려 한 .env 경로: {env_path}\n"
            f"이 경로에 .env 파일이 있는지, 그 안에 DISCORD_TOKEN=값 형태로 적혀있는지 확인해주세요."
        )

    threading.Thread(target=_watchdog_thread, name="loop-watchdog", daemon=True).start()

    try:
        # log_handler=None: discord.py가 자기 핸들러를 또 붙이면 로그가 두 번 찍혀요.
        # 형식은 위 _setup_logging()으로 통일합니다.
        bot.run(token, log_handler=None)
    except BaseException:
        log.exception("🛑 봇이 예기치 않게 종료됐어요.")
        raise
    else:
        log.warning("🛑 봇이 정상적으로(예외 없이) 종료됐어요. bot.run()이 그냥 반환됐어요.")