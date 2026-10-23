"""❓ "막히는 자리"에 붙이는 봇 매니저 버튼.

## 왜 (2026-10-23)

❓ 봇 매니저는 10-18에 켰는데 닷새 뒤 `assistant_usage`가 **1건**이었어요. 작동은
정상이에요 — 10-18에 누가 "코인어떻게모아"라고 적어서 제대로 답을 받았어요. 문제는
**전용 채널에만 있어서 아무도 못 찾는다**는 거예요.

그래서 상점처럼 **진열해두지 않고, 사람이 실제로 막히는 자리에 붙여요.**
(🎣 소형 낚시대를 "코인이 모자란 사람이 막히는 바로 그 자리"에 띄워서 구매자가
31%→71%로 늘어난 것과 같은 수법이에요. → `cogs/fishing.py`)

지금 붙은 자리:
- `utils/channel_check.py` — "이 명령어는 #채널에서만 쓸 수 있어요"
  (명령어를 쓰려다 거절당한 순간이라, 안 알려주면 그냥 포기해요)

## 🚨 Assistant cog를 import하지 마세요

`cogs/assistant.py`는 이 모듈을 쓰는 `utils/channel_check.py`를 import해요. 여기서
거꾸로 cog를 import하면 순환이 생겨서 **봇 전체가 안 떠요.** 그래서 실행 시점에
`interaction.client.get_cog("Assistant")`로 이름으로 찾아요(없으면 안내만 해요).

## 🚨 영속 뷰 — `self`에 상태를 담지 마세요

봇 전체에 객체가 하나뿐이에요. 이 뷰는 **아무 상태도 안 들고** 있고, 질문은 모달이
그때그때 받아요. (`cogs/team.py`가 이걸 어겨서 사고가 났어요)
"""
from __future__ import annotations

import logging

import discord

log = logging.getLogger(__name__)

ASK_CUSTOM_ID = "akgui:ask:open"

MIN_LEN = 2
MAX_LEN = 300


class AskModal(discord.ui.Modal, title="봇에게 물어보기"):
    """하고 싶은 걸 말로 적으면 어떤 명령어를 쓰면 되는지 알려줘요."""

    질문 = discord.ui.TextInput(
        label="무엇이 궁금하세요?",
        placeholder="코인 어떻게 모아?  /  낚시대 어디서 사?",
        style=discord.TextStyle.short,
        max_length=MAX_LEN,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 🚨 Claude 호출이 3초를 넘겨요. **먼저 토큰을 받아둬요.**
        #    (이 저장소의 상호작용 만료 사고가 전부 이 순서를 어겨서 났어요)
        await interaction.response.defer(ephemeral=True)

        question = str(self.질문.value).strip()
        if len(question) < MIN_LEN:
            await interaction.followup.send("질문을 조금 더 자세히 적어주세요.", ephemeral=True)
            return

        cog = interaction.client.get_cog("Assistant")
        if cog is None:
            await interaction.followup.send(
                "지금은 안내 기능이 꺼져 있어요. `/도움` 으로 다시 시도해 주세요.",
                ephemeral=True,
            )
            return

        embed, _used_ai = await cog.answer(question, interaction.user.id)
        await interaction.followup.send(embed=embed, ephemeral=True)


class AskHintView(discord.ui.View):
    """🚨 **상태를 들고 있지 않아요.** 봇 전체에 이 객체 하나만 등록돼요."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="봇에게 물어보기", emoji="❓",
                       style=discord.ButtonStyle.secondary, custom_id=ASK_CUSTOM_ID)
    async def ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AskModal())
