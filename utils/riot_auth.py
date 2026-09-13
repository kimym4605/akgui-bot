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
import asyncio
import logging
import base64
import json
import os
import re
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
    # ⚠️ expired=True는 "라이엇이 이 쿠키를 더 이상 안 받아준다"가 확인된 경우에만이에요.
    # 프록시 장애·타임아웃·라이엇 5xx 같은 일시적 실패는 ok=False지만 expired=False라,
    # 이걸 만료로 오해해서 저장된 쿠키를 지우면 안 돼요(멀쩡한 유저가 재로그인하게 돼요).
    expired: bool = False
    # 재인증 직후 라이엇이 새로 내려준 쿠키예요. 라이엇은 재인증할 때마다 ssid를 새로 발급하고
    # 이전 값을 무효화해서, 이걸 저장해두지 않으면 다음 조회부터 "만료"로 튕겨요.
    cookie_header: str = ""

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


# 유저가 붙여넣는 형태는 정말 제각각이에요. 아래 사례들을 전부 받아주려고 관대하게 파싱해요.
#   ssid=eyJ...                                   ← 안내대로 붙여넣은 정상 케이스
#   ssid=eyJ...; tdid=...; clid=...               ← Network 탭의 cookie 헤더를 통째로 복사
#   cookie: ssid=eyJ...                           ← 헤더 이름까지 같이 복사
#   eyJ...                                        ← Application 탭에서 "값" 칸만 복사
#   ssid⇥eyJ...⇥auth.riotgames.com⇥/⇥…            ← Application 탭에서 "행"을 통째로 복사(탭 구분)
#   "ssid=eyJ..."                                 ← 따옴표째 복사
#   ssid: eyJ...                                  ← 콜론으로 적어 넣음
#   여러 줄에 걸쳐 나뉜 형태                        ← 개행 구분
_COOKIE_SPLIT = re.compile(r"[;\r\n]+")
_QUOTES = "\"'“”‘’`"


def _cookie_header_to_dict(cookie_header: str) -> dict:
    cookies: dict[str, str] = {}
    for part in _COOKIE_SPLIT.split(cookie_header):
        part = part.strip().strip(_QUOTES).strip()
        if not part:
            continue

        # Application 탭에서 행을 드래그해 복사하면 "ssid⇥값⇥도메인⇥경로⇥…"처럼 탭으로 갈려요.
        # 이 경우 앞의 두 칸이 이름/값이고, 뒤는 도메인·만료일 같은 메타라 버리면 돼요.
        if "\t" in part:
            fields = [f.strip() for f in part.split("\t") if f.strip()]
            if len(fields) >= 2:
                cookies[fields[0].strip(_QUOTES)] = fields[1].strip(_QUOTES)
                continue

        key, sep, value = part.partition("=")
        if not sep:
            # "ssid: eyJ..."처럼 콜론으로 적은 경우도 받아줘요. JWT 값 안에는 콜론이 없어서
            # 이렇게 폴백해도 멀쩡한 값을 잘못 자를 일이 없어요.
            key, sep, value = part.partition(":")
        if not sep:
            continue

        key = key.strip().strip(_QUOTES).strip()
        value = value.strip().strip(_QUOTES).strip()
        if key and value:
            cookies[key] = value
    return cookies


def _looks_like_jwt(value: str) -> bool:
    """라이엇 ssid는 JWT라서 'eyJ'로 시작하고 점이 두 개 들어있어요."""
    return value.startswith("ey") and value.count(".") >= 2


def _normalize_cookie_input(raw: str) -> str:
    """유저가 붙여넣은 원문을 표준 cookie 헤더 형태에 가깝게 다듬어요."""
    text = raw.strip().strip(_QUOTES).strip()

    # "cookie: ssid=..." / "Cookie ssid=..." 처럼 헤더 이름까지 복사해온 경우를 떼어내요.
    lowered = text.lower()
    for prefix in ("cookie:", "set-cookie:", "cookie ="):
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    # 값만 복사해온 경우(ssid= 앞부분 없이 JWT만)엔 이름을 붙여줘요. 예전엔 이 보정이 없어서
    # "세션 만료"라는 엉뚱한 안내가 나갔어요. 중간에 줄바꿈이 섞여 들어오는 일도 잦아서
    # 공백류를 먼저 걷어내고 판단해요.
    compact = "".join(text.split())
    if "=" not in compact and ":" not in compact and _looks_like_jwt(compact):
        return f"ssid={compact}"
    return text


