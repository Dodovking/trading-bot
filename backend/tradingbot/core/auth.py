"""Anmeldung: Passwort (Argon2), optional TOTP-2FA, Sitzungen per Token (Cookie oder Bearer)."""
from __future__ import annotations

from datetime import timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import decrypt, encrypt, hash_token, new_token
from .db import utcnow
from .models import AuthSession, User

_ph = PasswordHasher()
SESSION_DAYS = 30
MIN_PASSWORD = 10


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def check_password(user: User, pw: str) -> bool:
    if not user.password_hash:
        _ph.hash("dummy-timing")
        return False
    try:
        return _ph.verify(user.password_hash, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(pw: str) -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"Passwort muss mindestens {MIN_PASSWORD} Zeichen haben"
    if pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        return "Passwort braucht Groß- und Kleinbuchstaben sowie eine Ziffer"
    return None


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="Trading-Bot")


def check_totp(user: User, code: str) -> bool:
    secret = decrypt(user.totp_secret_enc)
    return bool(secret) and pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def set_totp(user: User, secret: str | None) -> None:
    user.totp_secret_enc = encrypt(secret) if secret else None


def create_session(db: Session, user: User, device: str, ua: str, ip: str) -> str:
    token = new_token()
    db.add(AuthSession(user_id=user.id, token_hash=hash_token(token), device=device[:40], user_agent=ua[:300], ip=ip[:64],
                       expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
    user.last_login_at = utcnow()
    db.flush()
    return token


def session_user(db: Session, token: str | None) -> tuple[User, AuthSession] | None:
    if not token:
        return None
    s = db.scalars(select(AuthSession).where(AuthSession.token_hash == hash_token(token))).first()
    if s is None or s.revoked or s.expires_at < utcnow():
        return None
    u = db.get(User, s.user_id)
    if u is None or u.status != "aktiv":
        return None
    if utcnow() - s.last_seen_at > timedelta(minutes=5):
        s.last_seen_at = utcnow()
    return u, s


def device_label(ua: str) -> str:
    u = ua.lower()
    if "iphone" in u:
        return "iPhone"
    if "ipad" in u:
        return "iPad"
    if "android" in u:
        return "Android"
    if "windows" in u:
        return "Windows-PC"
    if "macintosh" in u or "mac os" in u:
        return "Mac"
    return "Browser"
