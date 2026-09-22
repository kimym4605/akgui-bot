"""
"내 계정의 개인 오늘의 상점"(로그인 필요, 4개 로테이션)을 보여주는 기능이에요.

⚠️⚠️ 중요 ⚠️⚠️
처음엔 봇이 직접 아이디/비밀번호를 받아 라이엇 로그인을 흉내내는 방식으로 만들었는데,
라이엇 로그인 폼이 클라우드플레어 봇 탐지 + hCaptcha로 보호되어 있어서 자동화된 로그인
시도는 자격증명이 맞아도 항상 거부당했어요(2026-08-27 확인). 이 보호를 우회하는 자동화는
하지 않기로 했어요.

그래서 지금은: 유저가 실제 브라우저에서 라이엇 공식 로그인 페이지를 직접 열어 로그인
(hCaptcha도 본인이 직접 통과)하고, 로그인 후 나오는 주소창 URL을 복사해서 붙여넣으면
그 URL 안의 토큰만 꺼내 써요. 비밀번호는 이 봇 서버에 전혀 남지 않아요.
매번 로그인하는 게 번거로운 유저를 위해, 선택적으로 세션 쿠키(ssid)를 직접 복사해서
등록해두면 당분간(쿠키 자체 만료 전까지, 대략 한 달 정도) 로그인 없이 바로 /오상을
쓸 수 있어요. 이 쿠키는 utils/riot_session_store.py에서 암호화해서 저장해요.

보여주는 것:
  🔫 오늘의 상점(스킨 4종) + 보유 재화(VP/RP/CD) — 기본 화면
  🎀 장식상점(건버디/스프레이/카드/칭호) · 🌙 야시장(열렸을 때만) · 📦 피처드 번들 — 버튼으로 전환

위시리스트(/위시리스트 추가):
  원하는 스킨을 담아두면, 매일 정해진 시각에 봇이 등록된 유저의 상점을 대신 조회해서
  담아둔 스킨이 떴을 때 DM으로 알려줘요. 대신 조회하려면 세션이 필요해서 **쿠키를
  등록해둔 유저만** 자동 알림 대상이에요.

설정 방법 (.env):
  VALORANT_SHOP_CHANNEL_ID=발로란트-상점_채널ID   ← 없으면 채널 제한 없이 아무 채널에서나 동작해요.
  VALORANT_WISHLIST_CHECK_TIME=09:10             ← 위시리스트 확인 시각(KST). 없으면 09:10이에요.
                                                    상점 로테이션이 바뀐 뒤여야 의미가 있어요.
"""
import logging
import asyncio
import datetime
import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.channel_check import restrict_to_channel
from utils import (
    atomic_json,
    riot_auth,
    riot_session_store,
    valorant_accessories,
    valorant_skins,
    vp_prices,
    wishlist_store,
)

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


# /오상을 쓸 수 있는 채널은 이제 /채널설정("발로란트 상점")으로 지정해요.
# .env의 VALORANT_SHOP_CHANNEL_ID는 설정이 없을 때만 쓰는 기본값으로 남겨뒀어요.
SHOP_CHANNEL_GROUP = "valorant_shop"
SHOP_CHANNEL_ENV = "VALORANT_SHOP_CHANNEL_ID"


def require_shop_channel():
    """이 데코레이터를 붙인 명령어는 지정한 채널(그 안의 스레드 포함)에서만 쓸 수 있어요.
    설정도 .env도 없으면 제한 없이 아무 채널에서나 동작해요."""
    return restrict_to_channel(SHOP_CHANNEL_GROUP, SHOP_CHANNEL_ENV)


# 발로란트 상점은 매일 자정 전후로 갱신돼요. 그 전에 미리 한 번 등록된 유저 전원의
# 쿠키를 재인증해서 저장해두면(SkinPeek류 봇과 동일한 방식) 쿠키 자체 만료(대략 1~3주) 전에
# 계속 갱신되니까, 한 번 등록만 해두면 사실상 다시 로그인할 일이 없어져요.
SESSION_REFRESH_TIME = datetime.time(hour=4, minute=0, tzinfo=KST)


def _parse_check_time(raw: str | None, default_hour: int, default_minute: int) -> datetime.time:
    """.env의 "HH:MM" 문자열을 KST 시각으로 바꿔요. 값이 없거나 이상하면 기본값을 써요."""
    if raw:
        try:
            hour, minute = (int(part) for part in raw.strip().split(":", 1))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return datetime.time(hour=hour, minute=minute, tzinfo=KST)
        except ValueError:
            log.warning(f"⚠️ VALORANT_WISHLIST_CHECK_TIME 값이 이상해요({raw!r}). 기본값을 쓸게요.")
    return datetime.time(hour=default_hour, minute=default_minute, tzinfo=KST)


# 상점 로테이션이 바뀐 뒤에 돌려야 의미가 있어요. 아시아 서버 기준으로 오전 중에 갱신돼서
# 기본값을 09:10 KST로 뒀고, 서버 지역이 다르면 .env의 VALORANT_WISHLIST_CHECK_TIME으로 바꿔요.
WISHLIST_CHECK_TIME = _parse_check_time(os.getenv("VALORANT_WISHLIST_CHECK_TIME"), 9, 10)


# ── 놓친 재인증 따라잡기 ──────────────────────────────────────────────────────
# `@tasks.loop(time=...)`은 그 시각에 봇이 꺼져 있으면 그날을 그냥 건너뛰어요. 배포·재시작이
# 04시 근처에 걸리면 그날 재인증이 통째로 빠지고, 며칠 연달아 놓치면 등록해둔 쿠키가 순서대로
# 만료돼서 "등록이 자꾸 풀린다"는 신고로 돌아와요. 그래서 마지막으로 성공한 시각을 볼륨에
# 적어두고, 봇이 켜질 때 가장 최근 04시를 넘겼는데 기록이 그보다 옛것이면 한 번 따라잡아요.
_REFRESH_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "myshop_refresh_state.json"


def _last_refresh_at() -> datetime.datetime | None:
    """마지막으로 세션 재인증을 끝낸 시각(KST). 기록이 없거나 깨졌으면 None."""
    try:
        raw = json.loads(_REFRESH_STATE_FILE.read_text(encoding="utf-8")).get("last_refresh")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw).astimezone(KST)
    except (TypeError, ValueError):
        return None


def _mark_refreshed():
    """지금을 마지막 재인증 시각으로 적어둬요. 실패해도 그냥 넘어가요(다음에 또 시도해요)."""
    try:
        atomic_json.write_json(
            _REFRESH_STATE_FILE,
            {"last_refresh": datetime.datetime.now(KST).isoformat()},
        )
    except OSError as error:
        log.warning(f"⚠️ 오상 재인증 시각 기록 실패: {error}")


def _latest_scheduled_refresh(now: datetime.datetime) -> datetime.datetime:
    """`now` 기준으로 가장 최근에 지나간 04:00(KST)이에요."""
    boundary = now.astimezone(KST).replace(
        hour=SESSION_REFRESH_TIME.hour, minute=SESSION_REFRESH_TIME.minute,
        second=0, microsecond=0,
    )
    if boundary > now:
        boundary -= datetime.timedelta(days=1)
    return boundary


def _refresh_is_overdue() -> bool:
    """가장 최근 04:00 이후로 재인증이 한 번도 안 돌았으면 True."""
    last = _last_refresh_at()
    if last is None:
        return True  # 기록이 없는 첫 가동이에요. 한 번 돌려두면 다음부터는 기록이 생겨요.
    return last < _latest_scheduled_refresh(datetime.datetime.now(KST))

# ui_locales=ko를 붙이면 로그인 페이지가 처음부터 한국어로 떠요(안 붙이면 en-US로 시작해요).
LOGIN_URL = (
    "https://auth.riotgames.com/authorize"
    "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
    "&client_id=play-valorant-web-prod"
    "&response_type=token%20id_token"
    "&scope=openid%20account"
    "&nonce=1"
    "&ui_locales=ko"
)

# 로그인 폼이 뜨기도 전에 "오류 발생"만 나온다는 신고가 있었어요(2026-09-01).
# 봇/서버 문제가 아니라(로그인 링크·봇 서버 모두 정상 확인) 유저 기기 쪽에서 라이엇 로그인
# 세션 초기화가 실패하는 케이스라, 안내문에 자가 해결법을 같이 적어둬요.
LOGIN_TROUBLE_TIP = (
    '-# ⚠️ 로그인 창에 **"오류 발생 / 문제가 발생했습니다"**만 뜬다면 (봇 문제가 아니에요)\n'
    "-# ① 디스코드 앱 안에서 열지 말고, 링크를 꾹 눌러 **크롬·사파리 등 외부 브라우저로 열기**\n"
    "-# ② 그래도 안 되면 **시크릿(비공개) 창**에서 열기\n"
    "-# ③ 그래도 안 되면 riotgames.com **쿠키·캐시 삭제** 후 재시도 (PC에서 하면 제일 잘 돼요)"
)

# 위시리스트 알림은 DM으로만 가는데, 서버 DM을 막아둔 유저는 알림이 조용히 사라져요.
# 실패가 서버 로그에만 남으면 본인은 영영 모르니까, 다음에 위시리스트를 열 때 알려줘요.
_DM_BLOCKED_TIP = (
    "-# ⚠️ **DM이 막혀 있어서 알림을 못 보냈어요.** 서버 이름 우클릭 → **개인정보 보호 설정**에서\n"
    "-# \"서버 멤버가 보내는 다이렉트 메시지 허용\"을 켜주세요. (켜면 다음 알림부터 정상으로 가요)"
)

VP_CURRENCY_ID = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"
RP_CURRENCY_ID = "e59aa87c-4cbf-517a-5983-6e81511be9b7"  # 레디어나이트 포인트
KC_CURRENCY_ID = "85ca954a-41f2-ce94-9b45-8ca3dd39a00d"  # 킹덤 크레딧 (표시는 "CD" — Credit)
SKIN_LEVEL_TYPE_ID = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"  # 번들 아이템 타입 판별용


def _format_remaining(seconds: int) -> str:
    seconds = max(0, seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}일 {hours}시간 후 갱신"
    return f"{hours}시간 {minutes}분 후 갱신"


def _first_cost(cost_map: dict | None) -> int:
    """{통화UUID: 가격} 형태에서 가격 하나를 꺼내요. 비어있거나 None이면 0이에요."""
    if not cost_map:
        return 0
    return next(iter(cost_map.values()), 0) or 0


def _format_wallet(wallet: dict | None) -> str:
    """보유 재화를 한 줄로 만들어요. 지갑 조회에 실패했으면 빈 문자열이라 표시에서 빠져요."""
    if not wallet:
        return ""
    balances = wallet.get("Balances") or {}
    vp = balances.get(VP_CURRENCY_ID)
    rp = balances.get(RP_CURRENCY_ID)
    kc = balances.get(KC_CURRENCY_ID)
    if vp is None and rp is None and kc is None:
        return ""

    parts = []
    if vp is not None:
        parts.append(f"💰 {vp:,} VP")
    if rp is not None:
        parts.append(f"🔶 {rp:,} RP")
    if kc is not None:
        parts.append(f"💠 {kc:,} CD")
    return " · ".join(parts)


_DEFAULT_TIER_COLOR = 0x555555


