"""
라이엇 계정으로 "본인의 개인 오늘의 상점"을 가져오는 모듈이에요.

⚠️ 원래는 봇이 직접 아이디/비밀번호를 받아 라이엇 로그인 API를 흉내내는 방식으로
만들었었는데, 라이엇의 로그인 폼이 클라우드플레어 봇 탐지 + hCaptcha로 보호되어 있어서
자동화된 요청은 자격증명이 맞아도 항상 거부당해요(2026-08-27 확인). 이 보호를 우회하는
건 하지 않기로 했어요.

그래서 지금 방식은: 유저가 실제 브라우저에서 라이엇 공식 로그인 페이지를 직접 열어
로그인(hCaptcha도 본인이 직접 통과)하면, 로그인 성공 후 playvalorant.com으로 리다이렉트
되면서 주소창에 access_token/id_token이 담겨요. 유저가 그 URL을 복사해서 붙여넣으면
여기서는 그 토큰만 꺼내 쓰고, 비밀번호는 아예 받지도 저장하지도 않아요. 다만 토큰
(1시간 유효)이 만료되면 매번 다시 로그인해야 하는 게 번거로워서, 원하는 유저는 세션
쿠키(ssid)를 직접 복사해서 한 번만 등록해두면 그 쿠키로 재로그인(reauth_with_cookies)
해서 당분간(쿠키 자체가 만료되기 전까지, 대략 한 달 정도) 매번 로그인하지 않아도 돼요.
이 쿠키는 utils/riot_session_store.py에서 암호화해서 저장해요.

흐름: parse_redirect_url()로 토큰 추출 -> puuid_from_access_token() +
      get_region() + get_entitlement()으로 정보를 모아서 get_storefront()까지.
재로그인은 reauth_with_cookies()로 비밀번호 없이 쿠키만으로 처리해요.
"""
import logging
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl

from curl_cffi.requests import AsyncSession

log = logging.getLogger(__name__)

# ⚠️ "/api/v1/authorization"(클라이언트용 로그인 API, POST/PUT 다단계)가 아니라
# 브라우저 로그인과 동일한 "/authorize"(GET, 쿠키 세션으로 즉시 리다이렉트)를 써야 해요.
# 예전에 잘못 "/api/v1/authorization"으로 되어있어서 재인증이 매번 400으로 실패했었어요.
AUTH_URL = "https://auth.riotgames.com/authorize"
ENTITLEMENT_URL = "https://entitlements.auth.riotgames.com/api/token/v1"
GEO_URL = "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant"
VERSION_URL = "https://valorant-api.com/v1/version"


@dataclass
class LoginResult:
    ok: bool = False
    error: str = ""
    access_token: str = ""
    id_token: str = ""

# curl_cffi가 흉내낼 브라우저 TLS/HTTP2 지문이에요. 로그인 자체는 유저의 실제 브라우저가
# 하니까 이건 우회 목적이 아니라, 그냥 이후 API 호출에 쓰는 HTTP 클라이언트예요.
_IMPERSONATE = "chrome131"

# entitlements.auth.riotgames.com 등 인증 관련 엔드포인트는 원래 발로란트 게임 클라이언트만
# 호출하는 API라, 일반 브라우저 User-Agent로 요청하면 라이엇 쪽에서 이상 트래픽으로 걸러낼 수
# 있어요(2026-08-28, entitlement만 403으로 계속 막히는 현상 확인). 유명 오픈소스 발로란트
# 상점봇(SkinPeek)도 이 엔드포인트들엔 브라우저 UA 대신 실제 게임 클라이언트 서명을 써요.
_RIOT_CLIENT_USER_AGENT = "RiotClient/62.0.1.4909243.4789131 rso-auth (Windows;10;;Professional, x64)"


# Fly.io(데이터센터 IP)에서 entitlements.auth.riotgames.com만 계속 403으로 막혀서
# (2026-08-28, User-Agent 교체로도 해결 안 됨 확인) 주거용 프록시를 거쳐서 나가요.
# .env / flyctl secrets의 RIOT_PROXY_URL이 없으면 그냥 직접 나가요(로컬 개발용).
_PROXY_URL = os.environ.get("RIOT_PROXY_URL")

