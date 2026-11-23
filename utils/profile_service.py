"""악귀 프로필 - 흩어져 있는 기록을 한 사람 분량으로 모아서 카드/임베드에 넘겨줘요.

`utils/profile_card.py`는 **그리기만** 하고 DB를 모르고, 여기는 **모으기만** 하고 그림을
몰라요. 나눠둔 이유는 `/프로필`(카드)과 `/업적`·`/내전전적`(임베드)이 같은 데이터를 쓰는데,
카드 쪽에 DB 조회가 섞여 있으면 임베드만 띄울 때도 Pillow가 끌려 들어오기 때문이에요.

## 모으는 곳

  - 디스코드: 닉네임·아바타·티어 역할
  - `title_store`: 지금 달고 있는 칭호와 색
  - `coin_wallet`: 악귀코인
  - `scrim_record_store`: 내전 승/패/연승
  - `agwi_weekly_store`: 이번 주 악귀력
  - `achievement_store`: 업적 해금 수 (겸 새 업적 판정) · 음성 누적 분 · 낚은 수 · 누적 미션
  - `voice_level` / `fishing_store`: 다음 레벨까지 남은 분 · 최대어 (2026-11-15)

## HenrikDev를 부르지 않아요

카드에 발로란트 정보가 들어가지만 **API 호출은 0회**예요. 티어는 디스코드 역할에서,
악귀력은 `/전적`이 남겨둔 주간 스냅샷에서 읽어요. 카드를 띄울 때마다 API를 부르면
분당 30회 한도(키 하나를 서버 전체가 나눠 씀)가 바로 녹아요.
"""
import logging

import discord

from utils import (
    achievement_store,
    agwi_weekly_store,
    balodle_data,
    balodle_logic,
    balodle_store,
    birthday_store,
    coin_wallet,
    cosmetic_store,
    custom_theme_store,
    fish_data,
    fishing_store,
    riot_account_store,
    scrim_record_store,
    tier_roles,
    title_store,
    voice_level,
)

log = logging.getLogger(__name__)

DEFAULT_ACCENT = (88, 101, 242)  # 디스코드 블러플 - 티어를 모를 때 쓰는 기본색
# 🧩 발로들 칭호 글자 색 (볼트 `악귀봇 디자인` D6). 연속 일수 → 색. 산 칭호의 금색과 구분돼요.
BALODLE_TITLE_COLORS = {7: (110, 220, 170), 30: (180, 140, 255)}


def _tier_info(member: discord.Member | None) -> tuple[str | None, tuple[int, int, int]]:
    """(티어 이름, 악센트 RGB). 티어 역할이 없으면 (None, 기본색)."""
    if member is None:
        return None, DEFAULT_ACCENT

    index = tier_roles.member_tier_index(member)
    if index is None:
        return None, DEFAULT_ACCENT

    name = tier_roles.tier_name_from_index(index)
    # '초월자 2' -> '초월자'. 색은 단계가 아니라 티어 이름으로 정해져 있어요.
    base = name.rsplit(" ", 1)[0] if " " in name else name
    color = tier_roles.TIER_COLOR_MAP.get(base)
    accent = color.to_rgb() if color is not None else DEFAULT_ACCENT
    return name, accent


async def _avatar_bytes(member: discord.abc.User) -> bytes | None:
    """카드에 붙일 아바타를 받아와요. 실패해도 카드는 나와야 해서 조용히 None."""
    try:
        asset = member.display_avatar.replace(size=256, format="png")
        return await asset.read()
    except Exception:
        log.warning("아바타를 받지 못했어요 (user=%s)", member.id, exc_info=True)
        return None