def _vp_balance(wallet: dict | None) -> int | None:
    """지갑에서 VP 잔액만 꺼내요. 지갑 조회에 실패했으면 None이라 VP 계산을 건너뛰어요."""
    if not wallet:
        return None
    return (wallet.get("Balances") or {}).get(VP_CURRENCY_ID)


# 보유 스킨은 /오상을 부를 때만 받아올 수 있어요(라이엇 API 호출이 필요해서요).
# 위시리스트 자동완성처럼 네트워크를 쓸 수 없는 곳에서도 "이미 가진 스킨"을 알려주려고,
# 마지막으로 조회한 결과를 (유저, 계정)별로 메모리에 담아둬요. 봇이 재시작되면 비워지는데,
# 그땐 표시가 안 될 뿐이라 동작에는 지장이 없어요.
# 계정 키가 빈 문자열("")인 건 쿠키를 등록하지 않고 URL 붙여넣기로 한 번만 조회한 경우예요.
_owned_skin_names: dict[tuple[int, str], set[str]] = {}


def _remember_owned(discord_id: int, account_key: str, owned_ids: set[str] | None):
    """보유 스킨 UUID를 이름 집합으로 바꿔서 기억해둬요. 조회 실패(None)면 기존 값을 유지해요."""
    if owned_ids is None:
        return
    names = set()
    for item_id in owned_ids:
        info = valorant_skins.get(item_id)
        if info and info.get("name"):
            names.add(info["name"])
    _owned_skin_names[(discord_id, account_key)] = names


def _owned_names(discord_id: int, account_key: str) -> set[str]:
    return _owned_skin_names.get((discord_id, account_key), set())


def _owned_names_any(discord_id: int) -> set[str]:
    """등록해둔 계정 중 **어느 하나라도** 가지고 있는 스킨 이름들이에요.
    위시리스트 자동완성의 '이미 보유' 표시에 써요. 본계로 가진 스킨을 부계 기준으로
    "없음"이라고 표시하면 오히려 헷갈리거든요."""
    names: set[str] = set()
    for (owner_id, _key), owned in _owned_skin_names.items():
        if owner_id == discord_id:
            names |= owned
    return names


def _forget_owned(discord_id: int, account_key: str | None = None):
    """계정을 지웠을 때 그 계정의 보유 목록도 같이 잊어요. account_key가 None이면 전부."""
    for key in [
        cached_key for cached_key in _owned_skin_names
        if cached_key[0] == discord_id and (account_key is None or cached_key[1] == account_key)
    ]:
        _owned_skin_names.pop(key, None)


def _forget_account_data(discord_id: int, account_key: str | None = None):
    """등록을 해제할 때 메모리에 남은 상점·잔액·보유목록까지 같이 치워요.
    (지웠는데 캐시 때문에 계속 보이면 곤란해요.) account_key가 None이면 그 유저 전부."""
    _invalidate_shop_cache(discord_id, account_key)
    _forget_owned(discord_id, account_key)


def _shop_offers(storefront: dict, owned: set[str] | None = None) -> list[dict]:
    """오늘의 상점 4종을 [{"item_id", "name", "cost", "info", "owned"}]로 뽑아요.
    임베드 구성과 VP 충전 계산이 똑같은 목록을 봐야 해서 여기 한 곳에서만 만들어요."""
    panel = storefront.get("SkinsPanelLayout") or {}
    offers_by_id = {}
    for offer in panel.get("SingleItemStoreOffers") or []:
        for reward in offer.get("Rewards") or []:
            offers_by_id[reward.get("ItemID")] = offer

    result = []
    for item_id in panel.get("SingleItemOffers") or []:
        info = valorant_skins.get(item_id)
        offer = offers_by_id.get(item_id)
        cost = 0
        if offer:
            cost_map = offer.get("Cost") or {}
            cost = cost_map.get(VP_CURRENCY_ID) or _first_cost(cost_map)
        result.append({
            "item_id": item_id,
            "name": info["name"] if info else "알 수 없는 스킨",
            "cost": cost,
            "info": info,
            "owned": bool(owned) and item_id in owned,
        })
    return result


def _need_to_buy(offers: list[dict]) -> list[dict]:
    """아직 안 가진, 가격을 아는 스킨들이에요. 합계·충전 계산은 이것만 대상으로 해요
    (이미 가진 스킨 값까지 더해서 "부족하다"고 하면 잘못된 안내가 되니까요)."""
    return [offer for offer in offers if offer["cost"] and not offer["owned"]]


def _affordability_line(offers: list[dict], balance: int | None) -> str:
    """헤더에 붙는 "합계 / 지금 몇 개 살 수 있는지" 한 줄이에요."""
    owned_count = sum(1 for offer in offers if offer["owned"])
    targets = _need_to_buy(offers)
    owned_note = f" · 🎒 보유 {owned_count}개" if owned_count else ""

    if not targets:
        if owned_count:
            return f"🎒 오늘 뜬 {owned_count}개는 이미 다 갖고 계세요!"
        return ""

    total = sum(offer["cost"] for offer in targets)
    label = "안 가진 " if owned_count else ""
    if balance is None:
        return f"🧮 {label}{len(targets)}종 합계 **{total:,} VP**{owned_note}"

    affordable = sum(1 for offer in targets if offer["cost"] <= balance)
    line = f"🧮 {label}{len(targets)}종 합계 **{total:,} VP** · 지금 **{affordable}개** 구매 가능"
    if total > balance:
        line += f" (전부 사려면 {total - balance:,} VP 부족)"
    return line + owned_note


def _build_shop_embeds(
    user: discord.abc.User,
    storefront: dict,
    riot_id: str = "",
    wallet: dict | None = None,
    owned: set[str] | None = None,
) -> list[discord.Embed]:
    """제트봇 스타일: 헤더 임베드 1개 + 스킨마다 등급색 테두리 임베드(작은 썸네일)로 구성해요."""
    panel = storefront.get("SkinsPanelLayout", {})
    remaining = panel.get("SingleItemOffersRemainingDurationInSeconds", 0)
    offers = _shop_offers(storefront, owned)
    balance = _vp_balance(wallet)

    description = f"**{riot_id or user.display_name}** | ⏳ {_format_remaining(remaining)}"
    wallet_line = _format_wallet(wallet)
    if wallet_line:
        description += f"\n{wallet_line}"
    afford_line = _affordability_line(offers, balance)
    if afford_line:
        description += f"\n{afford_line}"

    header = discord.Embed(description=description, color=0xFF4655)
    header.set_author(name="🔫 오상 · 오늘의 상점", icon_url=user.display_avatar.url)
    embeds = [header]

    for offer in offers:
        info = offer["info"]
        cost = offer["cost"]
        color = (info.get("tier_color") if info else None) or _DEFAULT_TIER_COLOR

        # 이미 가진 스킨은 가격 비교가 의미 없으니 보유 표시만 하고 넘어가요.
        price_text = f"{cost:,} VP"
        if offer["owned"]:
            price_text += " · 🎒 이미 보유"
        elif balance is not None and cost:
            # 잔액을 아는 경우에만 살 수 있는지 같이 보여줘요. 지갑 조회가 실패하면 가격만 나와요.
            price_text += " · ✅ 구매 가능" if cost <= balance else f" · ⚠️ {cost - balance:,} VP 부족"

        item_embed = discord.Embed(description=price_text, color=color)
        item_embed.set_author(name=offer["name"], icon_url=(info.get("tier_icon") if info else None))
        if info and info.get("icon"):
            item_embed.set_thumbnail(url=info["icon"])
        embeds.append(item_embed)

    if not offers:
        header.description += "\n오늘 로테이션된 아이템 정보를 못 받아왔어요."

    return embeds


_VP_TOPUP_COLOR = 0x00B8D4  # /vp계산과 같은 계열의 파란색이에요.


def _combo_text(need: int, table: dict) -> str:
    """부족한 VP를 채우는 가장 싼 충전 조합을 한 줄로 만들어요.
    /vp계산과 같은 계산기(utils/vp_prices)를 그대로 써서 두 명령어 결과가 항상 일치해요."""
    result = vp_prices.cheapest_combo(need, table["packs"])
    if result is None:
        return ""

    currency = table["currency"]
    packs = ", ".join(
        f"{pack_vp:,} VP 팩 ×{result['counts'][pack_vp]}"
        for pack_vp in sorted(result["counts"], reverse=True)
    )
    text = f"→ **{result['cost']:,}{currency}** ({packs})"
    if result["leftover"]:
        text += f" · 충전 후 {result['leftover']:,} VP 남음"
    return text


def _build_vp_topup_embed(offers: list[dict], balance: int | None) -> discord.Embed:
    """"🧮 VP 충전 계산" 버튼을 눌렀을 때 보여주는 화면이에요.
    오늘 상점에 뜬 스킨별로 얼마가 부족하고, 그걸 채우는 최저가 충전이 얼마인지 알려줘요."""
    table = vp_prices.load()
    embed = discord.Embed(title="🧮 VP 충전 계산", color=_VP_TOPUP_COLOR)

    if balance is None:
        embed.description = (
            "지갑 조회에 실패해서 보유 VP를 못 읽었어요.\n"
            "`/vp계산 목표vp:<가격> 보유vp:<잔액>` 으로 직접 계산할 수 있어요."
        )
        return embed

    embed.description = f"보유 **{balance:,} VP**"

    if not table["packs"]:
        embed.description += "\n\n⚠️ 충전 가격표가 설정돼 있지 않아서 금액 계산은 건너뛸게요."

    targets = _need_to_buy(offers)
    owned_names = [offer["name"] for offer in offers if offer["owned"]]
    if not targets and owned_names:
        embed.description += "\n\n🎒 오늘 뜬 스킨은 이미 다 갖고 계세요! 충전할 게 없어요."

    lines = []
    for offer in targets:
        cost = offer["cost"]
        if cost <= balance:
            lines.append(f"✅ **{offer['name']}** — {cost:,} VP · 지금 살 수 있어요")
            continue
        need = cost - balance
        line = f"⚠️ **{offer['name']}** — {cost:,} VP · **{need:,} VP** 부족"
        combo = _combo_text(need, table) if table["packs"] else ""
        if combo:
            line += f"\n{combo}"
        lines.append(line)

    if lines:
        embed.add_field(name="스킨별 필요 충전", value="\n".join(lines), inline=False)
    if owned_names:
        embed.add_field(
            name="🎒 이미 갖고 있어요 (계산에서 뺐어요)",
            value="\n".join(f"• {name}" for name in owned_names),
            inline=False,
        )

    total = sum(offer["cost"] for offer in targets)
    label = "안 가진 스킨 전부 사려면" if owned_names else "4종 전부 사려면"
    if total > balance:
        need_all = total - balance
        value = f"합계 **{total:,} VP** · **{need_all:,} VP** 부족"
        combo = _combo_text(need_all, table) if table["packs"] else ""
        if combo:
            value += f"\n{combo}"
        embed.add_field(name=label, value=value, inline=False)
    elif total:
        embed.add_field(
            name=label,
            value=f"합계 **{total:,} VP** · ✅ 보유 VP로 전부 살 수 있어요",
            inline=False,
        )

    footer = "더 자세한 계산은 /vp계산"
    if table["updated"]:
        footer += f" · 가격표 기준 {table['updated']}"
    embed.set_footer(text=footer)
    return embed


_ACCESSORY_COLOR = 0xC9A227  # 킹덤 크레딧을 상징하는 골드색이에요.


