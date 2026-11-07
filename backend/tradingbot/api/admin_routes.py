"""Administration: Benutzer einladen/sperren, Anbieterangaben (Impressum/AGB), Echtgeld-Schalter für Fremdnutzer."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.crypto import hash_token, new_token
from ..core.db import utcnow
from ..core.events import log_event
from ..core.models import AppSetting, AuthSession, BotRuntime, TermsAcceptance, User
from ..core.settings import settings
from ..legal import PROVIDER_FIELDS, provider
from .deps import admin, get_db

router = APIRouter(prefix="/api/admin")


def _set(db: Session, key: str, value: dict) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_at=utcnow()))
    else:
        row.value, row.updated_at = value, utcnow()


@router.get("/users")
def users(a: User = Depends(admin), db: Session = Depends(get_db)):
    out = []
    for u in db.scalars(select(User).order_by(User.id)):
        rt = db.get(BotRuntime, u.id)
        terms = db.scalars(select(TermsAcceptance).where(TermsAcceptance.user_id == u.id).order_by(TermsAcceptance.id.desc())).first()
        out.append({"id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email, "role": u.role,
                    "status": u.status, "totp": u.totp_enabled, "last_login_at": u.last_login_at, "created_at": u.created_at,
                    "bot_state": rt.state if rt else None, "terms": {"version": terms.version, "time": terms.time} if terms else None})
    return out


class InviteIn(BaseModel):
    display_name: str
    email: str
    role: str = "benutzer"


@router.post("/invite")
def invite(body: InviteIn, a: User = Depends(admin), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "E-Mail-Adresse ungültig")
    u = db.scalars(select(User).where(User.email == email)).first()
    if u is not None and u.status != "eingeladen":
        raise HTTPException(409, "E-Mail-Adresse ist bereits registriert")
    token = new_token(24)
    if u is None:
        u = User(email=email, display_name=body.display_name.strip()[:120] or email, role="admin" if body.role == "admin" else "benutzer",
                 status="eingeladen")
        db.add(u)
    u.invite_token_hash, u.invite_expires_at = hash_token(token), utcnow() + timedelta(days=7)
    db.flush()
    log_event(a.id, "info", "benutzer", f"{body.display_name} eingeladen", kind="benutzer", db=db)
    return {"link": f"{settings.site_url.rstrip('/')}/#/einladung/{token}", "expires_at": u.invite_expires_at}


class UserPatch(BaseModel):
    status: str | None = None
    role: str | None = None


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, a: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "Nicht gefunden")
    if u.id == a.id:
        raise HTTPException(400, "Eigenes Konto hier nicht änderbar")
    if body.status in ("aktiv", "gesperrt"):
        u.status = body.status
        if body.status == "gesperrt":
            for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id)):
                s.revoked = True
    if body.role in ("admin", "benutzer"):
        u.role = body.role
    log_event(a.id, "warnung", "benutzer", f"Benutzer {u.display_name}: {body.model_dump(exclude_none=True)}", kind="benutzer", db=db)
    return {"ok": True}


@router.get("/settings")
def get_settings(a: User = Depends(admin), db: Session = Depends(get_db)):
    fl = db.get(AppSetting, "fremd_live")
    return {"anbieter": provider(db), "fremd_live": bool(fl and fl.value.get("enabled")), "felder": list(PROVIDER_FIELDS)}


class SettingsIn(BaseModel):
    anbieter: dict | None = None
    fremd_live: bool | None = None
    fremd_live_bestaetigt: bool = False


@router.post("/settings")
def put_settings(body: SettingsIn, a: User = Depends(admin), db: Session = Depends(get_db)):
    if body.anbieter is not None:
        _set(db, "anbieter", {k: str(body.anbieter.get(k, ""))[:200] for k in PROVIDER_FIELDS})
    if body.fremd_live is not None:
        if body.fremd_live and not body.fremd_live_bestaetigt:
            raise HTTPException(400, "Bitte bestätigen, dass die rechtliche Prüfung erfolgt ist")
        _set(db, "fremd_live", {"enabled": body.fremd_live, "by": a.display_name, "time": utcnow().isoformat()})
        log_event(a.id, "warnung", "admin", f"Echtgeld für Fremdnutzer {'freigegeben' if body.fremd_live else 'gesperrt'}",
                  kind="admin", db=db)
    return get_settings(a, db)
