import io
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils import profile_card, profile_service
from utils.channel_check import channel_key, restrict_to_channel
from utils import attend_service
from utils.settings_store import set_setting

log = logging.getLogger(__name__)

COIN_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "coin.png"



def _fallback_embed(user: discord.abc.User, data: dict) -> discord.Embed:
    """Pillow가 없거나 카드를 그리다 실패했을 때 대신 띄우는 임베드예요.

    카드가 이 기능의 핵심이라 없으면 아쉽긴 한데, **명령어가 통째로 죽는 것보다는**
    글자로라도 보여주는 게 나아요(배포 직후 폰트/Pillow 문제로 전부 실패하는 상황 대비)."""
    record = data["record"]
    embed = discord.Embed(title=f"{data['name']}님의 악귀 프로필", color=0x5865F2)
    if data.get("title"):
        embed.description = f"「{data['title']}」"
    embed.add_field(name="VALORANT", value=data.get("tier") or "티어 미확인", inline=True)
    embed.add_field(name="악귀코인", value=f"{data['coin']:,}개", inline=True)
    embed.add_field(
        name="내전 전적",
        value=(f"{record['wins']}승 {record['losses']}패 (승률 {record['win_rate']:.0f}%)"
               if record["wins"] + record["losses"] else "아직 기록 없음"),
        inline=True,
    )
    embed.add_field(name="최고 연승", value=f"{record['best_streak']}", inline=True)
    embed.add_field(
        name="이번 주 악귀력",
        value=f"{data['agwi']:,.0f}" if data.get("agwi") else "`/전적`을 돌려주세요",
        inline=True,
    )
    embed.add_field(
        name="업적", value=f"{data['achievements']} / {data['achievements_total']}", inline=True
    )
    return embed


