"""
🎤 노래방 음성채널 음악 재생 기능이에요.

- /재생 <검색어 또는 유튜브 링크> 를 치면 노래를 대기열에 추가해요.
  아무것도 재생 중이 아니면 바로 재생을 시작하고, 봇이 음성채널에 없으면
  명령어를 실행한 사람이 있는 음성채널에 자동으로 들어가요.
- /일시정지, /재개, /스킵, /정지 로 재생을 제어해요.
- /음량 으로 재생 음량을 0~200%로 조절해요. (기본 100%, 서버별로 다음 곡에도 유지돼요)
- /대기열 로 지금 재생 중인 곡 + 대기 중인 곡 목록을 확인해요.
- /대기열삭제 로 특정 곡만 뺄 수 있고, /대기열섞기 로 순서를 무작위로 섞을 수 있어요.
- 봇 혼자 음성채널에 남으면 자동으로 나가고 대기열도 비워요.
- 재생 중/일시정지 상태로 5분 넘게 대기열이 비어있으면 자동으로 나가요.
- yt-dlp로 유튜브에서 오디오 스트림을 뽑아서 ffmpeg로 재생해요.
  검색어를 넣으면 유튜브 검색 결과 상위 5개를 드롭다운으로 보여주고 직접 고를 수 있어요.
  (유튜브 링크를 바로 넣으면 고를 것 없이 그 영상이 바로 재생돼요)
- 재생목록(플레이리스트) 링크를 넣으면 목록 전체(최대 50곡)를 한 번에 대기열에 담아요.
- 모든 명령어는 "노래방" 음성채널에 들어가 있어야만 사용할 수 있어요.

필요 패키지: yt-dlp, PyNaCl (requirements.txt). ffmpeg/libopus0는 Dockerfile에 설치돼있어요.

설정 방법 (.env):
  KARAOKE_VOICE_CHANNEL_ID=노래방_채널ID   ← 없으면 채널 제한 없이 아무 음성채널에서나 동작해요.
"""
import logging
import asyncio
import io
import os
import random
from collections import deque
from dataclasses import dataclass, field

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from utils.channel_check import get_allowed_channel_id

log = logging.getLogger(__name__)

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
}
SEARCH_YTDL_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",  # 스트림 URL까지는 필요 없고 후보 목록만 빠르게 뽑아요.
    "default_search": "ytsearch5",
}
PLAYLIST_PROBE_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "noplaylist": False,  # 링크가 재생목록이면 전체 항목을 훑어볼 수 있게 허용해요.
}
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"

# ============================================================
# 🔊 2026-11-25 끊김 대책 — "가끔 몇 초씩 멈춘다"는 제보
#
# 예전: FFmpegPCMAudio(날 PCM) + PCMVolumeTransformer → **봇(파이썬)이 20ms마다** 음량을 곱하고
#   Opus로 압축했어요. 같은 봇이 GIF·카드·전적 그림을 CPU 1개로 같이 그려서, 겹치면 20ms 마감을 놓쳐요.
#   그리고 ffmpeg↔봇 파이프(64KB)에 PCM은 **0.33초**밖에 안 쌓여서 유튜브가 잠깐만 늦어도 끊겼어요.
# 지금: FFmpegOpusAudio → 음량(-af volume)·Opus 압축을 **ffmpeg(별도 프로세스)**가 해요.
#   파이프도 1MB로 넓혀서(리눅스 F_SETPIPE_SZ) 256kbps 기준 **약 30초어치**를 미리 받아둬요.
# 대가: 재생 중 음량을 바꾸면 ffmpeg를 그 위치부터 다시 띄워요(0.5~1초 끊김).
# 같은 날 Fly 지표 확인: 최근 7일 CPU 스로틀 0시간, 메모리 여유 → 그쪽 원인은 아니었어요.
# ============================================================
PIPE_BUFFER_BYTES = 1 << 20
_F_SETPIPE_SZ = 1031          # 리눅스 fcntl 상수 (윈도우엔 fcntl이 없어서 그냥 건너뛰어요)
STALL_SECONDS = 0.3           # 이보다 오래 소리 조각을 못 보냈으면 '끊김'으로 기록해요
FRAME_SECONDS = 0.02          # 디스코드 음성 한 조각 = 20ms


# ============================================================
# 🌐 2026-11-25 (v233 직후) 실측: 끊김 로그가 **곡 시작부터 1~2초마다 "유튜브 전송이 늦음"**
#   (0.6~2.1초씩, 🧠 봇 바쁨은 0번). ffmpeg가 googlevideo 주소를 **연결 하나로 길게** 받으면
#   유튜브가 그 연결을 재생 속도 근처로 늦춰서, 버퍼를 아무리 넓혀도 채울 게 안 들어와요.
#   → 봇이 직접 **2MB씩 Range 요청을 나눠** 받아 ffmpeg 표준입력에 넣어요(yt-dlp가 쓰는 방식).
#   새 요청마다 처음 속도가 빨라서 재생보다 한참 앞서 받아둬요.
# ============================================================
CHUNK_BYTES = 2 * 1024 * 1024
CHUNK_RETRIES = 3


