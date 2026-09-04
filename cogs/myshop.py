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
import os
import time
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.channel_check import restrict_to_channel
from utils import (
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
# 마지막으로 조회한 결과를 유저별로 메모리에 담아둬요. 봇이 재시작되면 비워지는데,
# 그땐 표시가 안 될 뿐이라 동작에는 지장이 없어요.
_owned_skin_names: dict[int, set[str]] = {}


def _remember_owned(discord_id: int, owned_ids: set[str] | None):
    """보유 스킨 UUID를 이름 집합으로 바꿔서 기억해둬요. 조회 실패(None)면 기존 값을 유지해요."""
    if owned_ids is None:
        return
    names = set()
    for item_id in owned_ids:
        info = valorant_skins.get(item_id)
        if info and info.get("name"):
            names.add(info["name"])
    _owned_skin_names[discord_id] = names


def _owned_names(discord_id: int) -> set[str]:
    return _owned_skin_names.get(discord_id, set())


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
    ):
        super().__init__(timeout=600)
        self.shop_embeds = shop_embeds
        self._public = public
        self._owner_id = owner_id  # 이 상점을 부른 사람. 새로고침은 본인만 할 수 있어요.
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
        # 새로고침은 봇이 대신 다시 조회할 수 있어야(=쿠키 등록) 되는 기능이에요.
        if not can_refresh:
            self.remove_item(self.refresh_shop)

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
        _invalidate_shop_cache(self._owner_id)

        cookie_header = riot_session_store.get_session(self._owner_id)
        if not cookie_header:
            await interaction.followup.send(
                "등록해둔 쿠키가 없어서 다시 조회할 수 없어요. `/오상`을 다시 실행해주세요.",
                ephemeral=True,
            )
            return

        result, session = await riot_auth.reauth_with_cookies(cookie_header)
        try:
            if not result.ok:
                riot_session_store.delete_session(self._owner_id)
                await interaction.followup.send(
                    "등록해둔 로그인이 만료됐어요. `/오상`으로 다시 로그인(또는 쿠키 재등록)해주세요.",
                    ephemeral=True,
                )
                return
            storefront, wallet, owned, error = await _fetch_storefront(
                session, result.access_token, result.id_token
            )
        finally:
            await session.close()

        if storefront is None:
            await interaction.followup.send(error, ephemeral=True)
            return

        _remember_owned(self._owner_id, owned)
        riot_id = riot_auth.riot_id_from_id_token(result.id_token) or ""
        _cache_shop(self._owner_id, storefront, wallet, owned, riot_id)

        # 원래 메시지를 그 자리에서 갈아끼워요(새 메시지를 또 쌓지 않게).
        embeds = _fit_embeds(
            _build_shop_embeds(interaction.user, storefront, riot_id, wallet, owned)
        )
        view = ShopResultView(
            embeds, storefront, wallet, owned,
            can_refresh=True, public=self._public, owner_id=self._owner_id,
        )
        await interaction.edit_original_response(embeds=embeds, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:  # noqa: BLE001
            view.message = interaction.message


# ── 상점 결과 캐시 ──────────────────────────────────────────────────────────
# /오상 한 번에 라이엇 왕복이 재인증·지역·권한·상점·지갑·보유스킨까지 여러 번 일어나요.
# 상점 로테이션은 하루에 한 번만 바뀌니 원칙적으론 길게 캐시해도 되지만, **지갑 잔액과
# 보유 스킨은 유저가 게임에서 스킨을 사면 바로 바뀌어요.** 사고 나서 다시 불렀는데 옛날
# 잔액이 뜨면 오히려 잘못된 정보라, 짧게만 캐시하고 "새로고침" 버튼으로 직접 갱신할 수
# 있게 했어요. (로테이션 갱신이 5분 안 남았으면 그 시각에 맞춰 더 짧게 잡아요.)
_SHOP_CACHE_TTL_SECONDS = 300

_shop_cache: dict[int, dict] = {}


def _cache_shop(discord_id: int, storefront: dict, wallet: dict | None, owned: set[str] | None, riot_id: str):
    panel = storefront.get("SkinsPanelLayout") or {}
    remaining = panel.get("SingleItemOffersRemainingDurationInSeconds") or 0
    ttl = _SHOP_CACHE_TTL_SECONDS
    if 0 < remaining < ttl:
        ttl = remaining  # 로테이션이 곧 바뀌면 그 전까지만 써요.

    # 안 쓰는 사람 몫이 계속 쌓이지 않게, 저장할 때 만료된 것들을 같이 치워요.
    now = time.monotonic()
    for expired_id in [key for key, value in _shop_cache.items() if now >= value["expires"]]:
        _shop_cache.pop(expired_id, None)

    _shop_cache[discord_id] = {
        "expires": time.monotonic() + ttl,
        "storefront": storefront,
        "wallet": wallet,
        "owned": owned,
        "riot_id": riot_id,
    }


def _get_cached_shop(discord_id: int) -> dict | None:
    entry = _shop_cache.get(discord_id)
    if entry is None:
        return None
    if time.monotonic() >= entry["expires"]:
        _shop_cache.pop(discord_id, None)
        return None
    return entry


def _invalidate_shop_cache(discord_id: int):
    _shop_cache.pop(discord_id, None)


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
    session, access_token: str, id_token: str
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
        riot_auth.get_region(session, access_token, id_token),
        riot_auth.get_entitlement(session, access_token),
        return_exceptions=True,
    )
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
    storefront: dict,
    wallet: dict | None,
    owned: set[str] | None,
    riot_id: str,
    public: bool = True,
    can_refresh: bool = False,
) -> bool:
    """이미 받아온 상점 데이터를 화면으로 그려요. 새로 조회한 경우와 캐시를 쓴 경우가
    똑같은 화면을 내도록 여기 한 곳에서만 만들어요."""
    # 기본값은 제트봇처럼 채널에 공개로 올려요(로그인 과정 자체만 항상 본인만 보이게 처리).
    embeds = _fit_embeds(_build_shop_embeds(interaction.user, storefront, riot_id, wallet, owned))
    view = ShopResultView(
        embeds, storefront, wallet, owned,
        can_refresh=can_refresh, public=public, owner_id=interaction.user.id,
    )
    message = await interaction.followup.send(embeds=embeds, view=view, ephemeral=not public, wait=True)
    view.message = message
    return True


