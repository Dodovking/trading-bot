"""Meldungen über zwei unabhängige Kanäle (Abschnitt 8): Web-Push (iPhone/PC) und ntfy."""
from __future__ import annotations

import json
import logging
import queue
import threading

import httpx
from sqlalchemy import select

from ..core import bus
from ..core import db as dbm
from ..core.config import current_config
from ..core.events import add_listener
from ..core.models import BotEvent, PushSubscription
from ..core.settings import settings

log = logging.getLogger(__name__)
TRADE_KINDS = {"trade_eroeffnet", "trade_geschlossen", "modul_kauf", "modul_verkauf", "bestaetigung"}
REPORT_KINDS = {"tagesbericht", "wochenbericht"}
_q: queue.Queue = queue.Queue(maxsize=1000)


def _wanted(ev: BotEvent, n: dict) -> bool:
    if ev.severity in ("kritisch", "fehler"):
        return True
    if ev.severity == "warnung":
        return n.get("on_warning", True)
    if ev.kind in TRADE_KINDS:
        return n.get("on_trade", True)
    return ev.kind in REPORT_KINDS


def _on_event(ev: BotEvent) -> None:
    if ev.user_id is not None:
        bus.publish(ev.user_id, "event")
    if ev.user_id is None or (ev.severity == "info" and ev.kind not in TRADE_KINDS | REPORT_KINDS):
        return
    try:
        _q.put_nowait((ev.user_id, ev.severity, ev.kind, ev.message))
    except queue.Full:
        pass


def _send(user_id: int, severity: str, kind: str, message: str) -> None:
    with dbm.session_scope() as db:
        cfg, _ = current_config(db, user_id)
        n = cfg["notifications"]
        fake = BotEvent(severity=severity, kind=kind, message=message, module="")
        if not _wanted(fake, n):
            return
        title = {"kritisch": "Trading-Bot: KRITISCH", "fehler": "Trading-Bot: Fehler", "warnung": "Trading-Bot: Warnung"}.get(
            severity, "Trading-Bot")
        mode = "LIVE" if cfg["account"] == "live" else "PAPER"
        subs = list(db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))) if n.get("push", True) else []
        dead = []
        if subs and settings.vapid_private:
            from pywebpush import WebPushException, webpush
            for s in subs:
                try:
                    webpush({"endpoint": s.endpoint, "keys": s.keys}, json.dumps({"title": f"{title} [{mode}]", "body": message[:300]}),
                            vapid_private_key=settings.vapid_private, vapid_claims={"sub": settings.vapid_subject}, timeout=10)
                except WebPushException as e:
                    if e.response is not None and e.response.status_code in (404, 410):
                        dead.append(s)
                except Exception as e:  # noqa: BLE001
                    log.warning("Push fehlgeschlagen: %s", e)
        for s in dead:
            db.delete(s)
        topic = n.get("ntfy_topic")
    if topic:
        try:
            httpx.post(f"{settings.ntfy_server.rstrip('/')}/{topic}", content=message.encode()[:3000], timeout=10,
                       headers={"Title": f"{title} [{mode}]".encode("ascii", "ignore").decode(),
                                "Priority": "urgent" if severity == "kritisch" else "high" if severity == "warnung" else "default"})
        except httpx.HTTPError as e:
            log.warning("ntfy fehlgeschlagen: %s", e)


def _worker() -> None:
    while True:
        item = _q.get()
        try:
            _send(*item)
        except Exception:  # noqa: BLE001
            log.exception("Meldung fehlgeschlagen")


def start() -> None:
    add_listener(_on_event)
    threading.Thread(target=_worker, name="alerts", daemon=True).start()
