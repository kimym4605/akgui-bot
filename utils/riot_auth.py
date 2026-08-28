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
import base64
import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl

from curl_cffi.requests import AsyncSession

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


def new_session() -> AsyncSession:
    return AsyncSession(
        impersonate=_IMPERSONATE, timeout=15, headers={"User-Agent": _RIOT_CLIENT_USER_AGENT}
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

    session = new_session()
    session.cookies = _cookie_header_to_dict(cookie_header)
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
        print(f"🔍 오상 entitlement 디버그: status={resp.status_code} body={resp.text[:300]!r}")
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


async def get_client_version(session: AsyncSession) -> str:
    """상점 조회 헤더에 필요한 클라이언트 버전. valorant-api.com이 최신 패치 버전을
    항상 최신으로 유지해줘서 여기서 그대로 가져다 써요."""
    try:
        resp = await session.get(VERSION_URL)
        data = resp.json()
        return (data.get("data") or {}).get("riotClientVersion", "release-08.00-shipping-1-000000")
    except Exception:  # noqa: BLE001
        return "release-08.00-shipping-1-000000"


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


async def get_storefront(
    session: AsyncSession,
    *,
    access_token: str,
    entitlement: str,
    region: str,
    puuid: str,
) -> Optional[dict]:
    client_version = await get_client_version(session)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Riot-Entitlements-JWT": entitlement,
        "X-Riot-ClientPlatform": _CLIENT_PLATFORM,
        "X-Riot-ClientVersion": client_version,
        "User-Agent": _RIOT_CLIENT_USER_AGENT,
    }
    # v2 GET는 라이엇 쪽에서 폐기됐어요. 지금은 v3 POST(빈 바디)로 조회해야 해요.
    url = f"https://pd.{region}.a.pvp.net/store/v3/storefront/{puuid}"
    resp = await session.post(url, json={}, headers=headers)
    if resp.status_code != 200:
        return None
    return resp.json()
