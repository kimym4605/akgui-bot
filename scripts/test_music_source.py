"""🎤 노래방 재생 소스 테스트 (2026-11-25 끊김 대책) — 디스코드·유튜브·ffmpeg에 붙지 않아요."""
import asyncio
import os
import sys
import time
from collections import deque

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
sys.stdout.reconfigure(encoding="utf-8")

import types

import discord

# 로컬엔 yt-dlp가 없어요(Dockerfile이 배포 때 최신으로 깔아요). 이 테스트는 추출을 안 써요.
if "yt_dlp" not in sys.modules:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        sys.modules["yt_dlp"] = types.SimpleNamespace(YoutubeDL=None)

from cogs import music

failed: list[str] = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failed.append(name)


class FakeInner:
    """FFmpegOpusAudio 흉내. delays[i]초 기다렸다가 i번째 조각을 줘요."""
    def __init__(self, n=10, delays=None):
        self.n, self.i, self.delays = n, 0, delays or {}
        self.cleaned = False
        self._stdout = None

    def read(self):
        if self.i >= self.n:
            return b""
        time.sleep(self.delays.get(self.i, 0))
        self.i += 1
        return b"x"

    def cleanup(self):
        self.cleaned = True


print("[1] 위치·끊김 구분")
src = music.TimedOpusSource(FakeInner(n=5), start=10.0, label="t")
for _ in range(5):
    src.read()
check("is_opus", src.is_opus())
check("위치 = 시작 + 조각×20ms", abs(src.position - 10.1) < 1e-9, src.position)
check("정상 재생은 끊김 0", src.summary() is None)
src.read()
check("끝난 뒤 빈 조각은 위치에 안 셈", abs(src.position - 10.1) < 1e-9)

src = music.TimedOpusSource(FakeInner(n=3, delays={1: 0.35}), label="net")
for _ in range(3):
    src.read()
check("read가 오래 걸리면 전송 끊김", src.stalls == {"net": 1, "busy": 0}, src.stalls)

src = music.TimedOpusSource(FakeInner(n=3), label="busy")
src.read(); time.sleep(0.35); src.read()
check("호출 간격이 벌어지면 봇 바쁨", src.stalls == {"net": 0, "busy": 1}, src.stalls)
check("요약에 숫자", "봇 바쁨 1번" in (src.summary() or ""))

src = music.TimedOpusSource(FakeInner(n=3), label="pause")
src.read(); time.sleep(0.35); src.reset_clock(); src.read()
check("일시정지 뒤 재개는 끊김 아님", src.stalls == {"net": 0, "busy": 0}, src.stalls)
src.cleanup()
check("cleanup 전달", src.inner.cleaned)


print("[2] ffmpeg 옵션 · 이어 틀기")
made = []


class FakeOpus(FakeInner):
    def __init__(self, url, *, bitrate=None, before_options=None, options=None):
        super().__init__(n=1)
        made.append({"url": url, "bitrate": bitrate, "before": before_options, "options": options})


music.discord.FFmpegOpusAudio = FakeOpus


class FakeVC:
    def __init__(self):
        self.channel = type("C", (), {"bitrate": 256_000})()
        self.played = []
        self._playing = False

    def play(self, source, *, after, bitrate, signal_type):
        self.played.append(source)
        self.after = after
        self._playing = True

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return False


class FakeGuild:
    id = 1

    def __init__(self):
        self.voice_client = FakeVC()


async def run():
    loop = asyncio.get_running_loop()
    bot = type("B", (), {"loop": loop})()
    cog = music.Music(bot)
    guild = FakeGuild()
    state = cog._get_state(1)
    state.volume = 1.5
    t1 = music.Track(title="곡1", webpage_url="u1", duration=200, requester_name="a")
    t2 = music.Track(title="곡2", webpage_url="u2", duration=200, requester_name="a")
    state.current = t1
    state.stream_url = "http://stream/1"
    state.queue = deque([t2])

    cog._start_source(guild, state, t1, "http://stream/1")
    m = made[-1]
    check("ffmpeg가 채널 음질(256)로 압축", m["bitrate"] == 256)
    check("음량은 ffmpeg 필터", "-af volume=1.50" in m["options"], m["options"])
    check("처음부터면 -ss 없음", "-ss" not in m["before"])
    check("재연결 옵션 유지", "-reconnect 1" in m["before"])
    check("state.source 기억", state.source is guild.voice_client.played[-1])

    # /음량 변경 흉내: 지금 위치에서 restart_at → _play_next가 같은 곡을 이어 틀어요
    state.source.frames = 3000          # 60초 지점
    state.restart_at = state.source.position
    await cog._play_next(guild)
    m = made[-1]
    check("이어 틀기는 같은 주소", m["url"] == "http://stream/1")
    check("이어 틀기는 그 위치부터", "-ss 60.00" in m["before"], m["before"])
    check("이어 틀기 뒤 위치도 60초부터", abs(state.source.position - 60.0) < 1e-9)
    check("대기열은 그대로", list(state.queue) == [t2] and state.current is t1)
    check("restart_at 비움", state.restart_at is None)

    # 반복 '한 곡'에서도 이어 틀기가 곡을 대기열에 중복으로 넣지 않아요
    state.repeat_mode = music.REPEAT_ONE
    state.restart_at = 5.0
    await cog._play_next(guild)
    check("한 곡 반복 중 이어 틀기도 대기열 그대로", list(state.queue) == [t2])


asyncio.run(run())

print()
if failed:
    print(f"❌ 실패 {len(failed)}개: {failed}")
    sys.exit(1)
print("✅ 노래방 재생 소스 테스트 전부 통과")
