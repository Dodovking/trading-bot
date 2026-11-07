"""Leichter Benachrichtigungsbus: Engine-Thread → WebSocket-Clients (Live-Aktualisierung)."""
from __future__ import annotations

import threading
from typing import Callable

_subs: list[Callable[[int | None, str], None]] = []
_lock = threading.Lock()


def subscribe(fn: Callable[[int | None, str], None]) -> None:
    with _lock:
        _subs.append(fn)


def publish(user_id: int | None, topic: str = "update") -> None:
    with _lock:
        subs = list(_subs)
    for fn in subs:
        try:
            fn(user_id, topic)
        except Exception:
            pass