# ============================================================
# 카드 아래 버튼 (🏆 업적 · 🎯 발로란트 전적)
#
# 예전엔 "🐾 포켓몬 상세" 버튼도 있었는데, 2026-09-30에 포켓몬 기능을 접으면서 뺐어요.
# custom_id 정규식에서도 pokemon을 지웠으니, 그 전에 띄워둔 옛 카드의 포켓몬 버튼은
# 눌러도 아무 반응이 없어요(패턴이 안 맞아 되살아나지 않아요). 새로 `/프로필`을 부르면 돼요.
#
# ⚠️ 평범한 View가 아니라 DynamicItem인 이유 — 2026-09-29에 실제로 당했어요.
#
# 처음엔 `discord.ui.View(timeout=300)` 에 버튼을 달았는데, 보통의 View는 **봇이 재시작되면
# 메모리에서 사라져요.** 배포할 때마다 그 전에 띄워둔 카드의 버튼이 전부 죽어서, 눌러도
# 아무 반응이 없고 로그조차 안 남아요(핸들러에 진입을 못 하니까요). 5분 타임아웃도 짧아서
# 조금만 지나면 같은 증상이 났어요.
#
# DynamicItem은 버튼의 custom_id 문자열에 필요한 정보(누구 카드인지)를 다 박아두고, 눌린
# 순간 그걸 정규식으로 다시 꺼내 살아나요. 그래서 봇이 재시작돼도, 며칠 전 카드라도 그대로
# 동작해요. utils/dynamic_room.py의 SpeakGrantButton과 같은 방식이에요.
# ============================================================
class ProfileButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"profile:(?P<kind>achv|rank):(?P<user_id>\d+)",
):
    # kind -> (라벨, 이모지)
    KINDS = {
        "achv": ("업적 보기", "🏆"),
        "rank": ("발로란트 전적", "🎯"),
    }

    def __init__(self, kind: str, user_id: int):
        label, emoji = self.KINDS[kind]
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"profile:{kind}:{user_id}",
            )
        )
        self.kind = kind
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["kind"], int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """카드 주인만 누를 수 있어요.

        버튼이 전부 **카드 주인의** 정보를 여는 거라, 남이 눌렀을 때 누른 사람 것을
        보여주면 "내 카드인데 남의 전적이 뜨는" 식으로 엇갈려요."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "이 카드의 주인만 누를 수 있어요. `/프로필`로 본인 카드를 열어주세요.", ephemeral=True
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        # 버튼이 눌렸다는 흔적을 남겨둬요. 안 되던 시절엔 로그가 없어서 "눌렸는지조차"
        # 알 수 없었고, 그게 원인 찾기를 제일 어렵게 했어요.
        log.info("🎴 프로필 카드 버튼: kind=%s user=%s", self.kind, interaction.user.id)
        await interaction.response.defer(ephemeral=True)

        if self.kind == "achv":
            await self._send_achievements(interaction)
        else:
            await self._send_rank(interaction)

    async def _send_achievements(self, interaction: discord.Interaction):
        # 업적 화면은 achievement cog가 갖고 있어요(거기가 주인이라 서식도 거기 하나뿐이에요).
        from cogs.achievement import build_achievement_embed

        embed = await build_achievement_embed(interaction.user)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _send_rank(self, interaction: discord.Interaction):
        """`/전적`과 **똑같은 리포트**를 카드에서 바로 열어요.

        카드에 티어와 악귀력은 있지만 그건 저장해둔 값이라, KDA·ADR·HS%·선호 요원처럼
        경기를 실제로 뒤져야 나오는 건 없어요. rank cog의 조회를 그대로 불러요
        (서식이 두 벌이 되지 않게 `/전적` 본문을 함수로 갈라서 같이 써요).

        ⚠️ HenrikDev를 실제로 호출해요. 카드를 열 때마다가 아니라 **버튼을 눌렀을 때만**
        나가니까, `/전적`을 한 번 치는 것과 비용이 같아요."""
        rank_cog = interaction.client.get_cog("Rank")
        if rank_cog is None:
            await interaction.followup.send(
                "지금은 전적 기능을 쓸 수 없어요. 잠시 후 `/전적`으로 시도해주세요.", ephemeral=True
            )
            return
        # 본인에게만 보이게 해요. `/전적`은 #전적검색에 묶여 있는데 카드는 아무 채널에서나
        # 열리거든요 — ephemeral이면 그 채널이 전적 리포트로 덮이지 않아요.
        await rank_cog.send_rank_report(interaction, ephemeral=True)


def build_profile_view(user_id: int) -> discord.ui.View:
    """카드에 붙일 버튼 3개짜리 화면. `timeout=None`이라 시간이 지나도 안 죽어요."""
    view = discord.ui.View(timeout=None)
    for kind in ProfileButton.KINDS:
        view.add_item(ProfileButton(kind, user_id))
    return view


async def send_profile_card(interaction: discord.Interaction, target: discord.abc.User):
    """악귀 프로필 카드를 그려서 보내요. `/프로필`과 `/악귀프로필`이 같이 써요.

    ⚠️ 이 함수를 부르기 전에 반드시 `defer()`가 끝나 있어야 해요."""
    data = await profile_service.collect(target)
    avatar = await profile_service.avatar_for(target)
    png = await profile_card.render_card(data, avatar)

    view = build_profile_view(target.id)
    content = None

    # 카드를 보는 것만으로 밀린 업적이 열려요. 열렸으면 같이 알려줘야 코인이 왜 늘었는지 알죠.
    newly = data.get("newly_unlocked") or []
    if newly:
        total_reward = sum(a["reward"] for a in newly)
        names = ", ".join(f"{a['emoji']} **{a['name']}**" for a in newly[:5])
        if len(newly) > 5:
            names += f" 외 {len(newly) - 5}개"
        content = f"🎉 새 업적 {len(newly)}개 달성! {names} (+{total_reward}코인)"

    # 버튼이 영속(DynamicItem)이라 메시지를 붙잡아둘 필요가 없어요. 시간이 지나도, 봇이
    # 재시작돼도 custom_id만으로 되살아나니까 `view.message`를 기억하지 않아요.
    if png is None:
        await interaction.followup.send(
            content=content, embed=_fallback_embed(target, data), view=view
        )
    else:
        file = discord.File(io.BytesIO(png), filename=f"agwi_profile_{target.id}.png")
        await interaction.followup.send(content=content, file=file, view=view)


class Attendance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="출석", description="오늘의 출석체크를 합니다. (하루 1회, 악귀코인 획득)")
    @restrict_to_channel("attend")
    async def do_attend(self, interaction: discord.Interaction):
        # DB를 건드리기 전에 먼저 defer해요. DB 왕복이 3초를 넘기면 디스코드가
        # "애플리케이션이 응답하지 않았습니다"로 끊어버리거든요.
        await interaction.response.defer()

        # 누구나 출석할 수 있어요. 코인이 어디에 쌓이는지(트레이너 문서 / 지갑)는
        # utils/attend_service.py가 알아서 골라줘요.
        success, info = await attend_service.attend(interaction.user.id)

        if not success:
            await interaction.followup.send(
                f"오늘은 이미 출석하셨어요. 보유 악귀코인: **{info['coin']}개** "
                f"· 연속 출석 **{info['streak']}일째** · 내일 또 출석해주세요!",
                ephemeral=True,
            )
            return

        description = (
            f"획득 악귀코인: **+{info['coinGain']}개**\n"
            f"보유 악귀코인: **{info['coin']}개**\n"
            f"🔥 연속 출석: **{info['streak']}일째**"
        )
        embed = discord.Embed(
            title="✅ 출석 완료!",
            description=description,
            color=0x57F287,
        )
        embed.set_thumbnail(url="attachment://coin.png")
        coin_file = discord.File(COIN_IMAGE_PATH, filename="coin.png")
        await interaction.followup.send(embed=embed, file=coin_file)

    @app_commands.command(name="프로필", description="내 악귀 프로필 카드를 봐요. (내전 전적 · 악귀력 · 업적 · 칭호)")
    # ⚠️ 채널 그룹이 "attendance"(=#포켓몬)가 아니라 "profile"이에요.
    #
    # 예전 /프로필은 포켓몬 전용이라 #포켓몬에 묶는 게 맞았어요. 지금은 카드 내용의 대부분이
    # 티어·내전 전적·연승·악귀력·칭호(발로란트/서버 활동)고 포켓몬은 맨 아래 한 줄이에요.
    # 게다가 전적이 **쌓이는** 곳(/팀짜기 승리 버튼)은 아무 채널에서나 되는데 **보는** 곳만
    # 묶여 있으면 앞뒤가 안 맞아요.
    #
    # 2026-09-29에 실제로 재보니 #포켓몬은 50개 글이 쌓이는 데 23일이 걸리고 마지막 글이
    # 9일 전이었어요(#일반❓은 하루에 50개). 그래서 별도 그룹으로 떼어냈어요.
    # 설정값이 없으면 제한이 없으니 **기본은 아무 채널에서나** 되고, 도배가 문제되면
    # `/채널설정 프로필 #채널`로 언제든 묶을 수 있어요(재배포 필요 없어요).
    @restrict_to_channel("profile")
    async def profile(self, interaction: discord.Interaction):
        # 카드 렌더링 + DB 조회가 여럿이라 3초를 넘길 수 있어요.
        await interaction.response.defer()

        # 본인 카드만 봐요. 남의 프로필을 지정해서 꺼내보는 건 일부러 막아뒀어요.
        await send_profile_card(interaction, interaction.user)

    # 노래방만 "명령어를 친 채널"이 아니라 "들어가 있는 음성채널"을 보기 때문에 음성채널을 받아요.
    VOICE_GROUPS = {"karaoke"}

    @app_commands.command(name="채널설정", description="[서버 소유자 전용] 각 명령어를 쓸 수 있는 채널을 지정해요.")
    @app_commands.describe(기능="채널을 지정할 명령어 그룹", 채널="이 그룹의 명령어를 허용할 채널 (노래방만 음성채널)")
    @app_commands.choices(기능=[
        app_commands.Choice(name="출석 명령어 (/출석)", value="attend"),
        app_commands.Choice(name="프로필·업적 (/프로필, /업적, /내전전적, /주간랭킹)", value="profile"),
        app_commands.Choice(name="악귀코인 (/코인, /코인보내기)", value="coin"),
        app_commands.Choice(name="칭호 상점 (/칭호구매, /칭호, /칭호해제)", value="title"),
        app_commands.Choice(name="미션 (/미션)", value="mission"),
        app_commands.Choice(name="즉석생성형 통화방 명령어 (/방만들기 등)", value="room"),
        app_commands.Choice(name="전적 조회 명령어 (/전적)", value="tier_lookup"),
        app_commands.Choice(name="발로란트 개인 상점 (/오상)", value="valorant_shop"),
        app_commands.Choice(name="노래방 음성채널 (/재생 등) — 음성채널을 골라주세요", value="karaoke"),
    ])
    async def set_channel(
        self,
        interaction: discord.Interaction,
        기능: app_commands.Choice[str],
        채널: discord.TextChannel | discord.VoiceChannel,
    ):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return

        # 그룹마다 필요한 채널 종류가 달라서, 잘못 고르면 저장하기 전에 막아줘요.
        wants_voice = 기능.value in self.VOICE_GROUPS
        is_voice = isinstance(채널, discord.VoiceChannel)
        if wants_voice and not is_voice:
            await interaction.response.send_message(
                f"**{기능.name}**는 음성채널을 골라주세요. (지금 고른 {채널.mention}은 텍스트 채널이에요)",
                ephemeral=True,
            )
            return
        if not wants_voice and is_voice:
            await interaction.response.send_message(
                f"**{기능.name}**는 텍스트 채널을 골라주세요. (지금 고른 {채널.mention}은 음성채널이에요)",
                ephemeral=True,
            )
            return

        set_setting(channel_key(기능.value), 채널.id)
        where = "음성채널에 들어가 있어야" if wants_voice else "채널에서만"
        await interaction.response.send_message(
            f"✅ **{기능.name}**는 이제 {채널.mention} {where} 사용할 수 있어요.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Attendance(bot))
    # ⚠️ 이 등록이 없으면 카드 버튼을 눌러도 봇이 custom_id를 알아보지 못해서
    #    아무 반응이 없어요(room.py의 SpeakGrantButton과 같아요).
    bot.add_dynamic_items(ProfileButton)