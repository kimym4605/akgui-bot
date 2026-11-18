"""🛡️ 해킹 계정 스팸 차단 — 사이트 주소를 뿌리는 광고를 지우고, 계정을 잠시 묶고, 운영진에게 알려요.

판정 규칙은 `utils/spam_guard.py` 머리말에 있어요. 여기는 "걸린 뒤에 무엇을 하나"예요.

## 걸리면

1. **그 사람의 최근 90초 게시물 중 링크/첨부/같은 내용인 것을 전부 지워요** (여러 채널에 뿌린 것까지)
2. **타임아웃** (기본 24시간, `ANTISPAM_TIMEOUT_HOURS`). 추방·차단은 안 해요 —
   털린 계정의 주인은 피해자라서, 계정을 되찾으면 운영진이 타임아웃만 풀어주면 돼요.
3. 본인에게 DM: 계정이 털린 것 같으니 비밀번호 바꾸고 2단계 인증을 켜라고 안내
4. 🛡️ 방장-매니저 채널에 알림 (내용은 링크가 눌리지 않게 바꿔서)
5. 10분간 "격리": 타임아웃이 안 걸린 경우(관리자 계정 등)에도 링크/첨부 글은 바로 지워요

## 🚨 운영진도 검사해요

털린 계정이 운영진이면 피해가 제일 커요. 다만 **약한 신호**(링크 + 미끼 단어)로는 운영진을
잡지 않아요 — 운영진은 이벤트 공지에 "선착순·당첨" 같은 말을 링크와 같이 쓸 수 있어요.
**강한 신호**(여러 채널 도배, 위장 링크)는 운영진도 잡아요. 관리자 권한 계정은 디스코드가
타임아웃을 막아서 지우기 + 알림만 돼요.

⚠️ 메시지 내용 읽기(MESSAGE CONTENT 인텐트)가 꺼져 있으면 이 cog는 아무것도 못 봐요.
`bot.py`의 `ASSISTANT_READ_MESSAGES` 주석 참고.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import timedelta

import discord
from discord.ext import commands

from utils import spam_guard
from utils.spam_guard import Post, PostTracker, Verdict
from utils.staff_check import is_staff

log = logging.getLogger(__name__)

# 🛡️｜방장-매니저 (2026-11-08 기준). 바꾸려면 Fly secret으로 덮어써요.
DEFAULT_ALERT_CHANNEL_ID = 1495602706847502387
TIMEOUT_HOURS = float(os.getenv("ANTISPAM_TIMEOUT_HOURS", "24"))
QUARANTINE_SECONDS = 600.0


def _alert_channel_id() -> int:
    raw = os.getenv("ANTISPAM_ALERT_CHANNEL_ID", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_ALERT_CHANNEL_ID


DM_TEXT = (
    "🛡️ **겜악귀들의 천국** 자동 보안 알림이에요.\n\n"
    "방금 회원님 계정으로 **광고/사기 링크가 여러 채널에 올라와서** 자동으로 지우고 "
    "계정을 잠시 타임아웃했어요. 계정이 해킹됐을 가능성이 높아요.\n\n"
    "**지금 바로 해주세요**\n"
    "1. 디스코드 비밀번호 변경 (사용자 설정 → 내 계정)\n"
    "2. **2단계 인증(2FA) 켜기**\n"
    "3. 사용자 설정 → 기기 에서 모르는 기기 로그아웃\n"
    "4. 최근 받은 링크·파일·QR코드로 로그인한 적 있으면 그 PC를 백신으로 검사\n\n"
    "정리되면 운영진에게 말해주시면 타임아웃을 풀어드릴게요."
)


class AntiSpam(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tracker = PostTracker()
        self._quarantine: dict[int, float] = {}   # user_id → 격리 끝나는 monotonic 시각

    # ── 감지 ─────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.bot.intents.message_content:
            return
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        author = message.author
        if not isinstance(author, discord.Member):
            return

        now = time.monotonic()
        text = message.content or ""
        attachments = [(a.filename, a.size) for a in message.attachments]
        has_payload = bool(attachments) or bool(spam_guard.find_links(text))

        # 이미 걸린 사람: 남은 도배는 판정 없이 바로 지워요.
        until = self._quarantine.get(author.id)
        if until and now < until:
            if has_payload:
                await self._delete(message.channel.id, message.id)
            return

        post = Post(
            at=now, channel_id=message.channel.id, message_id=message.id,
            fingerprint=PostTracker.fingerprint(text, attachments), has_payload=has_payload,
        )
        verdict = self.tracker.add(author.id, post)
        if verdict is None:
            verdict = spam_guard.judge_content(text, message.mention_everyone)
        if verdict is None:
            return
        if not verdict.strong and is_staff(author):
            log.info("🛡️ 운영진이라 약한 신호는 넘겨요: user=%s 사유=%s", author, verdict.reason)
            return

        await self._punish(message, verdict, post)

    # ── 조치 ─────────────────────────────────────────────────────────
    async def _delete(self, channel_id: int, message_id: int) -> bool:
        channel = self.bot.get_channel(channel_id)
        if channel is None or not hasattr(channel, "get_partial_message"):
            return False
        try:
            await channel.get_partial_message(message_id).delete()
            return True
        except discord.NotFound:
            return True          # 이미 지워졌어요(디스코드 AutoMod나 본인이)
        except discord.HTTPException as e:
            log.warning("🛡️ 메시지 삭제 실패 ch=%s msg=%s: %s", channel_id, message_id, e)
            return False

    async def _punish(self, message: discord.Message, verdict: Verdict, trigger: Post):
        member: discord.Member = message.author  # type: ignore[assignment]
        guild = message.guild
        self._quarantine[member.id] = time.monotonic() + QUARANTINE_SECONDS

        # 1) 지우기 — 지금 글 + 최근 90초의 링크/첨부/같은 내용 글
        targets = [p for p in self.tracker.recent(member.id)
                   if p.has_payload or p.fingerprint == trigger.fingerprint]
        if all(p.message_id != message.id for p in targets):
            targets.append(trigger)
        deleted, channels = 0, set()
        for p in targets:
            if await self._delete(p.channel_id, p.message_id):
                deleted += 1
                channels.add(p.channel_id)
        self.tracker.forget(member.id)

        # 2) 타임아웃
        timeout_note = await self._timeout(member, verdict)

        # 3) 본인 DM
        try:
            await member.send(DM_TEXT)
            dm_note = "보냄"
        except discord.HTTPException:
            dm_note = "실패(DM 막힘)"

        log.warning("🛡️ 스팸 차단: user=%s(%s) 사유=%s 삭제=%d 채널=%d 타임아웃=%s",
                    member, member.id, verdict.reason, deleted, len(channels), timeout_note)

        # 4) 운영진 알림
        await self._alert(guild, member, verdict, message, deleted, channels, timeout_note, dm_note)

    async def _timeout(self, member: discord.Member, verdict: Verdict) -> str:
        me = member.guild.me
        if member.id == member.guild.owner_id or member.guild_permissions.administrator:
            return "불가(관리자 계정 — 디스코드가 막아요)"
        if me is None or member.top_role >= me.top_role:
            return "불가(봇 역할보다 높은 역할)"
        try:
            await member.timeout(timedelta(hours=TIMEOUT_HOURS),
                                 reason=f"자동 스팸 차단: {verdict.reason}")
            return f"{TIMEOUT_HOURS:g}시간"
        except discord.HTTPException as e:
            log.warning("🛡️ 타임아웃 실패 user=%s: %s", member, e)
            return f"실패({e.status})"

    async def _alert(self, guild, member, verdict, message, deleted, channels, timeout_note, dm_note):
        channel = guild.get_channel(_alert_channel_id())
        if channel is None:
            log.warning("🛡️ 알림 채널(%s)을 못 찾았어요.", _alert_channel_id())
            return
        embed = discord.Embed(
            title="🛡️ 스팸 자동 차단",
            description=f"{member.mention} (`{member.id}`)\n**사유**: {verdict.reason}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="삭제", value=f"{deleted}개 · {len(channels)}개 채널", inline=True)
        embed.add_field(name="타임아웃", value=timeout_note, inline=True)
        embed.add_field(name="본인 DM", value=dm_note, inline=True)
        if channels:
            embed.add_field(name="채널", value=" ".join(f"<#{c}>" for c in sorted(channels))[:1000],
                            inline=False)
        preview = spam_guard.defang(message.content) or "(글 없음)"
        if message.attachments:
            preview += f"\n📎 첨부 {len(message.attachments)}개: " + ", ".join(
                spam_guard.defang(a.filename, 60) for a in message.attachments[:5])
        embed.add_field(name="내용 (링크 무력화)", value=f"```{preview[:1000]}```", inline=False)
        embed.set_footer(text="오탐이면: 멤버 우클릭 → 타임아웃 해제. 계정 되찾은 뒤 풀어주세요.")
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            log.warning("🛡️ 운영진 알림 전송 실패: %s", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiSpam(bot))
