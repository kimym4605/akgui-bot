"""칭호 상점 - 악귀코인으로 나만의 역할(이름+색)을 한 달간 달아요.

서버에 이미 여왕님👑 / 교수님 / 잼민이 같은 재미 역할 문화가 있어서, 그걸 코인으로 살 수
있게 만든 거예요. 30코인 = 한 달 개근이라 "개근했다"는 표시가 눈에 보이는 형태로 남아요.

## 역할 위치 (색이 보이려면 중요해요)

디스코드는 **그 사람이 가진 역할 중 가장 위에 있는 '색 있는 역할'**의 색만 보여줘요.
새로 만든 역할은 맨 아래에 생기니까 그냥 두면 티어 역할 색에 가려서 안 보여요.
그래서 만들자마자 ANCHOR_ROLE_NAME 바로 위로 옮겨요.

⚠️ 여왕님👑/교수님처럼 앵커보다 위에 있는 역할을 이미 가진 사람은 여전히 그 색이 우선이에요.
칭호를 더 위로 올리고 싶으면 ANCHOR_ROLE_NAME을 더 높은 역할 이름으로 바꾸면 돼요.
"""
import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import coin_wallet, title_store
from utils.channel_check import restrict_to_channel
from utils.title_store import TITLE_DAYS, TITLE_PRICE

log = logging.getLogger(__name__)

# 이 역할 바로 위에 칭호를 놓아요. 없으면 위치 조정을 건너뛰어요(역할은 정상 생성돼요).
ANCHOR_ROLE_NAME = "😈 악귀"

MAX_NAME_LENGTH = 20
HEX_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")

# 이런 글자가 들어간 이름은 막아요. 멘션을 흉내 내거나 사칭에 쓰일 수 있어요.
BANNED_SUBSTRINGS = ("@everyone", "@here", "```")
BANNED_KEYWORDS = ("관리자", "매니저", "방장", "운영", "admin", "mod", "봇")


