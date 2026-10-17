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
        "team",       # /팀짜기 (+ 승리 보고 버튼 - 내전 전적이 쌓이는 유일한 경로예요)
        "scrim",      # /내전모집
        "map",        # /맵추천
        "achievement",  # /업적, /내전전적, /주간랭킹, /내전시즌
    ],
    "🔊 즉석 생성형 통화방": [
        "room",             # /방만들기 (랭크방/폐관수련방/프리미어방 등)
    ],
    "🎤 노래방": [
        "music",            # 노래방 음성채널 유튜브 음악 재생
    ],
    "📅 출석": [
        "attendance",    # /출석, /프로필, /채널설정
    ],
    "🪙 악귀코인": [
        "coin",          # /코인, /코인보내기 - 포켓몬 미시작자도 코인을 모을 수 있어요
        "mission",       # /미션 - 매일 3개 배정, 깰 때마다 악귀코인 1개
        "title_shop",    # /칭호구매 - 코인으로 10일/30일짜리 커스텀 역할
        "akgui_shop",    # /악귀상점 - 미션 리롤권·카드 테마 (코인 소비처 모음)
        "casino",        # /도박 - 슬롯·하이로우·블랙잭 (하우스 몫만큼 코인이 소각돼요)
        "card_gacha",    # /카드뽑기 - 악귀카드 83종 수집 (10코인에 3장)
        "card_market",   # /장터 - 카드를 코인으로 사고팔아요 (⚠️재분배라 소각 아님)
        "fishing",       # 🎣 /낚시 - 물고기를 낚아 팔아요 (⚠️코인을 찍어내는 쪽)
        "betting",       # /베팅개설 - 내전 승부에 코인 걸기 (파리뮤추얼 정산)
    ],
    "🛠️ 커뮤니티/운영": [
        "onboarding",    # 규칙 동의/온보딩
        "autorole",      # 자동 역할 부여
        "birthday",      # 생일 알림
        "adult_verify",  # 성인 인증(생년월일 자동 확인 + 매니저 승인)
        "notify",        # /알림설정 - 미션 완료·위시리스트 알림을 개인별로 끄고 켜기
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

# 🩺 메모리 흔적 남기기
#
# 2026-10-17 사고: 05:02에 프로세스가 **조용히** SIGKILL로 죽었다(exit_code=-1,
# 워치독 미발동, 트레이스백 없음). 원인을 메모리로 의심했지만 **확인할 방법이 없었다**:
#   - `flyctl ssh console` : 차단
#   - Fly Prometheus API   : 앱 스코프 토큰이라 401
#   - 로그                 : 죽기 전 32분간 무음
# 결국 "호스트 이벤트 같다"는 정황 추론으로 끝났다. 256MB로 버티는 봇에서 그건 매번
# 반복될 질문이라, **봇이 스스로 남기게** 한다. 다음엔 추론이 아니라 숫자로 본다.
#
# 🚨 여기서도 `logging`을 쓰지 않고 `os.write(2, ...)`로 쓴다. 이 함수는 워치독
#    스레드가 부르는데, 만약 멈춘 스레드가 logging 락을 쥔 채 굳었다면 로그를 찍으려는
#    순간 **워치독까지 같이 멈춘다**. 하필 "모든 게 멈췄을 때 동작해야 하는 코드"다.
#    (바로 아래 스택 덤프가 같은 이유로 락 없는 fd 쓰기를 쓴다.)
MEM_REPORT_INTERVAL = 600.0     # 10분마다 한 줄 = 하루 144줄, 추세를 보기에 충분
MEM_WARN_MB = 48.0              # 2026-09-06 실측 idle 여유가 68MB였다
#
# 🚨 2026-10-17: **여유 RAM만 보면 놓친다.** 256MB 시절 3시간 20분을 관측했더니 여유는
#    10~46MB에서 진동만 하는데(= 꽉 찬 채 평평) 스왑 여유가 434 → 368MB로 시간당 20MB씩
#    단조로 줄고 있었다. 즉 늘어나는 상주량이 스왑으로 흘러들어가 **RAM 쪽 숫자에는 안 보였다.**
#    512MB로 올린 뒤에는 여유가 넉넉해져 위 경고가 아예 안 뜨므로, 같은 일이 또 일어나면
#    더더욱 안 보인다. 그래서 스왑 쪽에도 경고를 두고, 한 줄 안에 **기동 대비 증감**을 같이 적는다
#    (한 줄만 보고도 추세를 알 수 있어야 한다 — 20줄을 눈으로 비교하다 이걸 늦게 발견했다).
MEM_SWAP_WARN_MB = 128.0        # 스왑 512MB 중 1/4. 이 밑이면 남은 시간이 몇 시간뿐이다
_last_mem_report = 0.0
_first_swap_free: float | None = None   # 기동 직후 스왑 여유. 추세 비교의 기준선


def _meminfo_mb() -> tuple[float, float] | None:
    """`/proc/meminfo`에서 (MemAvailable, SwapFree)를 MB로. 리눅스가 아니면 None.

    ⚠️ psutil을 쓰지 않아요 - `requirements.txt`는 `==`로 고정돼 있고, 진단용으로
    의존성을 늘릴 이유가 없어요. /proc 읽기는 표준 라이브러리로 충분해요."""
    try:
        with open("/proc/meminfo", "rb") as fp:
            raw = fp.read().decode("ascii", "replace")
    except OSError:
        return None                      # 윈도우 로컬 실행 등
    out = {}
    for line in raw.splitlines():
        name, _, rest = line.partition(":")
        if name in ("MemAvailable", "SwapFree"):
            parts = rest.split()
            if parts and parts[0].isdigit():
                out[name] = int(parts[0]) / 1024.0      # kB -> MB
    if "MemAvailable" not in out:
        return None
    return out["MemAvailable"], out.get("SwapFree", 0.0)


def _report_memory() -> None:
    """메모리 여유를 stderr에 한 줄 남겨요. 락을 쓰지 않아요(위 주석 참고)."""
    global _first_swap_free
    info = _meminfo_mb()
    if info is None:
        return
    avail, swap_free = info
    if _first_swap_free is None:
        _first_swap_free = swap_free
    drift = swap_free - _first_swap_free
    if avail < MEM_WARN_MB:
        mark = "🚨 여유 부족"
    elif swap_free < MEM_SWAP_WARN_MB:
        mark = "🚨 스왑 고갈"
    else:
        mark = "🩺"
    try:
        os.write(2, f"{mark} 메모리: 여유 {avail:.0f}MB · 스왑여유 "
                    f"{swap_free:.0f}MB (기동 대비 {drift:+.0f}MB)"
                    f"\n".encode("utf-8", "replace"))
    except OSError:
        pass


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
    global _last_mem_report

    # 🩺 기준선을 **지금 바로** 한 줄 남겨요. 기동 직후 수치가 있어야 나중에
    #    "원래 이랬나 늘어난 건가"를 비교할 수 있어요. 10분을 기다리면 그 사이에
    #    죽은 경우(= 제일 알고 싶은 경우) 아무 기록도 안 남아요.
    #
    # ⚠️ `_last_mem_report`를 0.0으로 두지 말고 `time.monotonic()`으로 맞춰요.
    #    리눅스에서 `monotonic()`은 **부팅 후 경과초**라, 0.0 기준이면 첫 보고 시점이
    #    "프로세스가 뜬 뒤 10분"이 아니라 "**VM이 부팅된 뒤** 10분"이 돼요. 머신을
    #    재시작만 한 경우엔 즉시 찍히고, 새 머신이면 부팅 시각에 좌우돼요.
    #    치명적이진 않지만 간격이 예측 가능해야 추세를 읽을 수 있어요.
    _report_memory()
    _last_mem_report = time.monotonic()

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)

        # 🩺 메모리 흔적은 **무장 여부와 무관하게** 남겨요. 부팅 중(캐시 수집 등)이
        #    제일 메모리를 많이 쓰는 구간인데, 무장 뒤로 미루면 그때를 놓쳐요.
        #
        # ⚠️ 이 스레드에서 찍는 이유: 이벤트 루프 위에 올리면 **루프가 막힌 순간
        #    같이 멈춰서**, 정작 알고 싶은 "죽기 직전"이 기록되지 않아요.
        now = time.monotonic()
        if now - _last_mem_report >= MEM_REPORT_INTERVAL:
            _last_mem_report = now
            _report_memory()

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

        # 🩺 멈춤의 단골 원인이 메모리 고갈이에요(스왑으로 밀려난 코드 페이지를 매번
        #    디스크에서 다시 읽느라 기어가는 상태). 스택만 보면 "어디서 멈췄나"는
        #    알아도 "왜"는 모르니, 죽기 직전 숫자를 같이 남겨요.
        _report_memory()

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

        # (2026-09-30) 예전엔 여기서 포켓몬 기술표/도감 캐시가 없으면 PokeAPI에서
        # 최대 10분간 수집했어요. 포켓몬 기능을 접으면서 캐시도 수집 스크립트도 지웠어요.
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