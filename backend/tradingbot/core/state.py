"""Zustandsautomat des Bots (Abschnitt 5.1)."""
from __future__ import annotations

STATES = ("INITIALISIERUNG", "SYNCHRONISIERUNG", "BEREIT", "AKTIV", "PAUSIERT", "GESPERRT", "NOT_AUS", "FEHLER")

STATE_LABELS = {
    "INITIALISIERUNG": "Startet", "SYNCHRONISIERUNG": "Abgleich", "BEREIT": "Bereit", "AKTIV": "Bot läuft",
    "PAUSIERT": "Pausiert", "GESPERRT": "Gesperrt", "NOT_AUS": "Not-Aus", "FEHLER": "Fehler",
}

NEW_ORDERS_ALLOWED = {"AKTIV"}

TRANSITIONS: dict[str, set[str]] = {
    "INITIALISIERUNG": {"SYNCHRONISIERUNG", "FEHLER", "NOT_AUS"},
    "SYNCHRONISIERUNG": {"BEREIT", "GESPERRT", "FEHLER", "NOT_AUS"},
    "BEREIT": {"AKTIV", "SYNCHRONISIERUNG", "GESPERRT", "FEHLER", "NOT_AUS"},
    "AKTIV": {"PAUSIERT", "BEREIT", "GESPERRT", "FEHLER", "NOT_AUS", "SYNCHRONISIERUNG"},
    "PAUSIERT": {"AKTIV", "BEREIT", "GESPERRT", "FEHLER", "NOT_AUS", "SYNCHRONISIERUNG"},
    # Aus GESPERRT, NOT_AUS und FEHLER nur über SYNCHRONISIERUNG und bewusste Freigabe.
    "GESPERRT": {"SYNCHRONISIERUNG", "NOT_AUS", "FEHLER"},
    "NOT_AUS": {"SYNCHRONISIERUNG"},
    "FEHLER": {"SYNCHRONISIERUNG", "NOT_AUS"},
}


class TransitionError(ValueError):
    pass


def check_transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in TRANSITIONS.get(current, set()):
        raise TransitionError(f"Wechsel von {STATE_LABELS.get(current, current)} nach {STATE_LABELS.get(target, target)} ist nicht erlaubt")