class TitleModal(discord.ui.Modal, title="칭호 만들기"):
    name = discord.ui.TextInput(
        label="칭호 이름",
        placeholder="예: 발로장인",
        max_length=MAX_NAME_LENGTH,
        required=True,
    )
    color = discord.ui.TextInput(
        label="색상 (헥스 코드)",
        placeholder="예: #e91e63  (색상 코드는 구글에 'color picker'로 검색)",
        min_length=6,
        max_length=7,
        required=True,
    )

    def __init__(self, cog: "TitleShop"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.purchase(interaction, str(self.name), str(self.color))


class TitleShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expire_titles.start()

    def cog_unload(self):
        self.expire_titles.cancel()

    # ------------------------------------------------------------------
    # 구매
    # ------------------------------------------------------------------
    def _validate(self, guild: discord.Guild, name: str, color_raw: str) -> tuple[str | None, int]:
        """(오류메시지, 색상값). 오류메시지가 None이면 통과예요."""
        name = name.strip()
        if not name:
            return "칭호 이름을 입력해주세요.", 0
        if len(name) > MAX_NAME_LENGTH:
            return f"칭호 이름은 {MAX_NAME_LENGTH}자까지예요.", 0
        if any(bad in name for bad in BANNED_SUBSTRINGS):
            return "쓸 수 없는 문자가 들어있어요.", 0

        lowered = name.lower()
        if any(word in lowered for word in BANNED_KEYWORDS):
            return "운영진을 사칭할 수 있는 단어는 쓸 수 없어요.", 0

        # 기존 역할과 같은 이름은 막아요(사칭 + 헷갈림 방지).
        if discord.utils.find(lambda r: r.name.lower() == lowered, guild.roles):
            return "이미 서버에 있는 역할과 같은 이름이에요.", 0

        matched = HEX_PATTERN.match(color_raw.strip())
        if not matched:
            return "색상은 `#e91e63` 같은 헥스 코드로 입력해주세요.", 0

        return None, int(matched.group(1), 16)

    async def purchase(self, interaction: discord.Interaction, name: str, color_raw: str):
        await interaction.response.defer(ephemeral=True)

        guild, user = interaction.guild, interaction.user
        if guild is None:
            await interaction.followup.send("서버 안에서만 쓸 수 있어요.", ephemeral=True)
            return

        error, color_value = self._validate(guild, name, color_raw)
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return

        name = name.strip()
        existing = await title_store.get(user.id)

        # ⚠️ 코인부터 빼요. 역할을 먼저 만들면, 코인이 모자랄 때 역할만 덩그러니 남아요.
        if not await coin_wallet.spend(user.id, TITLE_PRICE, reason="칭호구매"):
            balance = await coin_wallet.get_balance(user.id)
            await interaction.followup.send(
                f"악귀코인이 부족해요. 칭호는 **{TITLE_PRICE}개**가 필요한데 지금 **{balance}개** 갖고 있어요.\n"
                f"-# `/출석`과 `/미션`으로 매일 모을 수 있어요.",
                ephemeral=True,
            )
            return

        try:
            role = await self._apply_role(guild, user, existing, name, color_value)
        except discord.Forbidden:
            await coin_wallet.add(user.id, TITLE_PRICE, reason="칭호구매 실패 환불")
            await interaction.followup.send(
                "역할을 만들 권한이 없어요. 코인은 돌려드렸어요. (봇 역할이 충분히 위에 있는지 확인해주세요)",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await coin_wallet.add(user.id, TITLE_PRICE, reason="칭호구매 실패 환불")
            log.exception("칭호 역할 생성 실패 (user=%s)", user.id)
            await interaction.followup.send("역할을 만들지 못했어요. 코인은 돌려드렸어요.", ephemeral=True)
            return

        doc = await title_store.save(user.id, guild.id, role.id, name, color_value)
        remaining = title_store.remaining_days(doc)

        embed = discord.Embed(
            title="🏷️ 칭호를 달았어요!",
            description=(
                f"칭호: {role.mention}\n"
                f"사용한 악귀코인: **{TITLE_PRICE}개** (남은 코인 {await coin_wallet.get_balance(user.id)}개)\n"
                f"남은 기간: **{remaining}일**"
            ),
            color=color_value,
        )
        embed.set_footer(text="기간이 끝나면 자동으로 사라져요. 그 전에 다시 사면 기간이 이어져요.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        log.info("🏷️ 칭호 구매: %s → '%s' (#%06x)", user, name, color_value)

    async def _apply_role(
        self, guild: discord.Guild, user: discord.Member, existing: dict | None, name: str, color: int
    ) -> discord.Role:
        """이미 칭호가 있으면 그 역할의 이름/색을 바꾸고, 없으면 새로 만들어요."""
        role = None
        if existing:
            role = guild.get_role(int(existing["roleId"]))

        if role is not None:
            await role.edit(name=name, colour=discord.Colour(color), reason="칭호 갱신")
        else:
            role = await guild.create_role(
                name=name,
                colour=discord.Colour(color),
                reason=f"칭호 상점 구매 ({user})",
                # 권한은 하나도 안 줘요. 순수하게 이름표 역할이에요.
                permissions=discord.Permissions.none(),
            )
            await self._move_role(guild, role)

        if role not in user.roles:
            await user.add_roles(role, reason="칭호 구매")
        return role

    async def _move_role(self, guild: discord.Guild, role: discord.Role):
        """색이 보이도록 앵커 역할 바로 위로 옮겨요. 실패해도 구매는 유효해요."""
        anchor = discord.utils.get(guild.roles, name=ANCHOR_ROLE_NAME)
        if anchor is None:
            return
        target = anchor.position + 1
        # 봇 자신의 역할보다 위로는 못 올려요(디스코드 제약).
        if guild.me.top_role.position <= target:
            return
        try:
            await role.edit(position=target, reason="칭호 색이 보이도록 위치 조정")
        except discord.HTTPException:
            log.warning("칭호 역할 위치 조정 실패 (role=%s)", role.id, exc_info=True)

    # ------------------------------------------------------------------
    # 명령어
    # ------------------------------------------------------------------
    @app_commands.command(name="칭호구매", description=f"악귀코인 {TITLE_PRICE}개로 나만의 칭호를 {TITLE_DAYS}일간 달아요.")
    @restrict_to_channel("attendance")
    async def buy(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TitleModal(self))

    @app_commands.command(name="칭호", description="지금 달고 있는 칭호와 남은 기간을 확인해요.")
    @restrict_to_channel("attendance")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        doc = await title_store.get(interaction.user.id)
        if doc is None:
            await interaction.followup.send(
                f"아직 칭호가 없어요. `/칭호구매`로 악귀코인 **{TITLE_PRICE}개**를 내면 "
                f"이름과 색을 직접 정해서 **{TITLE_DAYS}일간** 달 수 있어요.",
                ephemeral=True,
            )
            return

        remaining = title_store.remaining_days(doc)
        embed = discord.Embed(
            title="🏷️ 내 칭호",
            description=f"**{doc['name']}**\n남은 기간: **{remaining}일**",
            color=doc.get("color", 0x99AAB5),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="칭호해제", description="달고 있는 칭호를 뗄게요. (코인은 돌려주지 않아요)")
    @restrict_to_channel("attendance")
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        doc = await title_store.get(interaction.user.id)
        if doc is None:
            await interaction.followup.send("달고 있는 칭호가 없어요.", ephemeral=True)
            return

        await self._destroy_role(doc)
        await title_store.delete(interaction.user.id)
        await interaction.followup.send("칭호를 뗐어요. (코인은 돌려드리지 않아요)", ephemeral=True)

    # ------------------------------------------------------------------
    # 만료 처리
    # ------------------------------------------------------------------
    async def _destroy_role(self, doc: dict):
        guild = self.bot.get_guild(int(doc["guildId"]))
        if guild is None:
            return
        role = guild.get_role(int(doc["roleId"]))
        if role is None:
            return  # 누가 이미 지웠어요
        try:
            await role.delete(reason="칭호 기간 만료")
        except discord.HTTPException:
            log.warning("칭호 역할 삭제 실패 (role=%s)", role.id, exc_info=True)

    @tasks.loop(hours=1)
    async def expire_titles(self):
        for doc in await title_store.expired():
            await self._destroy_role(doc)
            await title_store.delete(doc["_id"])
            log.info("🏷️ 칭호 만료: %s ('%s')", doc["_id"], doc.get("name"))

    @expire_titles.before_loop
    async def _before_expire(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(TitleShop(bot))
