"""Ereignisprotokoll (bot_events) mit Weiterleitung an Alarmierung und Live-Anzeige."""
from __future__ import annotations

import logging
from typing import Callable

from .db import session_scope, utcnow
from .models import BotEvent

log = logging.getLogger("tradingbot")

_listeners: list[Callable[[BotEvent], None]] = []


def add_listener(fn: Callable[[BotEvent], None]) -> None:
    _listeners.append(fn)


def clear_listeners() -> None:
    _listeners.clear()


def log_event(user_id: int | None, severity: str, module: str, message: str, kind: str = "",
              data: dict | None = None, db=None) -> BotEvent:
    ev = BotEvent(user_id=user_id, time=utcnow(), severity=severity, module=module, kind=kind,
                  message=message, data=data or {})
    if db is not None:
        db.add(ev)
        db.flush()
    else:
        with session_scope() as s:
            s.add(ev)
    getattr(log, {"info": "info", "warnung": "warning"}.get(severity, "error"))("[%s] %s: %s", user_id, module, message)
    for fn in list(_listeners):
        try:
            fn(ev)
        except Exception:  # Alarmierung darf das Protokoll nie blockieren
            log.exception("Event-Listener fehlgeschlagen")
    return ev