class ChunkedHTTPReader(io.RawIOBase):
    """유튜브 스트림 주소를 구간(Range)으로 나눠 받는 읽기 객체. discord.py의 파이프 쓰기 스레드가
    `read()`를 불러요(이벤트 루프가 아니라서 막혀도 괜찮아요)."""

    def __init__(self, url: str, headers: dict | None = None, chunk: int = CHUNK_BYTES):
        self.url = url
        self.headers = {k: v for k, v in (headers or {}).items() if k.lower() != "range"}
        self.chunk = chunk
        self.pos = 0
        self.buf = b""
        self.eof = False
        self._closed = False

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        self._closed = True
        super().close()

    def _fetch(self) -> bytes:
        import time
        import urllib.error
        import urllib.request
        end = self.pos + self.chunk - 1
        last_exc: Exception | None = None
        for attempt in range(CHUNK_RETRIES):
            if self._closed:
                return b""
            req = urllib.request.Request(
                self.url, headers={**self.headers, "Range": f"bytes={self.pos}-{end}"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    if resp.status == 200:
                        # 서버가 Range를 무시하고 통째로 줬어요 — 이게 전부예요.
                        self.eof = True
                    elif len(data) < self.chunk:
                        self.eof = True
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 416:          # 끝을 넘겨 요청 = 다 받았어요
                    self.eof = True
                    return b""
                last_exc = e
            except Exception as e:  # noqa: BLE001 — 끊긴 연결은 잠깐 쉬고 다시
                last_exc = e
            time.sleep(0.5 * (attempt + 1))
        log.warning(f"🎤 스트림 구간 받기 실패({self.pos}바이트 지점): {last_exc}")
        self.eof = True
        return b""

    def read(self, n: int = -1) -> bytes:
        if self._closed:
            return b""
        while not self.buf and not self.eof:
            got = self._fetch()
            self.pos += len(got)
            self.buf = got
            if not got:
                break
        if n is None or n < 0:
            out, self.buf = self.buf, b""
        else:
            out, self.buf = self.buf[:n], self.buf[n:]
        return out


class TimedOpusSource(discord.AudioSource):
    """FFmpegOpusAudio를 감싸서 ① 재생 위치를 세고 ② 끊김을 원인별로 기록해요.

    - 🌐 **전송**: ffmpeg에서 다음 조각을 받는 데(read) 오래 걸림 → 유튜브가 늦게 줌
    - 🧠 **봇이 바쁨**: read를 부르는 간격 자체가 벌어짐 → 재생 스레드가 차례를 못 받음
    """

    def __init__(self, inner: discord.FFmpegOpusAudio, start: float = 0.0, label: str = "",
                 reader: "ChunkedHTTPReader | None" = None):
        self.inner = inner
        self.reader = reader
        self.start = start
        self.label = label
        self.frames = 0
        self._last: float | None = None
        self.stalls = {"net": 0, "busy": 0}
        self.worst = 0.0
        try:
            import fcntl
            fcntl.fcntl(inner._stdout.fileno(), _F_SETPIPE_SZ, PIPE_BUFFER_BYTES)
        except Exception:  # noqa: BLE001 — 버퍼를 못 넓혀도 재생은 돼요
            pass

    @property
    def position(self) -> float:
        return self.start + self.frames * FRAME_SECONDS

    def reset_clock(self) -> None:
        """일시정지 → 재개 사이 간격을 끊김으로 세지 않게."""
        self._last = None

    def is_opus(self) -> bool:
        return True

    def read(self) -> bytes:
        import time
        t0 = time.perf_counter()
        if self._last is not None:
            gap = t0 - self._last
            if gap > STALL_SECONDS:
                self._note("busy", gap)
        data = self.inner.read()
        took = time.perf_counter() - t0
        # 첫 조각 전은 ffmpeg가 뜨고 처음 받는 시간이라 끊김이 아니에요(들리는 소리도 없어요).
        if took > STALL_SECONDS and self.frames > 0:
            self._note("net", took)
        self._last = time.perf_counter()
        if data:
            self.frames += 1
        return data

    def _note(self, kind: str, seconds: float) -> None:
        self.stalls[kind] += 1
        self.worst = max(self.worst, seconds)
        why = "🌐 유튜브 전송이 늦음" if kind == "net" else "🧠 봇이 바빠 늦게 보냄"
        log.warning(f"🎤 끊김 {seconds:.2f}초 ({why}) · {self.position:.0f}초 지점 · {self.label}")

    def summary(self) -> str | None:
        if not (self.stalls["net"] or self.stalls["busy"]):
            return None
        return (f"🎤 곡 끝 끊김 요약: 전송 {self.stalls['net']}번 · 봇 바쁨 {self.stalls['busy']}번 · "
                f"최장 {self.worst:.2f}초 · {self.position:.0f}초 재생 · {self.label}")

    def cleanup(self) -> None:
        if self.reader is not None:
            self.reader.close()      # 받던 구간 요청을 멈춰요(다음 곡으로 넘어갈 때)
        self.inner.cleanup()

IDLE_LEAVE_SECONDS = 300  # 대기열이 비고 이 시간 동안 다음 곡이 없으면 자동으로 나가요.
SEARCH_PICK_TIMEOUT_SECONDS = 60  # 검색 결과 드롭다운이 유효한 시간
MAX_PLAYLIST_TRACKS = 50  # 재생목록 링크 하나로 한 번에 담을 수 있는 최대 곡 수
EMBED_COLOR = 0x9B59B6


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def _extract_sync(query: str) -> dict:
    """블로킹 호출이라 항상 executor 안에서 돌려야 해요."""
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise ValueError("검색 결과가 없어요.")
            info = entries[0]
        return info


def _search_sync(query: str) -> list[dict]:
    """블로킹 호출이라 항상 executor 안에서 돌려야 해요. 검색 결과 후보 목록(최대 5개)을 반환해요."""
    with yt_dlp.YoutubeDL(SEARCH_YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        entries = info.get("entries", [info]) if isinstance(info, dict) else []
        return [e for e in entries if e][:5]


def _probe_playlist_sync(url: str) -> dict:
    """블로킹 호출이라 항상 executor 안에서 돌려야 해요. 링크가 재생목록이면 entries가 들어있어요."""
    with yt_dlp.YoutubeDL(PLAYLIST_PROBE_OPTIONS) as ydl:
        return ydl.extract_info(url, download=False)


def _entry_url(entry: dict) -> str | None:
    if entry.get("url"):
        return entry["url"]
    if entry.get("webpage_url"):
        return entry["webpage_url"]
    if entry.get("id"):
        return f"https://www.youtube.com/watch?v={entry['id']}"
    return None


def _entry_thumbnail(entry: dict) -> str | None:
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbnails = entry.get("thumbnails") or []
    return thumbnails[-1]["url"] if thumbnails else None


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return "?"
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}:{sec:02d}"


def _build_track_embed(track: "Track", *, status: str, extra_field: tuple[str, str] | None = None) -> discord.Embed:
    embed = discord.Embed(title=track.title, url=track.webpage_url, color=EMBED_COLOR)
    embed.set_author(name=status)
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    embed.add_field(name="길이", value=_format_duration(track.duration), inline=True)
    embed.add_field(name="신청자", value=track.requester_name, inline=True)
    if extra_field:
        name, value = extra_field
        embed.add_field(name=name, value=value, inline=True)
    return embed


# 노래방 음성채널도 /채널설정("노래방 음성채널")로 지정해요.
# .env의 KARAOKE_VOICE_CHANNEL_ID는 설정이 없을 때만 쓰는 기본값으로 남겨뒀어요.
KARAOKE_CHANNEL_GROUP = "karaoke"
KARAOKE_CHANNEL_ENV = "KARAOKE_VOICE_CHANNEL_ID"


def _get_karaoke_channel_id() -> int | None:
    return get_allowed_channel_id(KARAOKE_CHANNEL_GROUP, KARAOKE_CHANNEL_ENV)


def require_karaoke_channel():
    """이 데코레이터를 붙인 명령어는 지정한 노래방 음성채널에 들어가 있는 사람만 쓸 수 있어요.
    설정도 .env도 없으면 제한 없이 아무 음성채널에서나 동작해요.

    ⚠️ 다른 명령어들과 달리 "명령어를 친 채널"이 아니라 "지금 들어가 있는 음성채널"을 보기
    때문에, 공용 restrict_to_channel을 쓰지 않고 여기서 따로 판단해요."""

    async def predicate(interaction: discord.Interaction) -> bool:
        channel_id = _get_karaoke_channel_id()
        if channel_id is None:
            return True

        member = interaction.user
        if (
            isinstance(member, discord.Member)
            and member.voice is not None
            and member.voice.channel is not None
            and member.voice.channel.id == channel_id
        ):
            return True

        await interaction.response.send_message(
            f"이 명령어는 <#{channel_id}> 채널에 들어가 있어야 사용할 수 있어요.", ephemeral=True
        )
        return False

    return app_commands.check(predicate)


@dataclass
class Track:
    title: str
    webpage_url: str
    duration: int | None
    requester_name: str
    thumbnail: str | None = None


# 반복 재생 모드예요. /반복 으로 바꿔요.
REPEAT_OFF = "off"
REPEAT_ONE = "one"
REPEAT_ALL = "all"

REPEAT_LABELS = {
    REPEAT_OFF: "➡️ 반복 끄기",
    REPEAT_ONE: "🔂 한 곡 반복",
    REPEAT_ALL: "🔁 전체 반복",
}


@dataclass
class GuildMusicState:
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    text_channel: discord.abc.Messageable | None = None
    idle_task: asyncio.Task | None = None
    volume: float = 1.0  # 0.0~2.0 (0~200%)
    repeat_mode: str = REPEAT_OFF
    # /스킵으로 넘어온 경우엔 "한 곡 반복"이라도 같은 곡을 다시 틀면 안 되니까(영원히 안 넘어가요)
    # 이 표시를 세워두고 _play_next에서 한 번만 건너뛰어요.
    skip_repeat_once: bool = False
    # 🔊 지금 곡의 스트림 주소·소스 — /음량을 바꾸면 이 주소로 그 위치부터 다시 틀어요.
    stream_url: str | None = None
    stream_headers: dict = field(default_factory=dict)   # yt-dlp가 준 요청 헤더(구간 받기에 써요)
    stream_protocol: str = "https"                       # http/https만 구간 받기, m3u8 등은 ffmpeg 직접
    source: "TimedOpusSource | None" = None
    restart_at: float | None = None


# ============================================================
# 검색 결과 중 하나를 고르는 드롭다운 UI
# ============================================================
class SongPickView(discord.ui.View):
    def __init__(
        self,
        cog: "Music",
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        requester: discord.Member,
    ):
        super().__init__(timeout=SEARCH_PICK_TIMEOUT_SECONDS)
        self.cog = cog
        self.guild = guild
        self.voice_channel = voice_channel
        self.requester = requester
        self.message: discord.Message | None = None

        self.select: discord.ui.Select = discord.ui.Select(placeholder="원하는 곡을 선택하세요")
        self.select.callback = self._on_select
        self.add_item(self.select)

    def add_option(self, entry: dict):
        title = entry.get("title") or "제목 없음"
        duration = _format_duration(entry.get("duration"))
        channel_name = entry.get("channel") or entry.get("uploader") or ""
        url = entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id')}"
        self.select.add_option(label=title[:100], description=f"{duration} · {channel_name}"[:100], value=url)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester.id:
            await interaction.response.send_message("이 검색 결과는 요청한 사람만 고를 수 있어요.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        url = self.select.values[0]
        chosen_label = next((o.label for o in self.select.options if o.value == url), "선택한 곡")
        self.select.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content=f"✅ **{chosen_label}** 선택했어요!", view=self)
            except discord.HTTPException:
                pass
        self.stop()
        await self.cog.add_track_and_play(
            self.guild, self.voice_channel, interaction.channel, self.requester.display_name, url
        )

    async def on_timeout(self):
        self.select.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="⌛ 선택 시간이 지났어요. 다시 `/재생`으로 검색해주세요.", view=self)
            except discord.HTTPException:
                pass


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    # ============================================================
    # 헬퍼
    # ============================================================
    def _get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    def _cancel_idle_timer(self, guild_id: int):
        state = self._get_state(guild_id)
        if state.idle_task is not None and not state.idle_task.done():
            state.idle_task.cancel()
        state.idle_task = None

    def _schedule_idle_leave(self, guild: discord.Guild):
        self._cancel_idle_timer(guild.id)
        state = self._get_state(guild.id)
        state.idle_task = asyncio.create_task(self._leave_if_idle(guild.id))

    async def _leave_if_idle(self, guild_id: int):
        try:
            await asyncio.sleep(IDLE_LEAVE_SECONDS)
        except asyncio.CancelledError:
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None or guild.voice_client is None:
            return
        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
            return
        await guild.voice_client.disconnect(force=True)
        self.states.pop(guild_id, None)

    async def _play_next(self, guild: discord.Guild):
        state = self._get_state(guild.id)
        voice_client = guild.voice_client
        if voice_client is None:
            return

        if state.source is not None:
            summary = state.source.summary()
            if summary:
                log.warning(summary)
            state.source = None

        # 🔊 /음량으로 멈춘 거면 같은 곡을 그 위치부터 새 음량으로 이어 틀어요(대기열·반복은 그대로).
        restart_at, state.restart_at = state.restart_at, None
        if restart_at is not None and state.current is not None and state.stream_url:
            self._start_source(guild, state, state.current, state.stream_url, start=restart_at)
            return

        # 방금 끝난 곡을 반복 설정에 따라 대기열에 돌려놔요. 큐가 비었는지 확인하기 **전에**
        # 해야, 마지막 곡이 끝나도 반복이 이어져요.
        previous = state.current
        if previous is not None:
            if state.repeat_mode == REPEAT_ONE and not state.skip_repeat_once:
                state.queue.appendleft(previous)  # 같은 곡을 바로 다시
            elif state.repeat_mode == REPEAT_ALL:
                state.queue.append(previous)  # 맨 뒤로 보내서 한 바퀴 돌게
        state.skip_repeat_once = False

        # 추출에 실패한 곡은 건너뛰고 다음 곡으로 넘어가요. 예전엔 여기서 자기 자신을
        # 다시 호출(재귀)했는데, 연속으로 실패하면 재귀가 계속 깊어져서 반복문으로 바꿨어요.
        loop = asyncio.get_running_loop()
        while True:
            if not state.queue:
                state.current = None
                self._schedule_idle_leave(guild)
                return

            track = state.queue.popleft()
            state.current = track

            try:
                info = await loop.run_in_executor(None, _extract_sync, track.webpage_url)
                stream_url = info["url"]
                state.stream_headers = dict(info.get("http_headers") or {})
                state.stream_protocol = str(info.get("protocol") or "https")
                break
            except Exception as e:  # noqa: BLE001
                if state.text_channel is not None:
                    await state.text_channel.send(
                        f"⚠️ **{track.title}** 재생 준비 중 오류가 나서 건너뛸게요. ({e})"
                    )

        state.stream_url = stream_url
        self._start_source(guild, state, track, stream_url)

        if state.text_channel is not None:
            await state.text_channel.send(embed=_build_track_embed(track, status="🎶 지금 재생 중"))

    def _start_source(self, guild: discord.Guild, state: GuildMusicState, track: Track,
                      stream_url: str, *, start: float = 0.0) -> None:
        """ffmpeg를 띄워 재생을 시작해요. `start`초부터(=/음량 변경 뒤 이어 틀기)."""
        voice_client = guild.voice_client
        if voice_client is None:
            return

        # 🔊 인코더 비트레이트를 **채널 음질에 맞춰요**(2026-11-15 부스트 2레벨 → 채널 256kbps).
        #    채널 값보다 높게 보내봐야 의미가 없고, 512가 Opus 상한이에요.
        #    2026-11-25부터는 이 값으로 **ffmpeg가** 압축해요(봇은 다 된 조각을 보내기만).
        channel_kbps = getattr(voice_client.channel, "bitrate", 128_000) // 1000
        bitrate = max(64, min(channel_kbps, 512))
        # 🌐 ffmpeg는 이제 주소를 직접 받지 않고 표준입력(pipe)으로 받아요 → -reconnect 옵션은 안 써요
        #    (끊긴 구간은 ChunkedHTTPReader가 다시 요청해요). 파이프는 되감기가 안 돼서 -ss는
        #    ffmpeg가 그 지점까지 읽고 버리는 방식이에요(구간 받기가 빨라서 몇 초 안 걸려요).
        options = f"{FFMPEG_OPTIONS} -af volume={state.volume:.2f}"
        seek = f"-ss {start:.2f}" if start > 0 else ""
        if state.stream_protocol in ("http", "https"):
            reader = ChunkedHTTPReader(stream_url, state.stream_headers)
            inner = discord.FFmpegOpusAudio(reader, pipe=True, bitrate=bitrate,
                                            before_options=seek or None, options=options)
        else:
            # m3u8(HLS) 같은 건 여러 파일을 따라가야 해서 ffmpeg가 직접 받아요(예전 방식).
            reader = None
            inner = discord.FFmpegOpusAudio(stream_url, bitrate=bitrate,
                                            before_options=f"{FFMPEG_BEFORE_OPTIONS} {seek}".strip(),
                                            options=options)
        source = TimedOpusSource(inner, start=start, label=track.title[:40], reader=reader)
        state.source = source

        def _after(error):
            # ⚠️ 이 콜백은 이벤트 루프가 아니라 **오디오 재생 스레드**에서 불려요.
            # 예전엔 여기서 fut.result()로 다음 곡 준비가 끝날 때까지 기다렸는데, 그러면
            # 재생 스레드가 묶인 채 이벤트 루프까지 같은 락을 기다리다 통째로 멈춰버려요.
            # (2026-09-02 프로덕션에서 "heartbeat blocked for more than 10 seconds" 발생 →
            #  소리가 끊기고 봇이 잠깐 먹통이 됨.) 그래서 기다리지 않고 예약만 하고,
            # 실패하면 콜백으로 로그만 남겨요.
            if error:
                log.warning(f"⚠️ 음악 재생 중 오류: {error}")

            future = asyncio.run_coroutine_threadsafe(self._play_next(guild), self.bot.loop)

            def _log_failure(done):
                try:
                    done.result()
                except Exception as e:  # noqa: BLE001
                    log.warning(f"⚠️ 다음 곡 재생 예약 실패: {e}")

            future.add_done_callback(_log_failure)

        voice_client.play(source, after=_after, bitrate=bitrate, signal_type="music")

    async def add_track_and_play(
        self,
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        text_channel: discord.abc.Messageable,
        requester_name: str,
        webpage_url: str,
    ):
        """검색/링크로 확정된 영상 하나를 대기열에 넣고, 필요하면 바로 재생을 시작해요."""
        state = self._get_state(guild.id)
        state.text_channel = text_channel
        self._cancel_idle_timer(guild.id)

        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, _extract_sync, webpage_url)
        except Exception as e:  # noqa: BLE001
            await text_channel.send(f"⚠️ 불러오기에 실패했어요: {e}")
            return

        track = Track(
            title=info.get("title", "제목 없음"),
            webpage_url=info.get("webpage_url") or webpage_url,
            duration=info.get("duration"),
            requester_name=requester_name,
            thumbnail=info.get("thumbnail"),
        )
        state.queue.append(track)

        voice_client = guild.voice_client
        if voice_client is None:
            voice_client = await voice_channel.connect()
        elif voice_client.channel.id != voice_channel.id:
            await voice_client.move_to(voice_channel)

        if not voice_client.is_playing() and not voice_client.is_paused():
            await text_channel.send(embed=_build_track_embed(track, status="🎵 대기열에 추가했어요"))
            await self._play_next(guild)
        else:
            position = len(state.queue)
            embed = _build_track_embed(
                track, status="📋 대기열에 추가했어요", extra_field=("대기 순서", f"{position}번째")
            )
            await text_channel.send(embed=embed)

    async def add_playlist_and_play(
        self,
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        text_channel: discord.abc.Messageable,
        requester_name: str,
        entries: list[dict],
    ):
        """재생목록 링크로 확정된 여러 곡을 한 번에 대기열에 넣어요."""
        state = self._get_state(guild.id)
        state.text_channel = text_channel
        self._cancel_idle_timer(guild.id)

        added = 0
        for entry in entries[:MAX_PLAYLIST_TRACKS]:
            url = _entry_url(entry)
            if not url:
                continue
            state.queue.append(
                Track(
                    title=entry.get("title") or "제목 없음",
                    webpage_url=url,
                    duration=entry.get("duration"),
                    requester_name=requester_name,
                    thumbnail=_entry_thumbnail(entry),
                )
            )
            added += 1

        if added == 0:
            await text_channel.send("⚠️ 재생목록에서 곡을 하나도 못 가져왔어요.")
            return

        skipped = len(entries) - added
        note = f" (최대 {MAX_PLAYLIST_TRACKS}곡까지만 담았어요)" if skipped > 0 else ""
        await text_channel.send(f"📃 재생목록에서 **{added}곡**을 대기열에 추가했어요!{note}")

        voice_client = guild.voice_client
        if voice_client is None:
            voice_client = await voice_channel.connect()
        elif voice_client.channel.id != voice_channel.id:
            await voice_client.move_to(voice_channel)

        if not voice_client.is_playing() and not voice_client.is_paused():
            await self._play_next(guild)

    # ============================================================
    # 슬래시 명령어
    # ============================================================
    @app_commands.command(name="재생", description="노래방 음성채널에서 노래를 재생해요. (검색어 또는 유튜브 링크)")
    @app_commands.describe(검색어="재생할 노래 제목 또는 유튜브 링크")
    @require_karaoke_channel()
    async def play(self, interaction: discord.Interaction, 검색어: str):
        await interaction.response.defer()

        if (
            not isinstance(interaction.user, discord.Member)
            or interaction.user.voice is None
            or interaction.user.voice.channel is None
        ):
            await interaction.followup.send("❌ 먼저 음성채널에 들어가주세요.")
            return

        voice_channel = interaction.user.voice.channel
        guild = interaction.guild

        if _is_url(검색어):
            await interaction.followup.send("🔎 불러오는 중...")
            try:
                loop = asyncio.get_running_loop()
                probed = await loop.run_in_executor(None, _probe_playlist_sync, 검색어)
            except Exception as e:  # noqa: BLE001
                await interaction.channel.send(f"⚠️ 불러오기에 실패했어요: {e}")
                return

            entries = [e for e in probed.get("entries", []) if e] if isinstance(probed, dict) else []
            if len(entries) > 1:
                await self.add_playlist_and_play(
                    guild, voice_channel, interaction.channel, interaction.user.display_name, entries
                )
            else:
                await self.add_track_and_play(
                    guild, voice_channel, interaction.channel, interaction.user.display_name, 검색어
                )
            return

        try:
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, _search_sync, 검색어)
        except Exception as e:  # noqa: BLE001
            await interaction.followup.send(f"⚠️ 검색에 실패했어요: {e}")
            return

        if not results:
            await interaction.followup.send("검색 결과가 없어요.")
            return

        view = SongPickView(self, guild, voice_channel, interaction.user)
        for entry in results:
            view.add_option(entry)
        message = await interaction.followup.send("🔎 검색 결과 중 하나를 골라주세요:", view=view)
        view.message = message

    @app_commands.command(name="일시정지", description="지금 재생 중인 노래를 일시정지해요.")
    @require_karaoke_channel()
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client is None or not voice_client.is_playing():
            await interaction.response.send_message("지금 재생 중인 노래가 없어요.", ephemeral=True)
            return
        voice_client.pause()
        await interaction.response.send_message("⏸️ 일시정지했어요.")

    @app_commands.command(name="재개", description="일시정지한 노래를 다시 재생해요.")
    @require_karaoke_channel()
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client is None or not voice_client.is_paused():
            await interaction.response.send_message("일시정지된 노래가 없어요.", ephemeral=True)
            return
        state = self._get_state(interaction.guild.id)
        if state.source is not None:
            state.source.reset_clock()   # 멈춰 있던 시간을 '끊김'으로 세지 않게
        voice_client.resume()
        await interaction.response.send_message("▶️ 다시 재생할게요.")

    @app_commands.command(name="스킵", description="지금 노래를 건너뛰고 다음 곡을 재생해요.")
    @require_karaoke_channel()
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client is None or (not voice_client.is_playing() and not voice_client.is_paused()):
            await interaction.response.send_message("지금 재생 중인 노래가 없어요.", ephemeral=True)
            return
        # "한 곡 반복" 중에 스킵하면 같은 곡이 또 나와서 영영 안 넘어가요. 이번 한 번만
        # 반복을 건너뛰게 표시해두고 넘겨요(반복 설정 자체는 그대로 유지돼요).
        self._get_state(interaction.guild.id).skip_repeat_once = True
        voice_client.stop()  # after 콜백이 자동으로 다음 곡을 재생해요.
        await interaction.response.send_message("⏭️ 건너뛸게요.")

    @app_commands.command(name="반복", description="반복 재생을 설정해요. (끄기 / 한 곡 반복 / 전체 반복)")
    @app_commands.describe(모드="비우면 지금 설정이 뭔지만 알려줘요.")
    @app_commands.choices(모드=[
        app_commands.Choice(name="➡️ 반복 끄기", value=REPEAT_OFF),
        app_commands.Choice(name="🔂 한 곡 반복 (지금 곡만 계속)", value=REPEAT_ONE),
        app_commands.Choice(name="🔁 전체 반복 (대기열을 한 바퀴씩)", value=REPEAT_ALL),
    ])
    @require_karaoke_channel()
    async def repeat(self, interaction: discord.Interaction, 모드: app_commands.Choice[str] = None):
        state = self._get_state(interaction.guild.id)

        if 모드 is None:
            await interaction.response.send_message(
                f"지금 반복 설정: **{REPEAT_LABELS[state.repeat_mode]}**", ephemeral=True
            )
            return

        state.repeat_mode = 모드.value
        if 모드.value == REPEAT_OFF:
            message = "➡️ 반복을 껐어요. 대기열이 끝나면 그대로 멈춰요."
        elif 모드.value == REPEAT_ONE:
            message = "🔂 **한 곡 반복**으로 바꿨어요. 지금 곡이 계속 다시 재생돼요. (`/스킵`으로 다음 곡 이동)"
        else:
            message = "🔁 **전체 반복**으로 바꿨어요. 대기열이 끝나면 처음부터 다시 돌아요."
        await interaction.response.send_message(message)

    @app_commands.command(name="정지", description="재생을 멈추고 대기열을 비운 뒤 음성채널에서 나가요.")
    @require_karaoke_channel()
    async def stop(self, interaction: discord.Interaction):
        guild = interaction.guild
        voice_client = guild.voice_client
        if voice_client is None:
            await interaction.response.send_message("지금 음성채널에 있지 않아요.", ephemeral=True)
            return

        # 음성 연결 끊기는 게이트웨이 상태가 나쁠 때 늘어질 수 있어요(2026-09-04 사고 때
        # 음성 재연결이 계속 실패했었죠). 응답을 먼저 잡아두고 진행해요.
        await interaction.response.defer()

        self._cancel_idle_timer(guild.id)
        state = self._get_state(guild.id)
        state.queue.clear()
        await voice_client.disconnect(force=True)
        self.states.pop(guild.id, None)
        await interaction.followup.send("🛑 재생을 멈추고 나갔어요.")

    @app_commands.command(name="음량", description="재생 음량을 조절해요. (0~200%, 기본 100%)")
    @app_commands.describe(퍼센트="설정할 음량 (0~200). 비우면 현재 음량만 확인해요.")
    @require_karaoke_channel()
    async def volume(self, interaction: discord.Interaction, 퍼센트: app_commands.Range[int, 0, 200] = None):
        guild = interaction.guild
        state = self._get_state(guild.id)

        if 퍼센트 is None:
            await interaction.response.send_message(f"🔊 현재 음량: {int(state.volume * 100)}%", ephemeral=True)
            return

        changed = abs(state.volume - 퍼센트 / 100) > 1e-6
        state.volume = 퍼센트 / 100
        voice_client = guild.voice_client
        # 🔊 음량은 ffmpeg가 정해요(2026-11-25). 재생 중이면 지금 위치부터 새 음량으로 다시 틀어요.
        #    stop() → after 콜백 → _play_next가 restart_at을 보고 같은 곡을 이어 틀어요.
        if (changed and voice_client is not None and voice_client.is_playing()
                and state.source is not None and state.stream_url):
            state.restart_at = state.source.position
            voice_client.stop()
            await interaction.response.send_message(
                f"🔊 음량을 {퍼센트}%로 바꿨어요. (지금 곡을 이 자리부터 새 음량으로 이어서 틀어요)")
            return
        if changed and voice_client is not None and voice_client.is_paused():
            await interaction.response.send_message(
                f"🔊 음량을 {퍼센트}%로 설정했어요. 일시정지 중이라 **다음 곡부터** 적용돼요.")
            return

        await interaction.response.send_message(f"🔊 음량을 {퍼센트}%로 설정했어요.")

    @app_commands.command(name="대기열", description="지금 재생 중인 곡과 대기 중인 곡 목록을 봐요.")
    @require_karaoke_channel()
    async def queue_(self, interaction: discord.Interaction):
        guild = interaction.guild
        voice_client = guild.voice_client
        state = self._get_state(guild.id)

        if voice_client is None or (not voice_client.is_playing() and not voice_client.is_paused()):
            await interaction.response.send_message("지금 재생 중인 노래가 없어요.", ephemeral=True)
            return

        embed = discord.Embed(title="🎶 대기열", color=EMBED_COLOR)

        if state.current is not None:
            embed.add_field(
                name="지금 재생 중",
                value=(
                    f"[{state.current.title}]({state.current.webpage_url}) "
                    f"({_format_duration(state.current.duration)}) — 신청: {state.current.requester_name}"
                ),
                inline=False,
            )
            if state.current.thumbnail:
                embed.set_thumbnail(url=state.current.thumbnail)

        if state.queue:
            lines = [
                f"{i}. [{t.title}]({t.webpage_url}) ({_format_duration(t.duration)}) — 신청: {t.requester_name}"
                for i, t in enumerate(state.queue, start=1)
            ]
            embed.add_field(name=f"대기 중 ({len(state.queue)}곡)", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="대기 중", value="(없음)", inline=False)

        # 반복이 켜져 있으면 "대기열이 비었는데 왜 안 끝나지?" 하고 헷갈리니 같이 보여줘요.
        if state.repeat_mode != REPEAT_OFF:
            embed.set_footer(text=f"{REPEAT_LABELS[state.repeat_mode]} 중 · /반복 으로 변경")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="대기열삭제", description="대기열에서 특정 곡을 삭제해요.")
    @app_commands.describe(순번="/대기열에서 보이는 번호")
    @require_karaoke_channel()
    async def remove_from_queue(self, interaction: discord.Interaction, 순번: app_commands.Range[int, 1, 200]):
        state = self._get_state(interaction.guild.id)
        if 순번 > len(state.queue):
            await interaction.response.send_message("그 번호의 곡이 없어요. `/대기열`로 다시 확인해주세요.", ephemeral=True)
            return
        removed = state.queue[순번 - 1]
        del state.queue[순번 - 1]
        await interaction.response.send_message(f"🗑️ 대기열에서 삭제했어요: **{removed.title}**")

    @app_commands.command(name="대기열섞기", description="대기열 순서를 무작위로 섞어요.")
    @require_karaoke_channel()
    async def shuffle_queue(self, interaction: discord.Interaction):
        state = self._get_state(interaction.guild.id)
        if len(state.queue) < 2:
            await interaction.response.send_message("섞을 만큼 대기열에 곡이 충분하지 않아요.", ephemeral=True)
            return
        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)
        await interaction.response.send_message(f"🔀 대기열 {len(items)}곡을 섞었어요.")

    # ============================================================
    # 봇 혼자 남으면 자동으로 나가기
    # ============================================================
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.id == self.bot.user.id:
            return
        if before.channel is None:
            return
        if after.channel is not None and after.channel.id == before.channel.id:
            return  # 같은 채널에 그대로 있음 (음소거 등 상태 변경일 뿐 실제 퇴장이 아니에요)

        guild = before.channel.guild
        voice_client = guild.voice_client
        if voice_client is None or voice_client.channel.id != before.channel.id:
            return

        if len([m for m in before.channel.members if not m.bot]) == 0:
            self._cancel_idle_timer(guild.id)
            state = self._get_state(guild.id)
            state.queue.clear()
            await voice_client.disconnect(force=True)
            self.states.pop(guild.id, None)
            log.info(f"🎤 '{before.channel.name}'에 아무도 없어서 음악 재생을 멈추고 나갔어요.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
