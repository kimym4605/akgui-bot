"""🗺️ /작전판 — 미니맵에 요원·스킬을 놓아 가르치는 웹 전술판 (2026-11-25, 1단계).

## 흐름

`/작전판 맵:어센트` → 나만 보이는 **✏️ 편집 링크**와 **👀 보기 링크**.
편집 링크를 열면 브라우저(폰도 됨)에서 요원을 고르고 → 스킬(Q·E·C·X)을 골라 → 맵을 눌러 놓아요.
저장하면 보기 링크로 팀원에게 보여줄 수 있어요(보기 링크로는 못 고쳐요).
자료·검사·저장은 `utils/tactics.py`, 화면은 `config/tactics/board.html`.

## 🌐 봇 안의 작은 웹 서버

discord.py가 쓰는 aiohttp로 `0.0.0.0:$PORT(8080)`. Fly `[http_service]`가 `https://akgui-bot.fly.dev`로 이어줘요.

    GET  /e/<편집토큰>            편집 화면       GET  /v/<보기ID>     보기 화면 (같은 HTML)
    GET  /api/meta                맵·요원 자료    GET  /api/board/e/<토큰> · /api/board/v/<ID>
    POST /api/board/e/<토큰>      저장(256KB까지, 1초에 한 번)
    POST /api/board/e/<토큰>/post 📤 장면마다 그림을 그려 /작전판을 쓴 채널에 올리기(30초에 한 번)
    GET  /healthz

🚨 웹 서버가 못 떠도(포트 사용 중 등) 경고만 남기고 봇은 그대로 돌아요.
🚨 브라우저가 보낸 판 자료는 `tactics.clean_data`로 걸러서 저장해요(종류·좌표·글자 수·개수).

## 2026-11-25 같은 날 다듬기(사용자 요청 1~5)
던진 경로(끌면 곡선 점선, 끝에 떨어짐) · 벽 최대/고정 길이와 📏 거리 재기 · 장면 여러 개 ·
📤 그림으로 디스코드에 올리기(`utils/tactics_render.py`) · 휴대폰 두 손가락 확대·이동.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

from utils import tactics, tactics_render
from utils.interaction_ack import ack

log = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8080"))
BASE_URL = os.getenv("TACTICS_BASE_URL", "https://akgui-bot.fly.dev").rstrip("/")
PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "config", "tactics", "board.html")
MAX_BODY = 256 * 1024
SAVE_GAP = 1.0
POST_GAP = 30.0            # 📤 디스코드에 올리기는 판마다 30초에 한 번 (도배 방지)
SIDE_KO = {"atk": "공격", "def": "수비"}
COLOR = 0x4FC3F7
NOINDEX = {"X-Robots-Tag": "noindex"}


def read_page() -> str:
    with open(PAGE_PATH, encoding="utf-8") as f:
        return f.read()


def _json(obj, status: int = 200, cache: str = "no-store") -> web.Response:
    return web.Response(text=json.dumps(obj, ensure_ascii=False), status=status,
                        content_type="application/json", headers={**NOINDEX, "Cache-Control": cache})


def build_web_app(page_html: str, session_getter, poster=None) -> web.Application:
    """`poster(doc) -> (성공, 안내문)`: 📤 디스코드에 올리기. 없으면(테스트·미리보기) 503."""
    last_save: dict[str, float] = {}
    last_post: dict[str, float] = {}

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

    def _board_out(doc: dict, *, editable: bool) -> dict:
        return {"map": doc.get("map"), "title": doc.get("title") or "", "data": doc.get("data"),
                "view": doc["_id"], "editable": editable}

    async def board_edit(request: web.Request) -> web.Response:
        doc = await tactics.get_board(edit_token=request.match_info["token"])
        if doc is None:
            return _json({"error": "없는 편집 링크예요."}, 404)
        return _json(_board_out(doc, editable=True))

    async def board_view(request: web.Request) -> web.Response:
        doc = await tactics.get_board(view_id=request.match_info["id"])
        if doc is None:
            return _json({"error": "없는 작전판이에요."}, 404)
        return _json(_board_out(doc, editable=False))

    async def board_save(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        now = time.monotonic()
        if now - last_save.get(token, 0) < SAVE_GAP:
            return _json({"error": "너무 빨라요. 잠시 뒤 다시 저장해 주세요."}, 429)
        last_save[token] = now
        if len(last_save) > 5000:
            last_save.clear()
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
        ok = await tactics.save_board(token, data, str(title) if title is not None else None)
        if not ok:
            return _json({"error": "없는 편집 링크예요."}, 404)
        return _json({"ok": True})

    async def board_post(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        doc = await tactics.get_board(edit_token=token)
        if doc is None:
            return _json({"error": "없는 편집 링크예요."}, 404)
        if poster is None:
            return _json({"error": "지금은 올릴 수 없어요."}, 503)
        now = time.monotonic()
        wait = POST_GAP - (now - last_post.get(token, -POST_GAP))
        if wait > 0:
            return _json({"error": f"{int(wait) + 1}초 뒤에 다시 올릴 수 있어요."}, 429)
        last_post[token] = now
        try:
            ok, msg = await poster(doc)
        except Exception:  # noqa: BLE001
            log.warning("🗺️ 작전판 올리기 실패", exc_info=True)
            ok, msg = False, "올리다가 오류가 났어요."
        if not ok:
            last_post.pop(token, None)
        return _json({"ok": ok, "message": msg} if ok else {"error": msg}, 200 if ok else 400)

    async def health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application(client_max_size=MAX_BODY)
    app.router.add_post("/api/board/e/{token}/post", board_post)
    app.router.add_get("/e/{token}", page)
    app.router.add_get("/v/{id}", page)
    app.router.add_get("/api/meta", meta)
    app.router.add_get("/api/board/e/{token}", board_edit)
    app.router.add_get("/api/board/v/{id}", board_view)
    app.router.add_post("/api/board/e/{token}", board_save)
    app.router.add_get("/healthz", health)
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


class Tactics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self._runner: web.AppRunner | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        try:
            await tactics.ensure_indexes()
        except Exception:  # noqa: BLE001
            log.warning("🗺️ 전술판 색인을 만들지 못했어요", exc_info=True)
        try:
            self._runner = web.AppRunner(
                build_web_app(read_page(), lambda: self.session, poster=self.post_board), access_log=None)
            await self._runner.setup()
            await web.TCPSite(self._runner, "0.0.0.0", PORT).start()
            log.info("🌐 전술판 웹 서버: 포트 %s (%s)", PORT, BASE_URL)
        except Exception:  # noqa: BLE001 — 웹이 안 떠도 봇은 돌아야 해요
            log.warning("🌐 전술판 웹 서버를 못 띄웠어요 — /작전판 링크가 안 열려요", exc_info=True)
            self._runner = None

    async def cog_unload(self):
        if self._runner is not None:
            await self._runner.cleanup()
        if self.session is not None:
            await self.session.close()

    async def post_board(self, doc: dict) -> tuple[bool, str]:
        """📤 판을 그림으로 그려 `/작전판`을 쓴 채널에 올려요."""
        channel = self.bot.get_channel(int(doc["channel"])) if doc.get("channel") else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False, "올릴 채널을 못 찾았어요. 서버 채널에서 /작전판을 다시 만들어 주세요."
        images = await render_board_images(self.session, doc)
        if not images:
            return False, "빈 작전판이에요. 스킬이나 요원을 놓고 올려 주세요."
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="작전판 보기", emoji="👀", url=f"{BASE_URL}/v/{doc['_id']}"))
        await channel.send(
            f"🗺️ **{doc.get('title') or '작전판'}** — <@{doc.get('uid')}>님의 작전판",
            files=[discord.File(io.BytesIO(b), name) for name, b in images],
            view=view, allowed_mentions=discord.AllowedMentions.none())
        log.info("🗺️ 작전판 올림: %s → #%s (%d장)", doc["_id"], channel.name, len(images))
        return True, f"#{channel.name} 에 {len(images)}장 올렸어요"

    async def map_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            ms = await tactics.maps(self.session)
        except Exception:  # noqa: BLE001
            return []
        cur = (current or "").strip().lower()
        out = [app_commands.Choice(name=m["name"], value=key) for key, m in ms.items()
               if not cur or cur in m["name"].lower() or cur in key]
        return sorted(out, key=lambda c: c.name)[:25]

    @app_commands.command(name="작전판", description="미니맵에 요원·스킬을 놓아 작전을 그려요 (웹 전술판)")
    @app_commands.describe(맵="그릴 맵", 제목="예: A 공격 기본 연막 (비워도 돼요)")
    @app_commands.autocomplete(맵=map_autocomplete)
    async def board(self, interaction: discord.Interaction, 맵: str, 제목: str | None = None):
        if not await ack(interaction, ephemeral=True):
            return
        try:
            ms = await tactics.maps(self.session)
        except Exception:  # noqa: BLE001
            await interaction.followup.send("맵 자료를 못 받아왔어요. 잠시 뒤 다시 해 주세요.", ephemeral=True)
            return
        key = (맵 or "").strip().lower()
        if key not in ms:   # 한국어 이름을 그대로 친 경우
            key = next((k for k, m in ms.items() if m["name"] == (맵 or "").strip()), "")
        if key not in ms:
            await interaction.followup.send("그 맵을 못 찾았어요. 목록에서 골라 주세요.", ephemeral=True)
            return
        title = (제목 or "").strip() or f"{ms[key]['name']} 작전"
        view_id, edit_token = await tactics.create_board(interaction.user.id, key, title, interaction.channel_id)
        em = discord.Embed(
            title=f"🗺️ {title}",
            description=("**✏️ 편집**: 요원을 고르고 → 스킬(Q·E·C·X)을 골라 → 맵을 눌러 놓아요. 다 그리면 **저장**.\n"
                         "**👀 보기 링크**를 팀원에게 주면 같은 판을 볼 수 있어요(고치지는 못해요).\n"
                         "-# 🚨 편집 링크는 남에게 주지 마세요 — 받은 사람도 고칠 수 있어요."),
            color=COLOR)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="편집", emoji="✏️", url=f"{BASE_URL}/e/{edit_token}"))
        view.add_item(discord.ui.Button(label="보기 링크", emoji="👀", url=f"{BASE_URL}/v/{view_id}"))
        await interaction.followup.send(embed=em, view=view, ephemeral=True)
        log.info("🗺️ 작전판 생성: %s %s (%s)", interaction.user.id, key, view_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tactics(bot))
