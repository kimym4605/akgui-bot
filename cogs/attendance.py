import io
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils import profile_card, profile_service
from utils.ability_data import roll_ability
from utils.channel_check import channel_key, restrict_to_channel
from utils.pokemon_data import EVOLUTION, STAT_KEYS, calculate_stats, sprite_url
from utils.pokemon_store import (
    exp_needed,
    get_trainer,
    has_custom_starter,
    has_trainer,
    reset_user,
    save_trainer,
    start_trainer,
)
from utils import attend_service
from utils.settings_store import set_setting

COIN_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "coin.png"

STAT_LABELS = {
    "hp": "HP", "attack": "공격", "defense": "방어",
    "spAttack": "특공", "spDefense": "특방", "speed": "스피드",
}


def _exp_bar(exp: int, needed: int, length: int = 10) -> str:
    if needed <= 0:
        return "🟩" * length
    filled = min(length, int(length * exp / needed))
    return "🟩" * filled + "⬜" * (length - filled)


def _stats_text(stats: dict) -> str:
    return " · ".join(f"{STAT_LABELS[key]} {stats[key]}" for key in STAT_KEYS)


def _display_name(trainer: dict) -> str:
    nickname = trainer.get("nickname")
    return f"{nickname}({trainer['currentPokemon']})" if nickname else trainer["currentPokemon"]


# ------------------------------------------------------------------
# 악귀 프로필 카드
#
# `/프로필`은 원래 포켓몬 전용 임베드였어요. 지금은 **서버 활동 전체**(내전 전적·악귀력·
# 업적·칭호·코인)를 담은 이미지 카드가 기본이고, 포켓몬 상세는 버튼으로 내려갔어요.
# 포켓몬을 시작하지 않은 사람도 카드는 볼 수 있어요 - 출석만 하는 사람도 서버 활동은
# 쌓이고 있으니까요.
# ------------------------------------------------------------------
def _pokemon_embed(user: discord.abc.User, trainer: dict) -> discord.Embed:
    """예전 `/프로필`이 보여주던 포켓몬 상세 임베드 그대로예요."""
    needed = exp_needed(trainer["level"])
    bar = _exp_bar(trainer["exp"], needed)

    embed = discord.Embed(
        title=f"{user.display_name}님의 포켓몬 트레이너 프로필",
        color=0x5865F2,
    )
    embed.add_field(name="포켓몬", value=f"{_display_name(trainer)} (Lv.{trainer['level']})", inline=True)
    embed.add_field(name="성격 / 특성", value=f"{trainer['nature']} / {trainer['ability']}", inline=True)
    embed.add_field(name="골드", value=f"{trainer['gold']} G", inline=True)
    embed.add_field(name="악귀코인", value=f"{trainer.get('coin', 0)}개", inline=True)

    if trainer["level"] >= 100:
        embed.add_field(name="경험치", value="🏆 만렙(Lv.100)이에요!", inline=False)
    else:
        embed.add_field(name="경험치", value=f"{bar}\n{trainer['exp']} / {needed}", inline=False)

    embed.add_field(name="누적 출석", value=f"{trainer['attendance']}회", inline=True)
    embed.add_field(name="도감 등록", value=f"{len(trainer.get('pokedex', []))}종", inline=True)
    if trainer.get("evolutionLocked"):
        embed.add_field(name="🔒 변함없는돌", value="레벨 진화가 잠겨있어요", inline=True)

    items = trainer.get("items", {})
    item_text = ", ".join(f"{k} x{v}" for k, v in items.items() if v > 0) or "없음"
    embed.add_field(name="보유 아이템", value=item_text, inline=False)
    embed.add_field(name="기술", value=", ".join(trainer.get("moves", [])) or "없음", inline=False)
    embed.add_field(name="능력치", value=_stats_text(trainer["stats"]), inline=False)
    embed.set_image(url=sprite_url(trainer["currentPokemon"]))
    embed.set_footer(text=f"기본형: {trainer['basePokemon']}")
    return embed


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
    if data.get("pokemon"):
        embed.add_field(name="파트너", value=data["pokemon"], inline=False)
    return embed


