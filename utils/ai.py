"""🤖 Claude 호출을 한 곳으로 모아요. 여러 기능이 같은 클라이언트·캐시·안전장치를 써요.

## 왜 모았나 (2026-10-18)

처음엔 `cogs/assistant.py` 안에 클라이언트가 갇혀 있었어요. 거기에 전적 코칭·주간랭킹
해설·운영 리포트가 붙으면서, 기능마다 "키 확인 → 호출 → 실패하면 폴백"을 복제하게 됐어요.
그러면 한 곳만 고치고 나머지를 빠뜨리는 사고가 나요(이 저장소에서 반복된 패턴이에요).

## 🚨 AI가 없어도 봇은 그대로 돌아야 해요

`ANTHROPIC_API_KEY`가 없든, 패키지가 없든, 크레딧이 떨어졌든, API가 느리든 —
`ask()`는 **None을 돌려줄 뿐 절대 예외를 올리지 않아요.** 부른 쪽은 None이면 AI 부분만
빼고 평소 화면을 보여줘요. 실제로 10-18에 크레딧이 0이라 400이 떴는데, 그때도
`/도움`은 규칙 답변으로 멀쩡히 동작했어요. 그 성질을 여기서 보장해요.

## 💰 캐시가 비용을 결정해요

`/전적`처럼 자주 불리는 자리는 **같은 입력이면 같은 답**이에요. 새 경기가 없으면
조언도 같으니 다시 물어볼 이유가 없어요. `cache_key`를 주면 Atlas에 저장해두고
그대로 돌려줘요(= 호출 0원). 키에 **데이터 지문**을 넣는 게 요령이에요 —
경기 수나 KD가 바뀌면 키가 바뀌어서 저절로 새로 물어봐요.

⚠️ 프롬프트 캐싱(`cache_control`)과는 다른 얘기예요. 그건 Anthropic 쪽에서 **입력값**을
깎아주는 거고(5분 TTL), 이건 **호출 자체**를 안 하는 거예요. 둘 다 써요.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

_cache = _db["ai_cache"]

KST = timezone(timedelta(hours=9))

# 사용자가 고른 모델이에요(2026-10-18). 기능별로 바꾸고 싶으면 `model=`로 넘기세요.
DEFAULT_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5")
DEFAULT_TIMEOUT = 25.0

_client = None
_client_ready = False


def get_client():
    """없으면 None. **없다고 예외를 내지 않아요** — 부른 쪽이 AI만 빼고 진행해요."""
    global _client, _client_ready
    if _client_ready:
        return _client
    _client_ready = True

    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("🤖 ANTHROPIC_API_KEY가 없어요 — AI 기능은 건너뛰어요.")
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("🤖 anthropic 패키지가 없어요 — AI 기능은 건너뛰어요.")
        return None

    _client = AsyncAnthropic(timeout=DEFAULT_TIMEOUT, max_retries=1)
    log.info("🤖 Claude 준비됐어요 (기본 모델 %s).", DEFAULT_MODEL)
    return _client


def fingerprint(*parts) -> str:
    """캐시 키용 지문. 값이 하나라도 바뀌면 다른 키가 돼요."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _cache_get_sync(key: str, max_age_hours: float | None) -> str | None:
    doc = _cache.find_one({"_id": key})
    if not doc:
        return None
    if max_age_hours is not None:
        at = doc.get("at")
        if at is None:
            return None
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - at > timedelta(hours=max_age_hours):
            return None
    return doc.get("text")


def _cache_put_sync(key: str, text: str, feature: str) -> None:
    _cache.update_one(
        {"_id": key},
        {"$set": {"text": text, "at": datetime.now(timezone.utc), "feature": feature}},
        upsert=True,
    )


async def ask(
    system: str,
    user: str,
    *,
    feature: str,
    max_tokens: int = 500,
    model: str | None = None,
    cache_key: str | None = None,
    cache_hours: float | None = 72.0,
) -> str | None:
    """Claude에게 묻고 텍스트를 돌려줘요. **어떤 이유로든 안 되면 None이에요.**

    `feature`는 로그·캐시에 남는 꼬리표예요("전적코칭" 같은 것). 나중에 어떤 기능이
    얼마나 쓰는지 `ai_cache`에서 세어볼 수 있어요.

    `cache_key`를 주면 같은 키의 답을 재사용해요(호출 0원). 키에는 **입력 데이터의
    지문**을 넣으세요 — `fingerprint()`를 쓰면 돼요.
    """
    if cache_key:
        try:
            hit = await asyncio.to_thread(_cache_get_sync, cache_key, cache_hours)
        except Exception:  # noqa: BLE001
            hit = None  # 캐시가 삐끗해도 그냥 새로 물어보면 돼요
        if hit:
            log.info("🤖 [%s] 캐시 적중 (호출 안 함)", feature)
            return hit

    client = get_client()
    if client is None:
        return None

    try:
        message = await client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    # 같은 시스템 프롬프트가 연달아 쓰이면 입력값을 깎아줘요.
                    # ⚠️ Haiku 4.5는 4096토큰 미만이면 **조용히** 캐시가 안 걸려요
                    #    (에러가 아니라 그냥 할인이 없어요).
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
    except asyncio.TimeoutError:
        log.warning("🤖 [%s] 응답이 늦어 끊었어요", feature)
        return None
    except Exception:  # noqa: BLE001
        # 🚨 크레딧 부족(400)·레이트리밋(429)·네트워크 전부 여기로 와요.
        #    기능이 죽으면 안 되니 **반드시 삼키고 None**이에요.
        log.warning("🤖 [%s] 호출 실패", feature, exc_info=True)
        return None

    if message.stop_reason == "refusal":
        log.info("🤖 [%s] 답변이 거절됐어요", feature)
        return None

    text = "\n".join(
        b.text for b in message.content if getattr(b, "type", None) == "text"
    ).strip()
    if not text:
        return None

    u = message.usage
    # ⚠️ `input_tokens`는 **캐시되지 않은 입력**만 세요. 프롬프트 캐싱이 걸리면 이 값이
    #    작게 나오는데, 그건 정상이고 깎인 몫은 cache_creation/cache_read에 있어요.
    log.info(
        "🤖 [%s] 응답 (입력 %s · 캐시생성 %s · 캐시읽기 %s · 출력 %s)",
        feature,
        u.input_tokens,
        getattr(u, "cache_creation_input_tokens", 0),
        getattr(u, "cache_read_input_tokens", 0),
        u.output_tokens,
    )

    if cache_key:
        try:
            await asyncio.to_thread(_cache_put_sync, cache_key, text, feature)
        except Exception:  # noqa: BLE001
            log.warning("🤖 [%s] 캐시 저장 실패 (답변은 그대로 써요)", feature)

    return text


async def usage_by_feature() -> dict[str, int]:
    """`ai_cache`에 쌓인 기능별 건수. 실사용 확인용이에요."""

    def _sync():
        out: dict[str, int] = {}
        for row in _cache.aggregate([
            {"$group": {"_id": "$feature", "n": {"$sum": 1}}},
        ]):
            out[row["_id"] or "?"] = row["n"]
        return out

    try:
        return await asyncio.to_thread(_sync)
    except Exception:  # noqa: BLE001
        return {}