def _build_accessory_embeds(storefront: dict) -> list[discord.Embed]:
    """장식상점(건버디/스프레이/플레이어카드/칭호)을 스킨 상점과 같은 스타일로 보여줘요."""
    accessory_store = storefront.get("AccessoryStore", {})
    offers = accessory_store.get("AccessoryStoreOffers", [])
    remaining = accessory_store.get("AccessoryStoreRemainingDurationInSeconds", 0)

    if not offers:
        return []

    header = discord.Embed(
        description=f"⏳ {_format_remaining(remaining)}",
        color=_ACCESSORY_COLOR,
    )
    header.set_author(name="🎀 장식상점 (킹덤 크레딧)")
    embeds = [header]

    for entry in offers:
        offer = entry.get("Offer", {})
        rewards = offer.get("Rewards", [])
        if not rewards:
            continue
        item_id = rewards[0].get("ItemID")
        info = valorant_accessories.get(item_id)

        cost_map = offer.get("Cost", {})
        cost = next(iter(cost_map.values())) if cost_map else 0

        name = info["name"] if info else "알 수 없는 아이템"
        category = info["category"] if info else "장식 아이템"

        item_embed = discord.Embed(
            title=name, description=f"{category} · 💠 {cost:,} CD", color=_ACCESSORY_COLOR
        )
        if info and info.get("icon"):
            item_embed.set_thumbnail(url=info["icon"])
        embeds.append(item_embed)

    return embeds


_NIGHTMARKET_COLOR = 0x8B2FC9  # 야시장 특유의 보라색이에요.


def _build_nightmarket_embeds(storefront: dict, owned: set[str] | None = None) -> list[discord.Embed]:
    """야시장(BonusStore)은 시즌마다 한 번씩만 열려요. 안 열려있으면 빈 목록을 돌려주고,
    호출하는 쪽에서 버튼 자체를 안 붙여요."""
    bonus_store = storefront.get("BonusStore") or {}
    offers = bonus_store.get("BonusStoreOffers") or []
    if not offers:
        return []

    remaining = bonus_store.get("BonusStoreRemainingDurationInSeconds", 0)
    header = discord.Embed(
        description=f"⏳ {_format_remaining(remaining)}\n-# 게임에서 아직 카드를 안 깐 스킨은 가격이 가려져 있어요. 눌러야 보여요.",
        color=_NIGHTMARKET_COLOR,
    )
    header.set_author(name="🌙 야시장")
    embeds = [header]

    for entry in offers:
        offer = entry.get("Offer") or {}
        rewards = offer.get("Rewards") or []
        if not rewards:
            continue
        item_id = rewards[0].get("ItemID")
        info = valorant_skins.get(item_id)

        base_cost = _first_cost(offer.get("Cost"))
        discounted_cost = _first_cost(entry.get("DiscountCosts"))
        discount_percent = entry.get("DiscountPercent") or 0

        name = info["name"] if info else "알 수 없는 스킨"
        color = (info.get("tier_color") if info else None) or _NIGHTMARKET_COLOR

        if discount_percent:
            price_text = f"**{discounted_cost:,} VP** ~~{base_cost:,} VP~~  ·  🔻 **{discount_percent}% 할인**"
        else:
            price_text = f"{discounted_cost or base_cost:,} VP"

        # IsSeen이 False면 아직 게임에서 카드를 안 깐 상태예요. 재미를 뺏지 않으려고
        # 가격을 스포일러로 가려서, 보고 싶은 사람만 눌러서 보게 해요.
        if entry.get("IsSeen") is False:
            price_text = f"🎴 아직 안 깐 카드 · 스포일러 ||{price_text}||"
        if owned and item_id in owned:
            price_text += "  ·  🎒 이미 보유"

        item_embed = discord.Embed(description=price_text, color=color)
        item_embed.set_author(name=name, icon_url=(info.get("tier_icon") if info else None))
        if info and info.get("icon"):
            item_embed.set_thumbnail(url=info["icon"])
        embeds.append(item_embed)

    return embeds


_BUNDLE_COLOR = 0x0F1923  # 발로란트 다크 테마 색이에요.


def _build_bundle_embeds(storefront: dict) -> list[discord.Embed]:
    """오늘 상점 메인에 떠 있는 피처드 번들(있을 때만)을 보여줘요."""
    featured = storefront.get("FeaturedBundle", {})
    bundles = featured.get("Bundles") or ([featured["Bundle"]] if featured.get("Bundle") else [])
    if not bundles:
        return []

    embeds = []
    for bundle in bundles:
        items = bundle.get("Items", [])
        remaining = bundle.get("DurationRemainingInSeconds", 0)
        total_cost = bundle.get("TotalDiscountedCost") or {}
        total_base = bundle.get("TotalBaseCost") or {}
        total_price = next(iter(total_cost.values()), 0)
        base_price = next(iter(total_base.values()), 0) or total_price

        header = discord.Embed(description=f"⏳ {_format_remaining(remaining)}", color=_BUNDLE_COLOR)
        header.set_author(name="📦 오늘의 번들")
        price_text = f"{total_price:,} VP"
        if base_price and base_price != total_price:
            price_text += f" ~~{base_price:,} VP~~"
        header.add_field(name="번들 총 가격", value=price_text, inline=False)
        embeds.append(header)

        for entry in items:
            item = entry.get("Item", {})
            item_type_id = item.get("ItemTypeID")
            item_id = item.get("ItemID")
            price = entry.get("DiscountedPrice", entry.get("BasePrice", 0))

            info = valorant_skins.get(item_id) if item_type_id == SKIN_LEVEL_TYPE_ID else valorant_accessories.get(item_id)
            name = info["name"] if info else "알 수 없는 아이템"
            color = (info.get("tier_color") if info else None) or _DEFAULT_TIER_COLOR

            item_embed = discord.Embed(description=f"{price:,} VP", color=color)
            item_embed.set_author(name=name, icon_url=(info.get("tier_icon") if info else None))
            if info and info.get("icon"):
                item_embed.set_thumbnail(url=info["icon"])
            embeds.append(item_embed)

    return embeds


# 디스코드는 메시지 하나에 임베드를 최대 10개까지만 붙일 수 있어요. 번들처럼 아이템이
# 많을 땐 넘칠 수 있어서, 조용히 잘라내지 말고 "몇 개 더 있다"고 알려줘요.
MAX_EMBEDS = 10


def _fit_embeds(embeds: list[discord.Embed]) -> list[discord.Embed]:
    if len(embeds) <= MAX_EMBEDS:
        return embeds
    trimmed = embeds[: MAX_EMBEDS - 1]
    hidden = len(embeds) - len(trimmed)
    notice = discord.Embed(
        description=f"-# … 그리고 {hidden}개 더 있어요 (디스코드가 한 번에 {MAX_EMBEDS}개까지만 보여줄 수 있어요)",
        color=_DEFAULT_TIER_COLOR,
    )
    return trimmed + [notice]


class TimeoutDisablingView(discord.ui.View):
    """타임아웃되면 버튼을 눌러도 아무 반응이 없어서 유저가 헷갈리는데, 그때 버튼을
    회색으로 비활성화해줘요. message를 넣어줘야 동작해요."""

    def __init__(self, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except Exception:  # noqa: BLE001
            pass  # 메시지가 이미 지워졌거나 수정 권한이 만료됐으면 그냥 넘어가요.


class BackToShopView(TimeoutDisablingView):
    """장식상점/야시장/번들 화면에서 다시 스킨 상점으로 돌아가는 버튼 하나짜리 뷰예요."""

    def __init__(self, parent: "ShopResultView"):
        super().__init__(timeout=600)
        self._parent = parent

    @discord.ui.button(label="◀ 상점으로 돌아가기", style=discord.ButtonStyle.secondary)
    async def back_to_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embeds=self._parent.shop_embeds, view=self._parent)


