"""🎣 낚시 - 찌를 던져 물고기를 낚고, 어항에 모았다가 팔아 코인을 벌어요.

## 🚨 이건 코인을 **만들어내는** 기능이에요

뽑기·상점이 태우는 쪽이면 낚시는 찍어내는 쪽이에요. 숫자는 전부 `utils/fish_data.py`에
모아뒀고, 왜 그 값인지도 거기 적혀 있어요. **하루 상한이 없으니**(사용자 결정) 과열되면
`fish_data.MISS_RATE`를 먼저 올리세요.

## 찌타임 미니게임

1. `/낚시` -> "찌를 던졌어요" + **🎣 챔질 버튼**
2. 2~8초 뒤 메시지가 "🐟 입질이 왔어요!"로 바뀌어요
3. 그때부터 **2.5초 안에** 버튼을 눌러야 잡혀요

- 입질 전에 누르면 **성급** (꽝)
- 늦게 누르면 **놓침** (꽝)
- 제때 누르면 확률표대로 등급이 정해져요

⚠️ 버튼은 처음부터 **눌리는 상태**로 둬요. 비활성으로 두면 디스코드가 클릭 자체를
막아서 "성급하게 눌렀다"를 잡아낼 수가 없어요 - 미니게임의 절반이 사라져요.

⚠️ 기다리는 동안 `asyncio.sleep`을 쓰는데, 그건 이벤트 루프를 막지 않아요(동기 `time.sleep`
이었다면 봇 전체가 멈춰요 - 이 봇은 그 사고 전력이 있어요).

## 왜 어항인가

낚을 때마다 코인을 주지 않고 **팔 때 한 번만** 발행해요. `coin_log`에 `낚시판매`가
한 줄씩 깔끔하게 남아서 낚시가 얼마나 찍어냈는지 정확히 떼어볼 수 있어요.

## 🚨 가시성 - 낚시는 전부 **본인에게만** 보여요

| 명령어 | 보이는 범위 |
|---|---|
| `/낚시` `/어항` `/물고기판매` | **본인에게만** (ephemeral) |
| `/낚시왕` | 공개 (순위표라 같이 보는 게 맞아요) |

왜 비공개인가: 한 채널에서 여러 명이 동시에 던지면 **찌가 뒤섞여요.** 어느 게 내 건지
모르고, 남의 "입질이 왔어요!"를 보고 눌러버리기도 해요. 🎴 뽑기는 자랑하는 재미 때문에
뽑기방에서 공개인데, 낚시는 **몇 초짜리 실시간 조작**이라 성격이 정반대예요.

⚠️ `/물고기판매`는 **`defer`부터 ephemeral이어야** 해요. 공개로 defer하면 "생각 중..."
자리가 채널에 남아서, 결과만 비공개로 보내봐야 흔적이 섞여요.
⚠️ `strike` 버튼의 `defer()`는 컴포넌트 상호작용이라 **메시지를 만들지 않아요**
(deferred_message_update). 거기엔 ephemeral이 필요 없어요.
"""
import asyncio
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import coin_wallet, fish_data, fishing_store
from utils.channel_check import restrict_to_channel
from utils.fish_data import BY_KEY, FISH, GRADE_ORDER, GRADES, JUNK, MISS_RATE

log = logging.getLogger(__name__)

CHANNEL_GROUP = "fishing"
CHANNEL_ENV = "FISHING_CHANNEL_ID"
COIN_LOG_NOTE = "낚시판매"

BITE_MIN, BITE_MAX = 2.0, 8.0      # 입질까지 기다리는 시간
BITE_WINDOW = 2.5                  # 입질 후 챔질 제한시간
WAIT_COLOR, BITE_COLOR = 0x2B6CB0, 0x38A169
MISS_COLOR = 0x6B7280

_GRADE_KEYS = {g: [f["key"] for f in rows] for g, rows in FISH.items()}


def roll_catch(rng: random.Random | None = None) -> str | None:
    """한 번 챔질했을 때 뭐가 잡히나. None이면 꽝이에요.

    ⚠️ 꽝은 **챔질에 성공했는데도** 나올 수 있어요(미끼만 뜯긴 경우).
    타이밍을 맞추는 것과 물고기가 무는 건 별개라 둘 다 통과해야 잡혀요."""
    rng = rng or random
    if rng.uniform(0, 100) < MISS_RATE:
        return None
    grades = list(GRADES)
    weights = [GRADES[g]["weight"] for g in grades]
    grade = rng.choices(grades, weights=weights, k=1)[0]
    return rng.choice(_GRADE_KEYS[grade])


