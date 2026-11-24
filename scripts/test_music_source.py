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
    def __init__(self, src, *, pipe=False, bitrate=None, before_options=None, options=None):
        super().__init__(n=1)
        made.append({"src": src, "pipe": pipe, "bitrate": bitrate,
                     "before": before_options or "", "options": options})


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
    check("https는 구간 받기(pipe)로", m["pipe"] and isinstance(m["src"], music.ChunkedHTTPReader)
          and m["src"].url == "http://stream/1")
    check("state.source 기억", state.source is guild.voice_client.played[-1])
    check("소스가 reader를 들고 있음(정리용)", state.source.reader is m["src"])

    # /음량 변경 흉내: 지금 위치에서 restart_at → _play_next가 같은 곡을 이어 틀어요
    state.source.frames = 3000          # 60초 지점
    state.restart_at = state.source.position
    await cog._play_next(guild)
    m = made[-1]
    check("이어 틀기는 같은 주소", m["src"].url == "http://stream/1")
    check("이어 틀기는 그 위치부터", "-ss 60.00" in m["before"], m["before"])
    check("이어 틀기 뒤 위치도 60초부터", abs(state.source.position - 60.0) < 1e-9)
    check("대기열은 그대로", list(state.queue) == [t2] and state.current is t1)
    check("restart_at 비움", state.restart_at is None)

    # 반복 '한 곡'에서도 이어 틀기가 곡을 대기열에 중복으로 넣지 않아요
    state.repeat_mode = music.REPEAT_ONE
    state.restart_at = 5.0
    await cog._play_next(guild)
    check("한 곡 반복 중 이어 틀기도 대기열 그대로", list(state.queue) == [t2])

    state.stream_protocol = "m3u8_native"
    cog._start_source(guild, state, t1, "http://stream/hls.m3u8")
    m = made[-1]
    check("m3u8은 ffmpeg가 직접(재연결 옵션)", not m["pipe"] and m["src"] == "http://stream/hls.m3u8"
          and "-reconnect 1" in m["before"])
    check("m3u8은 reader 없음", state.source.reader is None)


asyncio.run(run())


print("[3] 구간(Range) 받기 — 로컬 HTTP 서버")
import http.server
import threading

BLOB = bytes(range(256)) * 4000 + b"END"     # 1,024,003바이트
hits = []


class RangeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        rng = self.headers.get("Range", "")
        hits.append((rng, self.headers.get("X-Test")))
        a, b = rng.replace("bytes=", "").split("-")
        a, b = int(a), min(int(b), len(BLOB) - 1)
        if a >= len(BLOB):
            self.send_response(416); self.end_headers(); return
        body = BLOB[a:b + 1]
        self.send_response(206)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/a"

r = music.ChunkedHTTPReader(url, {"X-Test": "ok", "Range": "bytes=999-"}, chunk=300_000)
got = bytearray()
while True:
    piece = r.read(8192)
    if not piece:
        break
    got += piece
check("나눠 받아도 원본과 똑같음", bytes(got) == BLOB, f"{len(got)} vs {len(BLOB)}")
check("2MB 대신 30만씩 4번 요청", len(hits) == 4, str([h[0] for h in hits]))
check("첫 요청은 0부터", hits[0][0] == "bytes=0-299999")
check("yt-dlp 헤더 전달 · 원래 Range는 버림", all(h[1] == "ok" for h in hits))

hits.clear()
r = music.ChunkedHTTPReader(url, {}, chunk=256)
r.read(10); r.close()
check("close 뒤엔 빈 값(다음 곡으로 넘어갈 때 멈춤)", r.read(10) == b"")

r = music.ChunkedHTTPReader(f"http://127.0.0.1:{srv.server_address[1]}/a", {}, chunk=len(BLOB))
check("딱 맞게 끝나면 416에서 멈춤", len(r.read(-1)) == len(BLOB) and r.read(10) == b"")
srv.shutdown()

print()
if failed:
    print(f"❌ 실패 {len(failed)}개: {failed}")
    sys.exit(1)
print("✅ 노래방 재생 소스 테스트 전부 통과")
