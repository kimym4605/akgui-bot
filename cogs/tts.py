"""
악귀봇 전용 목소리 TTS(텍스트 음성 변환) 기능이에요.

- /tts시작 을 실행하면, 명령어를 실행한 사람이 있는 음성채널에 봇이 들어가요.
- 그 다음부터는 **봇이랑 같은 음성채널에 들어와있는 사람이 아무 채널에나 채팅을 치면**,
  그 내용을 봇 전용 목소리로 자동으로 읽어줘요. (따로 명령어 안 쳐도 돼요)
- /tts나가기 로 봇을 음성채널에서 내보내면 자동 읽기도 같이 꺼져요.

사용하는 TTS 엔진: edge-tts (마이크로소프트 엣지 브라우저의 "소리내어 읽기" 엔진을
API 키 없이 무료로 쓸 수 있게 해주는 비공식 라이브러리예요). 여러 자연스러운 한국어
뉴럴 보이스 중 하나를 "봇 전용 목소리"로 고정해서 써요.

⚠️ 필수 조건:
- Discord 개발자 포털 > Bot 탭 > Privileged Gateway Intents 에서
  "MESSAGE CONTENT INTENT"를 켜야 채팅 내용을 읽을 수 있어요. (bot.py에서도 intents.message_content = True 설정 필요)
- 서버(컨테이너)에 FFmpeg가 설치되어 있어야 해요. (대부분의 Python 에그엔 기본 포함이지만
  재생이 안 되면 이것부터 확인해보세요)
- requirements.txt에 edge-tts, PyNaCl, davey가 추가되어 있어야 해요.
"""
import asyncio
import os
import time
import uuid
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import edge_tts

# 악귀봇 전용 목소리로 고정해둔 값이에요. 아래 후보 중에 골라서 바꿔도 되고,
# `edge-tts --list-voices`로 더 많은 후보를 찾아볼 수도 있어요.
BOT_VOICE = "ko-KR-SunHiNeural"  # 여성, 표준 톤
# 다른 한국어 후보: "ko-KR-InJoonNeural"(남성) / "ko-KR-BongJinNeural"(남성) / "ko-KR-GookMinNeural"(남성) /
#                   "ko-KR-HyunsuNeural"(남성, 젊은 톤) / "ko-KR-JiMinNeural"(여성) / "ko-KR-SeoHyeonNeural"(여성) /
#                   "ko-KR-SoonBokNeural"(여성) / "ko-KR-YuJinNeural"(여성)

DEFAULT_VOLUME = 0.5  # 기본 재생 음량이에요. 0.0(무음) ~ 2.0(200%) 사이로 조절 가능해요.

TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "tts_temp")
MAX_TEXT_LENGTH = 200  # 한 번에 읽을 수 있는 최대 글자 수예요. (너무 길면 음성채널이 오래 점유돼요)


class GuildTTSState:
    """서버(길드)마다 따로 관리하는 TTS 상태예요. 여러 서버에서 동시에 써도 서로 안 겹쳐요."""

    def __init__(self):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task] = None
        self.voice_client: Optional[discord.VoiceClient] = None