class ShopResultView(TimeoutDisablingView):
    """상점 결과 메시지에 붙는 버튼들이에요. 장식상점/야시장/번들은 바로 다 보여주지 않고,
    제트봇처럼 버튼을 눌러야만 그때 같은 메시지 안에서 화면을 전환해서 보여줘요."""

    def __init__(
        self,
        shop_embeds: list[discord.Embed],
        storefront: dict,
        wallet: dict | None = None,
        owned: set[str] | None = None,
        can_refresh: bool = False,
        public: bool = True,
        owner_id: int = 0,
        account_key: str = "",
    ):
        super().__init__(timeout=600)
        self.shop_embeds = shop_embeds
        self._public = public
        self._owner_id = owner_id  # 이 상점을 부른 사람. 새로고침은 본인만 할 수 있어요.
        self._account_key = account_key  # 지금 화면에 떠 있는 계정
        self._accessory_embeds = _build_accessory_embeds(storefront)
        self._nightmarket_embeds = _build_nightmarket_embeds(storefront, owned)
        self._bundle_embeds = _build_bundle_embeds(storefront)
        self._offers = _shop_offers(storefront, owned)
        self._balance = _vp_balance(wallet)

        if not self._accessory_embeds:
            self.remove_item(self.show_accessories)
        if not self._nightmarket_embeds:
            self.remove_item(self.show_nightmarket)
        if not self._bundle_embeds:
            self.remove_item(self.show_bundle)
        # 살 게 하나도 없으면(가격을 못 읽었거나 이미 다 보유) 계산할 게 없으니 버튼을 빼요.
        if not _need_to_buy(self._offers):
            self.remove_item(self.show_vp_topup)
        # 새로고침·계정 전환은 봇이 대신 다시 조회할 수 있어야(=쿠키 등록) 되는 기능이에요.
        if not can_refresh:
            self.remove_item(self.refresh_shop)
            self.remove_item(self.switch_account)

    async def _switch(self, interaction: discord.Interaction, embeds: list[discord.Embed]):
        child = BackToShopView(self)
        await interaction.response.edit_message(embeds=_fit_embeds(embeds), view=child)
        # 나만 보기(ephemeral)로 띄운 메시지는 interaction.message로는 수정이 안 돼요.
        # 타임아웃 때 버튼을 회색으로 만들려면 인터랙션 토큰으로 받은 메시지를 써야 해요.
        try:
            child.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            child.message = interaction.message

    @discord.ui.button(label="🎀 장식상점 보기", style=discord.ButtonStyle.secondary)
    async def show_accessories(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, self._accessory_embeds)

    @discord.ui.button(label="🌙 야시장 보기", style=discord.ButtonStyle.primary)
    async def show_nightmarket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, self._nightmarket_embeds)

    @discord.ui.button(label="📦 번들 보기", style=discord.ButtonStyle.secondary)
    async def show_bundle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, self._bundle_embeds)

    @discord.ui.button(label="🧮 VP 충전 계산", style=discord.ButtonStyle.secondary, row=1)
    async def show_vp_topup(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 다른 버튼과 달리 화면을 갈아끼우지 않고 나만 보기로 따로 띄워요. 상점 화면을
        # 그대로 두는 게 편하고, 남의 상점에서 눌러도 서로 방해가 안 돼요.
        await interaction.response.send_message(
            embed=_build_vp_topup_embed(self._offers, self._balance), ephemeral=True
        )

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        """게임에서 스킨을 사고 온 경우처럼, 잔액·보유 목록을 즉시 다시 받아와요."""
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(
                "이 상점을 부른 사람만 새로고침할 수 있어요. `/오상`으로 본인 상점을 열어주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        payload, error = await _load_shop_for_account(
            self._owner_id, self._account_key, use_cache=False
        )
        if payload is None:
            await interaction.followup.send(error, ephemeral=True)
            return

        # 원래 메시지를 그 자리에서 갈아끼워요(새 메시지를 또 쌓지 않게).
        embeds, view = _shop_screen(
            interaction.user, payload, public=self._public,
            owner_id=self._owner_id, account_key=self._account_key,
        )
        await interaction.edit_original_response(embeds=embeds, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            view.message = interaction.message

    @discord.ui.button(label="👤 계정", style=discord.ButtonStyle.secondary, row=1)
    async def switch_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        """본계/부계 전환과 계정 추가를 여기서 해요.

        상점 메시지에 드롭다운을 바로 붙이지 않고 버튼을 한 번 거치는 이유가 있어요.
        `/오상`은 기본이 채널 공개라, 드롭다운을 붙여버리면 **부계 라이엇 ID가 채널의
        모두에게 보여요.** 버튼을 누른 사람에게만 나만 보기로 목록을 띄우면 그 일이 없어요."""
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(
                "이 상점을 부른 사람만 계정을 바꿀 수 있어요. `/오상`으로 본인 상점을 열어주세요.",
                ephemeral=True,
            )
            return

        view = AccountPickerView(self)
        await interaction.response.send_message(
            embed=view.build_embed(), view=view, ephemeral=True
        )
        try:
            view.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            pass

    async def show_account(self, interaction: discord.Interaction, account_key: str):
        """고른 계정으로 상점 메시지를 그 자리에서 갈아끼워요.
        (계정 선택은 나만 보기 메시지에서 하니까, 원본 상점 메시지를 직접 수정해야 해요.)"""
        payload, error = await _load_shop_for_account(self._owner_id, account_key)
        if payload is None:
            await interaction.followup.send(error, ephemeral=True)
            return

        self._account_key = account_key
        embeds, view = _shop_screen(
            interaction.user, payload, public=self._public,
            owner_id=self._owner_id, account_key=account_key,
        )
        if self.message is not None:
            try:
                await self.message.edit(embeds=embeds, view=view)
                view.message = self.message
                self.stop()  # 갈아끼운 뒤엔 이전 뷰가 더 반응할 필요가 없어요.
                await interaction.followup.send(
                    f"🔀 **{payload['riot_id'] or '다른 계정'}** 상점으로 바꿨어요.", ephemeral=True
                )
                return
            except discord.HTTPException as error_edit:
                # 원본 메시지가 지워졌거나 수정 시한(15분)이 지난 경우예요.
                log.debug(f"상점 메시지 갱신 실패, 새 메시지로 보내요: {error_edit}")

        message = await interaction.followup.send(
            embeds=embeds, view=view, ephemeral=not self._public, wait=True
        )
        view.message = message
        self.stop()


class AccountPickerView(TimeoutDisablingView):
    """상점 화면의 `👤 계정` 버튼을 누르면 나만 보기로 뜨는 계정 목록이에요.
    등록해둔 계정 사이를 오가거나, 새 계정(부계)을 추가할 수 있어요."""

    def __init__(self, parent: ShopResultView):
        super().__init__(timeout=300)
        self._parent = parent
        self._owner_id = parent._owner_id
        self._accounts = riot_session_store.list_accounts(self._owner_id)

        if self._accounts:
            select = discord.ui.Select(
                placeholder="상점을 볼 계정을 고르세요",
                options=[
                    discord.SelectOption(
                        label=account["label"][:100],
                        value=account["key"],
                        description="지금 보고 있는 계정" if account["key"] == parent._account_key else None,
                        default=account["key"] == parent._account_key,
                        emoji="🔫",
                    )
                    for account in self._accounts
                ],
            )
            select.callback = self._on_select
            self.add_item(select)

        if len(self._accounts) >= riot_session_store.MAX_ACCOUNTS:
            self.remove_item(self.add_account)

    def build_embed(self) -> discord.Embed:
        lines = []
        for account in self._accounts:
            marks = []
            if account["key"] == self._parent._account_key:
                marks.append("지금 보는 중")
            elif account["is_default"]:
                marks.append("`/오상` 기본")
            suffix = f" — {', '.join(marks)}" if marks else ""
            lines.append(f"• **{account['label']}**{suffix}")

        embed = discord.Embed(
            title="👤 오상 · 내 계정",
            description="\n".join(lines) or "등록해둔 계정이 없어요.",
            color=0xFF4655,
        )
        remaining = riot_session_store.MAX_ACCOUNTS - len(self._accounts)
        if remaining > 0:
            embed.set_footer(
                text=f"{remaining}개 더 등록할 수 있어요 · 등록 해제는 /오상쿠키삭제"
            )
        else:
            embed.set_footer(
                text=f"계정은 최대 {riot_session_store.MAX_ACCOUNTS}개까지예요 · 등록 해제는 /오상쿠키삭제"
            )
        return embed

    async def _on_select(self, interaction: discord.Interaction):
        # 고른 계정의 상점을 받아오는 데 몇 초 걸려서 먼저 defer해요.
        await interaction.response.defer()
        account_key = interaction.data["values"][0]
        self.stop()
        await self._parent.show_account(interaction, account_key)

    @discord.ui.button(label="➕ 다른 계정 추가", style=discord.ButtonStyle.secondary, row=1)
    async def add_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔫 오상 · 계정 추가하기",
            description=(
                "추가할 계정으로 **쿠키를 등록**하면 그때부터 `👤 계정` 버튼으로 오갈 수 있어요.\n\n"
                "① 아래 **라이엇 로그인하기**로 추가할 계정에 로그인하세요.\n"
                "-# 이미 다른 계정으로 로그인돼 있으면 시크릿 창을 쓰거나 로그아웃 후 진행하세요.\n"
                "② **③ 쿠키 등록**으로 그 계정의 ssid를 등록하면 끝이에요.\n\n"
                "-# ② 로그인 후 URL 붙여넣기는 이번 한 번만 보는 방식이라 계정으로 저장되지 않아요."
            ),
            color=0xFF4655,
        )
        # 부계 라이엇 ID가 채널에 노출되지 않도록 추가 과정은 항상 나만 보기로 진행해요.
        view = StartView(public=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        try:
            view.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            pass


class DeleteAccountView(TimeoutDisablingView):
    """`/오상쿠키삭제`에서 계정이 둘 이상일 때 어느 걸 지울지 고르는 화면이에요."""

    def __init__(self, owner_id: int, accounts: list[dict]):
        super().__init__(timeout=300)
        self._owner_id = owner_id
        self._labels = {account["key"]: account["label"] for account in accounts}

        select = discord.ui.Select(
            placeholder="등록을 해제할 계정을 고르세요",
            options=[
                discord.SelectOption(
                    label=account["label"][:100], value=account["key"], emoji="🔫"
                )
                for account in accounts
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        account_key = interaction.data["values"][0]
        label = self._labels.get(account_key, "그 계정")
        _forget_account_data(self._owner_id, account_key)
        riot_session_store.delete_session(self._owner_id, account_key)
        self.stop()
        await interaction.response.edit_message(
            content=f"🗑️ **{label}** 등록을 해제했어요.", embed=None, view=None
        )

    @discord.ui.button(label="전부 등록 해제", style=discord.ButtonStyle.danger, row=1)
    async def delete_every(self, interaction: discord.Interaction, button: discord.ui.Button):
        _forget_account_data(self._owner_id)
        count = riot_session_store.delete_all_sessions(self._owner_id)
        self.stop()
        await interaction.response.edit_message(
            content=(
                f"🗑️ 등록해둔 계정 **{count}개**를 전부 해제했어요. "
                "이제 `/오상`은 매번 로그인 방식으로 동작해요."
            ),
            embed=None,
            view=None,
        )


# ── 상점 결과 캐시 ──────────────────────────────────────────────────────────
# /오상 한 번에 라이엇 왕복이 재인증·지역·권한·상점·지갑·보유스킨까지 여러 번 일어나요.
# 상점 로테이션은 하루에 한 번만 바뀌니 원칙적으론 길게 캐시해도 되지만, **지갑 잔액과
# 보유 스킨은 유저가 게임에서 스킨을 사면 바로 바뀌어요.** 사고 나서 다시 불렀는데 옛날
# 잔액이 뜨면 오히려 잘못된 정보라, 짧게만 캐시하고 "새로고침" 버튼으로 직접 갱신할 수
# 있게 했어요. (로테이션 갱신이 5분 안 남았으면 그 시각에 맞춰 더 짧게 잡아요.)
_SHOP_CACHE_TTL_SECONDS = 300

# 계정을 여러 개 등록할 수 있어서 캐시도 (유저, 계정)별로 따로 담아요. 유저 단위로만 담으면
# 본계를 보고 부계로 전환했을 때 본계 상점이 그대로 떠요.
_shop_cache: dict[tuple[int, str], dict] = {}


def _cache_shop(
    discord_id: int,
    account_key: str,
    storefront: dict,
    wallet: dict | None,
    owned: set[str] | None,
    riot_id: str,
):
    panel = storefront.get("SkinsPanelLayout") or {}
    remaining = panel.get("SingleItemOffersRemainingDurationInSeconds") or 0
    ttl = _SHOP_CACHE_TTL_SECONDS
    if 0 < remaining < ttl:
        ttl = remaining  # 로테이션이 곧 바뀌면 그 전까지만 써요.

    # 안 쓰는 사람 몫이 계속 쌓이지 않게, 저장할 때 만료된 것들을 같이 치워요.
    now = time.monotonic()
    for expired_key in [key for key, value in _shop_cache.items() if now >= value["expires"]]:
        _shop_cache.pop(expired_key, None)

    _shop_cache[(discord_id, account_key)] = {
        "expires": time.monotonic() + ttl,
        "storefront": storefront,
        "wallet": wallet,
        "owned": owned,
        "riot_id": riot_id,
    }


def _get_cached_shop(discord_id: int, account_key: str) -> dict | None:
    entry = _shop_cache.get((discord_id, account_key))
    if entry is None:
        return None
    if time.monotonic() >= entry["expires"]:
        _shop_cache.pop((discord_id, account_key), None)
        return None
    return entry


def _invalidate_shop_cache(discord_id: int, account_key: str | None = None):
    """account_key를 안 주면 그 유저의 모든 계정 캐시를 비워요."""
    for key in [
        cached_key for cached_key in _shop_cache
        if cached_key[0] == discord_id and (account_key is None or cached_key[1] == account_key)
    ]:
        _shop_cache.pop(key, None)


async def _load_shop_for_account(
    discord_id: int, account_key: str, use_cache: bool = True
) -> tuple[dict | None, str]:
    """등록해둔 계정 하나의 상점을 가져와요. ({storefront, wallet, owned, riot_id}, 오류문구).

    `/오상`·새로고침·계정 전환이 전부 이 함수를 거쳐요. 예전엔 같은 절차(재인증 → 회전된
    쿠키 저장 → 상점 조회 → 캐시)가 세 군데에 각각 적혀 있었는데, 그중 한 곳에서
    쿠키 재저장을 빠뜨려서 "등록이 자꾸 풀린다"는 신고로 이어진 적이 있어요."""
    if use_cache:
        cached = _get_cached_shop(discord_id, account_key)
        if cached is not None:
            # 캐시로 보여줬어도 '방금 본 계정'인 건 같아요. 여기서 안 찍으면 5분 안에 계정을
            # 바꿨을 때 다음 `/오상`이 이전 계정으로 되돌아가요.
            riot_session_store.touch(discord_id, account_key)
            return cached, ""
    else:
        _invalidate_shop_cache(discord_id, account_key)

    cookie_header = riot_session_store.get_session(discord_id, account_key)
    if not cookie_header:
        return None, "등록해둔 쿠키가 없어서 다시 조회할 수 없어요. `/오상`을 다시 실행해주세요."

    result, session = await riot_auth.reauth_with_cookies(cookie_header)
    try:
        if not result.ok:
            # 일시적인 실패(프록시·라이엇 장애)로 쿠키를 지우면 멀쩡한 유저가 재등록하게 돼요.
            if result.expired:
                riot_session_store.delete_session(discord_id, account_key)
                _invalidate_shop_cache(discord_id, account_key)
                _forget_owned(discord_id, account_key)
                return None, (
                    "등록해둔 로그인이 만료됐어요. `/오상`으로 다시 로그인(또는 쿠키 재등록)해주세요."
                )
            return None, f"⚠️ {result.error} (등록해둔 쿠키는 그대로 두었어요)"

        riot_auth.persist_refreshed_cookie(discord_id, result, account_key)
        storefront, wallet, owned, error = await _fetch_storefront(
            session, result.access_token, result.id_token, who=str(discord_id)
        )
    finally:
        await session.close()

    if storefront is None:
        return None, error

    _remember_owned(discord_id, account_key, owned)
    riot_id = riot_auth.riot_id_from_id_token(result.id_token) or ""
    _cache_shop(discord_id, account_key, storefront, wallet, owned, riot_id)
    # 다음에 그냥 `/오상`만 쳤을 때 방금 본 계정이 뜨도록 기억해둬요.
    riot_session_store.touch(discord_id, account_key)
    return {"storefront": storefront, "wallet": wallet, "owned": owned, "riot_id": riot_id}, ""


def _shop_screen(
    user: discord.abc.User,
    payload: dict,
    *,
    public: bool,
    owner_id: int,
    account_key: str,
) -> tuple[list[discord.Embed], "ShopResultView"]:
    """상점 데이터를 임베드+뷰 한 쌍으로 만들어요. 처음 조회든 새로고침이든 계정 전환이든
    똑같은 화면이 나오도록 여기 한 곳에서만 만들어요."""
    embeds = _fit_embeds(
        _build_shop_embeds(
            user, payload["storefront"], payload["riot_id"], payload["wallet"], payload["owned"]
        )
    )
    view = ShopResultView(
        embeds,
        payload["storefront"],
        payload["wallet"],
        payload["owned"],
        # 새로고침·계정 전환은 봇이 대신 다시 조회할 수 있어야 되는데, 그러려면 이 화면이
        # 어느 등록 계정의 것인지 알아야 해요. URL 붙여넣기로 한 번만 본 화면은 계정 키가
        # 없어서(빈 문자열) 버튼을 빼요. 예전처럼 "쿠키를 하나라도 등록했으면 켜기"로 두면,
        # 부계를 URL로 본 화면에서 새로고침했을 때 엉뚱하게 본계 상점이 떠요.
        can_refresh=bool(account_key),
        public=public,
        owner_id=owner_id,
        account_key=account_key,
    )
    return embeds, view


async def _ensure_static_data():
    """스킨/장식 아이템 이름·이미지 캐시를 확보해요.
    valorant-api.com은 로그인이 필요 없는 공개 API라 별도의 임시 세션을 써요."""
    if valorant_skins.is_loaded() and valorant_accessories.is_loaded():
        return
    async with aiohttp.ClientSession() as static_session:
        if not valorant_skins.is_loaded():
            await valorant_skins.load(static_session)
        if not valorant_accessories.is_loaded():
            await valorant_accessories.load(static_session)


async def _fetch_storefront(
    session, access_token: str, id_token: str, who: str = ""
) -> tuple[dict | None, dict | None, set[str] | None, str]:
    """(storefront, wallet, 보유스킨UUID들, 오류메시지)를 돌려줘요.
    성공하면 오류메시지가 빈 문자열이에요. /오상 명령어와 위시리스트 자동 알림이 같이 써요.

    ⚡ 라이엇 호출은 전부 주거용 프록시를 거쳐서 왕복 한 번이 비싸요(게임서버 기준 400~630ms,
    직접 연결이면 44ms — 2026-09-03 Fly 머신에서 측정). 그래서 서로 결과를 안 기다려도 되는
    호출은 묶어서 동시에 보내요. 순차로 하면 왕복 6번인데 이렇게 하면 3번이에요."""
    puuid = riot_auth.puuid_from_access_token(access_token)
    if not puuid:
        return None, None, None, "로그인 정보를 읽지 못했어요. 다시 시도해주세요."

    # 지역과 권한 토큰은 서로를 안 기다려도 돼요(둘 다 access_token만 있으면 됨).
    region, entitlement = await asyncio.gather(
        riot_auth.get_region(session, access_token, id_token, who=who),
        riot_auth.get_entitlement(session, access_token, who=who),
        return_exceptions=True,
    )
    # ⚠️ return_exceptions=True라서 예외가 조용히 값으로 바뀌어 돌아와요. 여기서 안 찍으면
    # 서버 로그엔 아무 흔적도 안 남고 유저에게만 실패 문구가 떠서 원인을 못 좁혀요.
    if isinstance(region, BaseException):
        log.warning(f"⚠️ [{who}] 오상 지역 확인 예외: {region!r}")
    if isinstance(entitlement, BaseException):
        log.warning(f"⚠️ [{who}] 오상 권한 토큰 예외: {entitlement!r}")

    if isinstance(region, BaseException) or not region:
        return None, None, None, "라이엇 서버 지역 확인에 실패했어요. 다시 시도해주세요."
    if isinstance(entitlement, BaseException) or not entitlement:
        return None, None, None, "라이엇 서버에서 권한 토큰을 못 받았어요. 잠시 후 다시 시도해주세요."

    # 아래 세 호출이 각자 내부에서 클라이언트 버전을 필요로 하는데, 캐시가 비어있으면
    # 셋이 동시에 같은 값을 받아오려고 해요. 여기서 먼저 한 번 데워두면 그 낭비가 없어요.
    await riot_auth.get_client_version(session)

    # 상점·지갑·보유스킨은 서로 독립이라 한꺼번에 보내요. 정적 데이터(스킨 이름/이미지)
    # 준비도 라이엇이 아니라 valorant-api.com이라 같이 태워도 서로 방해하지 않아요.
    storefront, wallet, owned, _static = await asyncio.gather(
        riot_auth.get_storefront(
            session, access_token=access_token, entitlement=entitlement, region=region, puuid=puuid
        ),
        riot_auth.get_wallet(
            session, access_token=access_token, entitlement=entitlement, region=region, puuid=puuid
        ),
        riot_auth.get_owned_skin_ids(
            session, access_token=access_token, entitlement=entitlement, region=region, puuid=puuid
        ),
        _ensure_static_data(),
        return_exceptions=True,
    )

    if isinstance(storefront, BaseException):
        log.warning(f"⚠️ 오상 상점 조회 실패: {storefront!r}")
        storefront = None
    if storefront is None:
        return None, None, None, "상점 정보를 못 받아왔어요. 잠시 후 다시 시도해주세요."

    # 지갑과 보유 스킨은 부가 정보라, 실패해도 상점은 그대로 보여줘요.
    if isinstance(wallet, BaseException):
        log.warning(f"⚠️ 오상 지갑 조회 실패: {wallet!r}")
        wallet = None
    if isinstance(owned, BaseException):
        log.warning(f"⚠️ 오상 보유 스킨 조회 실패: {owned!r}")
        owned = None
    if isinstance(_static, BaseException):
        # 이름/이미지 캐시가 없으면 "알 수 없는 스킨"으로 뜨긴 하지만 상점 자체는 보여줘요.
        log.warning(f"⚠️ 오상 정적 데이터 준비 실패: {_static!r}")

    return storefront, wallet, owned, ""


def _offered_skin_names(storefront: dict) -> list[str]:
    """오늘 상점(스킨 4종)에 뜬 스킨 이름들이에요. 위시리스트 대조에 써요."""
    panel = storefront.get("SkinsPanelLayout") or {}
    names = []
    for item_id in panel.get("SingleItemOffers") or []:
        info = valorant_skins.get(item_id)
        name = info.get("name") if info else None
        if name and name not in names:  # 같은 스킨이 두 번 잡히면 알림도 두 줄이 돼요.
            names.append(name)
    return names


async def _render_shop(
    interaction: discord.Interaction,
    payload: dict,
    public: bool = True,
    account_key: str = "",
) -> bool:
    """이미 받아온 상점 데이터를 화면으로 그려요. 새로 조회한 경우와 캐시를 쓴 경우가
    똑같은 화면을 내도록 여기 한 곳에서만 만들어요."""
    # 기본값은 제트봇처럼 채널에 공개로 올려요(로그인 과정 자체만 항상 본인만 보이게 처리).
    embeds, view = _shop_screen(
        interaction.user, payload,
        public=public, owner_id=interaction.user.id, account_key=account_key,
    )
    message = await interaction.followup.send(embeds=embeds, view=view, ephemeral=not public, wait=True)
    view.message = message
    return True


async def _send_shop(
    interaction: discord.Interaction,
    session,
    access_token: str,
    id_token: str,
    public: bool = True,
    account_key: str = "",
) -> bool:
    """access_token/id_token으로 상점까지 조회해서 결과를 보여줘요. 성공하면 True.

    account_key는 이 조회가 '등록해둔 어느 계정'의 것인지예요. URL 붙여넣기처럼 저장 없이
    한 번만 보는 경우엔 빈 문자열이고, 그땐 캐시도 새로고침도 하지 않아요."""
    storefront, wallet, owned, error = await _fetch_storefront(
        session, access_token, id_token, who=str(interaction.user.id)
    )
    if storefront is None:
        await interaction.followup.send(error, ephemeral=True)
        return False

    # 위시리스트 자동완성에서도 "이미 보유"를 알려주려고 결과를 기억해둬요.
    _remember_owned(interaction.user.id, account_key, owned)

    riot_id = riot_auth.riot_id_from_id_token(id_token) or ""
    payload = {"storefront": storefront, "wallet": wallet, "owned": owned, "riot_id": riot_id}
    # 등록해둔 계정일 때만 캐시해요(다시 조회할 수단이 있어야 캐시가 의미 있어요).
    if account_key:
        _cache_shop(interaction.user.id, account_key, storefront, wallet, owned, riot_id)
        riot_session_store.touch(interaction.user.id, account_key)
    return await _render_shop(interaction, payload, public=public, account_key=account_key)


class PasteUrlModal(discord.ui.Modal, title="🔫 오상 · URL 붙여넣기"):
    url_input = discord.ui.TextInput(
        label="로그인 후 나온 주소창 URL 전체",
        style=discord.TextStyle.paragraph,
        placeholder="https://playvalorant.com/.../opt_in/#access_token=...",
        max_length=4000,
    )

    def __init__(self, public: bool = True):
        super().__init__()
        self.public = public

    async def on_submit(self, interaction: discord.Interaction):
        # 디스코드 특성상 ephemeral로 defer하면 이후 followup도 전부 ephemeral로 고정돼요.
        # 성공 시엔 채널에 공개로 보여줘야 해서, 공개로 defer하고 실패 메시지만 개별적으로 ephemeral 처리해요.
        await interaction.response.defer(ephemeral=False)

        parsed = riot_auth.parse_redirect_url(self.url_input.value.strip())
        if not parsed:
            await interaction.followup.send(
                "❌ URL에서 로그인 정보를 못 찾았어요. 로그인 완료 후 나온 주소창 URL 전체를 다시 복사해서 붙여넣어주세요.",
                ephemeral=True,
            )
            return
        access_token, id_token = parsed

        session = riot_auth.new_session()
        try:
            await _send_shop(interaction, session, access_token, id_token, public=self.public)
        finally:
            await session.close()

    async def on_error(self, interaction: discord.Interaction, error: Exception):  # noqa: D401
        log.warning(f"⚠️ 오상 처리 중 오류: {error}")
        if interaction.response.is_done():
            await interaction.followup.send("처리 중 오류가 발생했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("처리 중 오류가 발생했어요.", ephemeral=True)


class RegisterCookieModal(discord.ui.Modal, title="🔫 오상 · 쿠키 등록(선택)"):
    cookie_input = discord.ui.TextInput(
        label="ssid 쿠키 값 (또는 cookie 헤더 전체)",
        style=discord.TextStyle.paragraph,
        placeholder="ssid=eyJhbGciOi...  (값만 붙여넣어도 돼요. 방법은 '❔ 쿠키 등록 방법' 버튼)",
        max_length=4000,
    )

    def __init__(self, public: bool = True):
        super().__init__()
        self.public = public

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        cookie_header = self.cookie_input.value.strip()
        result, session = await riot_auth.reauth_with_cookies(cookie_header)
        if not result.ok:
            await session.close()
            # ⚠️ 예전엔 여기서 로그를 안 남겨서, "쿠키 등록이 안 된다"는 신고가 들어와도 무엇이
            # 문제였는지 서버 쪽에 흔적이 하나도 없었어요. 값 자체는 계정이라 절대 찍지 않고,
            # 길이·형태만 남겨요(riot_auth 쪽에서 status/riot_error도 같이 찍혀요).
            log.warning(
                f"⚠️ [{interaction.user.id}] 오상 쿠키 등록 실패: {result.error} "
                f"(expired={result.expired}, 입력길이={len(cookie_header)}, "
                f"줄수={cookie_header.count(chr(10)) + 1})"
            )
            await interaction.followup.send(
                f"❌ {result.error or '등록에 실패했어요.'}\n"
                "-# 계속 안 되면 `❔ 쿠키 등록 방법` 버튼의 **자주 막히는 곳**을 확인해보세요.",
                ephemeral=True,
            )
            return

        # 상점을 부르기 전에 먼저 저장해요. 순서가 반대면 어느 계정 슬롯에 들어갈지 모르는
        # 채로 화면을 그리게 돼서, 방금 등록한 계정의 새로고침·전환 버튼이 엉뚱한 계정을
        # 가리켜요. 재인증이 성공한 시점에 이미 쿠키가 쓸 수 있다는 건 확인된 상태예요.
        #
        # 유저가 붙여넣은 원본이 아니라, 재인증으로 회전된 쿠키를 저장해요(원본은 이미
        # 라이엇 쪽에서 무효화됐을 수 있어요). 회전 값이 없을 때만 원본으로 폴백해요.
        riot_id = riot_auth.riot_id_from_id_token(result.id_token) or ""
        had_accounts = riot_session_store.account_count(interaction.user.id)
        account_key = riot_session_store.save_session(
            interaction.user.id,
            result.cookie_header or cookie_header,
            riot_id=riot_id,
        )
        if account_key is None:
            await session.close()
            await interaction.followup.send(
                f"⚠️ 계정은 최대 **{riot_session_store.MAX_ACCOUNTS}개**까지만 등록할 수 있어요.\n"
                "`/오상쿠키삭제`로 안 쓰는 계정을 먼저 지운 다음 다시 등록해주세요.",
                ephemeral=True,
            )
            return

        try:
            ok = await _send_shop(
                interaction, session, result.access_token, result.id_token,
                public=self.public, account_key=account_key,
            )
        finally:
            await session.close()

        if ok:
            is_additional = riot_session_store.account_count(interaction.user.id) > max(had_accounts, 1)
            extra = (
                "\n-# 계정이 여러 개예요. 상점 화면의 **👤 계정** 버튼으로 오갈 수 있어요."
                if is_additional else ""
            )
            await interaction.followup.send(
                f"✅ **{riot_id or '이 계정'}** 쿠키가 등록됐어요! "
                "이제부터는 로그인 없이 `/오상`만 실행하면 돼요.\n"
                "-# 매일 새벽 4시에 봇이 알아서 갱신해서 계속 이어져요. 혹시 만료되면 그때 다시 등록해주세요."
                + extra,
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):  # noqa: D401
        log.warning(f"⚠️ 오상 쿠키 등록 중 오류: {error}")
        if interaction.response.is_done():
            await interaction.followup.send("처리 중 오류가 발생했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("처리 중 오류가 발생했어요.", ephemeral=True)


COOKIE_GUIDE_INTRO = (
    "**한 번만 등록해두면** 그 다음부터는 `/오상`만 쳐도 바로 상점이 떠요. "
    "매일 새벽 4시에 봇이 알아서 갱신해서 계속 이어져요.\n"
    "비밀번호는 받지도 저장하지도 않고, 등록한 값은 암호화해서 보관해요.\n\n"
    "🖥️ **PC에서만 할 수 있어요.** 휴대폰 브라우저에는 개발자도구가 없어서 안 돼요.\n"
    "⏱️ **복사한 뒤 곧바로 등록**하는 게 제일 중요해요 (아래 3️⃣ 설명 참고)."
)

# ⚠️ F12가 아예 없는 키보드(텐키리스·미니배열·일부 노트북)를 쓰는 사람이 있어서, 키를 하나도
# 안 눌러도 되는 "우클릭 → 검사"를 맨 앞에 뒀어요. 라이엇 로그인 페이지가 우클릭을 막지
# 않는다는 건 2026-09-07에 직접 확인했어요.
COOKIE_GUIDE_STEP1 = (
    "먼저 크롬에서 <https://auth.riotgames.com/login> 에 **로그인**한 뒤,\n"
    "**아래 넷 중 아무거나** 하나로 개발자도구를 열어요.\n\n"
    "🖱️ **페이지 빈 곳에 우클릭 → `검사`(Inspect)** ← 키보드 없이 되는 방법\n"
    "🧭 크롬 오른쪽 위 **`⋮` → 도구 더보기 → 개발자 도구**\n"
    "⌨️ `Ctrl` + `Shift` + `I`  (F12 대신 쓰는 단축키)\n"
    "💻 노트북이면 `Fn` + `F12` / 맥이면 `⌘` + `⌥` + `I`\n\n"
    "-# 엣지·웨일·브레이브도 방법이 똑같아요. 파이어폭스는 우클릭 → `요소 검사`."
)

COOKIE_GUIDE_STEP2 = (
    "① 개발자도구 위쪽 탭에서 **`Application`**(애플리케이션) 클릭\n"
    "-# 탭이 안 보이면 탭 줄 오른쪽 끝의 **`≫`** 를 눌러 펼치면 있어요.\n"
    "② 왼쪽 목록에서 **`Storage`(저장용량) → `Cookies` → `https://auth.riotgames.com`** 클릭\n"
    "③ 표에서 **`Name`(이름)이 정확히 `ssid`** 인 줄을 찾아요\n"
    "④ 그 줄의 **`Value`(값) 칸을 더블클릭** → `Ctrl`+`A` → `Ctrl`+`C`\n\n"
    "⚠️ **드래그해서 긁으면 안 돼요.** 값이 800자쯤 되는데 화면에 보이는 데까지만 복사돼서 "
    "잘린 값이 들어가요. 꼭 더블클릭한 뒤 전체선택(`Ctrl`+`A`)으로 복사해주세요."
)

# ⚠️ 라이엇은 재인증할 때마다 ssid를 새로 발급하고 이전 값을 무효화해요. 그래서 복사해두고
# 시간이 지나거나, 그 사이 라이엇 페이지가 갱신되거나 발로란트를 켜면 복사해둔 값이 죽어요.
# "되는 사람 / 안 되는 사람"이 갈리는 가장 큰 이유라서 따로 떼어 강조해요.
COOKIE_GUIDE_STEP3 = (
    "**`③ 쿠키 등록`** 버튼을 눌러 복사한 값을 붙여넣으면 끝이에요.\n"
    "`ssid=eyJ...` 형태가 정석이지만, **값만 붙여넣어도** 봇이 알아서 처리해요.\n\n"
    "⏱️ **복사한 즉시 붙여넣어 주세요.**\n"
    "라이엇은 로그인 세션이 갱신될 때마다 이 값을 새로 발급하고 **예전 값을 즉시 못 쓰게** 해요. "
    "복사해두고 딴짓을 하거나, 그 사이에 **라이엇 페이지를 새로고침**하거나 **발로란트를 켜면** "
    "복사한 값이 죽어서 `만료됐다`는 안내가 떠요.\n\n"
    "-# 💡 등록하기 전에 **발로란트와 라이엇 클라이언트를 꺼두면** 훨씬 잘 돼요."
)

COOKIE_GUIDE_TROUBLE = (
    "**`ssid`가 없다고 나와요**\n"
    "-# 왼쪽 목록에서 고른 주소가 `auth.riotgames.com` 이 맞는지 확인해주세요. "
    "`playvalorant.com`이나 `riotgames.com`에는 `ssid`가 없어요.\n"
    "-# 로그인을 안 한 상태여도 안 보여요. 먼저 로그인부터 해주세요.\n\n"
    "**값이 잘렸다고 나와요**\n"
    "-# 드래그 대신 값 칸을 **더블클릭 → `Ctrl`+`A` → `Ctrl`+`C`** 로 복사해주세요.\n\n"
    "**만료됐다고 나와요**\n"
    "-# 발로란트·라이엇 클라이언트를 끄고 → 라이엇 페이지에서 **다시 로그인** → "
    "값을 **새로 복사해서 바로** 등록해보세요. 한 번 실패한 값은 다시 시도해도 안 살아나요.\n\n"
    "**계속 안 돼요**\n"
    "-# 쿠키 등록은 안 해도 괜찮아요. `/오상` → **`① 라이엇 로그인하기`** → "
    "**`② 로그인 후 URL 붙여넣기`** 로 매번 조회하는 방법이 그대로 있어요."
)

COOKIE_GUIDE_SAFETY = (
    "⚠️ 이 값은 **로그인된 본인 계정 그 자체**예요. 다른 사람이나 다른 봇에게 절대 주지 마세요.\n"
    "-# 봇은 이 값을 암호화해서 보관하고, 상점 조회 외에는 쓰지 않아요.\n"
    "-# 등록 해제는 `/오상쿠키삭제` 로 언제든 할 수 있어요."
)


def _build_cookie_guide_embed() -> discord.Embed:
    """`❔ 쿠키 등록 방법` 버튼에서 보여주는 안내예요. 한 덩어리 글이면 안 읽혀서 단계별로 쪼갰어요."""
    embed = discord.Embed(
        title="🍪 쿠키 등록 방법",
        description=COOKIE_GUIDE_INTRO,
        color=0xFF4655,
    )
    embed.add_field(name="1️⃣ 개발자도구 열기 (F12 없어도 돼요)", value=COOKIE_GUIDE_STEP1, inline=False)
    embed.add_field(name="2️⃣ ssid 값 복사하기", value=COOKIE_GUIDE_STEP2, inline=False)
    embed.add_field(name="3️⃣ 봇에 붙여넣기 — 복사하고 바로!", value=COOKIE_GUIDE_STEP3, inline=False)
    embed.add_field(name="😵 안 될 때 확인할 것", value=COOKIE_GUIDE_TROUBLE, inline=False)
    embed.add_field(name="🔒 안전 안내", value=COOKIE_GUIDE_SAFETY, inline=False)
    return embed


class StartView(TimeoutDisablingView):
    def __init__(self, public: bool = True):
        super().__init__(timeout=600)
        self.public = public
        self.add_item(discord.ui.Button(label="① 라이엇 로그인하기", style=discord.ButtonStyle.link, url=LOGIN_URL))

    @discord.ui.button(label="② 로그인 후 URL 붙여넣기", style=discord.ButtonStyle.primary)
    async def paste_url(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PasteUrlModal(public=self.public))

    @discord.ui.button(label="③ 쿠키 등록(선택, ~1달 자동)", style=discord.ButtonStyle.secondary)
    async def register_cookie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterCookieModal(public=self.public))

    @discord.ui.button(label="❔ 쿠키 등록 방법", style=discord.ButtonStyle.secondary)
    async def cookie_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=_build_cookie_guide_embed(), ephemeral=True)


def _build_wishlist_alert_embed(
    hits: list[str],
    nightmarket_hits: list[tuple[str, int, int, bool]],
    account_label: str = "",
) -> discord.Embed:
    """위시리스트에 담아둔 스킨이 상점/야시장에 떴을 때 DM으로 보내는 임베드예요.
    계정을 여러 개 등록해둔 사람에겐 어느 계정 상점인지 같이 알려줘요."""
    embed = discord.Embed(
        title="🔔 위시리스트 스킨이 상점에 떴어요!",
        color=0xFF4655,
    )
    if account_label:
        embed.set_author(name=account_label)

    if hits:
        embed.add_field(
            name="🔫 오늘의 상점",
            value="\n".join(f"• **{name}**" for name in hits),
            inline=False,
        )
    if nightmarket_hits:
        lines = []
        for name, discounted, percent, is_seen in nightmarket_hits:
            if not percent:
                lines.append(f"• **{name}**")
                continue
            price = f"{discounted:,} VP (🔻 {percent}% 할인)"
            # 게임에서 아직 카드를 안 깐 스킨은 상점 화면과 똑같이 가려요. 알림 때문에
            # 카드 까는 재미를 뺏으면 안 되니까, 이름만 알려주고 가격은 눌러야 보이게 해요.
            lines.append(f"• **{name}** — {price}" if is_seen else f"• **{name}** — 🎴 아직 안 깐 카드 ||{price}||")
        embed.add_field(name="🌙 야시장", value="\n".join(lines), inline=False)

    thumb = valorant_skins.icon_for_name((nightmarket_hits[0][0] if nightmarket_hits else hits[0]))
    if thumb and thumb.get("icon"):
        embed.set_thumbnail(url=thumb["icon"])

    embed.set_footer(text="자세한 가격은 /오상 으로 확인하세요 · 알림 해제는 /위시리스트 비우기")
    return embed


def _nightmarket_hits(storefront: dict, wanted: list[str]) -> list[tuple[str, int, int, bool]]:
    """야시장에 뜬 위시리스트 스킨을 (이름, 할인가, 할인율, 카드깠는지)로 뽑아요.
    is_seen은 DM에서도 상점 화면과 똑같이 스포일러 처리를 하려고 같이 넘겨요."""
    bonus_store = storefront.get("BonusStore") or {}
    hits = []
    for entry in bonus_store.get("BonusStoreOffers") or []:
        offer = entry.get("Offer") or {}
        rewards = offer.get("Rewards") or []
        if not rewards:
            continue
        info = valorant_skins.get(rewards[0].get("ItemID"))
        name = info.get("name") if info else None
        if name and name in wanted:
            hits.append((
                name,
                _first_cost(entry.get("DiscountCosts")),
                entry.get("DiscountPercent") or 0,
                entry.get("IsSeen") is not False,
            ))
    return hits


class MyShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 놓친 재인증 따라잡기는 이 프로세스에서 딱 한 번만 해요. 루프가 예외로 죽어서
        # 다시 켜질 때마다 따라잡으려 들면, 실패가 반복될 때 무한히 재시도하게 돼요.
        self._refresh_catchup_done = False
        self.refresh_sessions.start()
        self.check_wishlists.start()

    def cog_unload(self):
        self.refresh_sessions.cancel()
        self.check_wishlists.cancel()

    # ── 위시리스트 ────────────────────────────────────────────────────────────
    wishlist = app_commands.Group(
        name="위시리스트", description="원하는 발로란트 스킨을 등록해두면 상점에 뜬 날 DM으로 알려줘요."
    )

    @wishlist.command(name="추가", description="원하는 스킨을 위시리스트에 담아요.")
    @app_commands.describe(스킨="스킨 이름 (입력하면 자동완성이 떠요)")
    async def wishlist_add(self, interaction: discord.Interaction, 스킨: str):
        # _ensure_static_data()는 캐시가 비어있으면 스킨 목록을 네트워크로 받아와요.
        # 3초를 넘길 수 있으니 먼저 defer해둬요.
        await interaction.response.defer(ephemeral=True)

        await _ensure_static_data()
        if 스킨 not in valorant_skins.all_names():
            await interaction.followup.send(
                f"**{스킨}** 이라는 스킨을 못 찾았어요. 자동완성 목록에서 골라주세요.", ephemeral=True
            )
            return

        ok, message = wishlist_store.add_skin(interaction.user.id, 스킨)
        if ok and not riot_session_store.has_session(interaction.user.id):
            message += (
                "\n-# ⚠️ 자동 알림을 받으려면 `/오상`에서 **쿠키 등록**을 해두셔야 해요"
                " (봇이 매일 대신 상점을 확인해야 하거든요)."
            )
        if ok and wishlist_store.is_dm_blocked(interaction.user.id):
            message += f"\n{_DM_BLOCKED_TIP}"
        await interaction.followup.send(message, ephemeral=True)

    @wishlist_add.autocomplete("스킨")
    async def wishlist_add_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        await _ensure_static_data()
        # 이미 가진 스킨은 지우지 않고 표시만 해요. 목록에서 아예 빼버리면 "왜 검색이 안 되지?"
        # 하고 헷갈리거든요. 라벨만 바꾸고 실제 값(value)은 스킨 이름 그대로 보내요.
        owned = _owned_names_any(interaction.user.id)
        choices = []
        for name in valorant_skins.search_names(current, limit=25):
            label = f"{name} (이미 보유)" if name in owned else name
            choices.append(app_commands.Choice(name=label[:100], value=name[:100]))
        return choices

    @wishlist.command(name="삭제", description="위시리스트에서 스킨을 빼요.")
    @app_commands.describe(스킨="빼고 싶은 스킨 이름")
    async def wishlist_remove(self, interaction: discord.Interaction, 스킨: str):
        _, message = wishlist_store.remove_skin(interaction.user.id, 스킨)
        await interaction.response.send_message(message, ephemeral=True)

    @wishlist_remove.autocomplete("스킨")
    async def wishlist_remove_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """삭제할 땐 본인이 등록해둔 것만 보여줘요."""
        current = (current or "").lower()
        return [
            app_commands.Choice(name=name[:100], value=name[:100])
            for name in wishlist_store.get_skins(interaction.user.id)
            if current in name.lower()
        ][:25]

    @wishlist.command(name="목록", description="내 위시리스트를 봐요.")
    async def wishlist_list(self, interaction: discord.Interaction):
        skins = wishlist_store.get_skins(interaction.user.id)
        if not skins:
            await interaction.response.send_message(
                "위시리스트가 비어있어요. `/위시리스트 추가` 로 원하는 스킨을 담아보세요.", ephemeral=True
            )
            return

        owned = _owned_names_any(interaction.user.id)
        embed = discord.Embed(
            title="⭐ 내 위시리스트",
            description="\n".join(
                f"{i}. **{name}**" + ("  ·  🎒 이미 보유 (알림 안 가요)" if name in owned else "")
                for i, name in enumerate(skins, start=1)
            ),
            color=0xFF4655,
        )
        check_time = WISHLIST_CHECK_TIME.strftime("%H:%M")
        if not riot_session_store.has_session(interaction.user.id):
            embed.set_footer(text="⚠️ 자동 알림을 받으려면 /오상에서 쿠키 등록이 필요해요.")
        elif wishlist_store.is_dm_blocked(interaction.user.id):
            embed.description += f"\n\n{_DM_BLOCKED_TIP}"
            embed.set_footer(text="⚠️ DM이 막혀 있어서 알림을 못 보내고 있어요.")
        else:
            embed.set_footer(text=f"매일 {check_time}에 확인해서, 떴으면 DM으로 알려드려요.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @wishlist.command(name="비우기", description="위시리스트를 전부 비워요(알림도 꺼져요).")
    async def wishlist_clear(self, interaction: discord.Interaction):
        count = wishlist_store.clear(interaction.user.id)
        if count:
            await interaction.response.send_message(f"🧹 위시리스트 {count}개를 전부 비웠어요.", ephemeral=True)
        else:
            await interaction.response.send_message("이미 비어있어요.", ephemeral=True)

    @tasks.loop(time=WISHLIST_CHECK_TIME)
    async def check_wishlists(self):
        """등록된 유저들의 상점을 대신 조회해서, 위시리스트 스킨이 떴으면 DM으로 알려줘요.
        쿠키를 등록해둔 유저만 대상이에요(대신 조회하려면 세션이 필요해서)."""
        watchers = wishlist_store.all_watchers()
        if not watchers:
            return

        await _ensure_static_data()
        today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
        checked = notified = 0

        for discord_id, wanted in watchers.items():
            # ⚠️ 한 사람을 처리하다 예외가 새어나오면 남은 사람들이 통째로 스킵되는 걸로
            #    끝나지 않고, 이 @tasks.loop 자체가 영구 정지해요(discord.py는 예상 못한
            #    예외가 난 루프를 되살리지 않아요). 그러면 다음날부터 알림이 아예 안 가고,
            #    로그 한 줄 말고는 아무도 눈치채지 못해요. 그래서 사람 단위로 가둬둬요.
            try:
                did_check, did_notify = await self._check_one_watcher(discord_id, wanted, today)
            except Exception as error:  # noqa: BLE001
                log.warning(
                    f"⚠️ 위시리스트 확인 실패(이 사람만 건너뜀): {discord_id} — {error!r}"
                )
                continue
            checked += did_check
            notified += did_notify

        if checked:
            log.info(f"⭐ 위시리스트 확인: 계정 {checked}개 조회, {notified}명에게 알림 전송")

    async def _check_one_watcher(
        self, discord_id: int, wanted: list[str], today: str
    ) -> tuple[int, int]:
        """위시리스트를 걸어둔 한 사람 몫만 처리해요. (조회한 계정 수, 알림 보낸 수).

        위 루프가 사람 단위로 예외를 가두려고 따로 뺀 함수예요."""
        if wishlist_store.was_notified_today(discord_id, today):
            return 0, 0
        accounts = riot_session_store.list_accounts(discord_id)
        if not accounts:
            return 0, 0  # 쿠키 미등록 유저는 대신 조회할 수 없어요.

        checked = 0

        # 계정을 여러 개 등록해뒀으면 전부 확인해요. 부계 상점에 뜬 걸 놓치면
        # 위시리스트를 걸어둔 의미가 없으니까요. DM은 계정별로 따로 보내지 않고
        # 아래에서 임베드만 여러 장으로 묶어서 하루 한 통으로 보내요.
        alerts: list[discord.Embed] = []
        multi = len(accounts) > 1
        for account in accounts:
            account_key = account["key"]
            cookie_header = riot_session_store.get_session(discord_id, account_key)
            if not cookie_header:
                continue

            result, session = await riot_auth.reauth_with_cookies(cookie_header)
            try:
                if not result.ok:
                    continue  # 만료된 세션은 새벽 4시 갱신 루프 쪽에서 정리돼요.
                # 여기서도 회전된 쿠키를 저장해둬야 해요. 안 그러면 이 조회가 라이엇 쪽 ssid를
                # 돌려버린 뒤라, 정작 유저가 /오상을 부르면 낡은 쿠키로 만료 판정이 나요.
                riot_auth.persist_refreshed_cookie(discord_id, result, account_key)
                storefront, _wallet, owned, _error = await _fetch_storefront(
                    session, result.access_token, result.id_token, who=str(discord_id)
                )
            finally:
                await session.close()

            if storefront is None:
                continue

            # 매일 도는 루프라, 여기서 갱신해두면 /오상을 안 써도 보유 정보가 최신으로 유지돼요.
            _remember_owned(discord_id, account_key, owned)

            checked += 1

            # 이미 가진 스킨은 알려봤자 살 일이 없어서 알림에서 빼요. 보유 판정은 그 계정
            # 기준이에요(본계로 가진 스킨이 부계 상점에 떴으면 부계엔 여전히 살 만해요).
            # 보유 조회에 실패했으면 빈 집합이라 아무것도 안 걸러지고 전부 알려줘요.
            owned_names = _owned_names(discord_id, account_key)
            hits = [
                name for name in _offered_skin_names(storefront)
                if name in wanted and name not in owned_names
            ]
            night_hits = [
                hit for hit in _nightmarket_hits(storefront, wanted)
                if hit[0] not in owned_names
            ]
            if hits or night_hits:
                alerts.append(
                    _build_wishlist_alert_embed(
                        hits, night_hits,
                        account_label=account["label"] if multi else "",
                    )
                )

            # 라이엇 API를 연달아 두들기지 않도록 계정마다 조금씩 쉬어요.
            await asyncio.sleep(2)

        if not alerts:
            wishlist_store.mark_notified(discord_id, today)
            return checked, 0

        user = self.bot.get_user(discord_id)
        if user is None:
            # 계정이 삭제됐으면 NotFound(HTTPException의 한 종류)가 나요. 예전엔 이게
            # 그대로 위로 튀어서 루프를 죽일 수 있었어요.
            try:
                user = await self.bot.fetch_user(discord_id)
            except discord.HTTPException as error:
                log.warning(f"⚠️ 위시리스트 알림 대상 조회 실패: {discord_id} — {error}")
                return checked, 0
        if user is None:
            wishlist_store.mark_notified(discord_id, today)
            return checked, 0

        try:
            await user.send(embeds=alerts)
            wishlist_store.mark_notified(discord_id, today)
            wishlist_store.set_dm_blocked(discord_id, False)
            return checked, 1
        except discord.Forbidden:
            # DM을 아예 막아둔 경우예요. 다시 시도해도 똑같이 막히니까 오늘은 처리한
            # 걸로 두고, 대신 표시를 남겨서 /위시리스트에서 본인에게 알려줘요.
            log.warning(f"⚠️ 위시리스트 알림 DM 실패(차단/DM 비허용): {discord_id}")
            wishlist_store.mark_notified(discord_id, today)
            wishlist_store.set_dm_blocked(discord_id, True)
        except discord.HTTPException as error:
            # 일시적인 실패(디스코드 장애 등)라 오늘 처리 완료로 찍지 않아요.
            # 그래야 봇이 재시작돼 루프가 다시 돌 때 한 번 더 시도해요.
            log.warning(f"⚠️ 위시리스트 알림 DM 실패: {discord_id} — {error}")
        return checked, 0

    @check_wishlists.before_loop
    async def before_check_wishlists(self):
        await self.bot.wait_until_ready()

    @check_wishlists.error
    async def check_wishlists_error(self, error: BaseException):
        """루프 밖(위 for를 감싸는 코드)에서 예외가 나면 discord.py는 루프를 끄고 끝내요.
        여기서 받아서 다시 켜둬요. time= 루프라 재시작해도 곧바로 또 돌지 않고
        다음 예정 시각까지 기다려서, 예외가 반복돼도 폭주하지 않아요."""
        log.error(f"🚨 위시리스트 루프가 예외로 멈췄어요 — 다시 켤게요: {error!r}", exc_info=error)
        self.check_wishlists.restart()

    @tasks.loop(time=SESSION_REFRESH_TIME)
    async def refresh_sessions(self):
        await self._run_session_refresh()

    async def _run_session_refresh(self):
        """등록된 세션 전부를 재인증해요. 매일 04시 루프와 '놓친 날 따라잡기'가 같이 써요."""
        refreshed, expired, failed = await riot_auth.refresh_all_stored_sessions()
        # 여기까지 왔으면 한 바퀴는 돈 거예요(계정별 실패는 위에서 이미 세고 넘어갔어요).
        _mark_refreshed()
        if refreshed or expired or failed:
            log.info(
                f"🔫 오상 세션 자동 재인증: 갱신 {refreshed}건, 만료(재로그인 필요) {expired}건, "
                f"일시 실패(유지) {failed}건"
            )

    @refresh_sessions.before_loop
    async def before_refresh_sessions(self):
        await self.bot.wait_until_ready()
        # 04시에 봇이 꺼져 있었거나 배포 중이었으면 그날 재인증이 통째로 빠져요. 그걸
        # 여기서 메워요. 플래그를 돌리기 **전에** 세워서, 따라잡기가 실패해도 재시작
        # 때마다 다시 시도하는 일은 없게 해요.
        if self._refresh_catchup_done:
            return
        self._refresh_catchup_done = True
        try:
            if _refresh_is_overdue():
                log.info("🔫 오상 세션 재인증을 놓친 날이 있어서 지금 한 번 따라잡을게요.")
                await self._run_session_refresh()
        except Exception as error:  # noqa: BLE001
            # before_loop에서 예외가 새어나가면 루프가 아예 시작되지 않아요. 꼭 잡아야 해요.
            log.warning(f"⚠️ 오상 세션 재인증 따라잡기 실패: {error!r}")

    @refresh_sessions.error
    async def refresh_sessions_error(self, error: BaseException):
        """04시 재인증 루프가 예외로 멈추면 조용히 끝나버려요(디스코드에도 로그에도
        티가 안 나요). 며칠 지나면 쿠키가 순서대로 만료되니 여기서 다시 켜둬요."""
        log.error(f"🚨 오상 재인증 루프가 예외로 멈췄어요 — 다시 켤게요: {error!r}", exc_info=error)
        self.refresh_sessions.restart()

    @app_commands.command(
        name="오상",
        description="⚠️본인 라이엇 계정으로 로그인해서 개인 오늘의 상점(4개 로테이션)을 봐요.",
    )
    @app_commands.describe(공개="끄면 나만 보이게 조회해요 (기본: 채널에 공개)")
    @require_shop_channel()
    async def my_shop(self, interaction: discord.Interaction, 공개: bool = True):
        # 계정을 여러 개 등록해뒀으면 '마지막으로 본 계정'이 떠요. 다른 계정은 상점 화면의
        # 👤 계정 버튼으로 오갈 수 있고, 거기서 고른 계정이 다음 기본값이 돼요.
        account_key = riot_session_store.default_account_key(interaction.user.id)
        if account_key:
            # defer도 공개 여부를 따라가야 해요. 여기를 공개로 고정해두면 공개:False로 불러도
            # "생각 중…" 표시가 채널에 그대로 노출돼서, 숨기려던 의도가 절반 깨져요.
            await interaction.response.defer(ephemeral=not 공개)

            # 방금 본 상점이면 라이엇을 다시 부르지 않고 바로 보여줘요(몇 초 → 즉시).
            payload, error = await _load_shop_for_account(interaction.user.id, account_key)
            if payload is None:
                await interaction.followup.send(error, ephemeral=True)
                return
            await _render_shop(interaction, payload, public=공개, account_key=account_key)
            return

        embed = discord.Embed(
            title="🔫 오상 · 오늘의 상점 확인하기",
            description=(
                "① 아래 **라이엇 로그인하기** 버튼으로 실제 로그인 페이지를 열어 직접 로그인해주세요.\n"
                "② 로그인 완료 후 뜨는 흰 화면(playvalorant.com...) **주소창 URL 전체**를 복사하세요.\n"
                "③ **② 로그인 후 URL 붙여넣기** 버튼을 눌러 그 URL을 붙여넣으면 바로 오늘의 상점을 보여드려요.\n\n"
                "-# 매번 로그인하기 번거로우면 **③ 쿠키 등록**으로 한 번만 등록해두세요(약 한 달간 로그인 없이 바로 조회 가능).\n"
                "-# 비밀번호는 저장하지 않고 그 자리에서만 써요.\n\n"
                + LOGIN_TROUBLE_TIP
            ),
            color=0xFF4655,
        )
        view = StartView(public=공개)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        try:
            view.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            pass

    @app_commands.command(name="오상쿠키삭제", description="등록해둔 라이엇 로그인 쿠키를 봇에서 지워요.")
    async def delete_cookie(self, interaction: discord.Interaction):
        accounts = riot_session_store.list_accounts(interaction.user.id)
        if not accounts:
            await interaction.response.send_message("등록해둔 쿠키가 없어요.", ephemeral=True)
            return

        # 계정이 하나뿐이면 물어볼 게 없어요. 예전처럼 바로 지워요.
        if len(accounts) == 1:
            _forget_account_data(interaction.user.id, accounts[0]["key"])
            riot_session_store.delete_session(interaction.user.id, accounts[0]["key"])
            await interaction.response.send_message(
                "🗑️ 등록해둔 쿠키를 지웠어요. 이제 `/오상`은 매번 로그인 방식으로 동작해요.", ephemeral=True
            )
            return

        view = DeleteAccountView(interaction.user.id, accounts)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🗑️ 오상 · 등록 해제할 계정",
                description=(
                    "\n".join(f"• **{account['label']}**" for account in accounts)
                    + "\n\n지울 계정을 고르세요. 전부 지우려면 아래 버튼을 눌러요."
                ),
                color=0xFF4655,
            ),
            view=view,
            ephemeral=True,
        )
        try:
            view.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(MyShop(bot))