# ⚡ 그런데 프록시는 느려요. 2026-09-03에 Fly 머신에서 직접 재보니 게임 서버(pd.*.a.pvp.net)가
# 직접 연결 44ms vs 프록시 400~630ms 였어요. 정작 막히는 건 auth 계열 하나뿐이라, 게임 서버와
# valorant-api.com은 프록시를 안 태우고 직접 보내요. 같은 측정에서 직접 연결이 403(차단)이
# 아니라 400(인증 헤더 없음)을 돌려줘서 IP 차단이 없다는 것도 확인했어요.
#
# ⚠️ curl_cffi에서 "세션에 걸린 프록시"를 요청 하나만 무시하려면 `proxy=None`이 아니라
#    `proxies={"http": None, "https": None}`을 써야 해요. proxy=None은 세션 값으로 폴백돼서
#    그냥 프록시를 타요(실측으로 확인: proxy=None → 390ms, proxies=... → 45ms).
_DIRECT_PROXIES = {"http": None, "https": None}

# 문제가 생기면 재배포 없이 되돌릴 수 있는 비상 스위치예요.
#   flyctl secrets set RIOT_PROXY_SCOPE=all -a akgui-bot
# 로 바꾸면 머신이 재시작되면서 예전처럼 모든 호출이 프록시를 타요.
_PROXY_SCOPE = (os.environ.get("RIOT_PROXY_SCOPE") or "auth-only").strip().lower()


def _direct_kwargs() -> dict:
    """게임 서버/정적 API 호출에 붙일 kwargs.
    프록시를 안 쓰는 환경이거나 scope=all이면 빈 dict라 기존 동작 그대로예요."""
    if not _PROXY_URL or _PROXY_SCOPE == "all":
        return {}
    return {"proxies": _DIRECT_PROXIES}


async def _game_get(session: AsyncSession, url: str, **kwargs):
    """게임 서버 호출은 직접 연결이 기본이고, 혹시 라이엇이 데이터센터 IP를 막아서 403이
    돌아오면 그때만 프록시로 한 번 더 시도해요. 차단이 생겨도 기능이 죽지 않고 느려지기만 해요."""
    direct = _direct_kwargs()
    resp = await session.get(url, **kwargs, **direct)
    if direct and resp.status_code == 403:
        log.warning("⚠️ 게임 서버 직접 연결이 403이라 프록시로 재시도해요(차단 복귀 가능성).")
        resp = await session.get(url, **kwargs)
    return resp


async def _game_post(session: AsyncSession, url: str, **kwargs):
    """_game_get의 POST 판이에요(상점 조회가 POST라서요)."""
    direct = _direct_kwargs()
    resp = await session.post(url, **kwargs, **direct)
    if direct and resp.status_code == 403:
        log.warning("⚠️ 게임 서버 직접 연결이 403이라 프록시로 재시도해요(차단 복귀 가능성).")
        resp = await session.post(url, **kwargs)
    return resp


def new_session() -> AsyncSession:
    return AsyncSession(
        impersonate=_IMPERSONATE,
        timeout=15,
        headers={"User-Agent": _RIOT_CLIENT_USER_AGENT},
        proxy=_PROXY_URL,
    )


def parse_redirect_url(url: str) -> Optional[tuple[str, str]]:
    """로그인 후 리다이렉트된 전체 URL(유저가 복사해서 붙여넣은 것)에서
    access_token/id_token을 꺼내요. 토큰은 '#' 뒤 프래그먼트에 쿼리 형태로 들어있어요."""
    fragment = url.split("#", 1)[1] if "#" in url else url
    params = dict(parse_qsl(fragment))
    access_token = params.get("access_token")
    id_token = params.get("id_token")
    if not access_token or not id_token:
        return None
    return access_token, id_token


def _cookie_header_to_dict(cookie_header: str) -> dict:
    cookies = {}
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        key, _, value = part.strip().partition("=")
        cookies[key] = value
    return cookies