async def _send_shop(
    interaction: discord.Interaction, session, access_token: str, id_token: str, public: bool = True
) -> bool:
    """access_token/id_token으로 상점까지 조회해서 결과를 보여줘요. 성공하면 True."""
    storefront, wallet, owned, error = await _fetch_storefront(session, access_token, id_token)
    if storefront is None:
        await interaction.followup.send(error, ephemeral=True)
        return False

    # 위시리스트 자동완성에서도 "이미 보유"를 알려주려고 결과를 기억해둬요.
    _remember_owned(interaction.user.id, owned)

    riot_id = riot_auth.riot_id_from_id_token(id_token) or ""
    # 쿠키를 등록해둔 유저만 봇이 알아서 다시 조회할 수 있어서, 그 경우에만 캐시해요.
    can_refresh = riot_session_store.has_session(interaction.user.id)
    if can_refresh:
        _cache_shop(interaction.user.id, storefront, wallet, owned, riot_id)
    return await _render_shop(
        interaction, storefront, wallet, owned, riot_id, public=public, can_refresh=can_refresh
    )


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
        placeholder="ssid=eyJhbGciOi... 형태로 붙여넣으면 돼요. 자세한 방법은 '쿠키 등록 방법' 버튼을 눌러보세요.",
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
            await interaction.followup.send(
                f"❌ {result.error or '등록에 실패했어요.'} Cookie 값을 다시 확인해서 시도해주세요.", ephemeral=True
            )
            return

        try:
            ok = await _send_shop(
                interaction, session, result.access_token, result.id_token, public=self.public
            )
        finally:
            await session.close()

        if ok:
            riot_session_store.save_session(interaction.user.id, cookie_header)
            await interaction.followup.send(
                "✅ 쿠키가 등록됐어요. 이제부터는 로그인 없이 `/오상`만 실행하면 돼요(약 한 달간, 만료되면 다시 등록).",
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):  # noqa: D401
        log.warning(f"⚠️ 오상 쿠키 등록 중 오류: {error}")
        if interaction.response.is_done():
            await interaction.followup.send("처리 중 오류가 발생했어요.", ephemeral=True)
        else:
            await interaction.response.send_message("처리 중 오류가 발생했어요.", ephemeral=True)


