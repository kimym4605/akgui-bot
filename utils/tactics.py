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

## 2026-11-25 업그레이드 (사용자 요청 1~5)

1. **내 작전판 목록** — 편집 링크를 잃어버려도 다시 받아요. 편집 토큰을 `edit_token_for(보기ID)`
   (서버 비밀값으로 만든 HMAC)로 바꿔서, 저장해 두지 않아도 **언제나 같은 링크**를 다시 만들 수 있어요.
   예전 판(무작위 토큰)은 `edit_hash2`에 새 토큰 해시를 하나 더 달아요 → 옛 링크도 그대로 살아 있어요.
2. **서버 작전 모음** — 📤 디스코드에 올린 판은 `shared_at`이 찍혀 맵별 목록에 실려요.
3. **피드백** — `notes`(메모 핀: 누가·어느 장면·어디·글)와 복사해서 고치기(`forked_from`).
   피드백·같이 그리기 링크는 `make_pass`(디스코드 버튼으로만 발급, 서명 + 만료)로 **누구인지** 알아요.
4. **실시간 같이 그리기** — 항목마다 `id`, 장면마다 `sid`를 두고 연산(`apply_op`)으로 주고받아요.
   방·연결은 `utils/tactics_live.py`. 연산은 **두 번 와도 같은 결과**가 되게 했어요(재접속 때 다시 보내요).
