"""WebSocket: meldet Änderungen sofort an alle Geräte eines Benutzers (PC und iPhone gleicher Stand)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core import bus
from ..core import db as dbm
from ..core.auth import session_user
from .deps import COOKIE, has_accepted

router = APIRouter()
_clients: dict[int, set[WebSocket]] = {}
_loop: asyncio.AbstractEventLoop | None = None


def _notify(user_id: int | None, topic: str) -> None:
    if _loop is None:
        return
    targets = [ws for uid, s in _clients.items() if user_id is None or uid == user_id for ws in s]
    for ws in targets:
        asyncio.run_coroutine_threadsafe(_send(ws, topic), _loop)


async def _send(ws: WebSocket, topic: str) -> None:
    try:
        await ws.send_json({"topic": topic})
    except Exception:  # noqa: BLE001
        pass


bus.subscribe(_notify)


@router.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket):
    global _loop
    _loop = asyncio.get_running_loop()
    token = ws.cookies.get(COOKIE) or ws.query_params.get("token")
    with dbm.session_scope() as db:
        res = session_user(db, token)
        ok = res is not None and has_accepted(db, res[0].id)
        uid = res[0].id if res else None
    if not ok:
        await ws.close(code=4401)
        return
    await ws.accept()
    _clients.setdefault(uid, set()).add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.get(uid, set()).discard(ws)
