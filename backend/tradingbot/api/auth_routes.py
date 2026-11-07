"""Anmeldung, 2FA, Sitzungen, Einladungen, AGB-Zustimmung."""
from __future__ import annotations

import hmac
import io
import time
from collections import defaultdict

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.auth import (check_password, check_totp, create_session, device_label, hash_password, new_totp_secret,
                         password_problem, set_totp, totp_uri)
from ..core.crypto import hash_token
from ..core.db import utcnow
from ..core.events import log_event
from ..core.models import AuthSession, TermsAcceptance, User
from ..core.settings import settings
from ..legal import TERMS_VERSION, render
from .deps import COOKIE, auth_user, client_ip, get_db, has_accepted

router = APIRouter(prefix="/api/auth")
_fails: dict[str, list[float]] = defaultdict(list)


def _throttle(key: str) -> None:
    now = time.time()
    _fails[key] = [t for t in _fails[key] if now - t < 900]
    if len(_fails[key]) >= 8:
        raise HTTPException(429, "Zu viele Fehlversuche – bitte 15 Minuten warten")


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=30 * 86400, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")


def me_dict(db: Session, u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email, "role": u.role,
            "totp_enabled": u.totp_enabled, "terms_accepted": has_accepted(db, u.id), "terms_version": TERMS_VERSION}


class SetupIn(BaseModel):
    username: str
    display_name: str
    email: str
    password: str
    code: str = ""


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"needs_setup": db.scalar(select(func.count(User.id))) == 0, "setup_code_required": bool(settings.setup_code)}


