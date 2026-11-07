"""Rechtstexte (ENTWURF – vor Echtgeld-Betrieb mit Dritten anwaltlich prüfen lassen)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..core.models import AppSetting

TERMS_VERSION = "1.0"
_DIR = Path(__file__).parent
PROVIDER_FIELDS = {"name": "[Name des Anbieters]", "anschrift": "[Anschrift]", "email": "[E-Mail-Adresse]", "telefon": ""}


def provider(db: Session) -> dict:
    row = db.get(AppSetting, "anbieter")
    return {**PROVIDER_FIELDS, **(row.value if row else {})}


def render(name: str, db: Session) -> str:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    p = provider(db)
    for k, v in p.items():
        text = text.replace("{{" + k + "}}", v or PROVIDER_FIELDS.get(k) or "–")
    return text.replace("{{version}}", TERMS_VERSION)
