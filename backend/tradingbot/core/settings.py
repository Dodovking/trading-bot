"""Server-Einstellungen aus Umgebungsvariablen (Secrets nie im Code)."""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    master_key: str = field(default_factory=lambda: _env("MASTER_KEY", ""))
    setup_code: str = field(default_factory=lambda: _env("SETUP_CODE", ""))
    site_url: str = field(default_factory=lambda: _env("SITE_URL", "http://localhost:8000"))
    secure_cookies: bool = field(default_factory=lambda: _env("SECURE_COOKIES", "0") == "1")
    vapid_public: str = field(default_factory=lambda: _env("VAPID_PUBLIC_KEY", ""))
    vapid_private: str = field(default_factory=lambda: _env("VAPID_PRIVATE_KEY", ""))
    vapid_subject: str = field(default_factory=lambda: _env("VAPID_SUBJECT", "mailto:admin@example.com"))
    engine_enabled: bool = field(default_factory=lambda: _env("ENGINE_ENABLED", "1") == "1")
    market_data: str = field(default_factory=lambda: _env("MARKET_DATA", "kraken"))
    ntfy_server: str = field(default_factory=lambda: _env("NTFY_SERVER", "https://ntfy.sh"))

    @property
    def db_url(self) -> str:
        return _env("DATABASE_URL", f"sqlite:///{(self.data_dir / 'tradingbot.db').resolve()}")

    def _master_bytes(self) -> bytes:
        key = self.master_key
        if not key:
            keyfile = self.data_dir / ".master_key"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if not keyfile.exists():
                keyfile.write_text(base64.urlsafe_b64encode(os.urandom(32)).decode())
                keyfile.chmod(0o600)
            key = keyfile.read_text().strip()
        return hashlib.sha256(("tradingbot:" + key).encode()).digest()

    def derived_key(self, purpose: str) -> bytes:
        return hashlib.sha256(self._master_bytes() + purpose.encode()).digest()


settings = Settings()