def _dict_to_cookie_header(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


async def reauth_with_cookies(cookie_header: str) -> tuple[LoginResult, AsyncSession]:
    """저장해둔 쿠키(ssid 등)로 비밀번호 없이 재로그인해요. 세션이 아직 살아있으면
    바로 access_token이 담긴 리다이렉트가 돌아오고, 만료됐으면 ok=False로 다시
    로그인(또는 쿠키 재등록)을 해달라고 해야 해요."""
    # DevTools에서 "cookie: ssid=..." 처럼 헤더 이름까지 통째로 복사해오는 실수를 방지해요.
    cookie_header = cookie_header.strip()
    if cookie_header.lower().startswith("cookie:"):
        cookie_header = cookie_header.split(":", 1)[1].strip()

    # Application 탭에서 ssid의 "값"만 복사해오는 경우도 많아요(ssid= 앞부분 없이 JWT만).
    # 그럴 땐 파싱 결과가 비어서 "세션 만료"라는 엉뚱한 안내가 나가니까 여기서 보정해요.
    if "=" not in cookie_header and cookie_header.startswith("eyJ"):
        cookie_header = f"ssid={cookie_header}"

    session = new_session()
    cookies = _cookie_header_to_dict(cookie_header)
    if not cookies:
        return (
            LoginResult(
                ok=False,
                error="쿠키 값을 읽지 못했어요. `ssid=eyJ...` 형태로 붙여넣어주세요.",
            ),
            session,
        )
    session.cookies = cookies
    try:
        resp = await session.get(
            AUTH_URL,
            params={
                "client_id": "play-valorant-web-prod",
                "nonce": "1",
                "redirect_uri": "https://playvalorant.com/opt_in",
                "response_type": "token id_token",
                "scope": "openid account",
            },
            allow_redirects=False,
        )
        location = resp.headers.get("Location", "")
    except Exception as error:  # noqa: BLE001
        return LoginResult(ok=False, error=f"라이엇 서버 연결에 실패했어요: {error}"), session

    parsed = parse_redirect_url(location)
    if not parsed:
        return LoginResult(ok=False, error="저장된 세션이 만료됐어요. 쿠키를 다시 등록해주세요."), session

    access_token, id_token = parsed
    return LoginResult(ok=True, access_token=access_token, id_token=id_token), session


async def refresh_stored_session(discord_id: int) -> bool:
    """등록해둔 쿠키로 재인증하고, 라이엇이 새로 내려준 쿠키로 다시 저장해요(SkinPeek 등의
    발로란트 봇들이 쓰는 방식과 동일: 매번 갱신된 쿠키로 덮어써서 만료 시점을 계속 미뤄요).
    성공하면 True, 쿠키가 아예 만료돼서 저장된 세션을 지웠으면 False."""
    from utils import riot_session_store  # 순환 import 방지용 지연 import

    cookie_header = riot_session_store.get_session(discord_id)
    if not cookie_header:
        return False

    result, session = await reauth_with_cookies(cookie_header)
    try:
        if not result.ok:
            riot_session_store.delete_session(discord_id)
            return False
        riot_session_store.save_session(discord_id, _dict_to_cookie_header(dict(session.cookies)))
        return True
    finally:
        await session.close()


async def refresh_all_stored_sessions() -> tuple[int, int]:
    """등록된 모든 유저 세션을 순회하며 재인증+쿠키 재저장을 해요. (갱신 성공수, 만료로 삭제된 수)를 반환해요."""
    from utils import riot_session_store  # 순환 import 방지용 지연 import

    refreshed = 0
    expired = 0
    for discord_id in riot_session_store.all_discord_ids():
        if await refresh_stored_session(discord_id):
            refreshed += 1
        else:
            expired += 1
    return refreshed, expired


def _decode_jwt_payload(token: str) -> Optional[dict]:
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:  # noqa: BLE001
        return None


def puuid_from_access_token(access_token: str) -> Optional[str]:
    """access_token은 JWT라서 굳이 네트워크 호출 없이 payload만 디코드하면 puuid(sub)를
    바로 뽑을 수 있어요."""
    payload = _decode_jwt_payload(access_token)
    return payload.get("sub") if payload else None


def riot_id_from_id_token(id_token: str) -> Optional[str]:
    """id_token(JWT)의 acct 클레임에서 실제 라이엇 ID(게임이름#태그)를 꺼내요."""
    payload = _decode_jwt_payload(id_token)
    if not payload:
        return None
    acct = payload.get("acct") or {}
    game_name = acct.get("game_name")
    tag_line = acct.get("tag_line")
    if not game_name or not tag_line:
        return None
    return f"{game_name}#{tag_line}"


async def get_entitlement(session: AsyncSession, access_token: str) -> Optional[str]:
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": _RIOT_CLIENT_USER_AGENT}
    resp = await session.post(ENTITLEMENT_URL, json={}, headers=headers)
    if resp.status_code != 200:
        # 진단용 로그예요(토큰 값은 절대 안 찍어요). 원인 파악되면 지울 예정이에요.
        log.info(f"🔍 오상 entitlement 디버그: status={resp.status_code} body={resp.text[:300]!r}")
        return None
    data = resp.json()
    return data.get("entitlements_token")


async def get_region(session: AsyncSession, access_token: str, id_token: str) -> Optional[str]:
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": _RIOT_CLIENT_USER_AGENT}
    resp = await session.put(GEO_URL, json={"id_token": id_token}, headers=headers)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return (data.get("affinities") or {}).get("live")


_FALLBACK_CLIENT_VERSION = "release-08.00-shipping-1-000000"

# 클라이언트 버전은 패치 때만 바뀌는 전역 값인데, _game_headers()가 호출될 때마다
# 매번 valorant-api.com을 다시 불러요. /오상 한 번에 상점·지갑·보유스킨 3번을 부르니까
# 같은 값을 받으려고 왕복을 3번 하는 셈이라, 여기서 잠깐 캐시해요.
_client_version_cache: tuple[float, str] | None = None
_CLIENT_VERSION_TTL_SECONDS = 6 * 3600


async def get_client_version(session: AsyncSession) -> str:
    """상점 조회 헤더에 필요한 클라이언트 버전. valorant-api.com이 최신 패치 버전을
    항상 최신으로 유지해줘서 여기서 그대로 가져다 써요. 6시간 동안은 캐시해서 재사용해요."""
    global _client_version_cache

    now = time.monotonic()
    if _client_version_cache and now < _client_version_cache[0]:
        return _client_version_cache[1]

    try:
        # valorant-api.com은 라이엇 인증 서버가 아니라 공개 정적 데이터라 프록시가 필요 없어요.
        resp = await session.get(VERSION_URL, **_direct_kwargs())
        data = resp.json()
        version = (data.get("data") or {}).get("riotClientVersion", _FALLBACK_CLIENT_VERSION)
    except Exception:  # noqa: BLE001
        # 실패는 캐시하지 않아요. 다음 호출 때 다시 시도해서 최신 값을 받아야 하니까요.
        return _FALLBACK_CLIENT_VERSION

    _client_version_cache = (now + _CLIENT_VERSION_TTL_SECONDS, version)
    return version


_CLIENT_PLATFORM = base64.b64encode(
    json.dumps(
        {
            "platformType": "PC",
            "platformOS": "Windows",
            "platformOSVersion": "10.0.19042.1.256.64bit",
            "platformChipset": "Unknown",
        }
    ).encode()
).decode()


async def _game_headers(session: AsyncSession, access_token: str, entitlement: str) -> dict:
    """pd.{region}.a.pvp.net(게임 서버) API를 부를 때 공통으로 붙는 헤더예요."""
    client_version = await get_client_version(session)
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Riot-Entitlements-JWT": entitlement,
        "X-Riot-ClientPlatform": _CLIENT_PLATFORM,
        "X-Riot-ClientVersion": client_version,
        "User-Agent": _RIOT_CLIENT_USER_AGENT,
    }


