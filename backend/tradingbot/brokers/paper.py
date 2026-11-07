"""Simulations-Broker (Paper Trading, FA-51): echte Live-Kurse, simuliertes Konto.

Führt sein eigenes Konto (paper_ledger) und Orderbuch (paper_orders) – unabhängig vom
Order-Management, damit der Abgleich (Reconciliation) echte Abweichungen findet.
Kosten: Spread (echter Geld/Brief-Kurs), Slippage und Gebühr laut Konfiguration.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import utcnow
from ..core.models import PaperLedger, PaperOrder
from ..data.sources import Ticker
from .base import BrokerError, BrokerFill, BrokerOrderStatus, OrderRequest

STATUS = {"open": "offen", "filled": "ausgefuehrt", "canceled": "storniert", "rejected": "abgelehnt"}


class PaperBroker:
    name = "Paper-Simulation"

    def __init__(self, db: Session, account_id: int, ticker_fn: Callable[[str], Ticker | None],
                 fee_pct: Decimal, slippage_pct: Decimal, currency: str = "EUR"):
        self.db = db
        self.account_id = account_id
        self.ticker_fn = ticker_fn
        self.fee = Decimal(str(fee_pct)) / 100
        self.slip = Decimal(str(slippage_pct)) / 100
        self.currency = currency

    # --------------------------------------------------------------- Konto
    def _ledger(self, asset: str) -> PaperLedger:
        row = self.db.scalars(select(PaperLedger).where(PaperLedger.account_id == self.account_id,
                                                        PaperLedger.asset == asset)).first()
        if row is None:
            row = PaperLedger(account_id=self.account_id, asset=asset, amount=Decimal(0))
            self.db.add(row)
            self.db.flush()
        return row

    def deposit(self, amount: Decimal) -> None:
        led = self._ledger(self.currency)
        led.amount = led.amount + amount

    def reset(self, capital: Decimal) -> None:
        for row in self.db.scalars(select(PaperLedger).where(PaperLedger.account_id == self.account_id)):
            self.db.delete(row)
        for o in self.db.scalars(select(PaperOrder).where(PaperOrder.account_id == self.account_id, PaperOrder.status == "open")):
            o.status = "canceled"
            o.note = "Konto zurückgesetzt"
        self.db.flush()
        self.deposit(capital)

    def balances(self) -> dict[str, Decimal]:
        rows = self.db.scalars(select(PaperLedger).where(PaperLedger.account_id == self.account_id)).all()
        return {r.asset: r.amount for r in rows if r.amount != 0 or r.asset == self.currency}

    def check_connection(self) -> str:
        return "Simulation aktiv"

    # --------------------------------------------------------------- Orders
    def _status(self, o: PaperOrder) -> BrokerOrderStatus:
        fills = []
        if o.status == "filled" and o.avg_price is not None:
            fills = [BrokerFill(f"P{o.id}", o.avg_price, o.filled_qty, o.fee)]
        return BrokerOrderStatus(o.client_order_id, f"P{o.id}", STATUS[o.status], o.filled_qty, o.avg_price, o.fee, fills, o.note)

    def _get(self, client_order_id: str) -> PaperOrder | None:
        return self.db.scalars(select(PaperOrder).where(PaperOrder.client_order_id == client_order_id)).first()

    def submit(self, req: OrderRequest) -> BrokerOrderStatus:
        existing = self._get(req.client_order_id)
        if existing is not None:  # Idempotenz: gleiche Client-Order-ID => keine zweite Order
            return self._status(existing)
        o = PaperOrder(account_id=self.account_id, client_order_id=req.client_order_id, symbol=req.symbol,
                       side=req.side, type=req.type, qty=req.qty, stop_price=req.stop_price, status="open")
        self.db.add(o)
        self.db.flush()
        if req.type == "market":
            t = self.ticker_fn(req.symbol)
            if t is None:
                raise BrokerError("Kein aktueller Kurs für die Simulation")
            price = t.ask * (1 + self.slip) if req.side == "kauf" else t.bid * (1 - self.slip)
            self._fill(o, price)
        return self._status(o)

    def _fill(self, o: PaperOrder, price: Decimal) -> None:
        base = o.symbol.split("/")[0]
        value = price * o.qty
        fee = (value * self.fee).quantize(Decimal("0.00000001"))
        cash = self._ledger(self.currency)
        asset = self._ledger(base)
        if o.side == "kauf":
            if cash.amount < value + fee:
                o.status, o.note = "rejected", "Nicht genug Guthaben"
                return
            cash.amount = cash.amount - value - fee
            asset.amount = asset.amount + o.qty
        else:
            if asset.amount < o.qty:
                o.status, o.note = "rejected", "Bestand reicht nicht"
                return
            asset.amount = asset.amount - o.qty
            cash.amount = cash.amount + value - fee
        o.status, o.filled_qty, o.avg_price, o.fee, o.updated_at = "filled", o.qty, price, fee, utcnow()

    def query(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        o = self._get(client_order_id)
        if o is None:
            return BrokerOrderStatus(client_order_id, None, "unbekannt")
        return self._status(o)

    def cancel(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        o = self._get(client_order_id)
        if o is None:
            return BrokerOrderStatus(client_order_id, None, "unbekannt")
        if o.status == "open":
            o.status, o.updated_at = "canceled", utcnow()
        return self._status(o)

    def modify_stop(self, client_order_id: str, new_stop: Decimal) -> BrokerOrderStatus:
        o = self._get(client_order_id)
        if o is None or o.status != "open":
            return BrokerOrderStatus(client_order_id, None, "unbekannt" if o is None else STATUS[o.status])
        o.stop_price, o.updated_at = new_stop, utcnow()
        return self._status(o)

    def open_stop_orders(self) -> list[BrokerOrderStatus]:
        rows = self.db.scalars(select(PaperOrder).where(PaperOrder.account_id == self.account_id,
                                                        PaperOrder.status == "open", PaperOrder.type == "stop")).all()
        return [self._status(o) for o in rows]

    def on_prices(self) -> list[str]:
        """Prüft offene Stop-Orders gegen den aktuellen Kurs. Rückgabe: ausgelöste Client-Order-IDs."""
        triggered = []
        rows = self.db.scalars(select(PaperOrder).where(PaperOrder.account_id == self.account_id,
                                                        PaperOrder.status == "open", PaperOrder.type == "stop")).all()
        for o in rows:
            t = self.ticker_fn(o.symbol)
            if t is None or o.stop_price is None:
                continue
            if o.side == "verkauf" and t.bid <= o.stop_price:
                # Ausführung zum schlechteren Kurs aus Stop und Geldkurs, abzüglich Slippage
                self._fill(o, min(o.stop_price, t.bid) * (1 - self.slip))
                triggered.append(o.client_order_id)
            elif o.side == "kauf" and t.ask >= o.stop_price:
                self._fill(o, max(o.stop_price, t.ask) * (1 + self.slip))
                triggered.append(o.client_order_id)
        return triggered
