import calendar
import datetime
import os
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.birthday_store import delete_birthday, get_all_birthdays, get_birthday, set_birthday
from utils.settings_store import get_setting, set_setting

KST = ZoneInfo("Asia/Seoul")
ANNOUNCE_TIME = datetime.time(hour=9, minute=0, tzinfo=KST)  # 매일 오전 9시(한국시간)에 확인해요

# 자동으로 만들 채널 이름이에요. 원하는 이름으로 바꾸고 싶으면 .env에 BIRTHDAY_CHANNEL_NAME을 추가하세요.
DEFAULT_CHANNEL_NAME = os.getenv("BIRTHDAY_CHANNEL_NAME", "생일")


def _is_birthday_today(today: datetime.date, month: int, day: int) -> bool:
    if today.month == month and today.day == day:
        return True
    # 2월 29일생 배려: 평년에는 2월 28일에 축하해줘요
    if month == 2 and day == 29 and not calendar.isleap(today.year):
        return today.month == 2 and today.day == 28
    return False


def _next_occurrence(today: datetime.date, month: int, day: int) -> datetime.date:
    year = today.year
    try:
        target = datetime.date(year, month, day)
    except ValueError:
        target = datetime.date(year, 2, 28)
    if target < today:
        try:
            target = datetime.date(year + 1, month, day)
        except ValueError:
            target = datetime.date(year + 1, 2, 28)
    return target


class Birthday(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.birthday_check.start()

    def cog_unload(self):
        self.birthday_check.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇이 들어가 있는 모든 서버에 대해 생일 알림 채널이 있는지 확인하고, 없으면 만들어요.
        for guild in self.bot.guilds:
            await self._ensure_channel(guild)

    async def _ensure_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        setting_key = f"birthday_channel_{guild.id}"
        channel_id = get_setting(setting_key)

        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel is not None:
                return channel
            # 저장은 되어있는데 채널이 삭제된 상태 -> 아래에서 새로 찾거나 만들어요

        # 봇이 기록해둔 채널이 없어도, 이미 같은 이름의 채널이 서버에 있으면 그걸 재사용해요.
        existing = discord.utils.get(guild.text_channels, name=DEFAULT_CHANNEL_NAME)
        if existing is not None:
            set_setting(setting_key, existing.id)
            print(f"🎂 '{guild.name}' 서버의 기존 '#{existing.name}' 채널을 생일 알림용으로 재사용해요.")
            return existing

        try:
            channel = await guild.create_text_channel(
                DEFAULT_CHANNEL_NAME, reason="생일 알림용 채널 자동 생성"
            )
        except discord.Forbidden:
            print(f"⚠️ '{guild.name}' 서버에 채널을 만들 권한이 없어요. (봇 권한에 '채널 관리'가 필요해요)")
            return None

        set_setting(setting_key, channel.id)
        print(f"🎂 '{guild.name}' 서버에 '#{channel.name}' 채널을 자동으로 만들었어요.")
        return channel

    @app_commands.command(name="생일등록", description="생일을 등록합니다. (매년 그날 자동으로 축하 메시지가 올라가요)")
    @app_commands.describe(월="태어난 달 (1~12)", 일="태어난 일 (1~31)")
    async def register(
        self,
        interaction: discord.Interaction,
        월: app_commands.Range[int, 1, 12],
        일: app_commands.Range[int, 1, 31],
    ):
        max_day = calendar.monthrange(2024, 월)[1]  # 2024는 윤년이라 2/29까지 허용돼요
        if 일 > max_day:
            await interaction.response.send_message(
                f"{월}월은 {max_day}일까지밖에 없어요. 다시 확인해주세요.", ephemeral=True
            )
            return

        set_birthday(interaction.user.id, 월, 일)
        await interaction.response.send_message(f"🎂 생일이 **{월}월 {일}일**로 등록됐어요!")

    @app_commands.command(name="생일삭제", description="등록했던 내 생일을 삭제합니다.")
    async def delete(self, interaction: discord.Interaction):
        if delete_birthday(interaction.user.id):
            await interaction.response.send_message("생일 등록을 삭제했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("등록된 생일이 없어요.", ephemeral=True)

    @app_commands.command(name="생일확인", description="등록된 생일을 확인합니다.")
    @app_commands.describe(유저="확인할 유저 (비워두면 본인)")
    async def check(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        target = 유저 or interaction.user
        bday = get_birthday(target.id)

        if bday is None:
            await interaction.response.send_message(f"{target.display_name}님은 생일이 등록되어 있지 않아요.")
            return

        await interaction.response.send_message(f"🎂 {target.display_name}님의 생일: {bday['month']}월 {bday['day']}일")

    @app_commands.command(name="다가오는생일", description="다가오는 순서대로 생일 목록을 보여줍니다.")
    async def upcoming(self, interaction: discord.Interaction):
        all_birthdays = get_all_birthdays()

        if not all_birthdays:
            await interaction.response.send_message("등록된 생일이 없어요.")
            return

        today = datetime.datetime.now(KST).date()
        entries = []
        for user_id, b in all_birthdays.items():
            next_date = _next_occurrence(today, b["month"], b["day"])
            entries.append((next_date, user_id))
        entries.sort(key=lambda e: e[0])

        lines = []
        for next_date, user_id in entries[:15]:
            member = interaction.guild.get_member(int(user_id)) if interaction.guild else None
            name = member.display_name if member else f"(알 수 없음: {user_id})"
            d_day = (next_date - today).days
            d_text = "오늘! 🎉" if d_day == 0 else f"D-{d_day}"
            lines.append(f"{next_date.month}월 {next_date.day}일 — {name} ({d_text})")

        embed = discord.Embed(title="🎂 다가오는 생일", description="\n".join(lines), color=0xFF69B4)
        await interaction.response.send_message(embed=embed)

    @tasks.loop(time=ANNOUNCE_TIME)
    async def birthday_check(self):
        today = datetime.datetime.now(KST).date()
        todays_birthdays = [
            (user_id, b)
            for user_id, b in get_all_birthdays().items()
            if _is_birthday_today(today, b["month"], b["day"])
        ]
        if not todays_birthdays:
            return

        for guild in self.bot.guilds:
            channel = await self._ensure_channel(guild)
            if channel is None:
                continue
            for user_id, _ in todays_birthdays:
                if guild.get_member(int(user_id)) is not None:
                    await channel.send(f"🎉 오늘은 <@{user_id}>님의 생일이에요! 모두 축하해주세요 🎂")

    @birthday_check.before_loop
    async def before_birthday_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthday(bot))