class FishingView(discord.ui.View):
    """찌 하나짜리 화면. 한 사람의 한 번의 낚시에만 쓰여요.

    ⚠️ 영속(DynamicItem)이 아니에요. 낚시는 **몇 초 안에 끝나는 일회성**이라 봇이
    재시작되면 그 판은 그냥 없던 일이 되는 게 맞아요(뽑기 버튼과는 성격이 달라요)."""

    def __init__(self, user_id: int):
        super().__init__(timeout=BITE_MAX + BITE_WINDOW + 10)
        self.user_id = user_id
        self.bite_at: float | None = None     # 입질이 온 시각 (None = 아직)
        self.done = asyncio.Event()
        self.result: str | None = None        # "early" | "late" | "ok"
        self.caught: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "남의 찌예요. `/낚시`로 직접 던져주세요.", ephemeral=True)
        return False

    @discord.ui.button(label="챔질!", emoji="🎣", style=discord.ButtonStyle.primary)
    async def strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done.is_set():
            await interaction.response.defer()
            return
        if self.bite_at is None:
            # 🚨 입질 전에 누른 경우. 버튼을 처음부터 눌리게 둔 이유가 이걸 잡기 위해서예요.
            self.result = "early"
        elif time.monotonic() - self.bite_at > BITE_WINDOW:
            self.result = "late"
        else:
            self.result = "ok"
            self.caught = roll_catch()
        self.done.set()
        button.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        if not self.done.is_set():
            self.result = "late"
            self.done.set()


