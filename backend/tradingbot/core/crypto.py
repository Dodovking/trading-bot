"""Verschlüsselung gespeicherter Geheimnisse (API-Schlüssel, 2FA) und Tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .settings import settings


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(settings.derived_key("fernet")))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign(message: str, purpose: str = "risk-stamp") -> str:
    return hmac.new(settings.derived_key(purpose), message.encode(), hashlib.sha256).hexdigest()


def verify(message: str, signature: str, purpose: str = "risk-stamp") -> bool:
    return hmac.compare_digest(sign(message, purpose), signature or "")