async def get_storefront(
    session: AsyncSession,
    *,
    access_token: str,
    entitlement: str,
    region: str,
    puuid: str,
) -> Optional[dict]:
    headers = await _game_headers(session, access_token, entitlement)
    # v2 GET는 라이엇 쪽에서 폐기됐어요. 지금은 v3 POST(빈 바디)로 조회해야 해요.
    url = f"https://pd.{region}.a.pvp.net/store/v3/storefront/{puuid}"
    resp = await _game_post(session, url, json={}, headers=headers)
    if resp.status_code != 200:
        return None
    return resp.json()


async def get_wallet(
    session: AsyncSession,
    *,
    access_token: str,
    entitlement: str,
    region: str,
    puuid: str,
) -> Optional[dict]:
    """보유 재화 잔액을 가져와요. {"Balances": {통화UUID: 수량}} 형태로 내려와요.
    상점 조회에 실패해도 이건 부가 정보라, 실패하면 그냥 None을 주고 표시에서 빼요."""
    headers = await _game_headers(session, access_token, entitlement)
    url = f"https://pd.{region}.a.pvp.net/store/v1/wallet/{puuid}"
    try:
        resp = await _game_get(session, url, headers=headers)
    except Exception as error:  # noqa: BLE001
        log.warning(f"⚠️ 오상 지갑 조회 실패: {error}")
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


