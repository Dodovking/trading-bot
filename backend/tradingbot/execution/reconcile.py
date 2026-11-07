"""Abgleich (Reconciliation) nach Neustart und periodisch (Abschnitt 6).

Vergleicht offene Orders, Bestände und Schutz-Stops der Datenbank mit dem Broker.
Abweichungen sperren neue Orders, bis sie behoben sind.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from ..brokers.base import BrokerError
from ..core.events import log_event
from ..core.models import Instrument, Position
from .orders import OPEN_STATES, OrderManager

D = Decimal


@dataclass
class ReconcileResult:
    ok: bool
    note: str
    stopped_out: int = 0
    stops_restored: int = 0


def reconcile(om: OrderManager, mode: str) -> ReconcileResult:
    db = om.db
    try:
        closed = om.refresh_open()
        balances = om.broker.balances()
        open_stops = {s.client_order_id for s in om.broker.open_stop_orders()}
    except BrokerError as e:
        return ReconcileResult(False, f"Broker nicht erreichbar: {e}")
    positions = list(db.scalars(select(Position).where(Position.user_id == om.user_id, Position.account_id == om.account_id,
                                                       Position.status == "offen")))
    need: dict[str, Decimal] = defaultdict(lambda: D(0))
    insts = {}
    for p in positions:
        inst = db.get(Instrument, p.instrument_id)
        insts[p.id] = inst
        need[inst.base] += p.qty
    problems: list[str] = []
    for asset, qty in need.items():
        have = balances.get(asset, D(0))
        if mode == "paper":
            mismatch = abs(have - qty) > max(qty * D("0.000001"), D("0.00000001"))
        else:  # Echtkonto darf zusätzliche Bestände des Nutzers enthalten
            mismatch = have < qty * D("0.998")
        if mismatch:
            problems.append(f"{asset}: Bot erwartet {format(qty.normalize(), 'f')}, Broker meldet {format(have.normalize(), 'f')}")
    restored = 0
    for p in positions:
        if p.side == "bestand":
            continue  # Ertragsmodul-Bestand: bewusst ohne Stop, begrenzt durch Modulbudget
        so = om._order(p.stop_client_order_id)
        active = so is not None and so.status in OPEN_STATES and p.stop_client_order_id in open_stops
        bad_asset = any(x.startswith(insts[p.id].base + ":") for x in problems)
        if not active and not bad_asset:
            if om.place_stop(p, insts[p.id]):
                restored += 1
                log_event(om.user_id, "warnung", "abgleich", f"Fehlender Stop-Loss für {insts[p.id].symbol} neu gesetzt",
                          kind="stop_wiederhergestellt", db=db)
            else:
                problems.append(f"{insts[p.id].symbol}: kein Stop-Loss beim Broker")
    if problems:
        note = "; ".join(problems)
        log_event(om.user_id, "kritisch", "abgleich", f"Abgleich fehlgeschlagen – neue Orders gesperrt: {note}", kind="abgleich_fehler", db=db)
        return ReconcileResult(False, note, len(closed), restored)
    return ReconcileResult(True, "übereinstimmend", len(closed), restored)