@router.post("/setup")
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Erster Start: Administrator anlegen (nur solange noch kein Benutzer existiert)."""
    if db.scalar(select(func.count(User.id))) > 0:
        raise HTTPException(409, "Bereits eingerichtet")
    if settings.setup_code and not hmac.compare_digest(body.code.strip(), settings.setup_code):
        raise HTTPException(403, "Einrichtungscode falsch")
    _validate_new(db, body.username, body.email, body.password)
    u = User(username=body.username.strip().lower(), display_name=body.display_name.strip()[:120] or body.username,
             email=body.email.strip().lower(), password_hash=hash_password(body.password), role="admin", status="aktiv")
    db.add(u)
    db.flush()
    _set_cookie(response, create_session(db, u, device_label(request.headers.get("user-agent", "")),
                                         request.headers.get("user-agent", ""), client_ip(request)))
    log_event(u.id, "info", "benutzer", "Administrator angelegt", kind="benutzer", db=db)
    return me_dict(db, u)


def _validate_new(db: Session, username: str, email: str, pw: str) -> None:
    un = username.strip().lower()
    if not (3 <= len(un) <= 32) or not all(c.isalnum() or c in "._-" for c in un):
        raise HTTPException(400, "Benutzername: 3–32 Zeichen, nur Buchstaben, Ziffern, . _ -")
    if "@" not in email:
        raise HTTPException(400, "E-Mail-Adresse ungültig")
    if (p := password_problem(pw)):
        raise HTTPException(400, p)
    if db.scalars(select(User.id).where(User.username == un)).first():
        raise HTTPException(409, "Benutzername ist vergeben")
    if db.scalars(select(User.id).where(User.email == email.strip().lower())).first():
        raise HTTPException(409, "E-Mail-Adresse ist bereits registriert")


class LoginIn(BaseModel):
    username: str
    password: str
    code: str | None = None


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    un = body.username.strip().lower()
    _throttle(ip)
    _throttle("u:" + un)
    u = db.scalars(select(User).where((User.username == un) | (User.email == un))).first()
    if u is None or not check_password(u, body.password) or u.status != "aktiv":
        _fails[ip].append(time.time())
        _fails["u:" + un].append(time.time())
        raise HTTPException(401, "Benutzername oder Passwort falsch")
    if u.totp_enabled:
        if not body.code:
            return {"needs_code": True}
        if not check_totp(u, body.code):
            _fails["u:" + un].append(time.time())
            raise HTTPException(401, "Bestätigungscode falsch")
    ua = request.headers.get("user-agent", "")
    token = create_session(db, u, device_label(ua), ua, ip)
    _set_cookie(response, token)
    log_event(u.id, "info", "benutzer", f"Anmeldung von {device_label(ua)}", kind="anmeldung", data={"ip": ip}, db=db)
    return {**me_dict(db, u), "token": token}


@router.post("/logout")
def logout(request: Request, response: Response, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    request.state.session.revoked = True
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(u: User = Depends(auth_user), db: Session = Depends(get_db)):
    return me_dict(db, u)


# ------------------------------------------------------------------ AGB
@router.get("/terms")
def terms(db: Session = Depends(get_db)):
    return {"version": TERMS_VERSION, "agb": render("agb", db), "datenschutz": render("datenschutz", db)}


class AcceptIn(BaseModel):
    version: str
    agb: bool
    datenschutz: bool
    risiko: bool


@router.post("/terms/accept")
def accept_terms(body: AcceptIn, request: Request, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    if body.version != TERMS_VERSION:
        raise HTTPException(409, "Es gibt eine neuere AGB-Version – bitte neu laden")
    if not (body.agb and body.datenschutz and body.risiko):
        raise HTTPException(400, "Bitte alle drei Punkte bestätigen")
    if not has_accepted(db, u.id):
        db.add(TermsAcceptance(user_id=u.id, version=TERMS_VERSION, ip=client_ip(request)[:64],
                               user_agent=request.headers.get("user-agent", "")[:300]))
        log_event(u.id, "info", "benutzer", f"AGB Version {TERMS_VERSION} bestätigt", kind="agb", db=db)
    return me_dict(db, u)


# ------------------------------------------------------------------ Passwort, 2FA, Sitzungen
class PasswordIn(BaseModel):
    old: str
    new: str


@router.post("/password")
def change_password(body: PasswordIn, request: Request, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    if not check_password(u, body.old):
        raise HTTPException(400, "Aktuelles Passwort falsch")
    if (p := password_problem(body.new)):
        raise HTTPException(400, p)
    u.password_hash = hash_password(body.new)
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id, AuthSession.id != request.state.session.id)):
        s.revoked = True
    log_event(u.id, "info", "benutzer", "Passwort geändert – andere Sitzungen abgemeldet", kind="sicherheit", db=db)
    return {"ok": True}


@router.post("/2fa/setup")
def totp_setup(u: User = Depends(auth_user), db: Session = Depends(get_db)):
    if u.totp_enabled:
        raise HTTPException(409, "2FA ist bereits aktiv")
    secret = new_totp_secret()
    set_totp(u, secret)
    uri = totp_uri(secret, u.username or u.email)
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8).save(buf)
    return {"secret": secret, "uri": uri, "qr_svg": buf.getvalue().decode()}


class CodeIn(BaseModel):
    code: str
    password: str | None = None


@router.post("/2fa/enable")
def totp_enable(body: CodeIn, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    if not u.totp_secret_enc or not check_totp(u, body.code):
        raise HTTPException(400, "Code falsch – bitte die Uhrzeit des Handys prüfen und erneut versuchen")
    u.totp_enabled = True
    log_event(u.id, "info", "benutzer", "Zwei-Faktor-Anmeldung aktiviert", kind="sicherheit", db=db)
    return me_dict(db, u)


@router.post("/2fa/disable")
def totp_disable(body: CodeIn, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    if not body.password or not check_password(u, body.password) or not check_totp(u, body.code):
        raise HTTPException(400, "Passwort oder Code falsch")
    u.totp_enabled = False
    set_totp(u, None)
    log_event(u.id, "warnung", "benutzer", "Zwei-Faktor-Anmeldung deaktiviert", kind="sicherheit", db=db)
    return me_dict(db, u)


@router.get("/sessions")
def sessions(request: Request, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == u.id, AuthSession.revoked.is_(False),
                                                AuthSession.expires_at > utcnow()).order_by(AuthSession.last_seen_at.desc()))
    return [{"id": s.id, "device": s.device, "ip": s.ip, "created_at": s.created_at, "last_seen_at": s.last_seen_at,
             "current": s.id == request.state.session.id} for s in rows]


@router.delete("/sessions/{sid}")
def revoke_session(sid: int, u: User = Depends(auth_user), db: Session = Depends(get_db)):
    s = db.get(AuthSession, sid)
    if s is None or s.user_id != u.id:
        raise HTTPException(404, "Nicht gefunden")
    s.revoked = True
    return {"ok": True}


# ------------------------------------------------------------------ Einladung annehmen
class InviteIn(BaseModel):
    token: str
    username: str
    password: str


@router.get("/invite/{token}")
def invite_info(token: str, db: Session = Depends(get_db)):
    u = db.scalars(select(User).where(User.invite_token_hash == hash_token(token))).first()
    if u is None or u.status != "eingeladen" or (u.invite_expires_at and u.invite_expires_at < utcnow()):
        raise HTTPException(404, "Einladung ungültig oder abgelaufen")
    return {"display_name": u.display_name, "email": u.email}


@router.post("/invite")
def invite_accept(body: InviteIn, request: Request, response: Response, db: Session = Depends(get_db)):
    u = db.scalars(select(User).where(User.invite_token_hash == hash_token(body.token))).first()
    if u is None or u.status != "eingeladen" or (u.invite_expires_at and u.invite_expires_at < utcnow()):
        raise HTTPException(404, "Einladung ungültig oder abgelaufen")
    un = body.username.strip().lower()
    if (p := password_problem(body.password)):
        raise HTTPException(400, p)
    if not (3 <= len(un) <= 32) or not all(c.isalnum() or c in "._-" for c in un):
        raise HTTPException(400, "Benutzername: 3–32 Zeichen, nur Buchstaben, Ziffern, . _ -")
    if db.scalars(select(User.id).where(User.username == un, User.id != u.id)).first():
        raise HTTPException(409, "Benutzername ist vergeben")
    u.username, u.password_hash, u.status, u.invite_token_hash = un, hash_password(body.password), "aktiv", None
    ua = request.headers.get("user-agent", "")
    _set_cookie(response, create_session(db, u, device_label(ua), ua, client_ip(request)))
    log_event(u.id, "info", "benutzer", "Einladung angenommen", kind="benutzer", db=db)
    return me_dict(db, u)


