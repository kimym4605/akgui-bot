"""🛡️ 해킹 계정 스팸 판정 (순수 함수 — 디스코드에 접속하지 않아요).

## 왜 만들었나

2026-11 서버 멤버 계정이 털려서 "미스터 비스트 기프트" 같은 광고가 사이트 주소와 함께
여러 채널에 뿌려졌어요. 털린 계정 스팸은 모양이 거의 같아요.

1. **같은 내용을 짧은 시간에 여러 채널에** 올린다 (사람은 이렇게 안 해요)
2. **링크 + 미끼 단어**(무료 니트로·스팀 기프트·미스터비스트·카지노·$숫자 ...)
3. 링크 글자와 실제 주소가 다른 **위장 링크** (`[discord.com](https://수상한주소)`)

여기서는 "스팸인가"만 판정하고, 지우기·타임아웃·알림은 `cogs/anti_spam.py`가 해요.
판정을 떼어 둔 이유: `scripts/test_spam_guard.py`가 디스코드 없이 오탐/미탐을 검사해요.

## 🚨 오탐을 줄이려고 지킨 것

- **링크만 있다고 잡지 않아요.** 유튜브·트래커 링크는 매일 올라와요.
- **미끼 단어만 있다고 잡지 않아요.** "카지노"·"이벤트"는 서버 안 기능 이름이에요(/도박).
- 여러 채널 연속 게시는 **3개 채널 이상**이어야 해요. 두 곳에 같은 질문 올리는 사람은 있어요.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field

# ── 판정 기준값 ──────────────────────────────────────────────────────
WINDOW_SECONDS = 90.0          # 이 시간 안의 게시물끼리 비교해요
SAME_CONTENT_CHANNELS = 3      # 같은 내용이 이만큼 서로 다른 채널에 → 스팸
PAYLOAD_CHANNELS = 4           # 내용이 달라도 링크/첨부를 이만큼 다른 채널에 → 스팸
MAX_TRACK_PER_USER = 30        # 한 사람당 기억할 최근 게시물 수(메모리 상한)

# 보이지 않는 글자(제로폭 공백 등)로 단어를 쪼개 필터를 피하는 수법이 흔해요.
_INVISIBLE = re.compile(r"[​-‏⁠-⁤﻿­͏᠎]")

_URL = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|\b(?:discord(?:app)?\.(?:gg|com/invite)|dsc\.gg)/\S+"
    # 프로토콜 없이 도메인만 적는 경우 (steamcommunlty.com/gift 등)
    r"|\b[a-z0-9][a-z0-9-]{1,62}\.(?:com|net|org|gg|ru|xyz|io|me|link|ly|site|online|shop"
    r"|top|click|live|app|co|cc|info|pro|fun|store|icu|vip|bet|win|gift|club)\b(?:/\S*)?",
    re.IGNORECASE,
)

# [보이는 글자](실제 주소) — 보이는 글자가 도메인처럼 생겼는데 실제 주소와 다르면 위장이에요.
_MASKED = re.compile(r"\[([^\]]{1,200})\]\(\s*<?(https?://[^)\s>]+)>?\s*\)", re.IGNORECASE)
_DOMAIN_IN_TEXT = re.compile(r"([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.IGNORECASE)

# 미끼 단어. **링크와 같이 있을 때만** 의미가 있어요(위 머리말 참고).
# 띄어쓰기·점을 지운 뒤 비교하므로 "mr. beast" "미스터 비스트"도 잡혀요.
SCAM_WORDS = (
    "mrbeast", "미스터비스트",
    "freenitro", "nitrofree", "무료니트로", "무료나이트로", "니트로무료", "나이트로무료",
    "steamgift", "스팀기프트", "스팀선물", "giftcard", "기프트카드", "상품권",
    "giveaway", "기브어웨이", "airdrop", "에어드랍", "에어드롭",
    "crypto", "bitcoin", "btc", "usdt", "ethereum", "코인지급", "코인증정",
    "casino", "카지노", "promocode", "bonuscode", "프로모코드", "보너스코드",
    # ⚠️ "유출"·"leaked"는 뺐어요 — 게임 패치 유출 기사 링크가 실제로 자주 올라와요.
    "withdraw", "출금", "onlyfans", "nudes", "18+",
    "claimnow", "claimyour", "지금받기", "선착순", "당첨",
)
_DOLLAR = re.compile(r"\$\s?\d{2,}|\d{2,}\s?(?:\$|usd|달러)", re.IGNORECASE)


def normalize(text: str) -> str:
    """전각/특수 글꼴을 보통 글자로, 보이지 않는 글자는 지우고, 소문자로."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _INVISIBLE.sub("", text)
    return text.lower()


def find_links(text: str) -> list[str]:
    return _URL.findall(normalize(text))


def _squash(text: str) -> str:
    return re.sub(r"[\s.\-_·]+", "", text)


