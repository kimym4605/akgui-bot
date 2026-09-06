"""일일 미션 - `/미션`으로 확인하고, 깨면 악귀코인을 줘요.

미션 정의와 진행도 저장은 utils/mission_store.py에 있어요. 여기서는 "언제 진행도를 올릴지"와
"어떻게 보여줄지"만 다뤄요.

## 진행도를 올리는 세 가지 경로

1. **명령어 사용** - `on_app_command_completion` 하나로 전부 잡아요. 각 cog를 건드릴 필요가
   없어요(`mission_store.COMMAND_MISSIONS` 표만 고치면 미션을 추가할 수 있어요).
2. **통화방 체류** - 음성 상태 변화 + 5분마다 중간 정산. 통화를 길게 켜놔도 나갈 때까지
   기다리지 않아요(봇이 중간에 재시작돼도 그때까지 있던 시간은 반영돼요).
3. **발로란트 전적** - `/미션`을 칠 때만 조회해요. 상시 조회하면 API 호출량이 감당이 안 돼요.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.rank import HENRIK_BASE, _extract_player_match_stats
from utils import coin_wallet, mission_store, riot_account_store
from utils.channel_check import restrict_to_channel
from utils.mission_store import MISSIONS, ONE_TIME_MISSIONS

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

VOICE_FLUSH_MINUTES = 5   # 통화 중이어도 5분마다 중간 정산해요
MATCH_FETCH_SIZE = 10     # 전적은 최근 10경기만 봐요 (오늘 것만 걸러서 씀)
DEFAULT_REGION = "kr"


def _is_today_kst(unix_seconds: int | None) -> bool:
    if not unix_seconds:
        return False
    played = datetime.fromtimestamp(unix_seconds, KST).date()
    return played == datetime.now(KST).date()


class Mission(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        # {user_id: 이 채널에 들어온 시각} - 통화방 체류 시간 계산용
        self._voice_since: dict[int, datetime] = {}
        self.flush_voice.start()

    def cog_unload(self):
        self.flush_voice.cancel()
        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ------------------------------------------------------------------
    # 공통: 미션 완료 처리 + 코인 지급
    # ------------------------------------------------------------------
    async def _complete(self, user_id: int, key: str, channel: discord.abc.Messageable | None = None):
        """이번에 새로 깼으면 코인을 주고 알려줘요. 이미 깬 미션이면 아무 일도 안 해요."""
        if not await mission_store.progress(user_id, key):
            return

        balance = await coin_wallet.add(user_id, mission_store.REWARD_PER_MISSION, reason=f"미션:{key}")
        info = MISSIONS[key]
        log.info("🎯 미션 완료: %s / %s (+%d코인)", user_id, key, mission_store.REWARD_PER_MISSION)

        if channel is None:
            return
        try:
            await channel.send(
                f"🎯 <@{user_id}> **{info['title']}** 미션 완료! "
                f"악귀코인 **+{mission_store.REWARD_PER_MISSION}개** (보유 {balance}개)"
            )
        except discord.HTTPException:
            # 알림 실패로 코인 지급을 되돌리진 않아요. 코인은 이미 들어갔어요.
            log.warning("미션 완료 알림 전송 실패 (user=%s key=%s)", user_id, key, exc_info=True)

    async def _is_linked(self, user_id: int) -> bool:
        return riot_account_store.get_account(user_id) is not None

    # ------------------------------------------------------------------
    # 1. 명령어 사용 감지
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command
    ):
        key = mission_store.COMMAND_MISSIONS.get(command.name)
        if key is None or interaction.user.bot:
            return
        # 오늘 미션을 아직 안 받았을 수 있으니 먼저 배정해둬요.
        await mission_store.ensure_today(interaction.user.id, await self._is_linked(interaction.user.id))
        await self._complete(interaction.user.id, key, interaction.channel)

    # ------------------------------------------------------------------
    # 2. 통화방 체류 시간
    # ------------------------------------------------------------------
    def _countable(self, channel: discord.VoiceChannel | None) -> bool:
        """봇을 뺀 사람이 2명 이상인 채널만 인정해요 (혼자 접속해두는 어뷰징 차단)."""
        if channel is None:
            return False
        return len([m for m in channel.members if not m.bot]) >= mission_store.VOICE_MIN_MEMBERS

    async def _settle_voice(self, member: discord.Member, channel: discord.VoiceChannel | None):
        """지금까지 머문 시간을 미션 진행도에 반영해요."""
        started = self._voice_since.pop(member.id, None)
        if started is None or not self._countable(channel):
            return

        minutes = int((datetime.now(timezone.utc) - started).total_seconds() // 60)
        if minutes <= 0:
            return

        await mission_store.ensure_today(member.id, await self._is_linked(member.id))
        # ⚠️ 여기서 _complete()를 쓰면 안 돼요. 그건 진행도를 1씩만 올려서, 30분짜리 미션이
        # 5분 정산 한 번에 1분만 오르거든요. 실제로 머문 분만큼 올려야 해요.
        await self._add_voice_minutes(member, channel, minutes)

    async def _add_voice_minutes(self, member: discord.Member, channel, minutes: int):
        if await mission_store.progress(member.id, "voice_together", minutes):
            balance = await coin_wallet.add(
                member.id, mission_store.REWARD_PER_MISSION, reason="미션:voice_together"
            )
            try:
                await channel.send(
                    f"🎯 {member.mention} **{MISSIONS['voice_together']['title']}** 미션 완료! "
                    f"악귀코인 **+{mission_store.REWARD_PER_MISSION}개** (보유 {balance}개)"
                )
            except (discord.HTTPException, AttributeError):
                log.warning("통화 미션 알림 실패 (user=%s)", member.id, exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return
        if before.channel == after.channel:
            return  # 음소거 등 채널 이동이 아닌 변화는 무시해요

        if before.channel is not None:
            await self._settle_voice(member, before.channel)
        if after.channel is not None:
            self._voice_since[member.id] = datetime.now(timezone.utc)

    @tasks.loop(minutes=VOICE_FLUSH_MINUTES)
    async def flush_voice(self):
        """통화를 계속 켜놓고 있는 사람들의 시간을 중간 정산해요."""
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if not self._countable(channel):
                    continue
                for member in channel.members:
                    if member.bot or member.id not in self._voice_since:
                        continue
                    await self._settle_voice(member, channel)
                    self._voice_since[member.id] = datetime.now(timezone.utc)

    @flush_voice.before_loop
    async def _before_flush(self):
        await self.bot.wait_until_ready()
        # 봇이 켜질 때 이미 통화 중인 사람들의 타이머를 시작해요.
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        self._voice_since[member.id] = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # 3. 발로란트 전적 판정
    # ------------------------------------------------------------------
    async def _fetch_today_matches(self, name: str, tag: str) -> list[dict] | None:
        """오늘 플레이한 경기만 돌려줘요. 조회 실패면 None."""
        api_key = os.getenv("HENRIKDEV_API_KEY")
        if not api_key:
            return None

        session = await self._get_session()
        url = f"{HENRIK_BASE}/valorant/v3/matches/{DEFAULT_REGION}/{name}/{tag}"
        try:
            async with session.get(
                url, headers={"Authorization": api_key}, params={"size": MATCH_FETCH_SIZE}
            ) as resp:
                if resp.status != 200:
                    log.info("전적 조회 실패 (%s#%s status=%s)", name, tag, resp.status)
                    return None
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            log.warning("전적 조회 중 네트워크 오류 (%s#%s)", name, tag, exc_info=True)
            return None

        matches = payload.get("data") or []
        return [
            m for m in matches
            if m and _is_today_kst((m.get("metadata") or {}).get("game_start"))
        ]

    async def _check_valorant(self, user_id: int, keys: list[str], channel) -> str | None:
        """발로란트 미션들을 오늘 전적으로 판정해요. 조회를 못 하면 사유 문구를 돌려줘요."""
        account = riot_account_store.get_account(user_id)
        if account is None:
            return "라이엇 계정이 연동되어 있지 않아요. `/전적`에서 본인 계정을 등록해주세요."

        name, tag = account
        matches = await self._fetch_today_matches(name, tag)
        if matches is None:
            return "전적을 불러오지 못했어요. 잠시 뒤에 다시 시도해주세요."
        if not matches:
            return None  # 오늘 한 경기가 없을 뿐 - 정상이에요

        stats = [s for s in (_extract_player_match_stats(m, name, tag) for m in matches) if s]

        for key in keys:
            achieved = False
            if key == "val_play":
                achieved = len(stats) >= 1
            elif key == "val_win":
                achieved = any(s["won"] for s in stats)
            elif key == "val_kills15":
                achieved = any(s["kills"] >= 15 for s in stats)
            elif key == "val_kd1":
                achieved = any(s["kills"] / max(s["deaths"], 1) >= 1.0 for s in stats)
            elif key == "val_comp":
                achieved = any(
                    ((m.get("metadata") or {}).get("mode") or "").lower() == "competitive"
                    for m in matches
                )
            if achieved:
                await self._complete(user_id, key, channel)
        return None

    # ------------------------------------------------------------------
    # /미션
    # ------------------------------------------------------------------
    @app_commands.command(name="미션", description="오늘의 미션과 진행 상황을 확인해요.")
    @restrict_to_channel("attendance")
    async def show(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user_id = interaction.user.id
        linked = await self._is_linked(user_id)

        # ⚠️ 순서 주의: 1회성 미션 기록은 미션 문서 안에 들어가니, 문서를 먼저 만들어야 해요.
        doc = await mission_store.ensure_today(user_id, linked)

        # 연동만 해두고 아직 보상을 못 받았으면 1회성 미션을 여기서 챙겨줘요.
        if linked and await mission_store.claim_one_time(user_id, "link_riot"):
            reward = ONE_TIME_MISSIONS["link_riot"]["reward"]
            await coin_wallet.add(user_id, reward, reason="미션:link_riot")
            await interaction.followup.send(
                f"🎉 **라이엇 계정 연동** 미션 완료! 악귀코인 **+{reward}개**"
            )

        # 발로란트 미션이 배정돼 있으면 지금 전적을 조회해서 판정해요.
        note = None
        valorant_keys = [k for k in doc["picks"] if MISSIONS[k]["kind"] == "valorant"]
        if valorant_keys:
            note = await self._check_valorant(user_id, valorant_keys, None)
            doc = await mission_store.ensure_today(user_id, linked)  # 판정 결과 반영해서 다시 읽기

        lines = []
        for key in doc["picks"]:
            info = MISSIONS[key]
            done = key in doc.get("done", [])
            current = doc.get("progress", {}).get(key, 0)
            target = info["target"]

            if done:
                lines.append(f"✅ ~~**{info['title']}** — {info['desc']}~~")
            elif target > 1:
                lines.append(
                    f"⬜ **{info['title']}** — {info['desc']}\n"
                    f"　　진행 {min(current, target)}/{target}{info['unit']}"
                )
            else:
                lines.append(f"⬜ **{info['title']}** — {info['desc']}")

        done_count = len(doc.get("done", []))
        embed = discord.Embed(
            title="🎯 오늘의 미션",
            description="\n".join(lines),
            color=0x57F287 if done_count == len(doc["picks"]) else 0x5865F2,
        )
        embed.add_field(
            name="오늘 획득",
            value=f"악귀코인 **{done_count * mission_store.REWARD_PER_MISSION}개** "
                  f"({done_count}/{len(doc['picks'])} 완료)",
            inline=False,
        )
        if not linked:
            embed.add_field(
                name="💡 발로란트 미션도 받고 싶다면",
                value="`/전적`에서 본인 라이엇 계정을 등록하면 발로란트 미션이 배정되고, "
                      f"연동 보상으로 **{ONE_TIME_MISSIONS['link_riot']['reward']}코인**을 드려요.",
                inline=False,
            )
        if note:
            embed.set_footer(text=note)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Mission(bot))
