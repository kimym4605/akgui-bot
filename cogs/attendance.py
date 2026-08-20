import discord
from discord import app_commands
from discord.ext import commands

from utils.ability_data import roll_ability
from utils.channel_check import channel_key, restrict_to_channel
from utils.pokemon_data import EVOLUTION, STAT_KEYS, calculate_stats, sprite_url
from utils.pokemon_store import (
    attend,
    exp_needed,
    get_trainer,
    has_trainer,
    reset_user,
    save_trainer,
    start_trainer,
)
from utils.settings_store import set_setting
from utils.skill_data import MOVES, get_learnset
from utils.skill_store import get_current_skills

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


class Attendance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="시작", description="포켓몬 육성을 시작해요. 기본 형태 포켓몬 1마리를 받아요.")
    @restrict_to_channel("attendance")
    async def begin(self, interaction: discord.Interaction):
        if has_trainer(interaction.user.id):
            trainer = get_trainer(interaction.user.id)
            await interaction.response.send_message(
                f"이미 {_display_name(trainer)}(Lv.{trainer['level']})과 함께하고 있어요!",
                ephemeral=True,
            )
            return

        trainer = start_trainer(interaction.user.id)

        embed = discord.Embed(
            title="🎉 포켓몬 육성을 시작했어요!",
            description=(
                f"**{trainer['currentPokemon']}**을(를) 만났어요!\n"
                f"성격: {trainer['nature']} · 특성: {trainer['ability']}\n"
                f"시작 기술: {', '.join(trainer['moves']) or '없음'}"
            ),
            color=0x57F287,
        )
        embed.set_image(url=sprite_url(trainer["currentPokemon"]))
        embed.add_field(name="능력치", value=_stats_text(trainer["stats"]), inline=False)
        embed.set_footer(text="웹사이트(배틀/탐험)에서 레벨업하고 키워보세요! (만렙 Lv.100 도달 시 도감에 자동 등록돼요)")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="출석", description="오늘의 출석체크를 합니다. (하루 1회, 악귀코인 획득)")
    @restrict_to_channel("attend")
    async def do_attend(self, interaction: discord.Interaction):
        await interaction.response.defer()

        success, result = attend(interaction.user.id)

        if not success:
            trainer = result
            await interaction.followup.send(
                f"오늘은 이미 출석하셨어요. {_display_name(trainer)}(Lv.{trainer['level']})은(는) 내일 또 출석해주세요!",
                ephemeral=True,
            )
            return

        trainer = result["trainer"]

        embed = discord.Embed(
            title="✅ 출석 완료!",
            description=f"획득 악귀코인: **+{result['coin_gain']}개**\n보유 악귀코인: **{trainer['coin']}개**",
            color=0x57F287,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="프로필", description="내 포켓몬 트레이너 프로필을 봐요.")
    @restrict_to_channel("attendance")
    async def profile(self, interaction: discord.Interaction):
        trainer = get_trainer(interaction.user.id)
        if trainer is None:
            await interaction.response.send_message(
                "아직 시작하지 않았어요! `/시작`으로 첫 포켓몬을 받아보세요.",
                ephemeral=True,
            )
            return

        needed = exp_needed(trainer["level"])
        bar = _exp_bar(trainer["exp"], needed)

        embed = discord.Embed(
            title=f"{interaction.user.display_name}님의 포켓몬 트레이너 프로필",
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

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="기술", description="현재 포켓몬의 보유 기술을 확인해요.")
    @restrict_to_channel("attendance")
    async def skills(self, interaction: discord.Interaction):
        trainer = get_trainer(interaction.user.id)
        if trainer is None:
            await interaction.response.send_message(
                "아직 시작하지 않았어요! `/시작`으로 첫 포켓몬을 받아보세요.",
                ephemeral=True,
            )
            return

        moves = get_current_skills(interaction.user.id)
        embed = discord.Embed(
            title=f"{_display_name(trainer)} Lv.{trainer['level']}",
            description="기술 목록",
            color=0x5865F2,
        )
        if not moves:
            embed.add_field(name="\u200b", value="아직 배운 기술이 없어요.", inline=False)
        else:
            for i, move_name in enumerate(moves, start=1):
                info = MOVES.get(move_name, {})
                embed.add_field(
                    name=f"{i}. {move_name}",
                    value=(
                        f"타입: {info.get('type', '?')} · 위력: {info.get('power', '?')} · "
                        f"명중: {info.get('accuracy', '?')} · 분류: {info.get('category', '?')} · "
                        f"PP: {info.get('pp', '?')}"
                    ),
                    inline=False,
                )
        embed.set_thumbnail(url=sprite_url(trainer["currentPokemon"]))

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="기술목록", description="앞으로 배울 예정인 기술들을 확인해요.")
    @restrict_to_channel("attendance")
    async def upcoming_skills(self, interaction: discord.Interaction):
        trainer = get_trainer(interaction.user.id)
        if trainer is None:
            await interaction.response.send_message(
                "아직 시작하지 않았어요! `/시작`으로 첫 포켓몬을 받아보세요.",
                ephemeral=True,
            )
            return

        learnset = get_learnset(trainer["basePokemon"])
        upcoming = sorted(
            (int(lvl), move)
            for lvl, moves in learnset.items()
            for move in moves
            if int(lvl) > trainer["level"]
        )

        embed = discord.Embed(
            title=f"{trainer['currentPokemon']} 다음 습득 예정 기술",
            color=0x9B59B6,
        )
        if not upcoming:
            embed.description = "더 이상 배울 예정인 기술이 없어요."
        else:
            embed.description = "\n".join(f"Lv.{lvl} → {move}" for lvl, move in upcoming)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="출석리셋", description="[서버 소유자 전용/테스트용] 내 트레이너 데이터를 전부 초기화해요.")
    @restrict_to_channel("attendance")
    async def reset(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return

        had_data = reset_user(interaction.user.id)

        if not had_data:
            await interaction.response.send_message("초기화할 데이터가 없어요.", ephemeral=True)
            return

        await interaction.response.send_message(
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

        trainer = get_trainer(interaction.user.id)
        if trainer is None:
            trainer = start_trainer(interaction.user.id)

        trainer["basePokemon"] = target_base
        trainer["currentPokemon"] = 포켓몬
        trainer["evolutionStage"] = target_stage
        trainer["level"] = 레벨
        trainer["exp"] = 0
        trainer["ability"] = roll_ability(포켓몬)
        trainer["stats"] = calculate_stats(포켓몬, 레벨, trainer["iv"], trainer["nature"])

        save_trainer(interaction.user.id, trainer)

        embed = discord.Embed(
            title="🛠️ 테스트용 포켓몬 설정 완료",
            description=f"**{포켓몬}** (Lv.{레벨})로 강제 설정했어요.",
            color=0xE67E22,
        )
        embed.set_image(url=sprite_url(포켓몬))
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

    @app_commands.command(name="채널설정", description="[서버 소유자 전용] 포켓몬/랭크방 명령어를 쓸 수 있는 채널을 지정해요.")
    @app_commands.describe(기능="채널을 지정할 명령어 그룹", 채널="이 그룹의 명령어를 허용할 채널")
    @app_commands.choices(기능=[
        app_commands.Choice(name="출석 명령어 (/출석)", value="attend"),
        app_commands.Choice(name="육성 명령어 (/시작, /프로필, /기술, /기술목록 등)", value="attendance"),
        app_commands.Choice(name="랭크방/관전 명령어 (/랭크방, /관전입장권 등)", value="rank_room"),
        app_commands.Choice(name="전적 조회 명령어 (/전적)", value="tier_lookup"),
    ])
    async def set_channel(self, interaction: discord.Interaction, 기능: app_commands.Choice[str], 채널: discord.TextChannel):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("이 명령어는 서버 소유자만 쓸 수 있어요.", ephemeral=True)
            return

        set_setting(channel_key(기능.value), 채널.id)
        await interaction.response.send_message(
            f"✅ **{기능.name}**는 이제 {채널.mention} 채널에서만 사용할 수 있어요.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Attendance(bot))