class Fishing(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="낚시", description="찌를 던져 물고기를 낚아요. 입질이 오면 바로 챔질!")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def fish(self, interaction: discord.Interaction):
        view = FishingView(interaction.user.id)
        embed = discord.Embed(
            title="🎣 찌를 던졌어요",
            description="찌를 지켜보세요... **입질이 오면 바로 챔질!**",
            color=WAIT_COLOR,
        )
        embed.set_footer(text="너무 일찍 누르면 미끼만 날려요")
        # 🚨 **본인에게만** 보여요. 한 채널에서 여러 명이 동시에 던지면 찌가 뒤섞여서
        #    어느 게 내 건지 알 수 없고, 남의 '입질!'을 보고 눌러버리기도 해요.
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # 입질까지 기다려요. 그 사이에 유저가 누르면 done이 먼저 떨어져요(= 성급).
        wait = random.uniform(BITE_MIN, BITE_MAX)
        try:
            await asyncio.wait_for(view.done.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass

        if not view.done.is_set():
            # 입질! 여기서부터 BITE_WINDOW 안에 눌러야 해요.
            view.bite_at = time.monotonic()
            bite = discord.Embed(
                title="🐟 입질이 왔어요!",
                description="**지금 챔질하세요!**",
                color=BITE_COLOR,
            )
            try:
                await interaction.edit_original_response(embed=bite, view=view)
            except discord.HTTPException:
                log.info("입질 표시 실패 (메시지가 사라졌을 수 있어요)")
            try:
                await asyncio.wait_for(view.done.wait(), timeout=BITE_WINDOW + 1.0)
            except asyncio.TimeoutError:
                view.result = "late"
                view.done.set()

        view.stop()
        await self._finish(interaction, view)

    async def _finish(self, interaction: discord.Interaction, view: FishingView):
        key = view.caught if view.result == "ok" else None
        await fishing_store.record_cast(interaction.user.id, key)
        tank = (await fishing_store.get(interaction.user.id))["tank"]
        total = sum(tank.values())

        if key:
            grade, name = BY_KEY[key]
            g = GRADES[grade]
            embed = discord.Embed(
                title=f"{g['emoji']} {grade} · {name} 을(를) 낚았어요!",
                description=f"판매가 **{g['price']}코인**",
                color=g["color"],
            )
        else:
            reason = {
                "early": "너무 일찍 챘어요. 미끼만 날아갔네요.",
                "late": "늦었어요. 물고기가 도망갔어요.",
            }.get(view.result, f"**{random.choice(JUNK)}** 이(가) 걸려 올라왔어요.")
            embed = discord.Embed(title="🗑️ 꽝", description=reason, color=MISS_COLOR)

        embed.add_field(name="어항", value=f"**{total}마리**", inline=True)
        embed.set_footer(text="/어항 으로 확인하고 /물고기판매 로 한 번에 팔아요")
        try:
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="어항", description="낚아둔 물고기를 봐요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def tank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = await fishing_store.get(interaction.user.id)
        tank = data["tank"]

        embed = discord.Embed(title="🪣 내 어항", color=0x3B82F6)
        if not tank:
            embed.description = "어항이 비었어요. `/낚시` 로 한 마리 낚아보세요!"
        else:
            lines, value = [], 0
            for grade in GRADE_ORDER:
                rows = [(k, n) for k, n in tank.items() if BY_KEY.get(k, ("", ""))[0] == grade]
                if not rows:
                    continue
                g = GRADES[grade]
                part = " · ".join(f"{BY_KEY[k][1]} ×{n}" for k, n in sorted(rows))
                lines.append(f"{g['emoji']} **{grade}** ({g['price']}코인) — {part}")
                value += sum(g["price"] * n for _, n in rows)
            embed.description = "\n".join(lines)
            embed.add_field(name="마리 수", value=f"**{sum(tank.values())}마리**", inline=True)
            embed.add_field(name="팔면", value=f"**{value}코인**", inline=True)

        hit = f"{data['caught']}/{data['casts']}" if data["casts"] else "0/0"
        embed.add_field(name="성공률", value=f"{hit}", inline=True)
        if data.get("best"):
            bg, bn = BY_KEY.get(data["best"]["key"], ("?", "?"))
            embed.add_field(name="최고 기록",
                            value=f"{GRADES.get(bg, {}).get('emoji', '')} {bn}", inline=True)
        if data["sold"]:
            embed.add_field(name="누적 판매", value=f"**{data['sold']}코인**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="물고기판매", description="어항에 든 물고기를 전부 팔아요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def sell(self, interaction: discord.Interaction):
        # ⚠️ defer부터 ephemeral이어야 해요. 공개로 defer하면 "생각 중..." 자리가
        #    채널에 남아서, 결과만 비공개로 보내봐야 흔적이 섞여요.
        await interaction.response.defer(ephemeral=True)

        # 🚨 **비우면서 내용을 받아와요**(원자적). 읽고 나서 비우면 그 사이에 낚은
        #    물고기가 증발해요.
        tank, coins = await fishing_store.sell_all(interaction.user.id)
        if not tank:
            await interaction.followup.send(
                "어항이 비었어요. `/낚시` 로 한 마리 낚아보세요!", ephemeral=True)
            return

        try:
            balance = await coin_wallet.add(interaction.user.id, coins, reason=COIN_LOG_NOTE)
        except Exception:
            # 🚨 코인이 안 들어갔으면 물고기를 반드시 되돌려요.
            await fishing_store.restore(interaction.user.id, tank)
            log.exception("물고기 판매 실패 - 어항을 되돌렸어요 (user=%s)", interaction.user.id)
            await interaction.followup.send(
                "판매 중 문제가 생겼어요. **물고기는 어항에 그대로 있어요.**", ephemeral=True)
            return

        await fishing_store.add_sold(interaction.user.id, coins)

        lines = []
        for grade in GRADE_ORDER:
            n = sum(v for k, v in tank.items() if BY_KEY.get(k, ("", ""))[0] == grade)
            if n:
                g = GRADES[grade]
                lines.append(f"{g['emoji']} **{grade}** {n}마리 — {g['price'] * n}코인")

        embed = discord.Embed(
            title="🪙 물고기를 팔았어요!",
            description="\n".join(lines),
            color=0xFFC850,
        )
        embed.add_field(name="받은 코인", value=f"**+{coins}개**", inline=True)
        embed.add_field(name="보유 악귀코인", value=f"**{balance}개**", inline=True)
        embed.set_footer(text="어항이 비었어요 · /낚시 로 다시 채워보세요")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="낚시왕", description="누가 제일 많이 벌었는지 봐요.")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await fishing_store.leaderboard(10)
        if not rows:
            await interaction.followup.send("아직 아무도 물고기를 팔지 않았어요.")
            return
        medals = ["🥇", "🥈", "🥉"]
        body = "\n".join(
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — **{coins}코인**"
            for i, (uid, coins) in enumerate(rows)
        )
        embed = discord.Embed(title="🎣 낚시왕", description=body, color=0xFFC850)
        await interaction.followup.send(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(Fishing(bot))
