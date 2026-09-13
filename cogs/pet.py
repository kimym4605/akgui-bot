"""코드냥이(바탕화면 고양이 앱)를 내 악귀코인 계정에 연결해주는 명령어예요.

## 봇은 코드만 발급해요

코드냥이 앱은 **각자 PC에서 도는 프로그램**이라, 앱 안에 DB 접속정보를 넣어버리면
프로그램을 받은 사람이 그걸 꺼내서 자기 코인을 마음대로 찍을 수 있어요. 그래서 앱은
서버 비밀정보를 하나도 갖지 않고, 대신 **포켓몬 웹 서버(akgui-pokemon)의 API**를 통해서만
코인을 만져요.

문제는 "그 앱을 쓰는 사람이 디스코드에서 누구인가"를 확인하는 거예요. 그걸 이 명령어가 해요.

1. 여기서 6자리 코드를 만들어 `pet_pair_codes` 컬렉션에 넣어요 (5분 유효)
2. 유저가 그 코드를 앱에 입력하면, 앱이 웹 서버에 보내요
3. 웹 서버가 **같은 Atlas**에서 그 코드를 찾아 지우고, 기기 토큰을 내줘요

봇과 웹이 DB를 공유하니까 **봇에 HTTP 서버를 붙이지 않고도** 코드가 건너가요.
(봇 머신이 256MB라 웹서버를 얹고 싶지 않았어요.)

그리고 슬래시 명령은 이 서버 안에서만 칠 수 있으니, **서버원인지 자동으로 걸러져요.**
"""
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.channel_check import restrict_to_channel
from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_pair_codes = _db["pet_pair_codes"]
_tokens = _db["pet_tokens"]

CODE_TTL_MINUTES = 5

# 헷갈리는 글자(0/O, 1/I/L)는 뺐어요. 손으로 옮겨 적는 코드라서요.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def _make_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _issue_code_sync(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)

    # 전에 받아놓고 안 쓴 코드는 정리해요. 한 사람당 살아있는 코드는 하나면 충분해요.
    _pair_codes.delete_many({"userId": str(user_id)})

    # 아주 드물게 남의 코드와 겹칠 수 있으니 몇 번 다시 뽑아요.
    for _ in range(10):
        code = _make_code()
        try:
            _pair_codes.insert_one({
                "_id": code,
                "userId": str(user_id),
                "username": username,
                "createdAt": now,
                "expiresAt": now + timedelta(minutes=CODE_TTL_MINUTES),
            })
            return code
        except Exception:
            continue
    raise RuntimeError("코드 생성 실패")


def _revoke_sync(user_id: int) -> int:
    return _tokens.delete_many({"userId": str(user_id)}).deleted_count


class Pet(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="코드냥이",
        description="바탕화면 고양이 앱(코드냥이)을 내 악귀코인 계정에 연결해요.",
    )
    @restrict_to_channel("attendance")
    async def pair(self, interaction: discord.Interaction):
        # DB 왕복이 3초를 넘기면 디스코드가 끊으니 먼저 defer해요.
        await interaction.response.defer(ephemeral=True)

        try:
            code = await asyncio.to_thread(
                _issue_code_sync, interaction.user.id, interaction.user.display_name
            )
        except Exception:
            log.error("코드냥이 연동코드 발급 실패 (%s)", interaction.user, exc_info=True)
            await interaction.followup.send(
                "연동 코드를 만들지 못했어요. 잠시 뒤에 다시 시도해 주세요.", ephemeral=True
            )
            return

        log.info("🐱 %s 코드냥이 연동코드 발급", interaction.user)

        embed = discord.Embed(
            title="🐱 코드냥이 연동 코드",
            description=(
                f"# `{code}`\n"
                f"-# {CODE_TTL_MINUTES}분 안에 입력해 주세요. 한 번 쓰면 사라져요.\n\n"
                "**연결하는 법**\n"
                "1. 코드냥이를 실행하고 트레이 아이콘(고양이) → **설정**\n"
                "2. **악귀코인** 칸에 위 코드를 입력\n"
                "3. 끝! 이제 바탕화면 고양이가 내 코인을 알아봐요\n\n"
                "연결하면 이런 게 돼요\n"
                "· 디스코드에서 코인이 들어오면 고양이가 **바로 반응**해요\n"
                "· 코인으로 고양이한테 **모자·목도리·안경** 같은 걸 사줄 수 있어요\n"
                "· **간식**을 사서 먹이면 친밀도가 쑥 올라요\n"
                "· 집중해서 일하면 코인을 벌어요 (하루 3개까지)"
            ),
            color=0xF1C40F,
        )
        embed.set_footer(text="이 메시지는 나에게만 보여요. 코드를 남에게 알려주지 마세요.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="코드냥이연결해제",
        description="연결해둔 코드냥이를 전부 해제해요. (PC를 바꾸거나 잃어버렸을 때)",
    )
    @restrict_to_channel("attendance")
    async def unpair(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        count = await asyncio.to_thread(_revoke_sync, interaction.user.id)
        if count == 0:
            await interaction.followup.send("연결된 코드냥이가 없어요.", ephemeral=True)
            return
        log.info("🐱 %s 코드냥이 연결 %d개 해제", interaction.user, count)
        await interaction.followup.send(
            f"연결된 코드냥이 **{count}개**를 해제했어요.\n"
            "다시 연결하려면 `/코드냥이` 로 새 코드를 받으세요.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Pet(bot))
