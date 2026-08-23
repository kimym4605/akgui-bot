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
import asyncio
import os
import random
from collections import deque
from dataclasses import dataclass, field

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

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


def _get_karaoke_channel_id() -> int | None:
    raw = os.getenv("KARAOKE_VOICE_CHANNEL_ID")
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def require_karaoke_channel():
    """이 데코레이터를 붙인 명령어는 KARAOKE_VOICE_CHANNEL_ID로 지정한 음성채널에
    들어가 있는 사람만 쓸 수 있어요. 설정 안 했으면 제한 없이 아무 음성채널에서나 동작해요."""

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


@dataclass
class GuildMusicState:
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    text_channel: discord.abc.Messageable | None = None
    idle_task: asyncio.Task | None = None
    volume: float = 1.0  # 0.0~2.0 (0~200%)


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

        if not state.queue:
            state.current = None
            self._schedule_idle_leave(guild)
            return

        track = state.queue.popleft()
        state.current = track

        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, _extract_sync, track.webpage_url)
            stream_url = info["url"]
        except Exception as e:  # noqa: BLE001
            if state.text_channel is not None:
                await state.text_channel.send(f"⚠️ **{track.title}** 재생 준비 중 오류가 나서 건너뛸게요. ({e})")
            await self._play_next(guild)
            return

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, before_options=FFMPEG_BEFORE_OPTIONS, options=FFMPEG_OPTIONS),
            volume=state.volume,
        )

        def _after(error):
            if error:
                print(f"⚠️ 음악 재생 중 오류: {error}")
            fut = asyncio.run_coroutine_threadsafe(self._play_next(guild), self.bot.loop)
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ 다음 곡 재생 예약 실패: {e}")

        voice_client.play(source, after=_after)

        if state.text_channel is not None:
            await state.text_channel.send(embed=_build_track_embed(track, status="🎶 지금 재생 중"))

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
        voice_client.resume()
        await interaction.response.send_message("▶️ 다시 재생할게요.")

    @app_commands.command(name="스킵", description="지금 노래를 건너뛰고 다음 곡을 재생해요.")
    @require_karaoke_channel()
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client is None or (not voice_client.is_playing() and not voice_client.is_paused()):
            await interaction.response.send_message("지금 재생 중인 노래가 없어요.", ephemeral=True)
            return
        voice_client.stop()  # after 콜백이 자동으로 다음 곡을 재생해요.
        await interaction.response.send_message("⏭️ 건너뛸게요.")

    @app_commands.command(name="정지", description="재생을 멈추고 대기열을 비운 뒤 음성채널에서 나가요.")
    @require_karaoke_channel()
    async def stop(self, interaction: discord.Interaction):
        guild = interaction.guild
        voice_client = guild.voice_client
        if voice_client is None:
            await interaction.response.send_message("지금 음성채널에 있지 않아요.", ephemeral=True)
            return

        self._cancel_idle_timer(guild.id)
        state = self._get_state(guild.id)
        state.queue.clear()
        await voice_client.disconnect(force=True)
        self.states.pop(guild.id, None)
        await interaction.response.send_message("🛑 재생을 멈추고 나갔어요.")

    @app_commands.command(name="음량", description="재생 음량을 조절해요. (0~200%, 기본 100%)")
    @app_commands.describe(퍼센트="설정할 음량 (0~200). 비우면 현재 음량만 확인해요.")
    @require_karaoke_channel()
    async def volume(self, interaction: discord.Interaction, 퍼센트: app_commands.Range[int, 0, 200] = None):
        guild = interaction.guild
        state = self._get_state(guild.id)

        if 퍼센트 is None:
            await interaction.response.send_message(f"🔊 현재 음량: {int(state.volume * 100)}%", ephemeral=True)
            return

        state.volume = 퍼센트 / 100
        voice_client = guild.voice_client
        if voice_client is not None and isinstance(voice_client.source, discord.PCMVolumeTransformer):
            voice_client.source.volume = state.volume

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
            print(f"🎤 '{before.channel.name}'에 아무도 없어서 음악 재생을 멈추고 나갔어요.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