def scam_words_in(text: str) -> list[str]:
    squashed = _squash(normalize(text))
    hits = [w for w in SCAM_WORDS if w in squashed]
    if _DOLLAR.search(normalize(text)):
        hits.append("$금액")
    return sorted(set(hits))


def _host(url: str) -> str:
    host = re.sub(r"^https?://", "", url.lower()).split("/")[0].split("?")[0]
    return host[4:] if host.startswith("www.") else host


def masked_link_mismatch(text: str) -> str | None:
    """`[discord.com](https://딴곳)` 처럼 보이는 주소와 실제 주소가 다르면 그 쌍을 돌려줘요."""
    for label, url in _MASKED.findall(normalize(text)):
        shown = _DOMAIN_IN_TEXT.search(label)
        if not shown:
            continue
        shown_host = _host(shown.group(1))
        real = _host(url)
        if shown_host and real and not (real == shown_host or real.endswith("." + shown_host)):
            return f"{shown_host} → {real}"
    return None


@dataclass
class Verdict:
    reason: str          # 사람에게 보여줄 사유 한 줄
    strong: bool         # 운영진 계정이어도 조치할 만큼 확실한가


def judge_content(text: str, mentions_everyone: bool = False) -> Verdict | None:
    """메시지 한 개만 보고 내리는 판정. (여러 채널 연속 게시는 `PostTracker`가 봐요)"""
    links = find_links(text)
    mismatch = masked_link_mismatch(text)
    if mismatch:
        return Verdict(f"위장 링크 ({mismatch})", strong=True)
    if not links:
        return None
    words = scam_words_in(text)
    if words:
        return Verdict(f"링크 + 미끼 단어 ({', '.join(words[:4])})", strong=False)
    # 일반 멤버는 @everyone이 실제로 울리진 않지만, 털린 계정은 습관처럼 붙여요.
    if mentions_everyone or "@everyone" in text or "@here" in text:
        return Verdict("링크 + @everyone/@here", strong=False)
    return None


# ── 여러 채널 연속 게시 추적 ─────────────────────────────────────────
@dataclass
class Post:
    at: float
    channel_id: int
    message_id: int
    fingerprint: str
    has_payload: bool    # 링크나 첨부가 있나


@dataclass
class PostTracker:
    """사람별 최근 게시물을 메모리에 들고 있다가 "여러 채널 도배"를 알아봐요.

    재시작하면 비워져요 — 도배는 몇십 초 안에 벌어지는 일이라 저장할 필요가 없어요."""
    _posts: dict[int, deque] = field(default_factory=dict)

    @staticmethod
    def fingerprint(text: str, attachments: list[tuple[str, int]]) -> str:
        body = re.sub(r"\s+", " ", normalize(text)).strip()
        files = "|".join(f"{n.lower()}:{s}" for n, s in sorted(attachments))
        return f"{body}#{files}" if (body or files) else ""

    def _prune(self, user_id: int, now: float) -> deque:
        q = self._posts.setdefault(user_id, deque(maxlen=MAX_TRACK_PER_USER))
        while q and now - q[0].at > WINDOW_SECONDS:
            q.popleft()
        return q

    def add(self, user_id: int, post: Post) -> Verdict | None:
        q = self._prune(user_id, post.at)
        q.append(post)
        # 다른 사람들 몫도 가끔 비워서 메모리가 늘어나지 않게 해요.
        if len(self._posts) > 500:
            for uid in [u for u, d in self._posts.items() if not d or post.at - d[-1].at > WINDOW_SECONDS]:
                self._posts.pop(uid, None)

        if post.fingerprint:
            same = {p.channel_id for p in q if p.fingerprint == post.fingerprint}
            if len(same) >= SAME_CONTENT_CHANNELS:
                return Verdict(f"같은 내용을 {len(same)}개 채널에 연속 게시", strong=True)
        payload = {p.channel_id for p in q if p.has_payload}
        if post.has_payload and len(payload) >= PAYLOAD_CHANNELS:
            return Verdict(f"링크/첨부를 {len(payload)}개 채널에 연속 게시", strong=True)
        return None

    def recent(self, user_id: int, now: float | None = None) -> list[Post]:
        now = time.monotonic() if now is None else now
        return list(self._prune(user_id, now))

    def forget(self, user_id: int) -> None:
        self._posts.pop(user_id, None)


def defang(text: str, limit: int = 900) -> str:
    """운영진 알림에 내용을 그대로 붙이면 링크가 눌려요. 눌리지 않게 바꿔서 보여줘요."""
    text = (text or "").replace("http", "hxxp").replace("discord.gg", "discord[.]gg")
    text = re.sub(r"\.(com|net|org|gg|ru|xyz|io|me|link|ly|site|shop|top|app|co)\b", r"[.]\1", text)
    text = text.replace("@everyone", "@​everyone").replace("@here", "@​here")
    text = text.replace("`", "ˋ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