# 보유 아이템 조회는 종류별로 따로 불러야 해요. 스킨(레벨)만 필요해서 이것만 씁니다.
SKIN_LEVEL_ITEM_TYPE_ID = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"


async def get_owned_skin_ids(
    session: AsyncSession,
    *,
    access_token: str,
    entitlement: str,
    region: str,
    puuid: str,
) -> Optional[set[str]]:
    """계정이 이미 보유한 스킨(레벨) UUID들을 돌려줘요.

    상점에 뜬 UUID와 같은 체계(SkinLevel)라 그대로 대조하면 돼요.
    부가 정보라서 실패하면 None을 주고, 호출하는 쪽은 "보유 표시 없이" 진행해요."""
    headers = await _game_headers(session, access_token, entitlement)
    url = f"https://pd.{region}.a.pvp.net/store/v1/entitlements/{puuid}/{SKIN_LEVEL_ITEM_TYPE_ID}"
    try:
        resp = await _game_get(session, url, headers=headers)
    except Exception as error:  # noqa: BLE001
        log.warning(f"⚠️ 오상 보유 스킨 조회 실패: {error}")
        return None
    if resp.status_code != 200:
        return None

    try:
        entitlements = resp.json().get("Entitlements") or []
    except Exception as error:  # noqa: BLE001
        log.warning(f"⚠️ 오상 보유 스킨 응답 파싱 실패: {error}")
        return None
    return {item.get("ItemID") for item in entitlements if item.get("ItemID")}


async def get_wallet_with_cookies(cookie_header: str) -> tuple[Optional[dict], str]:
    """등록해둔 쿠키만으로 지갑(보유 재화)까지 한 번에 가져와요.
    상점은 안 부르고 지갑만 필요할 때 쓰는 가벼운 경로예요(/vp계산이 씁니다).

    돌려주는 값: (지갑 dict, 오류메시지). 성공하면 오류메시지가 빈 문자열이에요.
    """
    result, session = await reauth_with_cookies(cookie_header)
    try:
        if not result.ok:
            return None, result.error or "저장된 로그인이 만료됐어요."

        puuid = puuid_from_access_token(result.access_token)
        if not puuid:
            return None, "로그인 정보를 읽지 못했어요."

        region = await get_region(session, result.access_token, result.id_token)
        if not region:
            return None, "라이엇 서버 지역 확인에 실패했어요."

        entitlement = await get_entitlement(session, result.access_token)
        if not entitlement:
            return None, "라이엇 서버에서 권한 토큰을 못 받았어요."

        wallet = await get_wallet(
            session,
            access_token=result.access_token,
            entitlement=entitlement,
            region=region,
            puuid=puuid,
        )
        if wallet is None:
            return None, "보유 VP를 못 받아왔어요."
        return wallet, ""
    finally:
        await session.close()
