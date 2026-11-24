"""🗺️ 전술판 — 미니맵에 요원과 스킬을 놓아 "스킬을 어디 쓰는지" 가르치고 피드백하는 웹 작전판 (2026-11-25).

## 왜

랭크·일반 게임 뒤 피드백용(사용자 목적): "어센트 A 공격이면 오멘 연막은 여기 두 개, 소바 화살은 여기".
처음엔 경기 기록 복기(데스 지도)로 만들었는데 사용자가 원한 건 **스킬 배치를 가르치는 판**이라
그쪽은 접었어요(같은 날). 좌표 계산은 그때 실제 경기로 확인한 그대로예요.

## 좌표

valorant-api `maps`로 게임 좌표 → 미니맵 0~1:  u = y·xMultiplier + xScalarToAdd, v = x·yMultiplier + yScalarToAdd.
판에는 **0~1 좌표(u, v)**로만 저장해요. 스킬 크기(m)는 1m = 게임 100단위 → `m × 100 × |xMultiplier|`로
맵마다 실제 비율이 돼요(`unit` = 1m의 0~1 길이).

## 스킬 모양 (`SHAPES`)

- circle: 연막·화염·느려짐 등. 반경은 **대략값**이에요(화면에도 그렇게 적어요).
- line: 곧은 벽(바이퍼 벽·네온 길 등). 시작점에서 끝점까지 끌어요.
- path: 휘는 벽(하버 만조·피닉스 불길). 끄는 대로 곡선 — `pts`에 점 목록(64개까지)으로 저장해요.
  화살표(이동 경로)도 곡선이에요.
- 나머지: 아이콘.
키는 valorant-api **영어** 스킬 이름이에요(한국어판과 uuid·slot으로 이어요).

## 저장 (`tactic_boards`)

    {_id: 보기ID, edit_hash: sha256(편집토큰), uid, map, title, data: {scenes:[{items:[...]}]}, created_at, updated_at}

보기 링크(`/v/<보기ID>`)는 누구나 볼 수 있고, 편집 링크(`/e/<편집토큰>`)는 만든 사람만 받아요.
편집 토큰은 **해시로만** 저장해요(DB가 새도 남이 고칠 수 없게).
장면은 지금 1개지만 `scenes` 목록으로 둬서 나중에 여러 장면을 붙일 수 있어요.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

import aiohttp

from utils.pokemon_store import _db

log = logging.getLogger(__name__)

VAPI = "https://valorant-api.com/v1"
CACHE_TTL = 24 * 3600
MAX_ITEMS = 300
MAX_TEXT = 60
MAX_TITLE = 40

_boards = _db["tactic_boards"]
_cache: dict = {"maps_at": 0.0, "maps": {}, "agents_at": 0.0, "agents": []}
_lock = asyncio.Lock()

SLOT_KEY = {"Ability1": "Q", "Ability2": "E", "Grenade": "C", "Ultimate": "X"}
ROLE_ORDER = {"Controller": 0, "Initiator": 1, "Sentinel": 2, "Duelist": 3}

# 영어 스킬 이름 → 모양. r = 반경(m, 대략값).
SHAPES: dict[str, dict] = {
    # 연막
    "Dark Cover": {"kind": "circle", "r": 4.1, "style": "smoke"},
    "Sky Smoke": {"kind": "circle", "r": 4.1, "style": "smoke"},
    "Nebula": {"kind": "circle", "r": 4.75, "style": "smoke"},
    "Poison Cloud": {"kind": "circle", "r": 4.5, "style": "smoke"},
    "Cove": {"kind": "circle", "r": 4.5, "style": "smoke"},
    "Ruse": {"kind": "circle", "r": 4.1, "style": "smoke"},
    "Cloudburst": {"kind": "circle", "r": 3.4, "style": "smoke"},
    "Cyber Cage": {"kind": "circle", "r": 3.6, "style": "smoke"},
    # 장판(화염·독·느려짐 등)
    "Incendiary": {"kind": "circle", "r": 4.5, "style": "zone"},
    "Snake Bite": {"kind": "circle", "r": 4.5, "style": "zone"},
    "Nanoswarm": {"kind": "circle", "r": 4.5, "style": "zone"},
    "Hot Hands": {"kind": "circle", "r": 4.5, "style": "zone"},
    "Mosh Pit": {"kind": "circle", "r": 6.0, "style": "zone"},
    "FRAG/ment": {"kind": "circle", "r": 4.5, "style": "zone"},
    "Slow Orb": {"kind": "circle", "r": 6.5, "style": "zone"},
    "Gravity Well": {"kind": "circle", "r": 4.75, "style": "zone"},
    "Nova Pulse": {"kind": "circle", "r": 4.75, "style": "zone"},
    "GravNet": {"kind": "circle", "r": 6.0, "style": "zone"},
    "Orbital Strike": {"kind": "circle", "r": 9.0, "style": "zone"},
    "Viper's Pit": {"kind": "circle", "r": 15.0, "style": "smoke"},
    # 벽·선. max = 최대 길이(m), fixed = 길이가 정해진 벽(m). 둘 다 **대략값**(화면에 "대략"이라 적어요).
    "Toxic Screen": {"kind": "line", "style": "smoke", "max": 60},
    # 휘는 벽 — 게임에서도 조종해서 휘게 쏴요(2026-11-25 사용자 요청: 만조 곡선). 끄는 대로 그려요.
    "High Tide": {"kind": "path", "style": "smoke", "max": 60},
    "Blaze": {"kind": "path", "style": "zone", "max": 16},
    "Fast Lane": {"kind": "line", "style": "zone", "max": 50},
    "Barrier Orb": {"kind": "line", "style": "wall", "fixed": 6.5},
    "Barrier Mesh": {"kind": "line", "style": "wall", "fixed": 10},
    "Cosmic Divide": {"kind": "line", "style": "smoke"},
    "Fault Line": {"kind": "line", "style": "zone", "max": 45},
    "Trapwire": {"kind": "line", "style": "wall", "max": 15},
}
# 나머지 스킬(아이콘·원)은 **톡 누르면 놓기, 끌면 던진 경로**(튕김까지 곡선)를 그리고 끝에 떨어져요.
# 그때 항목은 u,v = 던진 곳, u2,v2 = 떨어진 곳, pts = 경로예요.


# ------------------------------------------------------------------
# valorant-api 자료 (하루 캐시)
# ------------------------------------------------------------------
async def _get(session: aiohttp.ClientSession, url: str) -> list:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
        r.raise_for_status()
        return (await r.json())["data"]


def to_uv(m: dict, loc: dict) -> tuple[float, float]:
    u = loc["y"] * m["xm"] + m["xa"]
    v = loc["x"] * m["ym"] + m["ya"]
    return round(u, 4), round(v, 4)


def map_entry(en_name: str, k: dict) -> dict:
    """valorant-api 한국어판 맵 하나 → 전술판에 필요한 것만."""
    e = {"key": en_name.lower(), "name": k["displayName"], "minimap": k["displayIcon"],
         "xm": k["xMultiplier"], "ym": k["yMultiplier"], "xa": k["xScalarToAdd"], "ya": k["yScalarToAdd"],
         "unit": round(100 * abs(k["xMultiplier"]), 6), "callouts": []}
    for c in k.get("callouts") or []:
        loc = c.get("location") or {}
        if "x" not in loc:
            continue
        sup = (c.get("superRegionName") or "").strip()
        region = (c.get("regionName") or "").strip()
        name = f"{sup} {region}" if sup and not region.startswith(sup) else region
        u, v = to_uv(e, loc)
        e["callouts"].append({"name": name, "u": u, "v": v})
    return e


async def maps(session: aiohttp.ClientSession) -> dict[str, dict]:
    """영어 맵 이름(소문자) → 맵 자료. 콜아웃이 있는 실제 경쟁 맵만."""
    if _cache["maps"] and time.monotonic() - _cache["maps_at"] < CACHE_TTL:
        return _cache["maps"]
    async with _lock:
        if _cache["maps"] and time.monotonic() - _cache["maps_at"] < CACHE_TTL:
            return _cache["maps"]
        en = await _get(session, f"{VAPI}/maps")
        ko = {m["uuid"]: m for m in await _get(session, f"{VAPI}/maps?language=ko-KR")}
        out = {}
        for m in en:
            k = ko.get(m["uuid"])
            if k and k.get("displayIcon") and k.get("xMultiplier") and k.get("callouts"):
                out[m["displayName"].lower()] = map_entry(m["displayName"], k)
        _cache.update(maps_at=time.monotonic(), maps=out)
        log.info("🗺️ 전술판: 맵 %d개", len(out))
        return out


def agent_entries(en: list[dict], ko: list[dict]) -> list[dict]:
    """요원 목록(역할 순) + 스킬 4개(Q·E·C·X)와 모양."""
    ko_by = {a["uuid"]: a for a in ko}
    out = []
    for a in en:
        k = ko_by.get(a["uuid"], a)
        abilities = []
        ko_ab = {ab["slot"]: ab for ab in k.get("abilities") or []}
        for ab in a.get("abilities") or []:
            slot = ab.get("slot")
            if slot not in SLOT_KEY:
                continue
            kab = ko_ab.get(slot, ab)
            abilities.append({"slot": SLOT_KEY[slot], "name": kab.get("displayName") or ab["displayName"],
                              "icon": ab.get("displayIcon"),
                              "shape": SHAPES.get(ab["displayName"], {"kind": "icon"})})
        abilities.sort(key=lambda x: "QECX".index(x["slot"]))
        role = (a.get("role") or {}).get("displayName") or ""
        out.append({"id": a["uuid"], "name": k["displayName"], "role": role,
                    "roleName": ((k.get("role") or {}).get("displayName") or role),
                    "icon": a.get("displayIcon"), "abilities": abilities})
    out.sort(key=lambda x: (ROLE_ORDER.get(x["role"], 9), x["name"]))
    return out


async def agents(session: aiohttp.ClientSession) -> list[dict]:
    if _cache["agents"] and time.monotonic() - _cache["agents_at"] < CACHE_TTL:
        return _cache["agents"]
    async with _lock:
        if _cache["agents"] and time.monotonic() - _cache["agents_at"] < CACHE_TTL:
            return _cache["agents"]
        en = await _get(session, f"{VAPI}/agents?isPlayableCharacter=true")
        ko = await _get(session, f"{VAPI}/agents?isPlayableCharacter=true&language=ko-KR")
        out = agent_entries(en, ko)
        _cache.update(agents_at=time.monotonic(), agents=out)
        log.info("🗺️ 전술판: 요원 %d명", len(out))
        return out


# ------------------------------------------------------------------
# 판 자료 검사 (브라우저가 보낸 걸 그대로 믿지 않아요)
# ------------------------------------------------------------------
ITEM_TYPES = {"agent", "ability", "arrow", "text"}


def _num(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if -0.5 <= f <= 1.5 else None


MAX_POINTS = 64


def clean_points(pts) -> list[list[float]] | None:
    """곡선 점 목록 [[u,v], …]. 2개 미만·64개 초과·이상한 값이면 None."""
    if not isinstance(pts, list) or not 2 <= len(pts) <= MAX_POINTS:
        return None
    out = []
    for p in pts:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        u, v = _num(p[0]), _num(p[1])
        if u is None or v is None:
            return None
        out.append([u, v])
    return out


def clean_data(data) -> dict | None:
    """저장할 판 자료를 정리해요. 이상하면 None."""
    if not isinstance(data, dict):
        return None
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes or len(scenes) > 10:
        return None
    out_scenes = []
    total = 0
    for sc in scenes:
        if not isinstance(sc, dict) or not isinstance(sc.get("items"), list):
            return None
        items = []
        for it in sc["items"]:
            if not isinstance(it, dict) or it.get("type") not in ITEM_TYPES:
                continue
            u, v = _num(it.get("u")), _num(it.get("v"))
            if u is None or v is None:
                continue
            row = {"type": it["type"], "u": u, "v": v,
                   "team": "enemy" if it.get("team") == "enemy" else "ally"}
            if it["type"] in ("ability", "agent"):
                row["agent"] = str(it.get("agent") or "")[:40]
            if it["type"] == "ability":
                row["slot"] = str(it.get("slot") or "")[:1]
            if it["type"] in ("arrow", "ability"):
                u2, v2 = _num(it.get("u2")), _num(it.get("v2"))
                if u2 is not None and v2 is not None:
                    row["u2"], row["v2"] = u2, v2
                pts = clean_points(it.get("pts"))
                if pts:
                    # 곡선: 처음·끝 점을 u,v / u2,v2에도 맞춰 둬요(목록·이동 계산이 같은 값을 쓰게)
                    row["pts"] = pts
                    (row["u"], row["v"]), (row["u2"], row["v2"]) = pts[0], pts[-1]
            if it["type"] == "arrow" and "u2" not in row:
                continue
            if it["type"] == "text":
                text = str(it.get("text") or "").strip()[:MAX_TEXT]
                if not text:
                    continue
                row["text"] = text
            items.append(row)
        total += len(items)
        if total > MAX_ITEMS:
            return None
        out_scenes.append({"title": str(sc.get("title") or "")[:MAX_TITLE], "items": items})
    return {"scenes": out_scenes, "side": "def" if data.get("side") == "def" else "atk"}


# ------------------------------------------------------------------
# 저장
# ------------------------------------------------------------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_sync(uid: int, map_key: str, title: str, channel_id: int | None) -> tuple[str, str]:
    view_id = secrets.token_urlsafe(8)
    edit_token = secrets.token_urlsafe(18)
    now = datetime.now(timezone.utc)
    _boards.insert_one({"_id": view_id, "edit_hash": _hash(edit_token), "uid": str(uid),
                        "channel": str(channel_id) if channel_id else None,   # 📤 올릴 채널(/작전판을 쓴 곳)
                        "map": map_key, "title": title[:MAX_TITLE],
                        "data": {"scenes": [{"title": "", "items": []}], "side": "atk"},
                        "created_at": now, "updated_at": now})
    return view_id, edit_token


async def create_board(uid: int, map_key: str, title: str, channel_id: int | None = None) -> tuple[str, str]:
    """(보기ID, 편집토큰)"""
    return await asyncio.to_thread(_create_sync, uid, map_key, title, channel_id)


def _get_sync(view_id: str | None, edit_token: str | None) -> dict | None:
    if edit_token:
        return _boards.find_one({"edit_hash": _hash(edit_token)})
    return _boards.find_one({"_id": view_id})


async def get_board(*, view_id: str | None = None, edit_token: str | None = None) -> dict | None:
    key = edit_token or view_id
    if not key or len(key) > 64:
        return None
    return await asyncio.to_thread(_get_sync, view_id, edit_token)


def _save_sync(edit_token: str, data: dict, title: str | None) -> bool:
    fields = {"data": data, "updated_at": datetime.now(timezone.utc)}
    if title is not None:
        fields["title"] = title[:MAX_TITLE]
    res = _boards.update_one({"edit_hash": _hash(edit_token)}, {"$set": fields})
    return res.matched_count == 1


async def save_board(edit_token: str, data: dict, title: str | None = None) -> bool:
    return await asyncio.to_thread(_save_sync, edit_token, data, title)


async def ensure_indexes() -> None:
    await asyncio.to_thread(_boards.create_index, "edit_hash", unique=True)
