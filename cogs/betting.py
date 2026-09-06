"""내전 베팅 - 경기에 악귀코인을 걸고, 이긴 팀에 건 사람들이 나눠 가져요.

## 흐름

1. `/베팅개설 @팀장1 @팀장2` - 채널에 베팅을 열어요
2. `/베팅 1팀|2팀 <코인>` - 코인을 걸어요 (거는 순간 코인이 빠져서 봇이 맡아둬요)
3. `/베팅마감` - 경기 시작. 더 이상 못 걸어요
4. `/베팅결과 1팀|2팀` - **양 팀장이 각각** 입력하고, 둘이 같으면 정산돼요
   - 엇갈리면 정산을 멈추고 매니저를 불러요
5. `/베팅취소` - 경기가 무산되면 전액 환불

## 왜 버튼이 아니라 명령어인가

버튼(View)은 봇이 재시작되면 죽어요. 베팅은 코인을 맡아두는 구조라 재시작 한 번에 판돈이
묶이면 안 돼서, 상태를 전부 DB에 두고 명령어로만 다뤄요.

## 승부조작에 대해

참가자도 아무 팀에나 걸 수 있게 열어뒀어요(운영 결정). 대신 **누가 어느 팀에 걸었는지**를
`/베팅현황`에서 전부 공개해요. 막지는 못해도 눈에 띄게는 만들어둬요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import bet_store, coin_wallet
from utils.bet_store import (
    MAX_WAGER,
    MIN_WAGER,
    STATUS_CANCELLED,
    STATUS_LOCKED,
    STATUS_OPEN,
    STATUS_SETTLED,
)

log = logging.getLogger(__name__)

TEAM_CHOICES = [
    app_commands.Choice(name="1팀 (🔴)", value=1),
    app_commands.Choice(name="2팀 (🔵)", value=2),
]

TEAM_EMOJI = {1: "🔴", 2: "🔵"}


def _team_name(doc: dict, team: int) -> str:
    return doc["teamNames"][team - 1]


def _build_status_embed(doc: dict, guild: discord.Guild | None) -> discord.Embed:
    t1, t2 = bet_store.totals(doc)
    status_label = {
        STATUS_OPEN: "🟢 베팅 받는 중",
        STATUS_LOCKED: "🔒 마감 (경기 중)",
        STATUS_SETTLED: "✅ 정산 완료",
        STATUS_CANCELLED: "❌ 취소됨",
    }.get(doc["status"], doc["status"])

    embed = discord.Embed(
        title="🎲 내전 베팅",
        description=f"{status_label}\n총 판돈 **{t1 + t2}코인**",
        color=0xE67E22,
    )

    for team in (1, 2):
        total = t1 if team == 1 else t2
        bettors = [w for w in doc.get("wagers", []) if w["team"] == team]
        # 누가 걸었는지 전부 공개해요. 참가자가 상대 팀에 걸면 여기서 드러나요.
        lines = [f"<@{w['userId']}> {w['amount']}" for w in bettors] or ["(아직 없음)"]
        embed.add_field(
            name=f"{TEAM_EMOJI[team]} {_team_name(doc, team)} — {total}코인",
            value="\n".join(lines)[:1024],
            inline=True,
        )

    if t1 > 0 and t2 > 0:
        # 지금 정산되면 1코인당 얼마를 받는지 (원금 포함)
        embed.add_field(
            name="예상 배당 (1코인당, 원금 포함)",
            value=f"{TEAM_EMOJI[1]} {1 + t2 / t1:.2f}배 · {TEAM_EMOJI[2]} {1 + t1 / t2:.2f}배",
            inline=False,
        )
    elif doc["status"] == STATUS_OPEN:
        embed.set_footer(text="한쪽에만 걸리면 배당 없이 원금만 돌려받아요.")

    captains = " vs ".join(f"<@{cid}>" for cid in doc["captains"])
    embed.add_field(name="팀장", value=captains, inline=False)
    return embed


class Betting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    @app_commands.command(name="베팅개설", description="이 채널에 내전 베팅을 열어요.")
    @app_commands.describe(
        팀장1="1팀 팀장", 팀장2="2팀 팀장",
        팀1이름="비워두면 팀장 이름을 써요", 팀2이름="비워두면 팀장 이름을 써요",
    )
    async def open_bet(
        self, interaction: discord.Interaction,
        팀장1: discord.Member, 팀장2: discord.Member,
        팀1이름: str | None = None, 팀2이름: str | None = None,
    ):
        await interaction.response.defer()

        if 팀장1.id == 팀장2.id:
            await interaction.followup.send("팀장 두 명은 서로 달라야 해요.", ephemeral=True)
            return

        doc = await bet_store.create(
            interaction.guild_id, interaction.channel_id, interaction.user.id,
            팀장1.id, 팀장2.id,
            (팀1이름 or f"{팀장1.display_name} 팀")[:40],
            (팀2이름 or f"{팀장2.display_name} 팀")[:40],
        )
        if doc is None:
            await interaction.followup.send(
                "이 채널에 이미 진행 중인 베팅이 있어요. `/베팅현황`으로 확인해주세요.", ephemeral=True
            )
            return

        embed = _build_status_embed(doc, interaction.guild)
        embed.set_footer(text=f"`/베팅`으로 코인을 걸어요 (한 사람당 최대 {MAX_WAGER}개)")
        await interaction.followup.send(embed=embed)
        log.info("🎲 베팅 개설: channel=%s by %s", interaction.channel_id, interaction.user)

    # ------------------------------------------------------------------
    @app_commands.command(name="베팅", description="진행 중인 내전 베팅에 악귀코인을 걸어요.")
    @app_commands.describe(팀="이길 것 같은 팀", 개수="걸 악귀코인 개수")
    @app_commands.choices(팀=TEAM_CHOICES)
    async def place(self, interaction: discord.Interaction, 팀: app_commands.Choice[int], 개수: int):
        await interaction.response.defer()

        team, amount = 팀.value, 개수
        doc = await bet_store.active(interaction.channel_id)
        if doc is None:
            await interaction.followup.send("이 채널에 진행 중인 베팅이 없어요.", ephemeral=True)
            return
        if doc["status"] != STATUS_OPEN:
            await interaction.followup.send("이미 마감된 베팅이에요.", ephemeral=True)
            return

        if not (MIN_WAGER <= amount <= MAX_WAGER):
            await interaction.followup.send(
                f"{MIN_WAGER}~{MAX_WAGER}개 사이로 걸어주세요.", ephemeral=True
            )
            return

        # 이미 건 팀과 다른 팀에는 못 걸어요(양쪽에 걸면 무조건 이득이라 베팅이 아니게 돼요).
        my_team, my_total = bet_store.user_wager(doc, interaction.user.id)
        if my_team is not None and my_team != team:
            await interaction.followup.send(
                f"이미 **{_team_name(doc, my_team)}**에 {my_total}개를 걸었어요. 양쪽에는 못 걸어요.",
                ephemeral=True,
            )
            return
        if my_total + amount > MAX_WAGER:
            await interaction.followup.send(
                f"한 경기에 최대 {MAX_WAGER}개까지예요. (지금까지 {my_total}개)", ephemeral=True
            )
            return

        # ⚠️ 코인부터 빼요(에스크로). 기록을 먼저 남기면 잔액이 모자란 베팅이 들어가요.
        if not await coin_wallet.spend(interaction.user.id, amount, reason="내전베팅"):
            balance = await coin_wallet.get_balance(interaction.user.id)
            await interaction.followup.send(
                f"악귀코인이 부족해요. 지금 **{balance}개** 갖고 있어요.", ephemeral=True
            )
            return

        if not await bet_store.add_wager(doc["_id"], interaction.user.id, team, amount):
            # 그 찰나에 마감됐어요. 코인을 돌려줘요.
            await coin_wallet.add(interaction.user.id, amount, reason="베팅 마감으로 환불")
            await interaction.followup.send(
                "방금 베팅이 마감돼서 취소했어요. 코인은 돌려드렸어요.", ephemeral=True
            )
            return

        doc = await bet_store.get(doc["_id"])
        await interaction.followup.send(
            content=f"{interaction.user.mention}님이 **{_team_name(doc, team)}**에 **{amount}코인**을 걸었어요!",
            embed=_build_status_embed(doc, interaction.guild),
        )

    # ------------------------------------------------------------------
    @app_commands.command(name="베팅현황", description="이 채널의 베팅 현황을 봐요.")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        doc = await bet_store.active(interaction.channel_id)
        if doc is None:
            await interaction.followup.send("이 채널에 진행 중인 베팅이 없어요.", ephemeral=True)
            return
        await interaction.followup.send(embed=_build_status_embed(doc, interaction.guild))

    # ------------------------------------------------------------------
    def _can_manage(self, doc: dict, user_id: int) -> bool:
        return str(user_id) == doc["createdBy"] or str(user_id) in doc["captains"]

    @app_commands.command(name="베팅마감", description="베팅을 마감해요. (개설자 또는 팀장)")
    async def lock(self, interaction: discord.Interaction):
        await interaction.response.defer()

        doc = await bet_store.active(interaction.channel_id)
        if doc is None:
            await interaction.followup.send("이 채널에 진행 중인 베팅이 없어요.", ephemeral=True)
            return
        if not self._can_manage(doc, interaction.user.id):
            await interaction.followup.send("개설자나 팀장만 마감할 수 있어요.", ephemeral=True)
            return
        if not await bet_store.set_status(doc["_id"], STATUS_LOCKED, STATUS_OPEN):
            await interaction.followup.send("이미 마감된 베팅이에요.", ephemeral=True)
            return

        doc = await bet_store.get(doc["_id"])
        await interaction.followup.send(
            content="🔒 베팅을 마감했어요! 경기 끝나면 **양 팀장이 각각** `/베팅결과`를 입력해주세요.",
            embed=_build_status_embed(doc, interaction.guild),
        )

    # ------------------------------------------------------------------
    @app_commands.command(name="베팅결과", description="이긴 팀을 보고해요. (양 팀장이 각각 입력)")
    @app_commands.choices(승리팀=TEAM_CHOICES)
    async def result(self, interaction: discord.Interaction, 승리팀: app_commands.Choice[int]):
        await interaction.response.defer()

        winner = 승리팀.value
        doc = await bet_store.active(interaction.channel_id)
        if doc is None:
            await interaction.followup.send("이 채널에 진행 중인 베팅이 없어요.", ephemeral=True)
            return
        if doc["status"] != STATUS_LOCKED:
            await interaction.followup.send(
                "먼저 `/베팅마감`으로 베팅을 마감해주세요.", ephemeral=True
            )
            return
        if str(interaction.user.id) not in doc["captains"]:
            await interaction.followup.send("팀장만 결과를 보고할 수 있어요.", ephemeral=True)
            return

        doc = await bet_store.report(doc["_id"], interaction.user.id, winner)
        reports = doc.get("reports", {})

        if len(reports) < 2:
            other = next(c for c in doc["captains"] if c not in reports)
            await interaction.followup.send(
                f"**{_team_name(doc, winner)} 승리**로 접수했어요. "
                f"<@{other}> 팀장도 `/베팅결과`를 입력하면 정산돼요."
            )
            return

        values = list(reports.values())
        if values[0] != values[1]:
            await interaction.followup.send(
                "⚠️ 두 팀장의 보고가 **엇갈렸어요.** 정산을 멈췄어요.\n"
                "다시 `/베팅결과`를 입력하거나, 매니저를 불러서 확인해주세요."
            )
            return

        await self._settle(interaction, doc, values[0])

    async def _settle(self, interaction: discord.Interaction, doc: dict, winner: int):
        # ⚠️ 상태를 먼저 settled로 바꿔요. 두 팀장이 동시에 입력하면 정산이 두 번 돌 수 있어요.
        if not await bet_store.set_status(doc["_id"], STATUS_SETTLED, STATUS_LOCKED):
            await interaction.followup.send("이미 정산된 베팅이에요.", ephemeral=True)
            return

        payouts, refunded = bet_store.compute_payouts(doc, winner)
        for user_id, amount in payouts.items():
            await coin_wallet.add(user_id, amount, reason=f"베팅정산:{'환불' if refunded else '승리'}")

        t1, t2 = bet_store.totals(doc)
        if refunded:
            description = (
                f"**{_team_name(doc, winner)}** 승리!\n\n"
                "이긴 팀에 아무도 걸지 않아서 **전원 환불**했어요."
            )
        else:
            lines = [
                f"<@{uid}> **+{amount}코인**"
                for uid, amount in sorted(payouts.items(), key=lambda x: -x[1])
            ]
            description = (
                f"🏆 **{_team_name(doc, winner)}** 승리!\n"
                f"총 판돈 {t1 + t2}코인\n\n" + ("\n".join(lines) if lines else "받아갈 사람이 없어요.")
            )

        embed = discord.Embed(title="🎲 베팅 정산 완료", description=description[:4000], color=0x2ECC71)
        await interaction.followup.send(embed=embed)
        log.info("🎲 베팅 정산: channel=%s winner=%s payouts=%s", doc["channelId"], winner, payouts)

    # ------------------------------------------------------------------
    @app_commands.command(name="베팅취소", description="베팅을 취소하고 건 코인을 전부 돌려줘요.")
    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.defer()

        doc = await bet_store.active(interaction.channel_id)
        if doc is None:
            await interaction.followup.send("이 채널에 진행 중인 베팅이 없어요.", ephemeral=True)
            return
        if not self._can_manage(doc, interaction.user.id):
            await interaction.followup.send("개설자나 팀장만 취소할 수 있어요.", ephemeral=True)
            return

        current = doc["status"]
        if not await bet_store.set_status(doc["_id"], STATUS_CANCELLED, current):
            await interaction.followup.send("이미 처리된 베팅이에요.", ephemeral=True)
            return

        refunds: dict[str, int] = {}
        for wager in doc.get("wagers", []):
            refunds[wager["userId"]] = refunds.get(wager["userId"], 0) + wager["amount"]
        for user_id, amount in refunds.items():
            await coin_wallet.add(user_id, amount, reason="베팅취소 환불")

        total = sum(refunds.values())
        await interaction.followup.send(
            f"❌ 베팅을 취소하고 **{total}코인**을 {len(refunds)}명에게 돌려줬어요."
        )
        log.info("🎲 베팅 취소: channel=%s 환불 %d코인", doc["channelId"], total)


async def setup(bot: commands.Bot):
    await bot.add_cog(Betting(bot))
