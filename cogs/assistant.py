"""❓ 봇 매니저 — 전용 채널에 질문을 적으면 봇 쓰는 법을 알려줘요.

## 왜 만들었나 (2026-10-18)

기능은 쌓였는데 **사람들이 못 쓰고 있었어요.** 실측으로 `/악귀상점` 구매 0건(열흘),
카드 거래 1건, 낚시 수혜자 12명. 구매력이 아니라 발견·사용법 문제예요.
`#🤖-봇-사용법` 글은 길어서 안 읽어요. 그래서 **물어보면 답하는 창구**를 하나 둬요.

## 두 갈래로 답해요 (하이브리드 — 사용자 결정)

1. 🆓 **규칙 매칭** — 키워드가 또렷하면 `utils/faq_knowledge.py`의 주제를 그대로 보여줘요.
   돈이 안 들고 즉시 답해요. 실측상 흔한 질문의 3/4이 여기서 끝나요.
2. 🤖 **Claude (Haiku 4.5)** — 규칙이 못 잡은 자연어 질문만 넘겨요. 지식 베이스를
   시스템 프롬프트로 먹이고, 거기 없는 건 모른다고 답하게 해요.

## 🚨 MESSAGE CONTENT INTENT가 필요해요 (전용 채널 쪽만)

메시지 **내용**을 읽는 건 특권 인텐트예요. 개발자 포털에서 안 켜고 코드에서만 켜면
**봇이 로그인에서 죽어요**(members 인텐트와 같아요). 그래서 `bot.py`가 환경변수
`ASSISTANT_READ_MESSAGES`로 잠가 뒀어요. 순서를 지켜주세요.

  1. 개발자 포털 > Bot > Privileged Gateway Intents > **MESSAGE CONTENT INTENT** 켜기
  2. `flyctl secrets set ASSISTANT_READ_MESSAGES=1`

인텐트를 안 켜도 `/도움` 명령어는 그냥 돼요. 전용 채널만 안 듣는 거예요.

## 비용 안전장치

- `utils/assistant_store.py`가 **사람별·서버별 하루 한도**를 세요. 넘으면 규칙 답변만 해요.
- 같은 사람이 연달아 긁지 못하게 쿨다운이 있어요.
- Claude 호출이 실패하면 세어둔 자리를 돌려줘요(돈이 안 나갔으니까요).
- 🚨 **`anthropic` 패키지나 API 키가 없어도 cog는 떠야 해요.** 안내 기능이 통째로
  사라지면 그게 더 나빠요. 그 경우 규칙 매칭만으로 동작해요.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import assistant_store, faq_knowledge
from utils.channel_check import get_allowed_channel_id

log = logging.getLogger(__name__)

CHANNEL_GROUP = "assistant"
CHANNEL_ENV = "ASSISTANT_CHANNEL_ID"

# 모델은 사용자가 Haiku 4.5로 정했어요(2026-10-18). 질문 하나에 몇 원 수준이에요.
# ⚠️ Haiku 4.5는 `output_config.effort`와 adaptive thinking을 안 받아요(400). 보내지 마세요.
MODEL = os.getenv("ASSISTANT_MODEL", "claude-haiku-4-5")
MAX_TOKENS = 600
API_TIMEOUT = 25.0

MIN_QUESTION_LEN = 2
MAX_QUESTION_LEN = 300
USER_COOLDOWN = 6.0        # 같은 사람이 Claude를 다시 부를 수 있는 간격(초)

RULE_COLOR = 0x3B82F6
AI_COLOR = 0x8B5CF6
MISS_COLOR = 0x6B7280

AI_FOOTER = "-# 🤖 AI가 쓴 답이라 틀릴 수 있어요. 이상하면 매니저에게 물어봐 주세요."


def _is_enabled_for_messages() -> bool:
    """전용 채널 듣기가 켜져 있나. (포털 인텐트를 켠 뒤 secrets로 올리는 스위치예요)"""
    return os.getenv("ASSISTANT_READ_MESSAGES", "").strip() in {"1", "true", "True", "yes"}


class Assistant(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._client = None
        self._client_ready = False
        self._last_call: dict[int, float] = {}
        self._channel_cache: tuple[float, int | None] = (0.0, None)

    # ── Claude 클라이언트 (있으면 쓰고 없으면 규칙만) ──────────────────────
    def _claude(self):
        """lazy 초기화. 패키지나 키가 없으면 None이고, 그땐 규칙 매칭만 돌아가요."""
        if self._client_ready:
            return self._client
        self._client_ready = True

        if not os.getenv("ANTHROPIC_API_KEY"):
            log.info("❓ 매니저: ANTHROPIC_API_KEY가 없어서 규칙 매칭만 써요.")
            return None
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            log.warning("❓ 매니저: anthropic 패키지가 없어서 규칙 매칭만 써요.")
            return None

        self._client = AsyncAnthropic(timeout=API_TIMEOUT, max_retries=1)
        log.info("❓ 매니저: Claude(%s) 준비됐어요.", MODEL)
        return self._client

    # ── 채널 판정 ────────────────────────────────────────────────────────
    def _assistant_channel_id(self) -> int | None:
        """허용 채널 ID. `/채널설정`은 파일을 읽으니 **30초 캐시**를 둬요.

        ⚠️ `on_message`는 서버의 모든 메시지마다 불려요. 매번 파일을 읽으면
        채팅이 활발할 때 이벤트 루프에 디스크 I/O가 계속 끼어들어요."""
        now = time.monotonic()
        cached_at, value = self._channel_cache
        if now - cached_at < 30.0:
            return value
        value = get_allowed_channel_id(CHANNEL_GROUP, CHANNEL_ENV)
        self._channel_cache = (now, value)
        return value

    # ── 답변 만들기 ──────────────────────────────────────────────────────
    def _rule_embed(self, topic: faq_knowledge.Topic) -> discord.Embed:
        embed = discord.Embed(
            title=topic.title,
            description=topic.text(),
            color=RULE_COLOR,
        )
        if topic.commands:
            embed.add_field(
                name="관련 명령어",
                value=" · ".join(f"`{c}`" for c in topic.commands),
                inline=False,
            )
        return embed

    def _miss_embed(self, related: list[faq_knowledge.Topic], note: str) -> discord.Embed:
        embed = discord.Embed(
            title="❓ 정확히는 잘 모르겠어요",
            description=note,
            color=MISS_COLOR,
        )
        if related:
            embed.add_field(
                name="혹시 이거 찾으셨나요?",
                value="\n".join(f"· {t.title} — {' · '.join(t.commands[:3])}" for t in related),
                inline=False,
            )
        return embed

    async def _ask_claude(self, question: str) -> str | None:
        """Claude에게 물어 답 텍스트를 받아요. 실패하면 None (부른 쪽이 폴백해요)."""
        client = self._claude()
        if client is None:
            return None

        system = faq_knowledge.build_system_prompt(self.bot)
        try:
            message = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system,
                        # 연달아 질문이 들어오면 지식 베이스를 캐시에서 읽어요(입력값 90% 절약).
                        # ⚠️ Haiku 4.5는 캐시가 붙는 최소 길이가 4096토큰이에요. 그보다 짧으면
                        #    에러 없이 **조용히 캐시가 안 걸려요**(동작은 정상이고 값만 못 깎아요).
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": question}],
            )
        except asyncio.TimeoutError:
            log.warning("❓ 매니저: Claude 응답이 늦어서 끊었어요.")
            return None
        except Exception:  # noqa: BLE001
            log.warning("❓ 매니저: Claude 호출 실패", exc_info=True)
            return None

        if message.stop_reason == "refusal":
            log.info("❓ 매니저: Claude가 답변을 거절했어요.")
            return None

        parts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
        answer = "\n".join(parts).strip()
        if not answer:
            return None

        usage = message.usage
        log.info(
            "❓ 매니저 Claude 응답 (입력 %s · 캐시읽기 %s · 출력 %s)",
            usage.input_tokens,
            getattr(usage, "cache_read_input_tokens", 0),
            usage.output_tokens,
        )
        return answer

    async def answer(self, question: str, user_id: int) -> tuple[discord.Embed, bool]:
        """(보낼 임베드, Claude를 썼나). 규칙 → Claude → 폴백 순이에요."""
        question = question.strip()
        topic, related = faq_knowledge.search(question)

        # ⒜ 규칙으로 또렷하면 거기서 끝. 돈이 안 들어요.
        if topic is not None:
            return self._rule_embed(topic), False

        # ⒝ 쿨다운 — 같은 사람이 연달아 긁는 걸 막아요.
        now = time.monotonic()
        last = self._last_call.get(user_id, 0.0)
        if now - last < USER_COOLDOWN:
            return self._miss_embed(
                related,
                f"잠깐만요, {USER_COOLDOWN:.0f}초쯤 뒤에 다시 물어봐 주세요. "
                "(연달아 물으면 비용이 커져서 조금 쉬어요)",
            ), False

        # ⒞ 하루 한도 — 자리를 **먼저** 잡아요(부른 뒤에 세면 한도를 넘겨요).
        allowed, reason = await assistant_store.take(user_id)
        if not allowed:
            note = (
                "오늘 제가 답할 수 있는 양을 다 썼어요. 내일 다시 물어봐 주세요."
                if reason == "guild"
                else f"오늘 하루 {assistant_store.PER_USER_DAILY}번까지만 답할 수 있어요. "
                "아래에서 찾아보거나 내일 다시 물어봐 주세요."
            )
            return self._miss_embed(related, note), False

        self._last_call[user_id] = now
        answer = await self._ask_claude(question)

        if answer is None:
            await assistant_store.refund(user_id)  # 돈이 안 나갔으니 한도도 돌려줘요
            return self._miss_embed(
                related,
                "지금은 제가 답을 만들지 못했어요. 아래에서 찾아보시거나 매니저에게 물어봐 주세요.",
            ), False

        embed = discord.Embed(
            description=f"{answer}\n\n{AI_FOOTER}",
            color=AI_COLOR,
        )
        return embed, True

    # ── 전용 채널 듣기 ───────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not _is_enabled_for_messages():
            return
        if message.author.bot or message.guild is None:
            return
        if message.content is None:
            return

        channel_id = self._assistant_channel_id()
        if channel_id is None:
            return  # 아직 `/채널설정 봇 매니저`를 안 했어요 → 아무 데서도 안 들어요

        # 그 채널 안의 스레드도 허용해요(다른 명령어의 채널 제한과 같은 규칙이에요).
        parent_id = getattr(message.channel, "parent_id", None)
        if message.channel.id != channel_id and parent_id != channel_id:
            return

        question = message.content.strip()
        if len(question) < MIN_QUESTION_LEN:
            return
        if len(question) > MAX_QUESTION_LEN:
            await message.reply(
                f"질문이 너무 길어요. {MAX_QUESTION_LEN}자 안쪽으로 줄여서 다시 물어봐 주세요.",
                mention_author=False,
            )
            return

        async with message.channel.typing():
            embed, _used_ai = await self.answer(question, message.author.id)
        await message.reply(embed=embed, mention_author=False)

    # ── 명령어 (인텐트 없이도 되는 쪽) ───────────────────────────────────
    @app_commands.command(
        name="도움",
        description="봇 쓰는 법을 물어보세요. (예: 코인 어떻게 모아?)",
    )
    @app_commands.describe(질문="궁금한 점을 그냥 한국어로 적어주세요.")
    async def help_command(self, interaction: discord.Interaction, 질문: str):
        """🚨 Claude 호출은 3초를 넘길 수 있어서 **먼저 `defer()`로 토큰을 받아둬요.**
        (이 저장소의 상호작용 만료 사고가 전부 이 순서를 어겨서 났어요)"""
        await interaction.response.defer(thinking=True)

        question = 질문.strip()
        if len(question) < MIN_QUESTION_LEN:
            await interaction.followup.send("질문을 조금 더 자세히 적어주세요.", ephemeral=True)
            return
        if len(question) > MAX_QUESTION_LEN:
            await interaction.followup.send(
                f"질문이 너무 길어요. {MAX_QUESTION_LEN}자 안쪽으로 줄여주세요.", ephemeral=True
            )
            return

        embed, _used_ai = await self.answer(question, interaction.user.id)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Assistant(bot))
