"""🗺️ /작전판 — 미니맵에 요원·스킬을 놓아 가르치는 웹 전술판 (2026-11-25).

## 흐름

`/작전판 맵:어센트`(또는 채널 패널의 🗺️ 새 작전판) → 나만 보이는 **✏️ 편집 링크**와 **👀 보기 링크**.
편집 링크를 열면 브라우저(폰도 됨)에서 요원을 고르고 → 스킬(Q·E·C·X)을 골라 → 맵을 눌러 놓아요.
자료·검사·저장은 `utils/tactics.py`, 화면은 `config/tactics/board.html`, 그림은 `utils/tactics_render.py`.

## 🌐 봇 안의 작은 웹 서버

discord.py가 쓰는 aiohttp로 `0.0.0.0:$PORT(8080)`. Fly `[http_service]`가 `https://akgui-bot.fly.dev`로 이어줘요.

    화면   /e/<편집토큰>   /v/<보기ID>   /c/<보기ID>/<통행증>(같이 그리기)   /f/<보기ID>/<통행증>(피드백)
    자료   GET  /api/meta · /api/board/<e|v>/<키> · /api/board/<c|f>/<보기ID>/<통행증>
    저장   POST /api/board/e/<토큰>          (실시간 연결이 안 될 때만 쓰는 통째 저장, 256KB·1초에 한 번)
    올리기 POST /api/board/e/<토큰>/post     📤 장면마다 그림 → 채널에(30초에 한 번) + 📚 작전 모음에 실림
    초대   POST /api/board/e/<토큰>/invite   👥 같이 그리기 초대 글(60초에 한 번)
    실시간 GET  /ws/<e|v>/<키> · /ws/<c|f>/<보기ID>/<통행증>   (WebSocket, `utils/tactics_live.py`)
    GET  /healthz

🚨 웹 서버가 못 떠도(포트 사용 중 등) 경고만 남기고 봇은 그대로 돌아요.
🚨 브라우저가 보낸 것은 전부 `tactics.clean_*`·`apply_op`로 걸러요(종류·좌표·글자 수·개수).

## 2026-11-25 업그레이드 (사용자 요청 1~5)

🚨 슬래시 명령어는 `/작전판` 하나뿐이에요(전역 100개 한도가 꽉 차서 더 못 늘려요). 맵 없이 쓰면 메뉴가 떠요.

1. 📂 **내 작전판** — 만든 판 목록에서 편집 링크를 다시 받아요(`/작전판` 메뉴, 패널 버튼). 지우기·모음에서 내리기도.
2. 🧭 **채널 패널**(`/작전판` 메뉴의 📌 버튼, 서버 소유자만 보임) + 📚 **작전 모음** — 📤 올린 판이 맵별로 모여요.
3. 💬 **피드백** — 올린 글의 [피드백 남기기] → 내 이름으로 메모 핀을 꽂는 개인 링크. [복사해서 고치기] → 내 판으로 복사.
   메모가 달리면 올린 글에 답글로 만든 사람을 불러요(같은 사람·같은 판은 10분에 한 번).
4. 👥 **같이 그리기** — 판을 연 사람끼리 실시간으로 같이 보여요. 초대 글의 [같이 그리기]를 누른 사람은 12시간 동안 고칠 수 있어요.
5. 🎬 **내 경기 장면** — 최근 경기의 한 라운드를 킬 순간마다 장면으로(`utils/tactics_match.py`, 라이엇 계정 연동 필요).

## 🚨 버튼 규칙
- 패널: `timeout=None` · 고정 `custom_id`(`akgui:tac:*`) · `cog_load`에서 `bot.add_view`. `self`에 상태를 담지 않아요.
- 올린 글·초대 글의 버튼은 **DynamicItem**(`akgui:tac:<fb|fork|join>:<보기ID>`) — 재시작 뒤에도 살아 있어야 해요.
- 비공개(ephemeral) 고르기 화면은 한 번 쓰고 버리는 평범한 View예요(5분 지나면 다시 열면 돼요).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from aiohttp import WSMsgType, web
from discord import app_commands
from discord.ext import commands

from utils import henrik_api, riot_account_store, settings_store, tactics, tactics_match, tactics_render
from utils.interaction_ack import ack
from utils.tactics_live import Hub

log = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8080"))
BASE_URL = os.getenv("TACTICS_BASE_URL", "https://akgui-bot.fly.dev").rstrip("/")
PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "config", "tactics", "board.html")
MAX_BODY = 256 * 1024
WS_MAX = 512 * 1024        # 장면 하나를 통째로 보내는 연산(sadd)이 들어갈 크기
SAVE_GAP = 1.0
POST_GAP = 30.0            # 📤 디스코드에 올리기는 판마다 30초에 한 번 (도배 방지)
INVITE_GAP = 60.0          # 👥 초대 글은 판마다 60초에 한 번
NOTE_NOTICE_GAP = 600.0    # 💬 메모 알림은 같은 사람·같은 판이면 10분에 한 번
MATCH_SIZE = 5             # 🎬 불러올 최근 경기 수 (한 판에 1MB쯤이라 적게)
SIDE_KO = {"atk": "공격", "def": "수비"}
COLOR = 0x4FC3F7
NOINDEX = {"X-Robots-Tag": "noindex"}
KEY_PANEL = "tactics:panel"   # {channel, message}
KST = timezone(timedelta(hours=9))
NO_PING = discord.AllowedMentions.none()
HUB_KEY = web.AppKey("tactics_hub", Hub)


def read_page() -> str:
    with open(PAGE_PATH, encoding="utf-8") as f:
        return f.read()


def _json(obj, status: int = 200, cache: str = "no-store") -> web.Response:
    return web.Response(text=json.dumps(obj, ensure_ascii=False), status=status,
                        content_type="application/json", headers={**NOINDEX, "Cache-Control": cache})


def live_doc(hub: Hub | None, doc: dict) -> dict:
    """누가 그 판을 열어 두고 있으면 아직 저장 안 된 최신 상태로 바꿔 줘요."""
    room = hub.room(doc["_id"]) if hub is not None else None
    if room is None:
        return doc
    return {**doc, "title": room.state["title"], "data": room.state["data"], "notes": room.state["notes"]}


# ------------------------------------------------------------------
# 🌐 웹
# ------------------------------------------------------------------
def build_web_app(page_html: str, session_getter, poster=None, inviter=None, namer=None,
                  hub: Hub | None = None) -> web.Application:
    """`poster(doc) -> (성공, 안내문)`: 📤 디스코드에 올리기. `inviter(doc)`: 👥 초대 글. 없으면(테스트·미리보기) 503.
    `namer(uid) -> 이름`: 통행증으로 들어온 사람의 서버 별명."""
    hub = hub or Hub()
    last_save: dict[str, float] = {}
    last_post: dict[str, float] = {}
    last_invite: dict[str, float] = {}

    async def page(request: web.Request) -> web.Response:
        return web.Response(text=page_html, content_type="text/html",
                            headers={**NOINDEX, "Cache-Control": "no-store"})

    async def meta(request: web.Request) -> web.Response:
        try:
            s = session_getter()
            ms, ags = await tactics.maps(s), await tactics.agents(s)
        except Exception:  # noqa: BLE001
            log.warning("🗺️ 전술판 자료를 못 받았어요", exc_info=True)
            return _json({"error": "맵·요원 자료를 못 받아왔어요. 잠시 뒤 새로고침해 주세요."}, 503)
        return _json({"maps": ms, "agents": ags}, cache="public, max-age=3600")

    async def load(kind: str, key: str, pw: str | None) -> tuple[dict | None, str, str | None]:
        """(판, 역할, uid). 못 들어오면 (None, 안내문, None)."""
        if kind == "e":
            doc = await tactics.get_board(edit_token=key)
            return (doc, "e", str(doc.get("uid") or "")) if doc else (None, "없는 편집 링크예요.", None)
        doc = await tactics.get_board(view_id=key)
        if doc is None:
            return None, "없는 작전판이에요.", None
        if kind == "v":
            return doc, "v", None
        got = tactics.check_pass(key, pw)
        if got is None or got[1] != kind:
            return None, "링크가 만료됐거나 잘못됐어요. 디스코드에서 버튼을 다시 눌러 주세요.", None
        return doc, kind, got[0]

    def board_out(doc: dict, role: str, uid: str | None) -> dict:
        doc = live_doc(hub, doc)
        return {"map": doc.get("map"), "title": doc.get("title") or "", "data": doc.get("data"),
                "notes": [tactics.note_out(n) for n in doc.get("notes") or []],
                "view": doc["_id"], "role": role, "editable": role in ("e", "c"), "by": tactics.by_of(uid)}

    def board_get(kind: str):
        async def handler(request: web.Request) -> web.Response:
            info = request.match_info
            doc, role, uid = await load(kind, info["key"], info.get("pw"))
            if doc is None:
                return _json({"error": role}, 404)
            return _json(board_out(doc, role, uid))
        return handler

    def gap_left(table: dict[str, float], key: str, gap: float) -> float:
        now = time.monotonic()
        left = gap - (now - table.get(key, -gap))
        if left <= 0:
            table[key] = now
            if len(table) > 5000:
                table.clear()
                table[key] = now
        return left

    async def board_save(request: web.Request) -> web.Response:
        token = request.match_info["key"]
        if gap_left(last_save, token, SAVE_GAP) > 0:
            return _json({"error": "너무 빨라요. 잠시 뒤 다시 저장해 주세요."}, 429)
        try:
            body = await request.json()
        except web.HTTPRequestEntityTooLarge:
            raise                      # 256KB 넘음 → 413 그대로
        except Exception:  # noqa: BLE001
            return _json({"error": "잘못된 요청이에요."}, 400)
        data = tactics.clean_data((body or {}).get("data"))
        if data is None:
            return _json({"error": "판 자료가 이상하거나 너무 커요(스킬·표시는 300개까지)."}, 400)
        title = (body or {}).get("title")
        title = str(title) if title is not None else None
        doc = await tactics.get_board(edit_token=token)
        if doc is None:
            return _json({"error": "없는 편집 링크예요."}, 404)
        room = hub.room(doc["_id"])
        if room is not None:
            room.reset(data, title)    # 열어 둔 사람들 화면도 이 내용으로
        elif not await tactics.save_board(token, data, title):
            return _json({"error": "없는 편집 링크예요."}, 404)
        return _json({"ok": True, "data": data})

    def owner_action(table: dict[str, float], gap: float, action_getter, fail_text: str):
        async def handler(request: web.Request) -> web.Response:
            token = request.match_info["key"]
            doc = await tactics.get_board(edit_token=token)
            if doc is None:
                return _json({"error": "없는 편집 링크예요."}, 404)
            action = action_getter()
            if action is None:
                return _json({"error": "지금은 할 수 없어요."}, 503)
            left = gap_left(table, token, gap)
            if left > 0:
                return _json({"error": f"{int(left) + 1}초 뒤에 다시 할 수 있어요."}, 429)
            try:
                ok, msg = await action(live_doc(hub, doc))
            except Exception:  # noqa: BLE001
                log.warning("🗺️ 작전판: %s", fail_text, exc_info=True)
                ok, msg = False, fail_text
            if not ok:
                table.pop(token, None)
            return _json({"ok": ok, "message": msg} if ok else {"error": msg}, 200 if ok else 400)
        return handler

    def ws_route(kind: str):
        async def handler(request: web.Request) -> web.StreamResponse:
            info = request.match_info
            doc, role, uid = await load(kind, info["key"], info.get("pw"))
            if doc is None:
                return _json({"error": role}, 404)
            ws = web.WebSocketResponse(heartbeat=25, max_msg_size=WS_MAX)
            await ws.prepare(request)
            name = "보는 사람"
            if uid:
                name = "멤버"
                if namer is not None:
                    try:
                        name = await namer(uid)
                    except Exception:  # noqa: BLE001
                        log.warning("🗺️ 이름을 못 찾았어요 (%s)", uid, exc_info=True)
            joined = hub.join(doc, ws, role, uid, name)
            if joined is None:
                await ws.close(code=1013, message=b"full")
                return ws
            room, conn = joined
            try:
                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        try:
                            room.handle(conn, msg.data)
                        except Exception:  # noqa: BLE001 — 메시지 하나 때문에 연결을 끊지 않아요
                            log.warning("👥 작전판 메시지 처리 실패 (%s)", room.view_id, exc_info=True)
                    elif msg.type == WSMsgType.ERROR:
                        break
            finally:
                await hub.leave(room, conn)
            return ws
        return handler

    async def health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def on_shutdown(app: web.Application) -> None:
        await hub.close_all()

    app = web.Application(client_max_size=MAX_BODY)
    app[HUB_KEY] = hub
    app.on_shutdown.append(on_shutdown)
    r = app.router
    r.add_post("/api/board/e/{key}/post", owner_action(last_post, POST_GAP, lambda: poster, "올리다가 오류가 났어요."))
    r.add_post("/api/board/e/{key}/invite",
               owner_action(last_invite, INVITE_GAP, lambda: inviter, "초대 글을 올리다가 오류가 났어요."))
    r.add_post("/api/board/e/{key}", board_save)
    r.add_get("/e/{key}", page)
    r.add_get("/v/{key}", page)
    r.add_get("/c/{key}/{pw}", page)
    r.add_get("/f/{key}/{pw}", page)
    r.add_get("/api/meta", meta)
    for kind in ("e", "v"):
        r.add_get(f"/api/board/{kind}/{{key}}", board_get(kind))
        r.add_get(f"/ws/{kind}/{{key}}", ws_route(kind))
    for kind in ("c", "f"):
        r.add_get(f"/api/board/{kind}/{{key}}/{{pw}}", board_get(kind))
        r.add_get(f"/ws/{kind}/{{key}}/{{pw}}", ws_route(kind))
    r.add_get("/healthz", health)
    return app


async def render_board_images(session, doc: dict) -> list[tuple[str, bytes]]:
    """판의 장면마다 그림 한 장(빈 장면은 건너뛰어요). [(파일 이름, JPEG)]"""
    ms = await tactics.maps(session)
    mapinfo = ms.get(doc.get("map"))
    if mapinfo is None:
        return []
    agents = {a["id"]: a for a in await tactics.agents(session)}
    data = doc.get("data") or {}
    scenes = (data.get("scenes") or [])[:10]
    used = [(i, sc) for i, sc in enumerate(scenes) if sc.get("items")]
    urls = []
    for _, sc in used:
        urls += tactics_render.needed_urls(mapinfo, agents, sc["items"])
    images = await tactics_render.fetch_images(session, urls)
    side = SIDE_KO.get(data.get("side"), "공격")
    out = []
    for i, sc in used:
        sub = f"{mapinfo['name']} · {side}"
        if len(scenes) > 1:
            sub += f" · 장면 {i + 1}/{len(scenes)}"
        title = doc.get("title") or f"{mapinfo['name']} 작전"
        if sc.get("title"):
            title = f"{title} - {sc['title']}"
        jpg = await asyncio.to_thread(
            tactics_render.render_scene, mapinfo=mapinfo, agents=agents, images=images,
            items=sc["items"], title=title, subtitle=sub)
        out.append((f"tactics_{i + 1}.jpg", jpg))
    return out


# ------------------------------------------------------------------
# 디스코드 화면
# ------------------------------------------------------------------
def _cog(interaction: discord.Interaction) -> "Tactics | None":
    return interaction.client.get_cog("Tactics")


def _md(text: str) -> str:
    return discord.utils.escape_markdown(text or "")


def _day(dt) -> str:
    if not isinstance(dt, datetime):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%m/%d")


def link_button(label: str, emoji: str, url: str) -> discord.ui.Button:
    return discord.ui.Button(label=label, emoji=emoji, url=url)


def links_view(view_id: str, edit_token: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(link_button("편집", "✏️", f"{BASE_URL}/e/{edit_token}"))
    view.add_item(link_button("보기 링크", "👀", f"{BASE_URL}/v/{view_id}"))
    return view


def created_embed(title: str, extra: str = "") -> discord.Embed:
    return discord.Embed(
        title=f"🗺️ {title}",
        description=("**✏️ 편집**: 요원을 고르고 → 스킬(Q·E·C·X)을 골라 → 맵을 눌러 놓아요. 저장은 자동이에요.\n"
                     "**👀 보기 링크**를 팀원에게 주면 같은 판을 실시간으로 같이 볼 수 있어요(고치지는 못해요).\n"
                     + (extra + "\n" if extra else "") +
                     "-# 🚨 편집 링크는 남에게 주지 마세요. 링크를 잃어버리면 `/작전판` → 📂 내 작전판에서 다시 받아요."),
        color=COLOR)


class BoardButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"akgui:tac:(?P<act>fb|fork|join):(?P<vid>[A-Za-z0-9_-]{6,20})",
):
    """올린 글·초대 글에 붙는 버튼. custom_id에 판(보기ID)이 들어 있어 재시작 뒤에도 살아 있어요."""
    LOOK = {"fb": ("피드백 남기기", "💬", discord.ButtonStyle.secondary),
            "fork": ("복사해서 고치기", "📝", discord.ButtonStyle.secondary),
            "join": ("같이 그리기", "👥", discord.ButtonStyle.success)}

    def __init__(self, act: str, vid: str):
        label, emoji, style = self.LOOK[act]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style,
                                           custom_id=f"akgui:tac:{act}:{vid}"))
        self.act, self.vid = act, vid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["act"], match["vid"])

    async def callback(self, interaction: discord.Interaction):
        if not await ack(interaction, ephemeral=True, thinking=True):
            return
        cog = _cog(interaction)
        if cog is None:
            await interaction.followup.send("작전판을 잠시 쓸 수 없어요. 조금 뒤 다시 눌러 주세요.", ephemeral=True)
            return
        await {"fb": cog.act_feedback, "fork": cog.act_fork, "join": cog.act_join}[self.act](interaction, self.vid)


class TacticsPanelView(discord.ui.View):
    """채널에 박아 두는 상설 패널. 🚨 봇 전체에 하나라 `self`에 상태를 담지 않아요."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _open(self, interaction: discord.Interaction, name: str) -> None:
        if not await ack(interaction, ephemeral=True, thinking=True):
            return
        cog = _cog(interaction)
        if cog is None:
            await interaction.followup.send("작전판을 잠시 쓸 수 없어요. 조금 뒤 다시 눌러 주세요.", ephemeral=True)
            return
        await getattr(cog, name)(interaction)

    @discord.ui.button(label="새 작전판", emoji="🗺️", style=discord.ButtonStyle.primary, custom_id="akgui:tac:new")
    async def new(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "show_new")

    @discord.ui.button(label="내 작전판", emoji="📂", style=discord.ButtonStyle.secondary, custom_id="akgui:tac:mine")
    async def mine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "show_mine")

    @discord.ui.button(label="작전 모음", emoji="📚", style=discord.ButtonStyle.secondary, custom_id="akgui:tac:lib")
    async def lib(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "show_library")

    @discord.ui.button(label="내 경기 장면", emoji="🎬", style=discord.ButtonStyle.secondary,
                       custom_id="akgui:tac:match")
    async def match(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "show_matches")


def panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🗺️ 작전판 — 미니맵에 스킬을 놓아 작전을 짜고 가르쳐요",
        color=COLOR,
        description=(
            "**🗺️ 새 작전판** 맵을 고르면 그리는 링크를 드려요. 브라우저에서 열려요(폰도 돼요).\n"
            "**📂 내 작전판** 만든 판을 다시 열어요. 통화하면서 **같이 그리기** 초대도 여기서 해요.\n"
            "**📚 작전 모음** 서버에 올라온 작전을 맵별로 봐요. 피드백을 남기거나 복사해서 고칠 수 있어요.\n"
            "**🎬 내 경기 장면** 최근 경기의 한 라운드를 킬 순간마다 장면으로 불러와요"
            "(`/티어 계정등록`으로 라이엇 계정 연동 필요).\n"
            "-# 다 그린 뒤 📤 디스코드에 올리기를 누르면 이 채널에 그림이 올라오고 작전 모음에 실려요."))


class PickView(discord.ui.View):
    """한 번 쓰고 버리는 드롭다운(비공개 메시지용). 고르면 `on_pick(interaction, 값)`."""

    def __init__(self, placeholder: str, options: list[discord.SelectOption], on_pick):
        super().__init__(timeout=300)
        self.on_pick = on_pick      # 테스트에서 고른 것처럼 부를 수 있게
        select = discord.ui.Select(placeholder=placeholder[:150], options=options[:25])

        async def picked(interaction: discord.Interaction):
            if not await ack(interaction):
                return
            await on_pick(interaction, select.values[0])

        select.callback = picked
        self.add_item(select)