class TTS(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildTTSState] = {}
        os.makedirs(TEMP_DIR, exist_ok=True)

    def _get_state(self, guild_id: int) -> GuildTTSState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildTTSState()
        return self.states[guild_id]

    async def _synthesize(self, text: str) -> str:
        """텍스트를 mp3 파일로 만들어서 파일 경로를 반환해요."""
        _t0 = time.monotonic()
        path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}.mp3")
        communicate = edge_tts.Communicate(text, BOT_VOICE)
        await communicate.save(path)
        print(f"⏱️ [TTS] 음성 생성(edge-tts): {time.monotonic() - _t0:.2f}초 (글자수 {len(text)})")
        return path

    async def _worker(self, guild_id: int):
        """이 서버의 TTS 대기열을 순서대로 처리해요. (동시에 여러 개 재생하면 소리가 겹치니까 한 번에 하나씩)"""
        state = self._get_state(guild_id)
        while True:
            text = await state.queue.get()
            _t_start = time.monotonic()
            try:
                if state.voice_client is None or not state.voice_client.is_connected():
                    print("⏱️ [TTS] 음성채널 연결 안 됨 - 건너뜀")
                    continue  # 봇이 음성채널에서 나가있으면 그냥 건너뛰어요.

                path = await self._synthesize(text)
                done_event = asyncio.Event()

                def _after_playback(error: Optional[Exception]):
                    if error:
                        print(f"⚠️ TTS 재생 중 오류: {error}")
                    self.bot.loop.call_soon_threadsafe(done_event.set)

                _t_play = time.monotonic()
                source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(path), volume=DEFAULT_VOLUME)
                state.voice_client.play(source, after=_after_playback)
                await done_event.wait()
                print(
                    f"⏱️ [TTS] 재생 완료: {time.monotonic() - _t_play:.2f}초 재생됨 / "
                    f"전체(대기열~완료): {time.monotonic() - _t_start:.2f}초"
                )

                try:
                    os.remove(path)
                except OSError:
                    pass
            except Exception as error:  # noqa: BLE001
                print(f"⚠️ TTS 처리 중 오류: {error}")
            finally:
                state.queue.task_done()

    @app_commands.command(name="tts시작", description="악귀봇을 음성채널에 불러서, 같이 있는 사람 채팅을 자동으로 읽어주게 해요.")
    async def tts_start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        voice_state = interaction.user.voice if isinstance(interaction.user, discord.Member) else None
        if voice_state is None or voice_state.channel is None:
            await interaction.followup.send("먼저 음성 채널에 입장한 뒤 사용해주세요.", ephemeral=True)
            return

        target_channel = voice_state.channel
        state = self._get_state(interaction.guild.id)

        _t_connect = time.monotonic()
        try:
            if state.voice_client is None or not state.voice_client.is_connected():
                state.voice_client = await target_channel.connect()
            elif state.voice_client.channel.id != target_channel.id:
                await state.voice_client.move_to(target_channel)
        except discord.ClientException as error:
            await interaction.followup.send(f"⚠️ 음성채널 접속 중 오류가 발생했어요: {error}", ephemeral=True)
            return
        print(f"⏱️ [TTS] 음성채널 접속/이동: {time.monotonic() - _t_connect:.2f}초")

        if state.worker_task is None or state.worker_task.done():
            state.worker_task = asyncio.create_task(self._worker(interaction.guild.id))

        await interaction.followup.send(
            f"🔊 {target_channel.mention}에 들어왔어요! 이제 여기 같이 있는 사람이 아무 채널에나 "
            f"채팅을 치면 자동으로 읽어드려요.\n(그만 쓰려면 `/tts나가기`)",
            ephemeral=True,
        )

    @app_commands.command(name="tts나가기", description="TTS 봇을 음성채널에서 내보내고, 채팅 자동 읽기를 꺼요.")
    async def tts_leave(self, interaction: discord.Interaction):
        state = self._get_state(interaction.guild.id)

        if state.voice_client is not None and state.voice_client.is_connected():
            await state.voice_client.disconnect()
            state.voice_client = None

            # 밀려있던 대기열도 다 비워줘요.
            while not state.queue.empty():
                state.queue.get_nowait()
                state.queue.task_done()

            await interaction.response.send_message("👋 음성채널에서 나갔어요. 자동 읽기도 꺼졌어요.", ephemeral=True)
        else:
            await interaction.response.send_message("지금 음성채널에 들어가있지 않아요.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 봇 자신이나 다른 봇이 보낸 메시지는 무시해요.
        if message.author.bot or message.guild is None:
            return

        state = self.states.get(message.guild.id)
        if state is None or state.voice_client is None or not state.voice_client.is_connected():
            return  # 이 서버에서 TTS가 켜져있지 않으면 아무것도 안 해요.

        # 메시지를 쓴 사람이 봇이랑 같은 음성채널에 있을 때만 읽어줘요.
        # (그래야 통화 중이 아닌 사람들 채팅까지 다 읽어버리는 걸 막을 수 있어요)
        author_voice = message.author.voice if isinstance(message.author, discord.Member) else None
        if author_voice is None or author_voice.channel is None:
            return
        if author_voice.channel.id != state.voice_client.channel.id:
            return

        text = message.content.strip()
        if not text or text.startswith(("!", "/")):
            return  # 빈 메시지나 명령어처럼 보이는 건 건너뛰어요.

        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]

        await state.queue.put(text)


async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot))