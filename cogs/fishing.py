"""🎣 낚시 - 찌를 던져 물고기를 낚고, 어항에 모았다가 팔아 코인을 벌어요.

## 🚨 발행 안전장치는 **"1개당 순이익 ≈ 0"** 이에요 (2026-10-17 4차)

낚시하려면 `/악귀상점`에서 **낚시대**를 사야 해요(`ROD_PRICE`코인 · 내구도 10회).
**몇 개든 살 수 있어요** - 하루 제한을 풀었거든요(사용자 결정).

    낚시대 1개: 수입 약 10.2코인 − 값 10코인 = 순이익 **+0.2**

제한을 푸는 대신 **일반 물고기 비중을 90.5%까지 올려** 1개당 순이익을 0 근처로 눌렀어요.
시간을 아무리 써도 평균적으로 본전이라 무한 발행이 안 생겨요.

### 설계가 세 번 바뀐 이유 (같은 실수를 반복하지 않게)

1. **상한 없음 + 꽝 60%** → 꽝 확률은 1회당 수익만 낮출 뿐 **총 발행량을 못 막아요**
   (작정하면 하루 189코인). 출석 3~5코인이 무의미해졌어요.
2. **낚시대 하루 1개(+8.8/일)** → 상한은 잡혔지만 "더 하고 싶다"는 요구가 남았어요.
3. **제한 해제 + 순이익 ≈ 0** ← 지금. 무제한이어도 안전해요.

🚨 **이제 `ROD_PRICE`는 발행 손잡이가 아니에요.** 값을 내리면 순이익이 양수가 되고
무제한이라 그대로 인플레예요. 값을 바꿀 땐 **반드시 일반 가중치도 같이** 조정해서
`fish_data.net_issue_per_rod()`를 0 근처로 유지하세요(테스트가 검사해요).

⚠️ 대가도 분명해요 - **낚시는 더 이상 "버는 수단"이 아니라 복권에 가까워요.** 평균은
본전이고 대물(2.7%)·전설(0.13%)이 터질 때만 크게 남아요. 캐주얼 유저가 하루 1개만
써도 기대수익이 +0.2라는 뜻이에요.

## 찌타임 미니게임

1. `/낚시` -> 내구도 1 소모 + "찌를 던졌어요" + **🎣 챔질 버튼**
2. 2~8초 뒤 메시지가 "🐟 입질이 왔어요!"로 바뀌어요
3. 그때부터 **2.5초 안에** 버튼을 눌러야 잡혀요

- 입질 전에 누르면 **성급** (놓침)
- 늦게 누르면 **놓침**
- 제때 누르면 **반드시** 물고기가 나와요 (꽝 없음)

⚠️ **타이밍을 놓쳐도 내구도는 줄어요**(사용자 결정). 안 그러면 낚시대 하나가 "물고기
10마리 확정"이 돼서 미니게임이 장식이 돼요.
🚨 **내구도는 던지기 전에 깎아요.** 끝나고 깎으면 미니게임 도중에 `/낚시`를 여러 번 쳐서
내구도 1개로 여러 판을 돌릴 수 있어요.

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
from utils.fish_data import (
    BY_KEY, COIN_PIECES, FISH, GRADE_ORDER, GRADES, ROD_DURABILITY, ROD_PER_DAY,
    ROD_PRICE, pieces_of, roll_size,
)

log = logging.getLogger(__name__)

CHANNEL_GROUP = "fishing"
CHANNEL_ENV = "FISHING_CHANNEL_ID"
COIN_LOG_NOTE = "낚시판매"
# 🚨 소각(낚시대)과 발행(판매)을 **다른 note로** 갈라요. 같으면 리포트에서
#    순발행을 계산할 수 없어요. 둘 다 "낚시"로 시작하지만 kind가 달라요.
ROD_NOTE = "낚시대"

BITE_MIN, BITE_MAX = 2.0, 8.0      # 입질까지 기다리는 시간
BITE_WINDOW = 2.5                  # 입질 후 챔질 제한시간
WAIT_COLOR, BITE_COLOR = 0x2B6CB0, 0x38A169
MISS_COLOR = 0x6B7280

_GRADE_KEYS = {g: [f["key"] for f in rows] for g, rows in FISH.items()}


def roll_catch(rng: random.Random | None = None) -> str:
    """한 번 챔질에 **성공했을 때** 뭐가 잡히나.

    ⚠️ **꽝이 없어요**(2026-10-17 2차 설계). 타이밍만 맞히면 반드시 물고기가 나와요.
    1차엔 꽝 60%로 발행을 조절했는데, 꽝 확률은 1회당 수익만 낮출 뿐 **총 발행량을
    못 막아요**. 이제는 낚시대(하루 1개·내구도 10)가 상한을 걸고, 발행 조절은
    `fish_data.ROD_PRICE`가 해요.

    못 잡는 경우는 이제 **타이밍 실패뿐**이고, 그건 내 실수지 운이 아니에요."""
    rng = rng or random
    grades = list(GRADES)
    weights = [GRADES[g]["weight"] for g in grades]
    grade = rng.choices(grades, weights=weights, k=1)[0]
    return rng.choice(_GRADE_KEYS[grade])


async def purchase_rod(user_id) -> tuple[bool, str]:
    """낚시대 한 개를 사요. (성공, 안내문). `/악귀상점`과 🎣 버튼이 **같이** 써요.

    🚨 **지급을 먼저, 차감을 나중에** 해요. 반대로 하면 차감 뒤 지급이 실패했을 때
    코인만 사라져요. 차감이 실패하면 `refund_rod`로 되돌려서 공짜 낚시대를 막아요.
    (🎲 도박 한도 연장권과 같은 순서예요.)"""
    # ⚠️ 하루 제한이 없어서(2026-10-17 4차) 지급은 항상 성공해요. 그래도 순서는
    #    그대로 지급 -> 차감 -> 실패 시 환불이에요.
    await fishing_store.buy_rod(user_id, ROD_DURABILITY)

    if not await coin_wallet.spend(user_id, ROD_PRICE, reason=ROD_NOTE):
        await fishing_store.refund_rod(user_id, ROD_DURABILITY)
        balance = await coin_wallet.get_balance(user_id)
        return False, (
            f"악귀코인이 부족해요. 낚시대는 **{ROD_PRICE}코인**인데 "
            f"지금 **{balance}개** 있어요.\n"
            "-# `/출석` · `/미션` · `/업적`으로 모을 수 있어요."
        )

    balance = await coin_wallet.get_balance(user_id)
    log.info("🎣 낚시대 구매: %s %d코인", user_id, ROD_PRICE)
    return True, (
        f"🎣 낚시대를 샀어요! **{ROD_DURABILITY}번** 던질 수 있어요.\n"
        f"남은 악귀코인 **{balance}개** · `/낚시` 로 시작해보세요"
    )


class BuyRodView(discord.ui.View):
    """🎣 낚시대 구매 버튼.

    🚨 `/악귀상점`에만 두면 안 팔려요 - 리롤권·보호권·테마가 **12일째 0건**이에요
    (구매력이 아니라 발견이 문제였어요). 그래서 **낚시대가 없어서 막힌 바로 그 자리**에
    버튼을 띄워요. 🔓 도박 한도 연장권이 같은 이유로 그렇게 해서 잘 팔려요."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="낚시대 사기", emoji="🎣", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        button.disabled = True
        ok, msg = await purchase_rod(interaction.user.id)
        try:
            await interaction.edit_original_response(content=msg, view=None)
        except discord.HTTPException:
            await interaction.followup.send(msg, ephemeral=True)


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
        self.size: int | None = None          # 📏 잡힌 물고기의 치수(cm)
        self.rod_left = 0                     # 이번 캐스트 뒤 남은 내구도

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
            # 📏 치수는 잡힌 **그 순간** 정해져요. 나중에 굴리면 같은 물고기가
            #    볼 때마다 크기가 달라져요.
            self.size = roll_size(self.caught)
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

    @app_commands.command(name="낚시", description="찌를 던져 물고기를 낚아요. (낚시대가 필요해요)")
    @restrict_to_channel(CHANNEL_GROUP, CHANNEL_ENV)
    async def fish(self, interaction: discord.Interaction):
        # 🚨 **내구도를 먼저 깎고** 시작해요. 던지고 나서 깎으면, 미니게임 도중에
        #    여러 번 `/낚시`를 쳐서 내구도 1개로 여러 판을 돌릴 수 있어요.
        left = await fishing_store.use_rod(interaction.user.id)
        if left is None:
            _, bought_today = await fishing_store.rod_state(interaction.user.id)
            if bought_today:
                msg = (f"🎣 낚시대가 부서졌어요. (하루 **{ROD_PER_DAY}개**까지만 살 수 있어요)\n"
                       "-# 내일 다시 사서 던질 수 있어요.")
                view = None
            else:
                msg = (f"🎣 낚시대가 없어요. **{ROD_PRICE}코인**으로 하나 사면 "
                       f"**{ROD_DURABILITY}번** 던질 수 있어요.")
                # 🚨 상점에 진열만 해두면 안 팔려요(리롤권·보호권·테마가 12일째 0건).
                #    **막힌 바로 이 자리**에서 바로 살 수 있게 버튼을 붙여요.
                view = BuyRodView(interaction.user.id)
            await interaction.response.send_message(msg, view=view, ephemeral=True)
            return

        view = FishingView(interaction.user.id)
        view.rod_left = left
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
        size = view.size if key else None
        await fishing_store.record_cast(interaction.user.id, key, size)
        state = await fishing_store.get(interaction.user.id)
        total = sum(len(v) for v in state["tank"].values())

        if key:
            grade, name = BY_KEY[key]
            g = GRADES[grade]
            pieces = pieces_of(key, size)
            lo, hi = fish_data.SIZE_BY_KEY[key]
            # 📏 같은 어종 안에서 몇 %짜리인지 - "대물급 피라미"의 재미가 여기서 나와요.
            pct = int((size - lo) / max(1, hi - lo) * 100)
            tag = " 🏆 **최대급!**" if pct >= 90 else (" ✨ 큼직해요" if pct >= 70 else "")
            embed = discord.Embed(
                title=f"{g['emoji']} {grade} · {name} {size}cm{tag}",
                description=f"판매가 **{pieces / COIN_PIECES:.1f}코인**",
                color=g["color"],
            )
        else:
            # ⚠️ 이제 **못 잡는 경우는 타이밍 실패뿐**이에요(꽝 제거, 2026-10-17 2차).
            #    운이 아니라 내 실수라서, 사유를 분명히 알려줘요.
            reason = {
                "early": "너무 일찍 챘어요. 미끼만 날아갔네요.",
                "late": "늦었어요. 물고기가 도망갔어요.",
            }.get(view.result, "놓쳤어요.")
            embed = discord.Embed(
                title="💨 놓쳤어요",
                description=reason + "\n-# 낚시대 내구도는 그대로 1 줄어요.",
                color=MISS_COLOR)

        embed.add_field(name="어항", value=f"**{total}마리**", inline=True)
        embed.add_field(name="🎣 낚시대",
                        value=(f"**{view.rod_left}번** 남음" if view.rod_left
                               else "**부서졌어요**"), inline=True)
        embed.set_footer(
            text=("/어항 으로 확인하고 /물고기판매 로 한 번에 팔아요" if view.rod_left
                  else f"내일 {ROD_PRICE}코인으로 새 낚시대를 살 수 있어요"))
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
            lines = []
            for grade in GRADE_ORDER:
                rows = [(k, s) for k, sizes in tank.items()
                        if BY_KEY.get(k, ("", ""))[0] == grade for s in sizes]
                if not rows:
                    continue
                g = GRADES[grade]
                lo_p, hi_p = g["pieces"]
                # 📏 **큰 놈부터** 보여줘요. 어항을 열었을 때 제일 궁금한 게 최대어예요.
                rows.sort(key=lambda r: -(r[1] or 0))
                part = " · ".join(
                    f"{BY_KEY[k][1]}" + (f" {s}cm" if s is not None else "")
                    for k, s in rows[:8])
                if len(rows) > 8:
                    part += f" 외 {len(rows) - 8}마리"
                lines.append(
                    f"{g['emoji']} **{grade}** "
                    f"({lo_p / COIN_PIECES:.1f}~{hi_p / COIN_PIECES:.1f}코인) — {part}")
            embed.description = "\n".join(lines)

            total_n = sum(len(v) for v in tank.values())
            pieces = data["pieces"] + data["dust"]
            embed.add_field(name="마리 수", value=f"**{total_n}마리**", inline=True)
            # ⚠️ 실제 지급은 **내림**이에요(나머지는 다음 판매로 넘어가요). 기대를
            #    부풀리지 않게 정확한 값과 받을 코인을 같이 보여줘요.
            embed.add_field(
                name="팔면",
                value=(f"**{pieces // COIN_PIECES}코인**"
                       + (f"\n-# (정확히 {pieces / COIN_PIECES:.1f} · "
                          f"남는 {pieces % COIN_PIECES / COIN_PIECES:.1f}은 다음에)"
                          if pieces % COIN_PIECES else "")),
                inline=True)

        # 🎣 낚시대 상태를 제일 먼저 보여줘요 - "오늘 몇 번 더 던질 수 있나"가
        #    낚시에서 제일 궁금한 정보예요.
        left, bought_today = await fishing_store.rod_state(interaction.user.id)
        if left:
            rod = f"**{left}/{ROD_DURABILITY}번** 남음"
        elif bought_today:
            rod = "**부서졌어요** (내일 다시)"
        else:
            rod = f"없어요 ({ROD_PRICE}코인)"
        embed.add_field(name="🎣 낚시대", value=rod, inline=True)

        hit = f"{data['caught']}/{data['casts']}" if data["casts"] else "0/0"
        embed.add_field(name="챔질 성공률", value=f"{hit}", inline=True)
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
            rows = [(k, sz) for k, sizes in tank.items()
                    if BY_KEY.get(k, ("", ""))[0] == grade for sz in sizes]
            if rows:
                g = GRADES[grade]
                sub = sum(pieces_of(k, sz) for k, sz in rows)
                big = max((sz for _, sz in rows if sz is not None), default=None)
                lines.append(
                    f"{g['emoji']} **{grade}** {len(rows)}마리 — "
                    f"{sub / COIN_PIECES:.1f}코인"
                    + (f" (최대 {big}cm)" if big else ""))

        embed = discord.Embed(
            title="🪙 물고기를 팔았어요!",
            description="\n".join(lines),
            color=0xFFC850,
        )
        embed.add_field(name="받은 코인", value=f"**+{coins}개**", inline=True)
        embed.add_field(name="보유 악귀코인", value=f"**{balance}개**", inline=True)
        # 🚨 남은 조각을 **반드시 알려줘요.** 안 그러면 "3.7코인어치인데 3개만 받았다"가
        #    떼먹힌 걸로 보여요. 다음 판매에 더해진다는 걸 명시해요.
        if dust:
            embed.add_field(name="다음에 더해져요",
                            value=f"**{dust / COIN_PIECES:.1f}코인**", inline=True)
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
