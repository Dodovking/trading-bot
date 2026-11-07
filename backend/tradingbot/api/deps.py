from __future__ import annotations

from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import db as dbm
from ..core.auth import session_user
from ..core.models import TermsAcceptance, User
from ..legal import TERMS_VERSION

COOKIE = "tb_session"


def get_db() -> Iterator[Session]:
    with dbm.session_scope() as s:
        yield s


def token_from(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.cookies.get(COOKIE)


def client_ip(request: Request) -> str:
    return request.headers.get("fly-client-ip") or (request.client.host if request.client else "")


def check_csrf(request: Request) -> None:
    # Cookie-Sitzungen: zustandsändernde Anfragen nur mit eigenem Header (wird von fremden Seiten nicht gesendet)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.cookies.get(COOKIE) \
            and request.headers.get("x-requested-with") != "tradingbot":
        raise HTTPException(403, "Ungültige Anfrage (CSRF-Schutz)")


def auth_user(request: Request, db: Session = Depends(get_db)) -> User:
    check_csrf(request)
    res = session_user(db, token_from(request))
    if res is None:
        raise HTTPException(401, "Bitte anmelden")
    request.state.session = res[1]
    return res[0]


def has_accepted(db: Session, user_id: int) -> bool:
    return db.scalars(select(TermsAcceptance.id).where(TermsAcceptance.user_id == user_id,
                                                       TermsAcceptance.version == TERMS_VERSION)).first() is not None


def user(u: User = Depends(auth_user), db: Session = Depends(get_db)) -> User:
    """Angemeldet UND aktuelle AGB bestätigt – Voraussetzung für jede Nutzung."""
    if not has_accepted(db, u.id):
        raise HTTPException(451, "Bitte zuerst die AGB bestätigen")
    return u


def admin(u: User = Depends(user)) -> User:
    if u.role != "admin":
        raise HTTPException(403, "Nur für Administratoren")
    return u