def action_button(label: str, emoji: str, style: discord.ButtonStyle, on_click) -> discord.ui.Button:
    """비공개 화면용 버튼 — 누르면 받아 두고(`ack`) `on_click(interaction)`."""
    button = discord.ui.Button(label=label, emoji=emoji, style=style)

    async def clicked(interaction: discord.Interaction):
        if not await ack(interaction):
            return
        await on_click(interaction)

    button.callback = clicked
    return button


# ------------------------------------------------------------------
# cog
# ------------------------------------------------------------------
class Tactics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self._runner: web.AppRunner | None = None
        self.hub = Hub(on_note=self.note_posted)
        self._invited: dict[str, float] = {}
        self._noted: dict[tuple, float] = {}

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        # 🚨 이 두 줄이 없으면 재시작 뒤 패널·올린 글의 버튼이 아무 반응이 없어요.
        self.bot.add_view(TacticsPanelView())
        self.bot.add_dynamic_items(BoardButton)
        try:
            await tactics.ensure_indexes()
        except Exception:  # noqa: BLE001
            log.warning("🗺️ 전술판 색인을 만들지 못했어요", exc_info=True)
        try:
            self._runner = web.AppRunner(
                build_web_app(read_page(), lambda: self.session, poster=self.post_board,
                              inviter=self.post_invite, namer=self.member_name, hub=self.hub),
                access_log=None)
            await self._runner.setup()
            await web.TCPSite(self._runner, "0.0.0.0", PORT).start()
            log.info("🌐 전술판 웹 서버: 포트 %s (%s)", PORT, BASE_URL)
        except Exception:  # noqa: BLE001 — 웹이 안 떠도 봇은 돌아야 해요
            log.warning("🌐 전술판 웹 서버를 못 띄웠어요 — /작전판 링크가 안 열려요", exc_info=True)
            self._runner = None

    async def cog_unload(self):
        self.bot.remove_dynamic_items(BoardButton)
        if self._runner is not None:
            await self._runner.cleanup()      # on_shutdown → 열려 있던 판 저장
        else:
            await self.hub.flush_all()
        if self.session is not None:
            await self.session.close()

    # -------------------------- 공용 --------------------------
    async def member_name(self, uid) -> str:
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return "멤버"
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if member is not None:
                return member.display_name[:24]
        user = self.bot.get_user(uid)
        return (user.display_name if user is not None else "멤버")[:24]

    async def current(self, view_id: str) -> dict | None:
        """판 하나(누가 열어 두고 있으면 아직 저장 안 된 최신 상태로)."""
        doc = await tactics.get_board(view_id=view_id)
        return live_doc(self.hub, doc) if doc else None

    def _text_channel(self, channel_id) -> discord.TextChannel | discord.Thread | None:
        try:
            channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, (discord.TextChannel, discord.Thread)) else None

    async def _room_for_new(self, interaction: discord.Interaction) -> bool:
        """새 판을 만들어도 되는지(한 사람 100개까지). 안 되면 안내하고 False."""
        if await tactics.count_boards(interaction.user.id) >= tactics.MAX_BOARDS_PER_USER:
            await interaction.followup.send(
                f"작전판은 한 사람이 {tactics.MAX_BOARDS_PER_USER}개까지 만들 수 있어요. "
                "📂 내 작전판에서 안 쓰는 판을 지워 주세요.", ephemeral=True)
            return False
        return True

    # -------------------------- 📤 올리기 · 👥 초대 · 💬 메모 알림 --------------------------
    async def post_board(self, doc: dict) -> tuple[bool, str]:
        """📤 판을 그림으로 그려 `/작전판`을 쓴 채널에 올리고 📚 작전 모음에 실어요."""
        channel = self._text_channel(doc.get("channel"))
        if channel is None:
            return False, "올릴 채널을 못 찾았어요. 서버 채널에서 /작전판을 다시 만들어 주세요."
        images = await render_board_images(self.session, doc)
        if not images:
            return False, "빈 작전판이에요. 스킬이나 요원을 놓고 올려 주세요."
        head = f"🗺️ **{_md(doc.get('title') or '작전판')}** — <@{doc.get('uid')}>님의 작전판"
        origin = doc.get("forked_uid")
        if origin and str(origin) != str(doc.get("uid")):
            head += f" (<@{origin}>님 작전판의 수정안)"
        head += "\n-# 💬 피드백을 남기거나 📝 복사해서 내 생각대로 고쳐 볼 수 있어요."
        view = discord.ui.View(timeout=None)
        view.add_item(link_button("작전판 보기", "👀", f"{BASE_URL}/v/{doc['_id']}"))
        view.add_item(BoardButton("fb", doc["_id"]))
        view.add_item(BoardButton("fork", doc["_id"]))
        message = await channel.send(
            head, files=[discord.File(io.BytesIO(b), name) for name, b in images],
            view=view, allowed_mentions=NO_PING)
        await tactics.set_shared(doc["_id"], channel.id, message.id)
        log.info("🗺️ 작전판 올림: %s → #%s (%d장)", doc["_id"], channel.name, len(images))
        return True, f"#{channel.name} 에 {len(images)}장 올렸어요 (📚 작전 모음에도 실렸어요)"

    async def post_invite(self, doc: dict, channel=None) -> tuple[bool, str]:
        """👥 같이 그리기 초대 글. 버튼을 누른 사람마다 12시간짜리 개인 링크를 받아요."""
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            channel = self._text_channel(doc.get("channel"))
        if channel is None:
            return False, "초대 글을 올릴 채널을 못 찾았어요. 서버 채널에서 다시 해 주세요."
        now = time.monotonic()
        left = INVITE_GAP - (now - self._invited.get(doc["_id"], -INVITE_GAP))
        if left > 0:
            return False, f"초대 글은 {int(left) + 1}초 뒤에 다시 올릴 수 있어요."
        self._invited[doc["_id"]] = now
        if len(self._invited) > 2000:
            self._invited.clear()
        view = discord.ui.View(timeout=None)
        view.add_item(BoardButton("join", doc["_id"]))
        view.add_item(link_button("보기만", "👀", f"{BASE_URL}/v/{doc['_id']}"))
        await channel.send(
            f"👥 **{_md(doc.get('title') or '작전판')}** — <@{doc.get('uid')}>님이 작전판을 같이 그리자고 해요.\n"
            "-# [같이 그리기]를 누르면 내 이름으로 들어가는 링크를 받아요(12시간 동안 고칠 수 있어요).",
            view=view, allowed_mentions=NO_PING)
        return True, f"#{channel.name} 에 초대 글을 올렸어요"

    def note_posted(self, room, note: dict) -> None:
        """💬 남이 메모 핀을 남겼어요 → 올린 글이 있으면 답글로 만든 사람을 불러요(10분에 한 번)."""
        key = (room.view_id, note.get("uid"))
        now = time.monotonic()
        if now - self._noted.get(key, -NOTE_NOTICE_GAP) < NOTE_NOTICE_GAP:
            return
        self._noted[key] = now
        if len(self._noted) > 2000:
            self._noted.clear()
        asyncio.ensure_future(self._announce_note(room.view_id, room.owner, room.state["title"], dict(note)))

    async def _announce_note(self, view_id: str, owner: str, title: str, note: dict) -> None:
        try:
            doc = await tactics.get_board(view_id=view_id)
            post = (doc or {}).get("post") or {}
            channel = self._text_channel(post.get("channel"))
            if channel is None or not owner.isdigit():
                return
            view = discord.ui.View(timeout=None)
            view.add_item(link_button("작전판 보기", "👀", f"{BASE_URL}/v/{view_id}"))
            reference = None
            if str(post.get("msg") or "").isdigit():
                reference = discord.MessageReference(message_id=int(post["msg"]), channel_id=channel.id,
                                                     fail_if_not_exists=False)
            await channel.send(
                f"💬 <@{owner}>님, **{_md(note.get('name') or '멤버')}**님이 「{_md(title or '작전판')}」에 "
                f"피드백을 남겼어요.\n> {_md(note.get('text') or '')[:150]}",
                view=view, reference=reference,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, replied_user=False,
                                                         users=[discord.Object(id=int(owner))]))
        except Exception:  # noqa: BLE001
            log.warning("💬 작전판 피드백 알림을 못 올렸어요 (%s)", view_id, exc_info=True)

    # -------------------------- 올린 글 버튼 --------------------------
    async def _owner_link(self, interaction: discord.Interaction, doc: dict) -> bool:
        """누른 사람이 그 판을 만든 사람이면 편집 링크를 줘요(통행증이 필요 없어요). 줬으면 True."""
        if str(doc.get("uid")) != str(interaction.user.id):
            return False
        token = await tactics.reissue_edit_token(doc["_id"], interaction.user.id)
        if token is None:
            return False
        await interaction.followup.send(
            f"**{_md(doc.get('title') or '작전판')}** — 내가 만든 판이에요. 편집 화면에서 받은 💬 피드백을 보고, "
            "나도 핀을 남기거나 지울 수 있어요.\n-# 🚨 편집 링크는 남에게 주지 마세요.",
            view=links_view(doc["_id"], token), ephemeral=True)
        return True

    async def act_feedback(self, interaction: discord.Interaction, view_id: str) -> None:
        doc = await tactics.get_board(view_id=view_id)
        if doc is None:
            await interaction.followup.send("지워진 작전판이에요.", ephemeral=True)
            return
        if await self._owner_link(interaction, doc):
            return
        view = discord.ui.View(timeout=None)
        view.add_item(link_button("피드백 남기러 가기", "💬",
                                  f"{BASE_URL}/f/{view_id}/{tactics.make_pass(view_id, interaction.user.id, 'f')}"))
        await interaction.followup.send(
            f"**{_md(doc.get('title') or '작전판')}** — 💬 피드백 핀을 고르고 맵을 누르면 그 자리에 메모가 남아요. "
            "만든 사람과 보는 사람 모두에게 보여요.\n"
            "-# 내 이름으로 남는 개인 링크예요. 남에게 주지 마세요.", view=view, ephemeral=True)

    async def act_join(self, interaction: discord.Interaction, view_id: str) -> None:
        doc = await tactics.get_board(view_id=view_id)
        if doc is None:
            await interaction.followup.send("지워진 작전판이에요.", ephemeral=True)
            return
        if await self._owner_link(interaction, doc):
            return
        view = discord.ui.View(timeout=None)
        view.add_item(link_button("같이 그리러 가기", "👥",
                                  f"{BASE_URL}/c/{view_id}/{tactics.make_pass(view_id, interaction.user.id, 'c')}"))
        await interaction.followup.send(
            f"**{_md(doc.get('title') or '작전판')}** — 들어가면 다른 사람이 그리는 게 바로 보이고, 나도 같이 그릴 수 있어요.\n"
            "-# 12시간 동안 쓸 수 있는 개인 링크예요. 남에게 주지 마세요.", view=view, ephemeral=True)

    async def act_fork(self, interaction: discord.Interaction, view_id: str) -> None:
        doc = await self.current(view_id)
        if doc is None:
            await interaction.followup.send("지워진 작전판이에요.", ephemeral=True)
            return
        if not await self._room_for_new(interaction):
            return
        new_id, token = await tactics.fork_board(doc, interaction.user.id, interaction.channel_id)
        log.info("🗺️ 작전판 복사: %s → %s (%s)", view_id, new_id, interaction.user.id)
        await interaction.followup.send(
            embed=created_embed(tactics.fork_title(doc.get("title") or ""),
                                "📝 원래 판은 그대로 두고 **내 판으로 복사**했어요. 고친 뒤 📤 올리면 수정안으로 올라가요."),
            view=links_view(new_id, token), ephemeral=True)

    # -------------------------- 🗺️ 새 작전판 --------------------------
    async def create_and_reply(self, interaction: discord.Interaction, map_key: str, title: str | None,
                               *, edit: bool) -> None:
        ms = await tactics.maps(self.session)
        if map_key not in ms:
            await self._say(interaction, "그 맵을 못 찾았어요. 목록에서 골라 주세요.", edit=edit)
            return
        if not await self._room_for_new(interaction):
            return
        title = (title or "").strip() or f"{ms[map_key]['name']} 작전"
        view_id, token = await tactics.create_board(interaction.user.id, map_key, title, interaction.channel_id)
        log.info("🗺️ 작전판 생성: %s %s (%s)", interaction.user.id, map_key, view_id)
        if edit:
            await interaction.edit_original_response(content=None, embed=created_embed(title),
                                                     view=links_view(view_id, token))
        else:
            await interaction.followup.send(embed=created_embed(title), view=links_view(view_id, token),
                                            ephemeral=True)

    @staticmethod
    async def _say(interaction: discord.Interaction, text: str, *, edit: bool) -> None:
        if edit:
            await interaction.edit_original_response(content=text, embed=None, view=None)
        else:
            await interaction.followup.send(text, ephemeral=True)

    async def show_new(self, interaction: discord.Interaction) -> None:
        try:
            ms = await tactics.maps(self.session)
        except Exception:  # noqa: BLE001
            await interaction.followup.send("맵 자료를 못 받아왔어요. 잠시 뒤 다시 해 주세요.", ephemeral=True)
            return
        options = [discord.SelectOption(label=m["name"], value=key)
                   for key, m in sorted(ms.items(), key=lambda kv: kv[1]["name"])]

        async def picked(it: discord.Interaction, key: str):
            await self.create_and_reply(it, key, None, edit=True)

        await interaction.followup.send("어느 맵에 그릴까요?", view=PickView("맵 고르기", options, picked),
                                        ephemeral=True)

    # -------------------------- 📂 내 작전판 --------------------------
    async def show_mine(self, interaction: discord.Interaction, *, edit: bool = False) -> None:
        boards = await tactics.list_boards(interaction.user.id)
        if not boards:
            await self._say(interaction, "아직 만든 작전판이 없어요. `/작전판`이나 패널의 🗺️ 새 작전판으로 만들어 보세요.",
                            edit=edit)
            return
        try:
            ms = await tactics.maps(self.session)
        except Exception:  # noqa: BLE001
            ms = {}
        options = []
        for b in boards:
            desc = f"{(ms.get(b.get('map')) or {}).get('name') or b.get('map') or '?'} · {_day(b.get('updated_at'))}"
            if b.get("shared_at"):
                desc += " · 📚 모음에 있음"
            options.append(discord.SelectOption(label=(b.get("title") or "작전판")[:100], value=b["_id"],
                                                description=desc[:100]))

        async def picked(it: discord.Interaction, view_id: str):
            await self.mine_detail(it, view_id)

        text = f"📂 내 작전판 {len(boards)}개 (최근 고친 순). 열 판을 골라 주세요."
        view = PickView("작전판 고르기", options, picked)
        if edit:
            await interaction.edit_original_response(content=text, embed=None, view=view)
        else:
            await interaction.followup.send(text, view=view, ephemeral=True)

    async def mine_detail(self, interaction: discord.Interaction, view_id: str, note: str = "") -> None:
        token = await tactics.reissue_edit_token(view_id, interaction.user.id)
        doc = await self.current(view_id) if token else None
        if doc is None:
            await self._say(interaction, "없는 작전판이에요(이미 지웠을 수 있어요).", edit=True)
            return
        ms = await tactics.maps(self.session)
        scenes = (doc.get("data") or {}).get("scenes") or []
        lines = [f"{(ms.get(doc.get('map')) or {}).get('name') or doc.get('map')} · 장면 {len(scenes)}개 · "
                 f"놓인 것 {sum(len(s.get('items') or []) for s in scenes)}개 · 💬 피드백 {len(doc.get('notes') or [])}개",
                 "📚 작전 모음에 실려 있어요." if doc.get("shared_at") else "아직 디스코드에 올리지 않았어요.",
                 "-# 🚨 편집 링크는 남에게 주지 마세요. 같이 그리려면 👥 같이 그리기 초대를 쓰세요."]
        if note:
            lines.insert(0, note)
        embed = discord.Embed(title=f"🗺️ {doc.get('title') or '작전판'}", description="\n".join(lines), color=COLOR)
        view = discord.ui.View(timeout=300)
        view.add_item(link_button("편집", "✏️", f"{BASE_URL}/e/{token}"))
        view.add_item(link_button("보기 링크", "👀", f"{BASE_URL}/v/{view_id}"))

        async def invite(it: discord.Interaction):
            ok, msg = await self.post_invite(doc, channel=it.channel)
            await self.mine_detail(it, view_id, ("👥 " if ok else "⚠️ ") + msg)

        async def unshare(it: discord.Interaction):
            await tactics.unshare(view_id, it.user.id)
            await self.mine_detail(it, view_id, "📚 작전 모음에서 내렸어요(올린 글은 그대로 있어요).")

        async def ask_delete(it: discord.Interaction):
            confirm = discord.ui.View(timeout=120)

            async def really(it2: discord.Interaction):
                if await tactics.delete_board(view_id, it2.user.id):
                    await self.hub.close_room(view_id, save=False)
                    log.info("🗺️ 작전판 삭제: %s (%s)", view_id, it2.user.id)
                await self.show_mine(it2, edit=True)

            async def cancel(it2: discord.Interaction):
                await self.mine_detail(it2, view_id)

            confirm.add_item(action_button("정말 삭제", "🗑️", discord.ButtonStyle.danger, really))
            confirm.add_item(action_button("취소", "↩️", discord.ButtonStyle.secondary, cancel))
            await it.edit_original_response(
                content=f"**{_md(doc.get('title') or '작전판')}** 을(를) 지울까요? 링크가 전부 안 열리게 되고 되돌릴 수 없어요.",
                embed=None, view=confirm)

        async def back(it: discord.Interaction):
            await self.show_mine(it, edit=True)

        view.add_item(action_button("같이 그리기 초대", "👥", discord.ButtonStyle.success, invite))
        if doc.get("shared_at"):
            view.add_item(action_button("모음에서 내리기", "📚", discord.ButtonStyle.secondary, unshare))
        view.add_item(action_button("삭제", "🗑️", discord.ButtonStyle.danger, ask_delete))
        view.add_item(action_button("목록", "↩️", discord.ButtonStyle.secondary, back))
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    # -------------------------- 📚 작전 모음 --------------------------
    async def show_library(self, interaction: discord.Interaction, *, edit: bool = False) -> None:
        counts = await tactics.shared_counts()
        ms = await tactics.maps(self.session)
        options = [discord.SelectOption(label=f"{ms[key]['name']} ({n})", value=key)
                   for key, n in sorted(counts.items(), key=lambda kv: -kv[1]) if key in ms]
        if not options:
            await self._say(interaction, "아직 올라온 작전이 없어요. 작전판을 그리고 📤 디스코드에 올리기를 누르면 여기에 모여요.",
                            edit=edit)
            return

        async def picked(it: discord.Interaction, key: str):
            await self.library_map(it, key)

        text = f"📚 서버 작전 모음 — 모두 {sum(counts.values())}개. 맵을 골라 주세요."
        view = PickView("맵 고르기", options, picked)
        if edit:
            await interaction.edit_original_response(content=text, embed=None, view=view)
        else:
            await interaction.followup.send(text, view=view, ephemeral=True)

    async def library_map(self, interaction: discord.Interaction, map_key: str) -> None:
        rows = await tactics.list_shared(map_key)
        ms = await tactics.maps(self.session)
        name = (ms.get(map_key) or {}).get("name") or map_key
        if not rows:
            await self._say(interaction, f"{name}에는 올라온 작전이 없어요.", edit=True)
            return
        options = []
        for b in rows:
            options.append(discord.SelectOption(
                label=(b.get("title") or "작전판")[:100], value=b["_id"],
                description=f"{await self.member_name(b.get('uid'))} · {_day(b.get('shared_at'))}"[:100]))

        async def picked(it: discord.Interaction, view_id: str):
            await self.library_detail(it, view_id, map_key)

        await interaction.edit_original_response(
            content=f"📚 {name} 작전 {len(rows)}개 (최근 올린 순). 볼 작전을 골라 주세요.", embed=None,
            view=PickView("작전 고르기", options, picked))

    async def library_detail(self, interaction: discord.Interaction, view_id: str, map_key: str) -> None:
        doc = await self.current(view_id)
        if doc is None or not doc.get("shared_at"):
            await self._say(interaction, "모음에서 내려갔거나 지워진 작전이에요.", edit=True)
            return
        ms = await tactics.maps(self.session)
        scenes = (doc.get("data") or {}).get("scenes") or []
        embed = discord.Embed(
            title=f"🗺️ {doc.get('title') or '작전판'}", color=COLOR,
            description=(f"{(ms.get(doc.get('map')) or {}).get('name') or doc.get('map')} · <@{doc.get('uid')}> · "
                         f"{_day(doc.get('shared_at'))} · 장면 {len(scenes)}개 · 💬 피드백 {len(doc.get('notes') or [])}개\n"
                         "-# 👀 보기로 열면 장면을 넘겨 볼 수 있어요. 고치고 싶으면 📝 복사해서 고치기."))
        view = discord.ui.View(timeout=None)
        view.add_item(link_button("작전판 보기", "👀", f"{BASE_URL}/v/{view_id}"))
        post = doc.get("post") or {}
        if interaction.guild_id and post.get("channel") and post.get("msg"):
            view.add_item(link_button("올린 글", "💬",
                                      f"https://discord.com/channels/{interaction.guild_id}/{post['channel']}/{post['msg']}"))
        view.add_item(BoardButton("fb", view_id))
        view.add_item(BoardButton("fork", view_id))
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    # -------------------------- 🎬 내 경기 장면 --------------------------
    async def fetch_matches(self, uid: int) -> tuple[list[dict], str]:
        """(경기 요약 목록, 안내문). 목록이 비면 안내문에 이유가 있어요."""
        account = riot_account_store.get_account(uid)
        if account is None:
            return [], "먼저 `/티어 계정등록`으로 내 라이엇 계정을 연동해 주세요. 그래야 내 경기를 찾을 수 있어요."
        api_key = os.getenv("HENRIKDEV_API_KEY")
        if not api_key:
            return [], "지금은 경기 기록을 불러올 수 없어요(전적 서버 설정 없음)."
        name, tag = account
        region = riot_account_store.get_region(uid) or riot_account_store.DEFAULT_REGION
        # 🚨 한 판에 1MB쯤이라 캐시에 남기지 않아요(cache_ttl=0). 필요한 것만 뽑아(summarize) 들고 있어요.
        status, payload = await henrik_api.request(
            self.session, f"/valorant/v3/matches/{region}/{name}/{tag}",
            headers={"Authorization": api_key}, params={"size": MATCH_SIZE}, cache_ttl=0)
        if status == 429:
            wait = (payload or {}).get(henrik_api.RETRY_AFTER_KEY)
            return [], f"전적 서버가 바빠요. {wait or 30}초쯤 뒤에 다시 눌러 주세요."
        if status != 200:
            log.warning("🎬 경기 기록 조회 실패: status=%s uid=%s", status, uid)
            return [], "경기 기록을 못 받아왔어요. 잠시 뒤 다시 해 주세요."
        ms = await tactics.maps(self.session)
        out = []
        for match in (payload or {}).get("data") or []:
            if not isinstance(match, dict):
                continue
            summary = tactics_match.summarize(match, name, tag)
            if summary and summary["map"].lower() in ms:
                out.append(summary)
        if not out:
            return [], "장면으로 만들 수 있는 최근 경기가 없어요(일반·경쟁 같은 폭파 모드 경기만 돼요)."
        return out, ""

    async def show_matches(self, interaction: discord.Interaction) -> None:
        try:
            matches, why = await self.fetch_matches(interaction.user.id)
            ms = await tactics.maps(self.session)
            agents = await tactics.agents(self.session)
        except Exception:  # noqa: BLE001
            log.warning("🎬 경기 장면 준비 실패", exc_info=True)
            matches, why = [], "경기 기록을 불러오다가 오류가 났어요. 잠시 뒤 다시 해 주세요."
        if not matches:
            await interaction.followup.send(why, ephemeral=True)
            return
        ko = {(a.get("en") or "").lower(): a["name"] for a in agents}
        options = []
        for i, s in enumerate(matches):
            m = ms[s["map"].lower()]
            when = datetime.fromtimestamp(s["start"], KST).strftime("%m/%d %H:%M") if s.get("start") else ""
            options.append(discord.SelectOption(
                label=f"{m['name']} · {tactics_match.MODE_KO.get(s['mode'], s['mode'])} · "
                      f"{s['score'][0]}:{s['score'][1]} {'승' if s['won'] else '패'}"[:100],
                description=f"{ko.get(s['agent'].lower(), s['agent'])} · {when}"[:100], value=str(i)))

        async def picked_match(it: discord.Interaction, value: str):
            await self.match_rounds(it, matches[int(value)], ms, agents)

        await interaction.followup.send(
            "🎬 어느 경기에서 가져올까요? (최근 경기)", view=PickView("경기 고르기", options, picked_match),
            ephemeral=True)

    async def match_rounds(self, interaction: discord.Interaction, summary: dict, ms: dict, agents: list) -> None:
        options = []
        for ri in range(len(summary["rounds"])):
            st = tactics_match.round_stats(summary, ri)
            if not st["kills"]:
                continue
            label = f"{ri + 1}라운드 · {'승' if st['won'] else '패'} · {st['end']}"
            if st["site"]:
                label += f" · {st['site']} 설치"
            desc = f"킬 {st['kills']}번 · 내 킬 {st['my_kills']}" + (" · 내가 죽음" if st["died"] else "")
            options.append(discord.SelectOption(label=label[:100], description=desc[:100], value=str(ri)))
        if not options:
            await self._say(interaction, "이 경기에는 장면으로 만들 킬 기록이 없어요.", edit=True)
            return

        async def picked_round(it: discord.Interaction, value: str):
            await self.match_create(it, summary, int(value), ms, agents)

        more = " (25라운드까지만 보여요)" if len(options) > 25 else ""
        await interaction.edit_original_response(
            content=f"어느 라운드를 볼까요? 킬이 난 순간마다 장면 하나가 돼요.{more}", embed=None,
            view=PickView("라운드 고르기", options, picked_round))

    async def match_create(self, interaction: discord.Interaction, summary: dict, ri: int, ms: dict,
                           agents: list) -> None:
        mapinfo = ms[summary["map"].lower()]
        made = tactics_match.round_scenes(summary, ri, mapinfo, agents)
        if made is None:
            await self._say(interaction, "이 라운드는 장면으로 만들지 못했어요.", edit=True)
            return
        if await tactics.count_boards(interaction.user.id) >= tactics.MAX_BOARDS_PER_USER:
            await self._say(interaction, f"작전판은 한 사람이 {tactics.MAX_BOARDS_PER_USER}개까지예요. "
                                         "📂 내 작전판에서 안 쓰는 판을 지워 주세요.", edit=True)
            return
        data, _ = made
        title = f"{mapinfo['name']} {ri + 1}라운드 복기"
        view_id, token = await tactics.create_board(
            interaction.user.id, summary["map"].lower(), title, interaction.channel_id, data=data,
            extra={"source": {"match": summary.get("id"), "round": ri}})
        log.info("🎬 경기 장면 작전판: %s %s R%d (%s)", interaction.user.id, summary["map"], ri + 1, view_id)
        await interaction.edit_original_response(
            content=None, view=links_view(view_id, token),
            embed=created_embed(title, f"🎬 킬이 난 순간마다 장면 하나예요({len(data['scenes'])}개, ← →로 넘겨요). "
                                       "🔵 아군 · 🔴 적군 · ✖ 그때 처치된 사람 · 노란 테두리 = 나 · 작은 화살촉 = 보던 방향.\n"
                                       "그 위에 스킬·화살표·글을 그려서 \"이때 이렇게 했어야\"를 정리해 보세요."))

    # -------------------------- 명령어 --------------------------
    async def map_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            ms = await tactics.maps(self.session)
        except Exception:  # noqa: BLE001
            return []
        cur = (current or "").strip().lower()
        out = [app_commands.Choice(name=m["name"], value=key) for key, m in ms.items()
               if not cur or cur in m["name"].lower() or cur in key]
        return sorted(out, key=lambda c: c.name)[:25]

    # 🚨 슬래시 명령어는 `/작전판` 하나뿐이에요. 봇 전체 전역 명령어가 디스코드 한도(100개)에 꽉 차 있어서,
    #    하나라도 더 만들면 봇이 시작하다가 꺼져요(CommandLimitReached). 내 작전판·패널 박기는 메뉴 버튼으로 가요.
    @app_commands.command(name="작전판", description="미니맵에 요원·스킬을 놓아 작전을 그려요 — 맵을 비우면 메뉴(내 작전판·작전 모음·경기 장면)")
    @app_commands.describe(맵="그릴 맵 (비우면 메뉴가 떠요)", 제목="예: A 공격 기본 연막 (비워도 돼요)")
    @app_commands.autocomplete(맵=map_autocomplete)
    async def board(self, interaction: discord.Interaction, 맵: str | None = None, 제목: str | None = None):
        if not await ack(interaction, ephemeral=True):
            return
        if not (맵 or "").strip():
            await self.show_menu(interaction)
            return
        try:
            ms = await tactics.maps(self.session)
        except Exception:  # noqa: BLE001
            await interaction.followup.send("맵 자료를 못 받아왔어요. 잠시 뒤 다시 해 주세요.", ephemeral=True)
            return
        key = 맵.strip().lower()
        if key not in ms:   # 한국어 이름을 그대로 친 경우
            key = next((k for k, m in ms.items() if m["name"] == 맵.strip()), "")
        await self.create_and_reply(interaction, key, 제목, edit=False)

    async def show_menu(self, interaction: discord.Interaction) -> None:
        """`/작전판`(맵 없이) — 패널과 같은 메뉴를 나만 보이게. 서버 소유자에게는 [이 채널에 패널 박기]도 보여요."""
        view = discord.ui.View(timeout=300)
        view.add_item(action_button("새 작전판", "🗺️", discord.ButtonStyle.primary, self.show_new))
        view.add_item(action_button("내 작전판", "📂", discord.ButtonStyle.secondary, self.show_mine))
        view.add_item(action_button("작전 모음", "📚", discord.ButtonStyle.secondary, self.show_library))
        view.add_item(action_button("내 경기 장면", "🎬", discord.ButtonStyle.secondary, self.show_matches))
        guild = interaction.guild
        if guild is not None and interaction.user.id == guild.owner_id:
            view.add_item(action_button("이 채널에 패널 박기", "📌", discord.ButtonStyle.success, self.post_panel))
        await interaction.followup.send(embed=panel_embed(), view=view, ephemeral=True)

    async def post_panel(self, interaction: discord.Interaction) -> None:
        """[서버 소유자 전용] 이 채널에 상설 패널을 올려요. 전에 올린 패널은 지워요."""
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("패널은 서버 소유자만 올릴 수 있어요.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("텍스트 채널에서 써주세요.", ephemeral=True)
            return
        old = settings_store.get_setting(KEY_PANEL) or {}
        try:
            message = await channel.send(embed=panel_embed(), view=TacticsPanelView())
        except discord.HTTPException:
            await interaction.followup.send("이 채널에 글을 못 올렸어요. 봇 권한(메시지 보내기·링크 첨부)을 확인해 주세요.",
                                            ephemeral=True)
            return
        settings_store.set_setting(KEY_PANEL, {"channel": channel.id, "message": message.id})
        log.info("🗺️ 작전판 패널 게시: 채널 %s", channel.id)
        if old.get("channel") and old.get("message") and int(old["message"]) != message.id:
            old_channel = self.bot.get_channel(int(old["channel"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    await old_channel.get_partial_message(int(old["message"])).delete()
                except discord.HTTPException:
                    pass
        await interaction.followup.send(
            f"🗺️ {channel.mention} 에 작전판 패널을 올렸어요. 패널에서 만든 판을 📤 올리면 이 채널에 그림이 올라와요.\n"
            "-# 메시지를 **고정(핀)** 해두면 새로 온 사람도 바로 찾아요.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tactics(bot))