5. **경기 장면** — `utils/tactics_match.py`가 실제 경기의 킬 순간 위치로 장면을 만들어요
   (요원 항목의 `rot` 시선·`dead` 처치됨·`me` 나).
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import logging
import os
import re
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
MAX_SCENES = 10
MAX_NOTES = 60            # 판 하나에 메모 핀
MAX_NOTE = 120            # 메모 한 개 글자 수
MAX_BOARDS_PER_USER = 100
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}$")
NOOP = {"t": "noop"}      # apply_op: 받아들였지만 바뀐 게 없음(이미 반영된 연산)

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
# 🎯 사거리(m, 대략값) — 그 요원이 맵에 놓여 있으면 **요원에서 이 거리 안에만** 놓여요(2026-11-25 서버 피드백).
# 던지는 스킬(몰리·섬광·화살 등)은 힘으로 거리가 정해져서 넣지 않았어요. 아스트라·사이퍼처럼 맵 전체는 없음.
# 🚨 확실하지 않은 값이에요 — 서버에서 틀렸다고 하면 여기 숫자만 고치면 돼요.
RANGES: dict[str, float] = {
    "Dark Cover": 50, "Sky Smoke": 50, "Ruse": 40,
    "Nanoswarm": 40, "ALARMBOT": 40, "TURRET": 40,
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
            shape = dict(SHAPES.get(ab["displayName"], {"kind": "icon"}))
            if ab["displayName"] in RANGES:
                shape["range"] = RANGES[ab["displayName"]]
            abilities.append({"slot": SLOT_KEY[slot], "name": kab.get("displayName") or ab["displayName"],
                              "icon": ab.get("displayIcon"), "shape": shape})
        abilities.sort(key=lambda x: "QECX".index(x["slot"]))
        role = (a.get("role") or {}).get("displayName") or ""
        out.append({"id": a["uuid"], "name": k["displayName"], "en": a["displayName"], "role": role,
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


def new_id() -> str:
    return secrets.token_urlsafe(6)          # 8글자


def _valid_id(x) -> bool:
    return isinstance(x, str) and bool(ID_RE.match(x))


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


def clean_item(it) -> dict | None:
    """항목 하나를 정리해요. 못 쓰면 None. `id`가 없거나 이상하면 새로 붙여요."""
    if not isinstance(it, dict) or it.get("type") not in ITEM_TYPES:
        return None
    u, v = _num(it.get("u")), _num(it.get("v"))
    if u is None or v is None:
        return None
    row = {"id": it["id"] if _valid_id(it.get("id")) else new_id(),
           "type": it["type"], "u": u, "v": v,
           "team": "enemy" if it.get("team") == "enemy" else "ally"}
    if it["type"] in ("ability", "agent"):
        row["agent"] = str(it.get("agent") or "")[:40]
    if it["type"] == "agent":
        # 🎬 경기 장면용: 시선(라디안) · 처치됨 · 나
        rot = it.get("rot")
        if isinstance(rot, (int, float)) and not isinstance(rot, bool) and -7 <= rot <= 7:
            row["rot"] = round(float(rot), 3)
        if it.get("dead") is True:
            row["dead"] = True
        if it.get("me") is True:
            row["me"] = True
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
        return None
    if it["type"] == "text":
        text = str(it.get("text") or "").strip()[:MAX_TEXT]
        if not text:
            return None
        row["text"] = text
    return row


def clean_data(data) -> dict | None:
    """저장할 판 자료를 정리해요. 이상하면 None. 장면 `sid`·항목 `id`가 없으면 붙여요."""
    if not isinstance(data, dict):
        return None
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes or len(scenes) > MAX_SCENES:
        return None
    out_scenes = []
    total = 0
    sids: set[str] = set()
    for sc in scenes:
        if not isinstance(sc, dict) or not isinstance(sc.get("items"), list):
            return None
        items = []
        ids: set[str] = set()
        for it in sc["items"]:
            row = clean_item(it)
            if row is None:
                continue
            if row["id"] in ids:
                row["id"] = new_id()
            ids.add(row["id"])
            items.append(row)
        total += len(items)
        if total > MAX_ITEMS:
            return None
        sid = sc.get("sid")
        if not _valid_id(sid) or sid in sids:
            sid = new_id()
        sids.add(sid)
        out_scenes.append({"sid": sid, "title": str(sc.get("title") or "")[:MAX_TITLE], "items": items})
    return {"scenes": out_scenes, "side": "def" if data.get("side") == "def" else "atk"}


def ensure_ids(data: dict) -> bool:
    """예전 판(항목 id·장면 sid 없음)에 id를 붙여요. 바뀌었으면 True."""
    changed = False
    sids: set[str] = set()
    for sc in data.get("scenes") or []:
        if not _valid_id(sc.get("sid")) or sc["sid"] in sids:
            sc["sid"] = new_id()
            changed = True
        sids.add(sc["sid"])
        ids: set[str] = set()
        for it in sc.get("items") or []:
            if not _valid_id(it.get("id")) or it["id"] in ids:
                it["id"] = new_id()
                changed = True
            ids.add(it["id"])
    return changed


def empty_data() -> dict:
    return {"scenes": [{"sid": new_id(), "title": "", "items": []}], "side": "atk"}


# ------------------------------------------------------------------
# 👥 실시간 연산 — 상태 = {"title": 제목, "data": {scenes, side}, "notes": [메모 핀]}
#   브라우저의 `applyOps`(config/tactics/board.html)와 **같은 규칙**이에요. 한쪽을 고치면 다른 쪽도.
# ------------------------------------------------------------------
def _scene_of(data: dict, sid) -> dict | None:
    if not isinstance(sid, str):
        return None
    return next((s for s in data["scenes"] if s.get("sid") == sid), None)


def _total_items(data: dict) -> int:
    return sum(len(s["items"]) for s in data["scenes"])


def apply_op(state: dict, op) -> dict | None:
    """연산 하나를 상태에 적용해요.

    돌려주는 것: 다른 사람에게 보낼 **정리된 연산** · `NOOP`(이미 반영돼 있어 바뀐 게 없음) · None(거절).
    🚨 같은 연산이 두 번 와도 결과가 같아야 해요 — 끊겼다 이으면 브라우저가 확인 못 받은 연산을 다시 보내요.
       그래서 "이미 있는 것 추가"·"없는 것 삭제"는 거절이 아니라 NOOP예요.
    """
    if not isinstance(op, dict):
        return None
    t = op.get("t")
    data = state["data"]
    if t == "meta":
        out: dict = {"t": "meta"}
        if isinstance(op.get("title"), str):
            title = op["title"].strip()[:MAX_TITLE]
            if title != (state.get("title") or ""):
                state["title"] = title
                out["title"] = title
        if op.get("side") in ("atk", "def") and op["side"] != data.get("side"):
            data["side"] = op["side"]
            out["side"] = op["side"]
        return out if len(out) > 1 else NOOP
    if t == "sadd":
        sc = op.get("scene")
        after = op.get("after")
        if (not isinstance(sc, dict) or not _valid_id(sc.get("sid")) or not isinstance(sc.get("items"), list)
                or not (after is None or isinstance(after, str))):
            return None
        if _scene_of(data, sc["sid"]) is not None:
            return NOOP
        if len(data["scenes"]) >= MAX_SCENES:
            return None
        items = []
        ids: set[str] = set()
        for it in sc["items"]:
            if not isinstance(it, dict) or not _valid_id(it.get("id")) or it["id"] in ids:
                return None
            row = clean_item(it)
            if row is None:
                return None
            ids.add(row["id"])
            items.append(row)
        if _total_items(data) + len(items) > MAX_ITEMS:
            return None
        scene = {"sid": sc["sid"], "title": str(sc.get("title") or "")[:MAX_TITLE], "items": items}
        if after is None:
            idx = 0
        else:
            idx = next((i + 1 for i, s in enumerate(data["scenes"]) if s["sid"] == after), len(data["scenes"]))
        data["scenes"].insert(idx, scene)
        return {"t": "sadd", "after": after, "scene": scene}

    sc = _scene_of(data, op.get("sid"))
    if t == "sdel":
        if sc is None:
            return NOOP
        if len(data["scenes"]) <= 1:
            return None
        data["scenes"].remove(sc)
        state["notes"] = [n for n in state.get("notes") or [] if n.get("sid") != sc["sid"]]
        return {"t": "sdel", "sid": sc["sid"]}
    if t not in ("stitle", "add", "upd", "del"):
        return None
    if sc is None:
        return NOOP                      # 남이 먼저 지운 장면
    if t == "stitle":
        title = str(op.get("title") or "")[:MAX_TITLE]
        if (sc.get("title") or "") == title:
            return NOOP
        sc["title"] = title
        return {"t": "stitle", "sid": sc["sid"], "title": title}
    if t == "del":
        idx = next((i for i, it in enumerate(sc["items"]) if it.get("id") == op.get("id")), -1)
        if idx < 0:
            return NOOP
        sc["items"].pop(idx)
        return {"t": "del", "sid": sc["sid"], "id": op["id"]}
    raw = op.get("item")
    if not isinstance(raw, dict) or not _valid_id(raw.get("id")):
        return None
    row = clean_item(raw)
    if row is None:
        return None
    idx = next((i for i, it in enumerate(sc["items"]) if it.get("id") == row["id"]), -1)
    if idx >= 0:
        if sc["items"][idx] == row:
            return NOOP
        sc["items"][idx] = row
        return {"t": "upd", "sid": sc["sid"], "item": row}
    if t == "upd":
        return NOOP                      # 남이 먼저 지운 항목
    if _total_items(data) >= MAX_ITEMS:
        return None
    sc["items"].append(row)
    return {"t": "add", "sid": sc["sid"], "item": row}


# ------------------------------------------------------------------
# 💬 메모 핀 (피드백)
# ------------------------------------------------------------------
def note_out(n: dict) -> dict:
    """브라우저로 내보낼 모양 — 디스코드 ID 대신 `by`(짧은 서명)만 줘요."""
    return {"id": n["id"], "sid": n["sid"], "u": n["u"], "v": n["v"], "text": n["text"],
            "name": n.get("name") or "멤버", "by": by_of(n.get("uid")), "at": n.get("at")}


def add_note(state: dict, raw, uid, name: str) -> dict | None:
    if not isinstance(raw, dict) or not _valid_id(raw.get("id")):
        return None
    notes = state.setdefault("notes", [])
    if len(notes) >= MAX_NOTES or any(n.get("id") == raw["id"] for n in notes):
        return None
    if _scene_of(state["data"], raw.get("sid")) is None:
        return None
    u, v = _num(raw.get("u")), _num(raw.get("v"))
    text = " ".join(str(raw.get("text") or "").split())[:MAX_NOTE]
    if u is None or v is None or not text:
        return None
    note = {"id": raw["id"], "sid": raw["sid"], "u": u, "v": v, "text": text,
            "uid": str(uid), "name": str(name or "멤버")[:24], "at": int(time.time())}
    notes.append(note)
    return note


def del_note(state: dict, note_id, uid, *, anyone: bool = False) -> bool:
    """쓴 사람만 지워요. `anyone`(판 주인)이면 누구 것이든."""
    notes = state.get("notes") or []
    for i, n in enumerate(notes):
        if n.get("id") == note_id:
            if not anyone and str(n.get("uid")) != str(uid):
                return False
            notes.pop(i)
            return True
    return False


# ------------------------------------------------------------------
# 🔑 링크 — 편집 토큰 · 개인 통행증(같이 그리기 c / 피드백 f)
# ------------------------------------------------------------------
_FALLBACK_SECRET = secrets.token_bytes(32)        # 토큰이 없는 곳(테스트·미리보기)용 — 재시작하면 바뀌어요
PASS_TTL = {"c": 12 * 3600, "f": 30 * 86400}      # 같이 그리기 12시간 · 피드백 30일


def _secret() -> bytes:
    raw = os.getenv("TACTICS_SECRET") or os.getenv("DISCORD_TOKEN") or ""
    if not raw:
        return _FALLBACK_SECRET
    return hashlib.sha256(b"akgui-tactics-v1:" + raw.encode()).digest()


def _sig(msg: str, n: int) -> str:
    mac = hmac.new(_secret(), msg.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")[:n]


def by_of(uid) -> str:
    return _sig(f"by:{uid}", 10) if uid else ""


def edit_token_for(view_id: str) -> str:
    """보기ID → 편집 토큰. 저장해 두지 않아도 언제나 같은 값을 다시 만들 수 있어요(봇 토큰이 바뀌면 달라져요)."""
    return _sig(f"edit:{view_id}", 24)


def make_pass(view_id: str, uid: int, role: str) -> str:
    """디스코드 버튼을 누른 사람에게 주는 개인 링크 조각: `uid.역할.만료.서명`."""
    exp = int(time.time()) + PASS_TTL[role]
    body = f"{int(uid)}.{role}.{exp:x}"
    return f"{body}.{_sig(f'pass:{view_id}:{body}', 16)}"


def check_pass(view_id: str, text) -> tuple[str, str] | None:
    """(uid, 역할) 또는 None(위조·만료)."""
    if not isinstance(text, str) or len(text) > 80:
        return None
    parts = text.split(".")
    if len(parts) != 4 or not parts[0].isdigit() or parts[1] not in PASS_TTL:
        return None
    body = ".".join(parts[:3])
    if not hmac.compare_digest(parts[3], _sig(f"pass:{view_id}:{body}", 16)):
        return None
    try:
        exp = int(parts[2], 16)
    except ValueError:
        return None
    if exp < time.time():
        return None
    return parts[0], parts[1]


# ------------------------------------------------------------------
# 저장
# ------------------------------------------------------------------
LIST_FIELDS = {"title": 1, "map": 1, "uid": 1, "updated_at": 1, "shared_at": 1, "post": 1, "forked_from": 1}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _by_token(token: str) -> dict:
    h = _hash(token)
    return {"$or": [{"edit_hash": h}, {"edit_hash2": h}]}


def _create_sync(uid: int, map_key: str, title: str, channel_id: int | None,
                 data: dict | None, extra: dict | None) -> tuple[str, str]:
    view_id = secrets.token_urlsafe(8)
    edit_token = edit_token_for(view_id)
    now = datetime.now(timezone.utc)
    doc = {"_id": view_id, "edit_hash": _hash(edit_token), "uid": str(uid),
           "channel": str(channel_id) if channel_id else None,   # 📤 올릴 채널(/작전판을 쓴 곳)
           "map": map_key, "title": title[:MAX_TITLE],
           "data": data or empty_data(), "notes": [],
           "created_at": now, "updated_at": now}
    doc.update(extra or {})
    _boards.insert_one(doc)
    return view_id, edit_token


async def create_board(uid: int, map_key: str, title: str, channel_id: int | None = None,
                       data: dict | None = None, extra: dict | None = None) -> tuple[str, str]:
    """(보기ID, 편집토큰)"""
    return await asyncio.to_thread(_create_sync, uid, map_key, title, channel_id, data, extra)


async def count_boards(uid: int) -> int:
    return await asyncio.to_thread(_boards.count_documents, {"uid": str(uid)})


def _get_sync(view_id: str | None, edit_token: str | None) -> dict | None:
    doc = _boards.find_one(_by_token(edit_token)) if edit_token else _boards.find_one({"_id": view_id})
    if doc and isinstance(doc.get("data"), dict) and ensure_ids(doc["data"]):
        # 예전 판에 id를 한 번만 붙여 둬요(그 사이 저장됐으면 건드리지 않아요)
        _boards.update_one({"_id": doc["_id"], "updated_at": doc.get("updated_at")},
                           {"$set": {"data": doc["data"]}})
    return doc


async def get_board(*, view_id: str | None = None, edit_token: str | None = None) -> dict | None:
    key = edit_token or view_id
    if not key or len(key) > 64:
        return None
    return await asyncio.to_thread(_get_sync, view_id, edit_token)


def _save_sync(edit_token: str, data: dict, title: str | None) -> bool:
    fields = {"data": data, "updated_at": datetime.now(timezone.utc)}
    if title is not None:
        fields["title"] = title[:MAX_TITLE]
    res = _boards.update_one(_by_token(edit_token), {"$set": fields})
    return res.matched_count == 1


async def save_board(edit_token: str, data: dict, title: str | None = None) -> bool:
    return await asyncio.to_thread(_save_sync, edit_token, data, title)


def _save_state_sync(view_id: str, state: dict) -> bool:
    res = _boards.update_one({"_id": view_id}, {"$set": {
        "data": state["data"], "title": (state.get("title") or "")[:MAX_TITLE],
        "notes": state.get("notes") or [], "updated_at": datetime.now(timezone.utc)}})
    return res.matched_count == 1


async def save_state(view_id: str, state: dict) -> bool:
    """실시간 방의 상태(판·제목·메모)를 통째로 저장해요."""
    return await asyncio.to_thread(_save_state_sync, view_id, state)


def _reissue_sync(view_id: str, uid: int) -> str | None:
    doc = _boards.find_one({"_id": view_id, "uid": str(uid)}, {"edit_hash": 1, "edit_hash2": 1})
    if doc is None:
        return None
    token = edit_token_for(view_id)
    h = _hash(token)
    if h not in (doc.get("edit_hash"), doc.get("edit_hash2")):
        _boards.update_one({"_id": view_id}, {"$set": {"edit_hash2": h}})
    return token


async def reissue_edit_token(view_id: str, uid: int) -> str | None:
    """📂 내 작전판: 만든 사람에게 편집 링크를 다시 줘요. 남의 판이면 None. 옛 링크는 그대로 살아 있어요."""
    return await asyncio.to_thread(_reissue_sync, view_id, uid)


def _list_sync(query: dict, sort_key: str, limit: int) -> list[dict]:
    return list(_boards.find(query, LIST_FIELDS).sort(sort_key, -1).limit(limit))


async def list_boards(uid: int, limit: int = 25) -> list[dict]:
    """내가 만든 판(최근 고친 순). 판 내용은 빼고 목록용 값만."""
    return await asyncio.to_thread(_list_sync, {"uid": str(uid)}, "updated_at", limit)


async def list_shared(map_key: str, limit: int = 25) -> list[dict]:
    """📚 서버 작전 모음: 그 맵에서 디스코드에 올린 판(최근 올린 순)."""
    return await asyncio.to_thread(
        _list_sync, {"map": map_key, "shared_at": {"$exists": True}}, "shared_at", limit)


def _shared_counts_sync() -> dict[str, int]:
    rows = _boards.aggregate([{"$match": {"shared_at": {"$exists": True}}},
                              {"$group": {"_id": "$map", "n": {"$sum": 1}}}])
    return {r["_id"]: r["n"] for r in rows if r.get("_id")}


async def shared_counts() -> dict[str, int]:
    return await asyncio.to_thread(_shared_counts_sync)


async def set_shared(view_id: str, channel_id: int, message_id: int) -> None:
    await asyncio.to_thread(_boards.update_one, {"_id": view_id}, {"$set": {
        "shared_at": datetime.now(timezone.utc), "post": {"channel": str(channel_id), "msg": str(message_id)}}})


def _unshare_sync(view_id: str, uid: int) -> bool:
    res = _boards.update_one({"_id": view_id, "uid": str(uid)}, {"$unset": {"shared_at": ""}})
    return res.matched_count == 1


async def unshare(view_id: str, uid: int) -> bool:
    return await asyncio.to_thread(_unshare_sync, view_id, uid)


def _delete_sync(view_id: str, uid: int) -> bool:
    return _boards.delete_one({"_id": view_id, "uid": str(uid)}).deleted_count == 1


async def delete_board(view_id: str, uid: int) -> bool:
    return await asyncio.to_thread(_delete_sync, view_id, uid)


def fork_title(title: str) -> str:
    tail = " 수정안"
    base = (title or "작전").strip()
    return base if base.endswith(tail.strip()) else base[:MAX_TITLE - len(tail)] + tail


async def fork_board(src: dict, uid: int, channel_id: int | None) -> tuple[str, str]:
    """📝 복사해서 고치기: 남의(또는 내) 판을 내 판으로 복사해요. 메모 핀은 안 따라가요."""
    data = clean_data(copy.deepcopy(src.get("data"))) or empty_data()
    return await create_board(uid, src.get("map"), fork_title(src.get("title") or ""), channel_id, data=data,
                              extra={"forked_from": src["_id"], "forked_uid": src.get("uid")})


async def ensure_indexes() -> None:
    await asyncio.to_thread(_boards.create_index, "edit_hash", unique=True)
    await asyncio.to_thread(_boards.create_index, "edit_hash2", sparse=True)
    await asyncio.to_thread(_boards.create_index, [("uid", 1), ("updated_at", -1)])
    await asyncio.to_thread(_boards.create_index, [("map", 1), ("shared_at", -1)])
