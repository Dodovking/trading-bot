"""FastAPI-Anwendung: API, WebSocket, Rechtstexte und die Web-App (PC + iPhone) aus einem Server."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .api import admin_routes, assistant_routes, auth_routes, bot_routes, ws
from .api.deps import get_db
from .core import db as dbm
from .core.db import utcnow
from .core.settings import settings
from .legal import render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
FRONTEND = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbm.init_engine()
    from .data.instruments import seed_instruments
    with dbm.session_scope() as db:
        seed_instruments(db)
    if settings.engine_enabled:
        from .alerts import notify
        from .engine import get_engine
        notify.start()
        get_engine().start()
    yield
    if settings.engine_enabled:
        from .engine import get_engine
        get_engine().stop()


app = FastAPI(title="Trading-Bot", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(auth_routes.router)
app.include_router(bot_routes.router)
app.include_router(admin_routes.router)
app.include_router(assistant_routes.router)
app.include_router(ws.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if settings.secure_cookies:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.url.path.startswith("/api"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.get("/api/health")
def health():
    from .engine import engine
    e = engine
    age = (utcnow() - e.last_tick).total_seconds() if e and e.last_tick else None
    ok = not settings.engine_enabled or (age is not None and age < 120)
    return JSONResponse({"ok": ok, "engine_tick_age_s": age, "engine_error": e.tick_error if e else ""}, status_code=200 if ok else 503)


@app.get("/legal/{name}", response_class=PlainTextResponse)
def legal(name: str, db: Session = Depends(get_db)):
    if name not in ("agb", "datenschutz", "impressum"):
        return PlainTextResponse("Nicht gefunden", status_code=404)
    return render(name, db)


if (FRONTEND / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str):
    f = (FRONTEND / path).resolve()
    if path and f.is_file() and FRONTEND.resolve() in f.parents:
        headers = {"Cache-Control": "no-cache"} if f.name in ("sw.js", "manifest.webmanifest") else {}
        return FileResponse(f, headers=headers)
    index = FRONTEND / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h1>Trading-Bot</h1><p>Frontend noch nicht gebaut.</p>")
