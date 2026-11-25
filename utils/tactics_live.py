"""👥 전술판 실시간 방 — 여러 명이 한 판을 같이 보고 그려요 (2026-11-25, 사용자 요청 4번).

## 구조

판 하나 = 방(`Room`) 하나. 누가 그 판을 열면(WebSocket) 방이 생기고, 마지막 사람이 나가면 저장하고 없어져요.
봇은 머신 한 대라 방은 **메모리에만** 있어요(여러 대로 늘리면 이 방식은 못 써요).

- 방의 상태(`{"title", "data", "notes"}`)가 정답이에요. 브라우저는 바뀐 것만 연산으로 보내고(`tactics.apply_op`),
  방은 검사해서 적용한 뒤 **다른 사람에게만** 그대로 돌려요. 보낸 사람에게는 `ack`만.
- 저장은 2초 모아서 한 번(`SAVE_DELAY`), 마지막 사람이 나갈 때 한 번 더.
- 거절된 연산(개수 한도 등)이 있으면 그 사람에게 `init`(reset)을 보내 화면을 서버 상태로 되돌려요.

## 역할 (`Conn.role`)

    e 편집 링크(만든 사람)   c 같이 그리기 통행증   f 피드백 통행증(메모 핀만)   v 보기 링크(받기만)

## 🚨 느린 연결 하나가 전체를 붙잡지 않게

`ws.send_str`을 바로 await하면 받는 쪽이 막힌 연결 하나 때문에 이벤트 루프(=디스코드 봇 전체)가 물려요.
연결마다 보낼 줄(`Conn.q`)과 쓰는 작업을 따로 두고, 줄이 꽉 차면 그 연결만 끊어요(다시 붙으면 `init`).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time

from utils import tactics

log = logging.getLogger(__name__)

COLORS = ["#f5c518", "#57c785", "#c792ea", "#ff9f43", "#4dd0e1", "#f78fb3", "#a3e635", "#ffffff"]
MAX_ROOM_CONNS = 30
MAX_CONNS = 300
SAVE_DELAY = 2.0
SEND_QUEUE = 256
RATE_PER_SEC = 40           # 연결 하나가 1초에 보낼 수 있는 메시지
MAX_OPS = 400               # 메시지 하나의 연산 수
NOTE_GAP = 1.5              # 메모 핀은 1.5초에 하나
CUR_GAP = 0.08
PING_GAP = 0.4
CAN_EDIT = ("e", "c")
CAN_NOTE = ("e", "c", "f")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Conn:
    def __init__(self, cid: int, ws, role: str, uid: str | None, name: str, color: str):
        self.cid, self.ws, self.role, self.uid, self.name, self.color = cid, ws, role, uid, name, color
        self.q: asyncio.Queue = asyncio.Queue(maxsize=SEND_QUEUE)
        self.task: asyncio.Task | None = None
        self.tokens = float(RATE_PER_SEC)
        self.stamp = time.monotonic()
        self.last: dict[str, float] = {}

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(RATE_PER_SEC, self.tokens + (now - self.stamp) * RATE_PER_SEC)
        self.stamp = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True

    def gap(self, key: str, seconds: float) -> bool:
        """그 종류를 마지막으로 보낸 지 `seconds`가 지났으면 True(그리고 시각을 새로 적어요)."""
        now = time.monotonic()
        if now - self.last.get(key, -1e9) < seconds:
            return False
        self.last[key] = now
        return True

    def push(self, text: str) -> bool:
        try:
            self.q.put_nowait(text)
            return True
        except asyncio.QueueFull:
            return False

    async def writer(self) -> None:
        try:
            while True:
                await self.ws.send_str(await self.q.get())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 끊긴 연결. 읽는 쪽이 정리해요.
            pass

    def info(self) -> dict:
        return {"c": self.cid, "name": self.name, "role": self.role, "color": self.color}


class Room:
    def __init__(self, hub: "Hub", doc: dict):
        self.hub = hub
        self.view_id: str = doc["_id"]
        self.owner = str(doc.get("uid") or "")
        data = copy.deepcopy(doc.get("data")) if isinstance(doc.get("data"), dict) else tactics.empty_data()
        if not data.get("scenes"):
            data = tactics.empty_data()
        tactics.ensure_ids(data)
        self.state = {"title": doc.get("title") or "", "data": data, "notes": list(doc.get("notes") or [])}
        self.conns: dict[int, Conn] = {}
        self.dirty = False
        self._timer: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()

    # ------------------------------ 내보내기
    def notes_out(self) -> list[dict]:
        return [tactics.note_out(n) for n in self.state["notes"]]

    def who(self) -> dict:
        return {"t": "who", "list": [c.info() for c in self.conns.values() if c.role != "v"],
                "viewers": sum(1 for c in self.conns.values() if c.role == "v")}

    def init_msg(self, conn: Conn, *, reset: bool = False) -> dict:
        who = self.who()
        return {"t": "init", "reset": reset, "me": {**conn.info(), "by": tactics.by_of(conn.uid)},
                "title": self.state["title"], "data": self.state["data"], "notes": self.notes_out(),
                "who": who["list"], "viewers": who["viewers"]}

    def send(self, conn: Conn, obj) -> None:
        if not conn.push(_dump(obj)):
            self.hub.drop(conn)

    def broadcast(self, obj, skip: Conn | None = None) -> None:
        text = _dump(obj)
        for c in list(self.conns.values()):
            if c is not skip and not c.push(text):
                self.hub.drop(c)

    # ------------------------------ 저장
    def touch(self) -> None:
        self.dirty = True
        if self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(SAVE_DELAY, self._kick)

    def _kick(self) -> None:
        self._timer = None
        asyncio.ensure_future(self.flush())

    async def flush(self) -> None:
        async with self._lock:           # 저장이 겹쳐 옛 상태가 나중에 쓰이지 않게
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if not self.dirty:
                return
            self.dirty = False
            snap = copy.deepcopy(self.state)   # 저장은 스레드에서 해요 — 그 사이 바뀌어도 되게 복사
            try:
                if self.hub.saver is not None:
                    await self.hub.saver(self.view_id, snap)
                else:
                    await tactics.save_state(self.view_id, snap)
            except Exception:  # noqa: BLE001
                log.warning("👥 작전판 저장 실패 (%s) — 다시 시도해요", self.view_id, exc_info=True)
                self.dirty = True
                if self.conns and self._timer is None:
                    self._timer = asyncio.get_running_loop().call_later(SAVE_DELAY * 5, self._kick)

    def reset(self, data: dict, title: str | None) -> None:
        """통째 저장(실시간 연결이 안 된 편집자의 POST)이 왔을 때: 방 상태를 바꾸고 모두에게 다시 줘요."""
        tactics.ensure_ids(data)
        sids = {s["sid"] for s in data["scenes"]}
        self.state["data"] = data
        if title is not None:
            self.state["title"] = title[:tactics.MAX_TITLE]
        self.state["notes"] = [n for n in self.state["notes"] if n.get("sid") in sids]
        self.touch()
        for c in list(self.conns.values()):
            self.send(c, self.init_msg(c, reset=True))

    # ------------------------------ 받은 메시지
    def handle(self, conn: Conn, raw: str) -> None:
        if not conn.allow():
            return
        try:
            m = json.loads(raw)
        except ValueError:
            return
        if not isinstance(m, dict):
            return
        t = m.get("t")
        if t == "ops":
            self._ops(conn, m)
        elif t == "nadd":
            self._nadd(conn, m)
        elif t == "ndel":
            self._ndel(conn, m)
        elif t in ("cur", "ping"):
            self._point(conn, m)
        elif t == "at":
            if conn.role in CAN_EDIT and tactics._scene_of(self.state["data"], m.get("sid")) is not None:
                self.broadcast({"t": "at", "c": conn.cid, "sid": m["sid"]}, skip=conn)

    def _ops(self, conn: Conn, m: dict) -> None:
        ops = m.get("ops")
        if conn.role not in CAN_EDIT or not isinstance(ops, list) or len(ops) > MAX_OPS:
            return
        out, rejected = [], False
        for op in ops:
            res = tactics.apply_op(self.state, op)
            if res is None:
                rejected = True
            elif res is not tactics.NOOP:
                out.append(res)
        if out:
            self.touch()
            self.broadcast({"t": "ops", "ops": out, "c": conn.cid}, skip=conn)
        if rejected:
            self.send(conn, self.init_msg(conn, reset=True))
        elif isinstance(m.get("n"), int):
            self.send(conn, {"t": "ack", "n": m["n"]})

    def _nadd(self, conn: Conn, m: dict) -> None:
        if conn.role not in CAN_NOTE or not conn.uid or not conn.gap("note", NOTE_GAP):
            return
        note = tactics.add_note(self.state, m.get("note"), conn.uid, conn.name)
        if note is None:
            self.send(conn, {"t": "err", "message": "메모를 남기지 못했어요(판 하나에 60개까지)."})
            return
        self.touch()
        self.broadcast({"t": "nadd", "note": tactics.note_out(note)})
        if self.hub.on_note is not None and conn.uid != self.owner:
            try:
                self.hub.on_note(self, note)
            except Exception:  # noqa: BLE001
                log.warning("👥 메모 알림 실패", exc_info=True)

    def _ndel(self, conn: Conn, m: dict) -> None:
        if conn.role not in CAN_NOTE or not conn.uid:
            return
        if tactics.del_note(self.state, m.get("id"), conn.uid, anyone=conn.role == "e"):
            self.touch()
            self.broadcast({"t": "ndel", "id": m.get("id")})

    def _point(self, conn: Conn, m: dict) -> None:
        if conn.role == "v" or len(self.conns) < 2:
            return
        u, v = tactics._num(m.get("u")), tactics._num(m.get("v"))
        if u is None or v is None:
            return
        if m["t"] == "cur":
            if conn.gap("cur", CUR_GAP):
                self.broadcast({"t": "cur", "c": conn.cid, "u": u, "v": v}, skip=conn)
        elif conn.gap("ping", PING_GAP):
            self.broadcast({"t": "ping", "c": conn.cid, "u": u, "v": v}, skip=conn)


class Hub:
    """방 전체. `saver(view_id, state)`·`on_note(room, note)`는 바꿔 끼울 수 있어요(테스트·디스코드 알림)."""

    def __init__(self, saver=None, on_note=None):
        self.rooms: dict[str, Room] = {}
        self.saver = saver
        self.on_note = on_note
        self.count = 0
        self._cid = 0

    def room(self, view_id: str) -> Room | None:
        return self.rooms.get(view_id)

    def join(self, doc: dict, ws, role: str, uid: str | None, name: str) -> tuple[Room, Conn] | None:
        """방에 들어가요. 꽉 찼으면 None. (await가 없어서 방이 두 개 생기지 않아요.)"""
        room = self.rooms.get(doc["_id"])
        if self.count >= MAX_CONNS or (room is not None and len(room.conns) >= MAX_ROOM_CONNS):
            return None
        if room is None:
            room = self.rooms[doc["_id"]] = Room(self, doc)
        self._cid += 1
        conn = Conn(self._cid, ws, role, uid, name, COLORS[self._cid % len(COLORS)])
        room.conns[conn.cid] = conn
        self.count += 1
        conn.task = asyncio.ensure_future(conn.writer())
        room.send(conn, room.init_msg(conn))
        room.broadcast(room.who(), skip=conn)
        return room, conn

    async def leave(self, room: Room, conn: Conn) -> None:
        if room.conns.pop(conn.cid, None) is None:
            return
        self.count -= 1
        if conn.task is not None:
            conn.task.cancel()
        room.broadcast({"t": "bye", "c": conn.cid})
        room.broadcast(room.who())
        if not room.conns:
            await room.flush()
            if not room.conns and not room.dirty and self.rooms.get(room.view_id) is room:
                del self.rooms[room.view_id]

    def drop(self, conn: Conn) -> None:
        """보낼 줄이 꽉 찬(느린) 연결을 끊어요. 정리는 그 연결의 읽기 루프가 해요."""
        asyncio.ensure_future(self._close(conn.ws, 1013, "slow"))

    @staticmethod
    async def _close(ws, code: int, reason: str) -> None:
        try:
            await ws.close(code=code, message=reason.encode())
        except Exception:  # noqa: BLE001
            pass

    async def flush(self, view_id: str) -> None:
        room = self.rooms.get(view_id)
        if room is not None:
            await room.flush()

    async def flush_all(self) -> None:
        for room in list(self.rooms.values()):
            await room.flush()

    async def close_room(self, view_id: str, *, save: bool = True) -> None:
        """판이 지워졌을 때 등: 모두 내보내요(4404 = 브라우저가 다시 붙지 않아요)."""
        room = self.rooms.pop(view_id, None)
        if room is None:
            return
        if save:
            await room.flush()
        else:
            room.dirty = False
        for c in list(room.conns.values()):
            await self._close(c.ws, 4404, "gone")

    async def close_all(self) -> None:
        await self.flush_all()
        for room in list(self.rooms.values()):
            for c in list(room.conns.values()):
                await self._close(c.ws, 1001, "restart")