async def collect(member: discord.Member | discord.User, *, evaluate_achievements: bool = True) -> dict:
    """카드/임베드에 필요한 모든 값을 한 dict으로 모아요.

    `evaluate_achievements=True`면 모으는 김에 새 업적도 판정해서 `newly_unlocked`에 담아줘요
    (`/프로필`을 보는 것만으로 밀린 업적이 열리게 하려는 거예요)."""
    guild_member = member if isinstance(member, discord.Member) else None
    tier_name, accent = _tier_info(guild_member)

    # --- 칭호 ---
    title_name = None
    title_color = None
    title_doc = await title_store.get(member.id)
    if title_doc:
        title_name = title_doc.get("name")
        raw_color = title_doc.get("color")
        if isinstance(raw_color, int):
            title_color = ((raw_color >> 16) & 0xFF, (raw_color >> 8) & 0xFF, raw_color & 0xFF)

    # --- 코인 · 내전 · 악귀력 ---
    coin = await coin_wallet.get_balance(member.id)
    record = await scrim_record_store.get_record(member.id)
    weekly = await agwi_weekly_store.get(member.id)

    # --- 발로란트 간략 전적 ---
    # 악귀력 칸은 "이번 주"만 쓰지만, 전적은 마지막으로 조회한 값을 보여줘요(이번 주에 아직
    # `/전적`을 안 돌렸다고 카드에서 전적이 사라지면 허전해서요). 여기서도 API 호출은 0회예요.
    valorant_doc = weekly if (weekly or {}).get("stats") else await agwi_weekly_store.latest(member.id)
    valorant = (valorant_doc or {}).get("stats")

    # --- 업적 (판정 겸 집계) ---
    riot_linked = riot_account_store.get_account(member.id) is not None
    birthday_set = bool(await birthday_store.get_birthday(member.id))
    stats = await achievement_store.collect_stats(
        member.id,
        tier_index=tier_roles.member_tier_index(guild_member) if guild_member else None,
        riot_linked=riot_linked,
        birthday_set=birthday_set,
    )
    newly = await achievement_store.evaluate(member.id, stats) if evaluate_achievements else []
    summary = await achievement_store.summary(member.id, stats)

    # 업적 보상 코인이 방금 들어왔으면 카드에도 반영돼야 자연스러워요.
    if newly:
        coin += sum(a["reward"] for a in newly)

    # --- 🎙️ 음성 레벨 · 🎣 낚시 (2026-11-15 카드 2번째 줄) ---
    # 레벨·누적 분·낚은 수는 업적 판정용 `stats`에 이미 있어요(같은 값이 두 군데서 따로
    # 계산되면 카드와 업적이 어긋나요). 다음 레벨까지 남은 분과 최대어만 여기서 더 구해요.
    v_level, v_done, v_need = voice_level.progress(stats.get("voice_minutes", 0))
    best_fish = None
    try:
        best = (await fishing_store.get(member.id)).get("best") or {}
        if best.get("key") in fish_data.BY_KEY:
            grade, fname = fish_data.BY_KEY[best["key"]]
            best_fish = {"name": fname, "grade": grade, "size": best.get("size")}
    except Exception:  # noqa: BLE001 — 최대어 한 줄 때문에 카드가 죽으면 안 돼요
        log.warning("최대어 조회 실패 (user=%s)", member.id, exc_info=True)

    # --- 🧩 발로들 연속·칭호 (2026-11-24) ---
    # 연속은 카드 오른쪽 위 배지로 나와요(0이면 숨겨요). 칭호는 **산 칭호가 없을 때만** 칭호 자리에
    # 보여줘요 — 산 칭호(`title_store`)를 덮지 않아요.
    balodle_streak, balodle_title = 0, None
    try:
        b_user = await balodle_store.get_user(member.id)
        balodle_streak = balodle_logic.live_streak(
            int(b_user.get("streak", 0) or 0), b_user.get("last_solved_day"),
            balodle_logic.today_iso())
        b_titles = balodle_data.SETTINGS.get("titles") or {}
        balodle_title = balodle_logic.top_title(b_user.get("titles"), b_titles)
        if balodle_title and not title_name:
            title_name = balodle_title
            title_color = BALODLE_TITLE_COLORS.get(
                balodle_logic.title_days(balodle_title, b_titles))
    except Exception:  # noqa: BLE001 — 발로들 한 줄 때문에 카드가 죽으면 안 돼요
        log.warning("발로들 기록 조회 실패 (user=%s)", member.id, exc_info=True)

    # --- 🖼️ 커스텀 테마 그림 (고른 사람만 DB에서 꺼내요 — ~100KB라 아무나 꺼내면 낭비) ---
    theme = await cosmetic_store.selected_theme(member.id)
    custom_art = (await custom_theme_store.approved_art(member.id)
                  if theme == custom_theme_store.THEME_KEY else None)

    total_games = record["wins"] + record["losses"]
    return {
        "name": member.display_name,
        "title": title_name,
        "title_color": title_color,
        "tier": tier_name,
        "accent_color": accent,
        # 카드 배경 테마 (`/악귀상점`에서 사서 고른 것). 모르는 이름이면 카드가 기본으로 그려요.
        "theme": theme,
        "custom_art": custom_art,
        "coin": coin,
        "record": {
            "wins": record["wins"],
            "losses": record["losses"],
            "best_streak": record.get("bestStreak", 0),
            "win_rate": scrim_record_store.win_rate(record) or 0,
        },
        "streak_now": scrim_record_store.streak_text(record) if total_games else "",
        "agwi": weekly.get("score") if weekly else None,
        "agwi_grade": (weekly.get("grade") or "") if weekly else "",
        "achievements": summary["unlocked"],
        "achievements_total": summary["total"],
        "attendance": stats["attendance"],
        "attendance_streak": stats["attendance_streak"],
        "voice": {
            "level": v_level, "minutes": stats.get("voice_minutes", 0),
            "into": v_done, "need": v_need,
        },
        "fishing": {"caught": stats.get("fish_caught", 0), "best": best_fish},
        "mission_total": stats.get("mission_total", 0),
        # 🧩 발로들 — 지금 살아 있는 연속(0이면 배지를 안 그려요)과 얻은 칭호 중 가장 높은 것
        "balodle_streak": balodle_streak,
        "balodle_title": balodle_title,
        "season": scrim_record_store.current_season(),
        # 발로란트 간략 전적 (없으면 None → 카드에서 그 줄을 통째로 빼요)
        "valorant": valorant,
        # 화면 쪽에서 쓰는 부가 정보
        "newly_unlocked": newly,
        "stats": stats,
        "riot_id": (valorant_doc or weekly or {}).get("riotId"),
    }


async def avatar_for(member: discord.abc.User) -> bytes | None:
    return await _avatar_bytes(member)