def _dict_to_cookie_header(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


async def reauth_with_cookies(cookie_header: str) -> tuple[LoginResult, AsyncSession]:
    """저장해둔 쿠키(ssid 등)로 비밀번호 없이 재로그인해요. 세션이 아직 살아있으면
    바로 access_token이 담긴 리다이렉트가 돌아오고, 만료됐으면 ok=False로 다시
    로그인(또는 쿠키 재등록)을 해달라고 해야 해요."""
    # 붙여넣기 형태가 제각각이라(헤더 이름째 복사, 값만 복사, 탭/개행 섞임 등) 여기서 다듬어요.
    cookie_header = _normalize_cookie_input(cookie_header)

    session = new_session()
    cookies = _cookie_header_to_dict(cookie_header)
    if not cookies:
        return (
            LoginResult(
                ok=False,
                # 값 자체가 깨진 거라 재시도해도 안 살아나요. 저장돼 있었다면 지우는 게 맞아요.
                expired=True,
                error=(
                    "붙여넣은 값에서 쿠키를 읽지 못했어요. `ssid=eyJ...` 형태로 붙여넣어주세요. "
                    "(`❔ 쿠키 등록 방법` 버튼에 그림처럼 순서가 적혀 있어요.)"
                ),
            ),
            session,
        )
    # ssid가 없으면 라이엇은 그냥 "로그인 안 된 상태"로 처리해서, 아래에서 만료와 똑같은 응답이
    # 돌아와요. 그러면 멀쩡한 사람에게 "세션 만료"라고 안내하게 되니 여기서 미리 갈라줘요.
    if "ssid" not in cookies:
        found = ", ".join(f"`{k}`" for k in sorted(cookies)[:6]) or "없음"
        return (
            LoginResult(
                ok=False,
                expired=True,
                error=(
                    "붙여넣은 값에 로그인 세션 쿠키인 **`ssid`** 가 없어요 (읽어낸 쿠키: "
                    f"{found}). 쿠키 목록에서 **`auth.riotgames.com`** 을 고른 뒤 이름이 "
                    "정확히 **`ssid`** 인 줄의 값을 복사해주세요."
                ),
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
        status = resp.status_code
    except Exception as error:  # noqa: BLE001
        # 프록시/네트워크 문제예요. 쿠키는 멀쩡할 수 있으니 expired로 올리지 않아요.
        log.warning(f"⚠️ 오상 재인증 연결 실패: {error}")
        return LoginResult(ok=False, error=f"라이엇 서버 연결에 실패했어요: {error}"), session

    # 재인증 직후의 쿠키를 여기서 바로 떠둬요. 이 뒤에 게임 서버(pd.*.pvp.net) 호출이 이어지면
    # 그쪽 쿠키까지 같은 병에 섞여서, 나중에 뜨면 auth용 쿠키 헤더가 지저분해져요.
    refreshed = _dict_to_cookie_header(dict(session.cookies))

    parsed = parse_redirect_url(location)
    if not parsed:
        # 라이엇/프록시가 잠깐 맛이 간 것과, 쿠키가 진짜 죽은 걸 구분해요.
        if status >= 500 or status in (408, 429):
            log.warning(f"⚠️ 오상 재인증 일시 실패(status={status}) — 만료로 취급하지 않아요.")
            return (
                LoginResult(
                    ok=False,
                    error="라이엇 서버가 일시적으로 응답하지 않아요. 잠시 후 다시 시도해주세요.",
                ),
                session,
            )

        # ⚠️ 여기까지 왔다는 건 "라이엇이 토큰을 안 줬다"는 것뿐이라, 원인이 여러 가지예요
        # (쿠키가 진짜 만료 / 값이 잘려서 복사됨 / 복사한 뒤 브라우저에서 ssid가 회전됨 등).
        # 예전엔 전부 "세션 만료"로 뭉뚱그려 안내하고 로그도 안 남겨서 원인을 못 좁혔어요.
        # 실패 응답엔 토큰이 없으니 Location을 찍어도 민감정보가 새지 않아요.
        fragment = location.split("#", 1)[1] if "#" in location else ""
        riot_error = dict(parse_qsl(fragment)).get("error", "") if fragment else ""
        ssid_len = len(cookies.get("ssid", ""))
        log.warning(
            f"⚠️ 오상 재인증 거부: status={status} riot_error={riot_error or '-'} "
            f"쿠키={sorted(cookies)} ssid길이={ssid_len} location={location[:120] or '(없음)'}"
        )

        # 라이엇이 "이 세션 못 쓴다"고 판단하면 로그인 페이지로 303 리다이렉트를 보내요
        # (2026-09-07 죽은 쿠키로 직접 확인: status=303 → authenticate.riotgames.com/login).
        # 그게 아닌 예상 밖 응답(프록시·클라우드플레어의 403 같은 것)까지 만료로 단정하면,
        # 멀쩡한 유저의 저장된 쿠키를 지워서 괜히 재등록하게 만들어요.
        redirected_to_login = "authenticate.riotgames.com" in location or "/login" in location
        if not redirected_to_login and not riot_error:
            return (
                LoginResult(
                    ok=False,
                    error=(
                        f"라이엇 서버가 예상 밖의 응답을 보냈어요(status={status}). "
                        "잠시 후 다시 시도해주세요."
                    ),
                ),
                session,
            )

        # ssid는 JWT라 보통 800자 안팎이에요. 눈에 띄게 짧으면 값이 잘려서 복사된 거예요.
        if ssid_len and (ssid_len < 200 or not _looks_like_jwt(cookies["ssid"])):
            return (
                LoginResult(
                    ok=False,
                    expired=True,
                    error=(
                        f"`ssid` 값이 잘려서 들어온 것 같아요(길이 {ssid_len}자). 값 칸을 "
                        "**더블클릭한 뒤 `Ctrl+A` → `Ctrl+C`** 로 전체를 복사해주세요. "
                        "드래그로 긁으면 화면에 보이는 데까지만 복사돼요."
                    ),
                ),
                session,
            )

        return (
            LoginResult(
                ok=False,
                expired=True,
                error=(
                    "라이엇이 이 쿠키로는 로그인을 안 받아줬어요(세션이 만료됐거나 값이 이미 "
                    "바뀐 경우예요). 브라우저에서 라이엇에 **다시 로그인한 뒤 새로 복사해서 "
                    "바로** 등록해주세요 — 복사한 다음 라이엇 페이지를 새로고침하거나 발로란트를 "
                    "켜면 값이 바뀌어서 못 쓰게 돼요."
                ),
            ),
            session,
        )

    access_token, id_token = parsed
    return (
        LoginResult(
            ok=True, access_token=access_token, id_token=id_token, cookie_header=refreshed
        ),
        session,
    )


def persist_refreshed_cookie(
    discord_id: int, result: LoginResult, account_key: Optional[str] = None
) -> None:
    """재인증에 성공했으면 라이엇이 새로 내려준 쿠키로 갈아끼워요.

    ⚠️ 이걸 빼먹으면 안 돼요. 라이엇은 재인증할 때마다 ssid를 새로 발급하면서 이전 값을
    무효화해서, 저장된 쿠키가 그대로 남아있으면 다음 조회에서 "만료"로 튕겨요. 예전엔 새벽 4시
    갱신 루프에서만 저장하고 /오상·새로고침·위시리스트·/vp계산 경로는 회전된 쿠키를 버려서,
    쿠키를 등록해둔 유저가 며칠에 한 번씩 재등록해야 하는 증상이 있었어요.

    계정을 여러 개 등록해둘 수 있어서, 어느 슬롯에 써야 하는지도 같이 넘겨줘야 해요.
    account_key를 모르는 호출부를 위해 id_token에서 라이엇 ID를 뽑아 대조하니까,
    account_key를 안 줘도 엉뚱한 계정의 쿠키를 덮어쓰진 않아요."""
    from utils import riot_session_store  # 순환 import 방지용 지연 import

    if not result.ok or not result.cookie_header:
        return
    riot_session_store.save_session(
        discord_id,
        result.cookie_header,
        riot_id=riot_id_from_id_token(result.id_token) or "",
        account_key=account_key,
    )


async def refresh_stored_session(discord_id: int, account_key: Optional[str] = None) -> str:
    """등록해둔 쿠키로 재인증하고, 라이엇이 새로 내려준 쿠키로 다시 저장해요(SkinPeek 등의
    발로란트 봇들이 쓰는 방식과 동일: 매번 갱신된 쿠키로 덮어써서 만료 시점을 계속 미뤄요).

    account_key를 안 주면 그 유저의 기본 계정을 갱신해요.

    "refreshed"(갱신 성공) / "expired"(만료 확인돼서 삭제함) / "failed"(일시 실패, 그대로 둠)."""
    from utils import riot_session_store  # 순환 import 방지용 지연 import

    cookie_header = riot_session_store.get_session(discord_id, account_key)
    if not cookie_header:
        return "expired"

    result, session = await reauth_with_cookies(cookie_header)
    try:
        if result.ok:
            persist_refreshed_cookie(discord_id, result, account_key)
            return "refreshed"
        # 만료가 "확인된" 경우에만 지워요. 프록시가 잠깐 죽은 날 이걸 안 가리면
        # 등록된 유저 쿠키가 한 번에 전부 날아가요(재로그인 반복 신고의 원인이었어요).
        if result.expired:
            riot_session_store.delete_session(discord_id, account_key)
            return "expired"
        return "failed"
    finally:
        await session.close()


async def refresh_all_stored_sessions() -> tuple[int, int, int]:
    """등록된 모든 세션을 순회하며 재인증+쿠키 재저장을 해요. 한 사람이 계정을 여러 개
    등록해뒀으면 계정마다 각각 갱신해요(하나만 갱신하면 나머지가 만료돼버려요).
    (갱신 성공수, 만료로 삭제된 수, 일시 실패해서 그대로 둔 수)를 반환해요."""
    from utils import riot_session_store  # 순환 import 방지용 지연 import

    refreshed = 0
    expired = 0
    failed = 0
    for discord_id, account_key, _cookie in riot_session_store.all_sessions():
        status = await refresh_stored_session(discord_id, account_key)
        if status == "refreshed":
            refreshed += 1
        elif status == "expired":
            expired += 1
        else:
            failed += 1
    return refreshed, expired, failed


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


async def get_entitlement(
    session: AsyncSession, access_token: str, attempts: int = 2, who: str = ""
) -> Optional[str]:
    """권한 토큰(entitlements_token)을 받아와요. 실패하면 None.

    ⚠️ 이 호출은 주거용 프록시를 거쳐요(데이터센터 IP는 라이엇이 403으로 막아요). 프록시가
    잠깐 흔들리면 여기서만 터지는데, 예전엔 그 예외가 `_fetch_storefront`의
    `return_exceptions=True`에 그대로 삼켜져서 **로그가 한 줄도 안 남았어요.** 유저에겐
    "권한 토큰을 못 받았어요"만 뜨고 서버 쪽엔 단서가 없어서 원인을 못 좁혔죠. 그래서
    여기서 직접 잡아 로그를 남기고, 일시적인 실패는 한 번 더 시도해요."""
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": _RIOT_CLIENT_USER_AGENT}
    tag = f"[{who}] " if who else ""
    for attempt in range(1, attempts + 1):
        try:
            resp = await session.post(ENTITLEMENT_URL, json={}, headers=headers)
        except Exception as error:  # noqa: BLE001
            log.warning(f"⚠️ {tag}오상 entitlement 연결 실패({attempt}/{attempts}): {error}")
            if attempt < attempts:
                await asyncio.sleep(1)
                continue
            return None

        if resp.status_code == 200:
            return resp.json().get("entitlements_token")

        # 진단용 로그예요(토큰 값은 절대 안 찍어요).
        log.info(
            f"🔍 {tag}오상 entitlement 디버그({attempt}/{attempts}): "
            f"status={resp.status_code} body={resp.text[:300]!r}"
        )
        # 429(요청 과다)·5xx는 잠깐 뒤에 다시 하면 되는 경우가 많아요. 403/400은 다시 해도
        # 똑같으니(계정/IP 문제) 바로 포기해요.
        if (resp.status_code in (408, 429) or resp.status_code >= 500) and attempt < attempts:
            await asyncio.sleep(1)
            continue
        return None
    return None


async def get_region(
    session: AsyncSession, access_token: str, id_token: str, who: str = ""
) -> Optional[str]:
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": _RIOT_CLIENT_USER_AGENT}
    tag = f"[{who}] " if who else ""
    try:
        resp = await session.put(GEO_URL, json={"id_token": id_token}, headers=headers)
    except Exception as error:  # noqa: BLE001
        log.warning(f"⚠️ {tag}오상 지역 확인 연결 실패: {error}")
        return None
    if resp.status_code != 200:
        log.info(f"🔍 {tag}오상 지역 확인 디버그: status={resp.status_code} body={resp.text[:200]!r}")
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


async def get_wallet_with_cookies(
    cookie_header: str, discord_id: Optional[int] = None, account_key: Optional[str] = None
) -> tuple[Optional[dict], str]:
    """등록해둔 쿠키만으로 지갑(보유 재화)까지 한 번에 가져와요.
    상점은 안 부르고 지갑만 필요할 때 쓰는 가벼운 경로예요(/vp계산이 씁니다).

    discord_id를 주면 재인증으로 회전된 쿠키를 저장까지 해줘요(안 주면 조회만 하고 버려요).
    이때 **어느 쿠키를 넘겼는지(account_key)도 같이 줘야 해요.** 안 그러면 계정을 여러 개
    등록한 사람의 회전된 쿠키가 엉뚱한 슬롯에 저장될 수 있어요.

    돌려주는 값: (지갑 dict, 오류메시지). 성공하면 오류메시지가 빈 문자열이에요.
    """
    result, session = await reauth_with_cookies(cookie_header)
    try:
        if not result.ok:
            return None, result.error or "저장된 로그인이 만료됐어요."
        if discord_id is not None:
            persist_refreshed_cookie(discord_id, result, account_key)

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