COOKIE_GUIDE = (
    "**쿠키를 한 번 등록해두면** 그 다음부터는 `/오상`만 치면 바로 상점이 떠요 "
    "(쿠키가 만료되는 약 한 달 뒤까지, 매일 새벽 4시에 봇이 알아서 갱신해요).\n"
    "비밀번호는 받지도 저장하지도 않고, 등록한 쿠키는 암호화해서 보관해요.\n\n"
    "**PC 크롬 기준 방법**\n"
    "① 크롬에서 <https://auth.riotgames.com/login> 접속 후 **로그인**\n"
    "② `F12` (또는 `Ctrl+Shift+I`) 눌러 개발자도구 열기\n"
    "③ 위쪽 탭에서 **Application**(응용 프로그램) 선택\n"
    "④ 왼쪽 목록에서 **Storage → Cookies → https://auth.riotgames.com** 클릭\n"
    "⑤ 목록에서 **`ssid`** 를 찾아 **Value(값)** 칸을 더블클릭 → 전체 복사\n"
    "⑥ **③ 쿠키 등록** 버튼을 눌러 `ssid=복사한값` 형태로 붙여넣기\n\n"
    "-# ⚠️ 이 값은 로그인된 본인 계정 그 자체예요. 절대 다른 사람이나 다른 봇에 주지 마세요.\n"
    "-# 등록 해제는 `/오상쿠키삭제` 로 언제든 할 수 있어요."
)


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
        embed = discord.Embed(title="🍪 쿠키 등록 방법", description=COOKIE_GUIDE, color=0xFF4655)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _build_wishlist_alert_embed(
    hits: list[str], nightmarket_hits: list[tuple[str, int, int, bool]]
) -> discord.Embed:
    """위시리스트에 담아둔 스킨이 상점/야시장에 떴을 때 DM으로 보내는 임베드예요."""
    embed = discord.Embed(
        title="🔔 위시리스트 스킨이 상점에 떴어요!",
        color=0xFF4655,
    )

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
        owned = _owned_names(interaction.user.id)
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

        owned = _owned_names(interaction.user.id)
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
            if wishlist_store.was_notified_today(discord_id, today):
                continue
            cookie_header = riot_session_store.get_session(discord_id)
            if not cookie_header:
                continue  # 쿠키 미등록 유저는 대신 조회할 수 없어요.

            result, session = await riot_auth.reauth_with_cookies(cookie_header)
            try:
                if not result.ok:
                    continue  # 만료된 세션은 새벽 4시 갱신 루프 쪽에서 정리돼요.
                storefront, _wallet, owned, _error = await _fetch_storefront(
                    session, result.access_token, result.id_token
                )
            finally:
                await session.close()

            if storefront is None:
                continue

            # 매일 도는 루프라, 여기서 갱신해두면 /오상을 안 써도 보유 정보가 최신으로 유지돼요.
            _remember_owned(discord_id, owned)

            checked += 1

            # 이미 가진 스킨은 알려봤자 살 일이 없어서 알림에서 빼요.
            # 보유 조회에 실패했으면 빈 집합이라 아무것도 안 걸러지고 전부 알려줘요.
            owned_names = _owned_names(discord_id)
            hits = [
                name for name in _offered_skin_names(storefront)
                if name in wanted and name not in owned_names
            ]
            night_hits = [
                hit for hit in _nightmarket_hits(storefront, wanted) if hit[0] not in owned_names
            ]
            if not hits and not night_hits:
                wishlist_store.mark_notified(discord_id, today)
                continue

            user = self.bot.get_user(discord_id) or await self.bot.fetch_user(discord_id)
            if user is None:
                wishlist_store.mark_notified(discord_id, today)
                continue
            try:
                await user.send(embed=_build_wishlist_alert_embed(hits, night_hits))
                notified += 1
                wishlist_store.mark_notified(discord_id, today)
                wishlist_store.set_dm_blocked(discord_id, False)
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

            # 라이엇 API를 연달아 두들기지 않도록 유저마다 조금씩 쉬어요.
            await asyncio.sleep(2)

        if checked:
            log.info(f"⭐ 위시리스트 확인: {checked}명 조회, {notified}명에게 알림 전송")

    @check_wishlists.before_loop
    async def before_check_wishlists(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=SESSION_REFRESH_TIME)
    async def refresh_sessions(self):
        refreshed, expired = await riot_auth.refresh_all_stored_sessions()
        if refreshed or expired:
            log.info(f"🔫 오상 세션 자동 재인증: 갱신 {refreshed}건, 만료(재로그인 필요) {expired}건")

    @refresh_sessions.before_loop
    async def before_refresh_sessions(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="오상",
        description="⚠️본인 라이엇 계정으로 로그인해서 개인 오늘의 상점(4개 로테이션)을 봐요.",
    )
    @app_commands.describe(공개="끄면 나만 보이게 조회해요 (기본: 채널에 공개)")
    @require_shop_channel()
    async def my_shop(self, interaction: discord.Interaction, 공개: bool = True):
        cookie_header = riot_session_store.get_session(interaction.user.id)
        if cookie_header:
            # defer도 공개 여부를 따라가야 해요. 여기를 공개로 고정해두면 공개:False로 불러도
            # "생각 중…" 표시가 채널에 그대로 노출돼서, 숨기려던 의도가 절반 깨져요.
            await interaction.response.defer(ephemeral=not 공개)

            # 방금 본 상점이면 라이엇을 다시 부르지 않고 바로 보여줘요(몇 초 → 즉시).
            cached = _get_cached_shop(interaction.user.id)
            if cached is not None:
                await _render_shop(
                    interaction,
                    cached["storefront"],
                    cached["wallet"],
                    cached["owned"],
                    cached["riot_id"],
                    public=공개,
                    can_refresh=True,
                )
                return

            result, session = await riot_auth.reauth_with_cookies(cookie_header)
            try:
                if not result.ok:
                    riot_session_store.delete_session(interaction.user.id)
                    _invalidate_shop_cache(interaction.user.id)
                    await interaction.followup.send(
                        "등록해둔 로그인이 만료됐어요. `/오상`으로 다시 로그인(또는 쿠키 재등록)해주세요.",
                        ephemeral=True,
                    )
                    return
                await _send_shop(interaction, session, result.access_token, result.id_token, public=공개)
            finally:
                await session.close()
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
        # 쿠키를 지우면 캐시에 남은 상점/잔액도 같이 지워야 해요(지웠는데 계속 보이면 곤란해요).
        _invalidate_shop_cache(interaction.user.id)
        _owned_skin_names.pop(interaction.user.id, None)
        if riot_session_store.delete_session(interaction.user.id):
            await interaction.response.send_message(
                "🗑️ 등록해둔 쿠키를 지웠어요. 이제 `/오상`은 매번 로그인 방식으로 동작해요.", ephemeral=True
            )
        else:
            await interaction.response.send_message("등록해둔 쿠키가 없어요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MyShop(bot))
