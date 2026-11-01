"""🎿 정모 참가 신청 — 잠긴 공지 채널에서도 인원을 셀 수 있게 하는 버튼 5개.

## 왜 (2026-11-01)

겨울 정모(2027-01-08~10) 1차 공지를 올린 뒤 **인원을 셀 수단이 없어서** 방장이
`@everyone ... 저에게 DM 남겨주세용`으로 받기 시작했어요. DM은 봇이 못 세요.

⭐ **버튼은 글쓰기 권한이 필요 없어요** — `#📢｜공지사항`이 @everyone에게 잠겨 있어도
봇 메시지의 버튼은 눌려요. 그래서 이미 올라간 **1차 공지 그 메시지에 버튼만 붙였어요**
(새 글을 올리면 알림이 또 가고, 이미 읽은 사람은 돌아오지 않아요).

## 🚨 영속 뷰 — `self`에 정모 이름을 담지 마세요

정모는 두 달 뒤라 그 사이 봇이 수십 번 재시작돼요. 버튼은 `timeout=None` + 고정
`custom_id` + `bot.add_view`로 살려두고, **어느 정모인지는 메시지 id로** 찾아요
(`meetup_store._panels`). 뷰 객체에 담으면 다음 정모가 같은 집계를 공유해요 —
`cogs/team.py`가 이걸 어겨서 "9/22 배포 이후 내전 경기가 한 건도 기록되지 못한"
사고가 났어요.

## 🚨 집계를 공지에 그려 넣지 않아요

누를 때마다 공지를 수정하면 **429 `30046`**(1시간 넘은 메시지 편집 한도)에 걸려서
공지가 깨져요. 누른 사람에게 **비공개로** 현황을 보여주고, 전체는 `/정모현황`이에요.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import adult_check, meetup_store
from utils.interaction_ack import ack
from utils.staff_check import restrict_to_staff

log = logging.getLogger("akgui")

# 명단을 임베드 한 칸에 적을 때의 상한(디스코드 칸 한도가 1024자예요).
NAME_LIMIT = 30


def _counts_line(counts: dict[str, int]) -> str:
    parts = []
    for key, meta in meetup_store.CHOICES.items():
        parts.append(f"{meta['emoji']} {meta['label']} **{counts.get(key, 0)}**")
    return " · ".join(parts)


class MeetupRsvpView(discord.ui.View):
    """참가 신청 버튼 5개. 🚨 상태를 들고 있지 않아요(위 머리말 참고)."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _pick(self, interaction: discord.Interaction, choice: str):
        # 🚨 DB보다 ack()가 먼저예요 — 상호작용 토큰이 3초라서, Atlas가 느린 날엔
        #    먼저 받아두지 않으면 "앱이 응답하지 않았습니다"만 남아요.
        if not await ack(interaction, ephemeral=True, thinking=True):
            return
        message_id = interaction.message.id if interaction.message else 0
        meetup = await meetup_store.meetup_of(message_id)
        try:
            before, now = await meetup_store.set_choice(meetup, interaction.user.id, choice)
        except Exception:
            log.warning("정모 신청 저장 실패 (user=%s, choice=%s)",
                        interaction.user.id, choice, exc_info=True)
            await interaction.followup.send(
                "⚠️ 지금 신청을 저장하지 못했어요. 잠시 뒤에 다시 눌러주세요.", ephemeral=True
            )
            return

        counts = await meetup_store.counts(meetup)
        meta = meetup_store.CHOICES[choice]
        if now is None:
            head = f"{meta['emoji']} **{meta['label']}**를 **취소**했어요."
        elif before is None:
            head = f"{meta['emoji']} **{meta['label']}**로 신청했어요!"
        else:
            old = meetup_store.CHOICES.get(before, {})
            head = (f"{old.get('emoji', '')} {old.get('label', '이전 선택')} → "
                    f"{meta['emoji']} **{meta['label']}**로 바꿨어요.")

        lines = [
            head,
            f"-# {meetup_store.CHOICE_HELP[choice]}",
            "",
            _counts_line(counts),
            f"-# 지금까지 **올 수 있는 사람 {meetup_store.headcount(counts)}명** "
            f"(확실히 온다 {meetup_store.confirmed(counts)}명)",
            "-# 같은 버튼을 한 번 더 누르면 취소돼요. 언제든 바꿀 수 있어요.",
        ]
        warn = meetup_store.date_warning(counts)
        if warn:
            lines.append(warn)
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # 🚨 custom_id는 **고정**이어야 영속 뷰가 재시작 뒤에도 살아나요.
    #    정모 이름을 여기 넣지 않는 이유는 머리말에 있어요.
    @discord.ui.button(label="갈래요", emoji="✅", style=discord.ButtonStyle.success,
                       custom_id="akgui:meetup:going", row=0)
    async def going(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "going")

    @discord.ui.button(label="일정 보고", emoji="🤔", style=discord.ButtonStyle.primary,
                       custom_id="akgui:meetup:maybe", row=0)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "maybe")

    @discord.ui.button(label="안 타지만 놀러는", emoji="🎿",
                       style=discord.ButtonStyle.primary,
                       custom_id="akgui:meetup:resort", row=0)
    async def resort(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "resort")

    @discord.ui.button(label="그날은 안 돼요", emoji="📅",
                       style=discord.ButtonStyle.secondary,
                       custom_id="akgui:meetup:other_date", row=1)
    async def other_date(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "other_date")

    @discord.ui.button(label="못 가요", emoji="❌", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:meetup:no", row=1)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "no")


class MeetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.view: MeetupRsvpView | None = None

    async def cog_load(self):
        # 영속 버튼은 봇이 뜰 때 **한 번 등록**해둬야 재시작 전에 올라간 공지의
        # 버튼도 동작해요. 상태를 안 들고 있으니 인스턴스는 하나로 충분해요.
        self.view = MeetupRsvpView()
        self.bot.add_view(self.view)

    @app_commands.command(
        name="정모현황",
        description="겨울 정모 참가 신청 현황을 봐요. (운영진은 명단까지)",
    )
    async def status(self, interaction: discord.Interaction):
        if not await ack(interaction, ephemeral=True):
            return
        meetup = meetup_store.DEFAULT_MEETUP
        counts = await meetup_store.counts(meetup)
        total = sum(counts.values())

        embed = discord.Embed(
            title="🎿 겨울 정모 참가 현황",
            description=(
                f"**2027년 1월 8일(금) 저녁 ~ 10일(일)** · 1박 2일\n"
                f"응답 **{total}명** · 올 수 있는 사람 "
                f"**{meetup_store.headcount(counts)}명** · 확실히 온다 "
                f"**{meetup_store.confirmed(counts)}명**"
            ),
            color=0x5BC0DE,
        )
        for key, meta in meetup_store.CHOICES.items():
            embed.add_field(
                name=f"{meta['emoji']} {meta['label']}",
                value=f"**{counts.get(key, 0)}명**",
                inline=True,
            )
        warn = meetup_store.date_warning(counts)
        if warn:
            embed.add_field(name="⚠️ 확인할 것", value=warn, inline=False)

        # 운영진에게만 명단을 보여줘요 — 방 배정·카풀·보호자 동의를 챙겨야 해요.
        if interaction.guild is not None and _is_staff(interaction.user):
            roster = await meetup_store.members(meetup)
            for key in ("going", "resort", "maybe", "other_date"):
                ids = roster.get(key) or []
                if not ids:
                    continue
                meta = meetup_store.CHOICES[key]
                embed.add_field(
                    name=f"📋 {meta['emoji']} {meta['label']} 명단 ({len(ids)}명)",
                    value=_roster_text(interaction.guild, ids),
                    inline=False,
                )
            adults, minors, unknown = _age_split(interaction.guild,
                                                 (roster.get("going") or [])
                                                 + (roster.get("resort") or []))
            embed.add_field(
                name="🔞 확실히 온다 중 성인 여부",
                value=(
                    f"성인 **{adults}명** · 성인 역할 없음 **{minors}명**"
                    + (f" · 서버에 없는 사람 {unknown}명" if unknown else "")
                    + "\n-# 숙박이라 방 배정·보호자 동의가 걸려요. "
                    "메모리상 **11월 말까지** 미성년 참가 자격을 정해 2차 공지에 실어야 해요."
                ),
                inline=False,
            )
        else:
            embed.set_footer(text="명단은 운영진만 볼 수 있어요.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="정모패널",
        description="[운영진] 이 채널에 정모 참가 신청 버튼을 올려요.",
    )
    @restrict_to_staff("`/정모패널`")
    async def panel(self, interaction: discord.Interaction):
        if not await ack(interaction, ephemeral=True):
            return
        lines = ["## 🎿 겨울 정모 참가 신청", "",
                 "**2027년 1월 8일(금) 저녁 출발 ~ 10일(일)** · 1박 2일 · 스키 + 리조트", ""]
        for key, meta in meetup_store.CHOICES.items():
            lines.append(f"{meta['emoji']} **{meta['label']}** — {meetup_store.CHOICE_HELP[key]}")
        lines += ["", "-# 언제든 바꿀 수 있어요. 같은 버튼을 한 번 더 누르면 취소돼요.",
                  "-# 장소와 비용은 아직 정하는 중이에요. 지금은 **날짜만 비워두시면** 돼요."]
        message = await interaction.channel.send("\n".join(lines), view=MeetupRsvpView())
        await meetup_store.register_panel(
            message.id, meetup_store.DEFAULT_MEETUP,
            guild_id=interaction.guild_id, channel_id=interaction.channel_id,
        )
        await interaction.followup.send(
            f"✅ 패널을 올렸어요 — {message.jump_url}", ephemeral=True
        )


def _is_staff(user) -> bool:
    from utils import staff_check
    return staff_check.is_staff(user)


def _roster_text(guild: discord.Guild, ids: list[str]) -> str:
    """이름 목록. 🚨 **멘션을 쓰지 않아요** — 명단을 열 때마다 수십 명에게 알림이 가요."""
    names = []
    for uid in ids[:NAME_LIMIT]:
        member = guild.get_member(int(uid)) if uid.isdigit() else None
        names.append(member.display_name if member else f"(서버에 없음 {uid})")
    text = ", ".join(names) if names else "(없음)"
    if len(ids) > NAME_LIMIT:
        text += f" 외 {len(ids) - NAME_LIMIT}명"
    return text[:1024]


def _age_split(guild: discord.Guild, ids: list[str]) -> tuple[int, int, int]:
    """(성인, 성인 역할 없음, 서버에 없음).

    🚨 성인 판정은 `utils/adult_check.py` 하나만 써요 — `ADULT_ROLE_ID`를 여기서 또
    읽으면 네 번째 상수가 돼요(그 파일 머리말의 경고)."""
    adults = minors = unknown = 0
    for uid in ids:
        member = guild.get_member(int(uid)) if uid.isdigit() else None
        if member is None:
            unknown += 1
        elif adult_check.is_adult(member):
            adults += 1
        else:
            minors += 1
    return adults, minors, unknown


async def setup(bot: commands.Bot):
    await bot.add_cog(MeetupCog(bot))