class ProfileView(discord.ui.View):
    """카드 아래에 붙는 버튼이에요. 누가 눌러도 되고, 결과는 누른 사람에게만 보여요
    (남의 프로필을 열어봐도 채널이 지저분해지지 않게)."""

    def __init__(self, target: discord.abc.User):
        super().__init__(timeout=300)
        self._target = target
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="포켓몬 상세", emoji="🐾", style=discord.ButtonStyle.secondary)
    async def pokemon_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        trainer = await get_trainer(self._target.id)

        if trainer is None or not has_custom_starter(trainer):
            who = "이 사람은" if self._target.id != interaction.user.id else "아직"
            await interaction.followup.send(
                f"{who} 스타팅 포켓몬을 고르지 않았어요.\n"
                "악귀포켓몬 웹사이트에서 **까멍이 · 오로리 · 타누비** 중 하나를 고르면 시작할 수 있어요.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=_pokemon_embed(self._target, trainer), ephemeral=True)

    @discord.ui.button(label="업적 보기", emoji="🏆", style=discord.ButtonStyle.secondary)
    async def achievements(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        # 업적 화면은 achievement cog가 갖고 있어요(거기가 주인이라 서식도 거기 하나뿐이에요).
        from cogs.achievement import build_achievement_embed

        embed = await build_achievement_embed(self._target)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def send_profile_card(interaction: discord.Interaction, target: discord.abc.User):
    """악귀 프로필 카드를 그려서 보내요. `/프로필`과 `/악귀프로필`이 같이 써요.

    ⚠️ 이 함수를 부르기 전에 반드시 `defer()`가 끝나 있어야 해요."""
    data = await profile_service.collect(target)
    avatar = await profile_service.avatar_for(target)
    png = await profile_card.render_card(data, avatar)

    view = ProfileView(target)
    content = None

    # 카드를 보는 것만으로 밀린 업적이 열려요. 열렸으면 같이 알려줘야 코인이 왜 늘었는지 알죠.
    newly = data.get("newly_unlocked") or []
    if newly and target.id == interaction.user.id:
        total_reward = sum(a["reward"] for a in newly)
        names = ", ".join(f"{a['emoji']} **{a['name']}**" for a in newly[:5])
        if len(newly) > 5:
            names += f" 외 {len(newly) - 5}개"
        content = f"🎉 새 업적 {len(newly)}개 달성! {names} (+{total_reward}코인)"

    if png is None:
        message = await interaction.followup.send(
            content=content, embed=_fallback_embed(target, data), view=view, wait=True
        )
    else:
        file = discord.File(io.BytesIO(png), filename=f"agwi_profile_{target.id}.png")
        message = await interaction.followup.send(
            content=content, file=file, view=view, wait=True
        )
    view.message = message


class Attendance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="출석", description="오늘의 출석체크를 합니다. (하루 1회, 악귀코인 획득)")
    @restrict_to_channel("attend")
    async def do_attend(self, interaction: discord.Interaction):
        # DB를 건드리기 전에 먼저 defer해요. DB 왕복이 3초를 넘기면 디스코드가
        # "애플리케이션이 응답하지 않았습니다"로 끊어버리거든요.
        await interaction.response.defer()

        # 포켓몬을 시작하지 않았어도 출석할 수 있어요. 코인은 지갑에 쌓였다가, 나중에 웹에서
        # 스타팅을 고르면 연속 출석 기록까지 그대로 따라가요. (utils/attend_service.py)
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
        if not info["isTrainer"]:
            description += (
                "\n\n-# 아직 포켓몬을 시작하지 않았어요. 모아둔 코인과 연속 출석은 그대로 보관되고, "
                "악귀포켓몬 웹사이트에서 스타팅을 고르면 **그대로 이어져요.**"
            )

        embed = discord.Embed(
            title="✅ 출석 완료!",
            description=description,
            color=0x57F287,
        )
        embed.set_thumbnail(url="attachment://coin.png")
        coin_file = discord.File(COIN_IMAGE_PATH, filename="coin.png")
        await interaction.followup.send(embed=embed, file=coin_file)

    @app_commands.command(name="프로필", description="악귀 프로필 카드를 봐요. (내전 전적 · 악귀력 · 업적 · 포켓몬)")
    @app_commands.describe(유저="다른 사람의 프로필을 보려면 지정하세요. 비우면 내 프로필이에요.")
    @restrict_to_channel("attendance")
    async def profile(self, interaction: discord.Interaction, 유저: discord.Member | None = None):
        # 카드 렌더링 + DB 조회가 여럿이라 3초를 넘길 수 있어요.
        await interaction.response.defer()

        target = 유저 or interaction.user
        await send_profile_card(interaction, target)

    @app_commands.command(name="출석리셋", description="[서버 소유자 전용/테스트용] 내 트레이너 데이터를 전부 초기화해요.")
    @restrict_to_channel("attendance")
    async def reset(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        had_data = await reset_user(interaction.user.id)

        if not had_data:
            await interaction.followup.send("초기화할 데이터가 없어요.", ephemeral=True)
            return

        await interaction.followup.send(
            "🧹 트레이너 데이터를 초기화했어요. `/시작`으로 새로 시작해보세요!",
            ephemeral=True,
        )

    @app_commands.command(name="포켓몬설정", description="[서버 소유자 전용/테스트용] 포켓몬 종류와 레벨을 직접 지정해요.")
    @app_commands.describe(포켓몬="설정할 포켓몬 이름 (진화 계보 아무 단계나 가능)", 레벨="1~100 사이 레벨")
    @restrict_to_channel("attendance")
    async def set_pokemon(self, interaction: discord.Interaction, 포켓몬: str, 레벨: app_commands.Range[int, 1, 100]):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return

        target_base = None
        target_stage = None
        for base_name, data in EVOLUTION.items():
            family = data["family"]
            if 포켓몬 in family:
                target_base = base_name
                target_stage = family.index(포켓몬)
                break

        if target_base is None:
            await interaction.response.send_message(
                f"'{포켓몬}'을(를) 찾을 수 없어요. 정확한 포켓몬 이름을 입력해주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        trainer = await get_trainer(interaction.user.id)
        if trainer is None:
            trainer = await start_trainer(interaction.user.id)

        trainer["basePokemon"] = target_base
        trainer["currentPokemon"] = 포켓몬
        trainer["evolutionStage"] = target_stage
        trainer["level"] = 레벨
        trainer["exp"] = 0
        trainer["ability"] = roll_ability(포켓몬)
        trainer["stats"] = calculate_stats(포켓몬, 레벨, trainer["iv"], trainer["nature"])

        await save_trainer(interaction.user.id, trainer)

        embed = discord.Embed(
            title="🛠️ 테스트용 포켓몬 설정 완료",
            description=f"**{포켓몬}** (Lv.{레벨})로 강제 설정했어요.",
            color=0xE67E22,
        )
        embed.set_image(url=sprite_url(포켓몬))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @set_pokemon.autocomplete("포켓몬")
    async def set_pokemon_autocomplete(self, interaction: discord.Interaction, current: str):
        all_names = sorted({name for data in EVOLUTION.values() for name in data["family"] if not name.startswith("__")})

        if not current:
            matches = all_names[:25]
        else:
            starts_with = [n for n in all_names if n.startswith(current)]
            contains = [n for n in all_names if current in n and n not in starts_with]
            matches = (starts_with + contains)[:25]

        return [app_commands.Choice(name=n, value=n) for n in matches]

    # 노래방만 "명령어를 친 채널"이 아니라 "들어가 있는 음성채널"을 보기 때문에 음성채널을 받아요.
    VOICE_GROUPS = {"karaoke"}

    @app_commands.command(name="채널설정", description="[서버 소유자 전용] 각 명령어를 쓸 수 있는 채널을 지정해요.")
    @app_commands.describe(기능="채널을 지정할 명령어 그룹", 채널="이 그룹의 명령어를 허용할 채널 (노래방만 음성채널)")
    @app_commands.choices(기능=[
        app_commands.Choice(name="출석 명령어 (/출석)", value="attend"),
        app_commands.Choice(name="육성 명령어 (/시작, /프로필 등)", value="attendance"),
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