"""악귀코인 잔액 확인과 유저 간 송금이에요.

코인이 어디에 담기는지(트레이너 문서 / 지갑)는 utils/coin_wallet.py가 알아서 처리해요.
그래서 여기서는 "누가 누구에게 몇 개"만 신경 쓰면 돼요.
"""
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils import coin_wallet
from utils.channel_check import restrict_to_channel

log = logging.getLogger(__name__)

COIN_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "coin.png"

# 한 번에 보낼 수 있는 최대치. 실수로 0을 하나 더 붙이는 사고를 막아줘요.
MAX_TRANSFER = 1000


def _log_line(entry: dict, uid: str) -> str:
    """coin_log 한 줄 → `+5 미션완주 · 11/15 01:04`.

    ⚠️ 송금(`transfer`)은 from·to가 둘 다 있어서, 내가 어느 쪽인지로 부호를 정해요."""
    from utils.coin_ledger import kst_of

    amount = int(entry.get("amount") or 0)
    kind = entry.get("kind")
    if kind == "add":
        sign = "+"
    elif kind == "transfer":
        sign = "+" if entry.get("to") == uid else "−"
    else:
        sign = "−"
    note = entry.get("note") or ("송금" if kind == "transfer" else "기타")
    when = kst_of(entry["_id"]).strftime("%m/%d %H:%M")
    return f"`{sign}{amount}` {note} — {when}"


async def build_coin_embed(user: discord.abc.User) -> discord.Embed:
    """잔액 + 최근 입출금 10건. `/프로필`의 📋 자세히 보기 → 🪙 코인이 써요.

    ⭐ "코인이 왜 늘었/줄었지?"에 답하는 화면이에요. 지금까진 coin_log를 DB에서 직접
    봐야만 알 수 있었어요. **본인에게만** 보여요(남의 지출 내역은 사생활이에요)."""
    uid = str(user.id)
    balance = await coin_wallet.get_balance(user.id)
    rows = await coin_wallet.recent_log(user.id, limit=10)

    embed = discord.Embed(
        title=f"🪙 {user.display_name}님의 악귀코인",
        description=f"보유 **{balance}코인**",
        color=0xF1C40F,
    )
    if rows:
        embed.add_field(
            name="최근 입출금 (위가 최신)",
            value="\n".join(_log_line(r, uid) for r in rows),
            inline=False,
        )
        gained = sum(int(r.get("amount") or 0) for r in rows
                     if r.get("kind") == "add" or (r.get("kind") == "transfer" and r.get("to") == uid))
        spent = sum(int(r.get("amount") or 0) for r in rows) - gained
        embed.set_footer(text=f"이 10건 합계: 받은 {gained} · 쓴 {spent}")
    else:
        embed.add_field(name="최근 입출금", value="아직 기록이 없어요.", inline=False)
    return embed


class Coin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="코인", description="내 악귀코인 잔액을 확인해요.")
    # ⚠️ 그룹이 "attendance"(=#포켓몬)에서 "coin"으로 바뀌었어요.
    #
    # 악귀코인을 칭호 같은 **소비처로 밀기로 해서**, 잔액을 확인하는 길이 막혀 있으면 안 돼요.
    # #포켓몬은 2026-09-29 기준 마지막 글이 9일 전인 죽은 채널이라, 거기 묶여 있으면
    # "코인을 쓰라"면서 정작 얼마 있는지 보려면 아무도 안 가는 곳에 가야 하는 꼴이었어요.
    # /칭호구매를 같은 이유로 떼어냈으니 /코인도 같이 나와야 앞뒤가 맞아요.
    # 설정값이 없으면 제한이 없으니 기본은 아무 채널에서나 돼요.
    @restrict_to_channel("coin")
    async def balance(self, interaction: discord.Interaction):
        # DB 왕복이 3초를 넘기면 디스코드가 끊어버려서 먼저 defer해요.
        await interaction.response.defer(ephemeral=True)

        amount = await coin_wallet.get_balance(interaction.user.id)
        description = f"보유 악귀코인: **{amount}개**"

        embed = discord.Embed(title="🪙 악귀코인", description=description, color=0xF1C40F)
        embed.set_thumbnail(url="attachment://coin.png")
        await interaction.followup.send(
            embed=embed, file=discord.File(COIN_IMAGE_PATH, filename="coin.png"), ephemeral=True
        )

    @app_commands.command(name="코인보내기", description="다른 사람에게 악귀코인을 보내요.")
    @app_commands.describe(상대="코인을 받을 사람", 개수="보낼 악귀코인 개수")
    @restrict_to_channel("coin")
    async def send(self, interaction: discord.Interaction, 상대: discord.Member, 개수: int):
        await interaction.response.defer()

        sender, receiver, amount = interaction.user, 상대, 개수

        if receiver.bot:
            await interaction.followup.send("봇에게는 코인을 보낼 수 없어요.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.followup.send("1개 이상만 보낼 수 있어요.", ephemeral=True)
            return
        if amount > MAX_TRANSFER:
            await interaction.followup.send(
                f"한 번에 보낼 수 있는 건 {MAX_TRANSFER}개까지예요.", ephemeral=True
            )
            return

        ok, reason = await coin_wallet.transfer(sender.id, receiver.id, amount)

        if not ok:
            messages = {
                "self": "자기 자신에게는 보낼 수 없어요.",
                "amount": "1개 이상만 보낼 수 있어요.",
                "balance": (
                    f"코인이 부족해요. 지금 **{await coin_wallet.get_balance(sender.id)}개** 갖고 있어요."
                ),
            }
            await interaction.followup.send(messages.get(reason, "송금에 실패했어요."), ephemeral=True)
            return

        log.info("🪙 %s → %s 코인 %d개 송금", sender, receiver, amount)

        embed = discord.Embed(
            title="🪙 코인을 보냈어요!",
            description=(
                f"{sender.mention} → {receiver.mention}\n"
                f"보낸 악귀코인: **{amount}개**\n"
                f"내 잔액: **{await coin_wallet.get_balance(sender.id)}개**"
            ),
            color=0xF1C40F,
        )
        embed.set_thumbnail(url="attachment://coin.png")
        await interaction.followup.send(
            embed=embed, file=discord.File(COIN_IMAGE_PATH, filename="coin.png")
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Coin(bot))
