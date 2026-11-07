"""Mehrere Echtgeld-Verbindungen gleichzeitig: jeder Markt läuft über den passenden Anbieter.

Krypto → z. B. Kraken, Aktien/ETFs → Alpaca. Nach außen verhält sich der Router wie ein einzelner Broker,
damit Order-Management, Abgleich und Risikomodul unverändert bleiben. Kontostände werden zusammengeführt
(alles in €), für die Positionsgröße zählt aber nur das Guthaben beim jeweiligen Anbieter.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .base import BrokerError, BrokerOrderStatus, BrokerRejected, OrderRequest

D = Decimal
VENUE_LABEL = {"krypto": "Krypto", "aktie": "Aktien/ETFs"}


def market_of(symbol: str) -> str:
    from ..data.stocks import STOCK_SYMBOLS
    return "aktie" if symbol in STOCK_SYMBOLS else "krypto"


class RouterBroker:
    def __init__(self, venues: dict[str, tuple[str, object]], market_of_order: Callable[[str], str | None] | None = None):
        """venues: Markt („krypto“/„aktie“) → (Anbietername, Broker)."""
        self.venues = venues
        self.market_of_order = market_of_order or (lambda coid: None)
        self.name = " + ".join(n for n, _ in venues.values())
        self.last_balances: dict[str, dict[str, Decimal]] = {}

    def has(self, market: str) -> bool:
        return market in self.venues

    def _for_market(self, market: str):
        v = self.venues.get(market)
        if v is None:
            raise BrokerRejected(f"Kein Echtgeld-Konto für {VENUE_LABEL.get(market, market)} verbunden")
        return v[1]

    def _for_order(self, coid: str) -> list:
        m = self.market_of_order(coid)
        if m in self.venues:
            return [self.venues[m][1]]
        return [b for _, b in self.venues.values()]

    def check_connection(self) -> str:
        return " · ".join(f"{VENUE_LABEL.get(m, m)}: {b.check_connection()}" for m, (_, b) in self.venues.items())

    def balances(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        per: dict[str, dict[str, Decimal]] = {}
        for m, (_, b) in self.venues.items():
            bal = b.balances()
            per[m] = bal
            for k, v in bal.items():
                out[k] = out.get(k, D(0)) + v
        self.last_balances = per
        return out

    def cash(self, market: str, currency: str = "EUR") -> Decimal:
        """Verfügbares Guthaben beim Anbieter dieses Markts (für die Positionsgröße)."""
        if market not in self.venues:
            return D(0)
        if market not in self.last_balances:
            self.balances()
        return self.last_balances.get(market, {}).get(currency, D(0))

    def submit(self, req: OrderRequest) -> BrokerOrderStatus:
        return self._for_market(market_of(req.symbol)).submit(req)

    def _first(self, coid: str, fn: Callable) -> BrokerOrderStatus:
        last: BrokerOrderStatus | None = None
        err: Exception | None = None
        for b in self._for_order(coid):
            try:
                st = fn(b)
            except BrokerError as e:
                err = e
                continue
            if st.status != "unbekannt":
                return st
            last = st
        if last is None and err is not None:
            raise err
        return last or BrokerOrderStatus(coid, None, "unbekannt")

    def query(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        return self._first(client_order_id, lambda b: b.query(client_order_id, broker_order_id))

    def cancel(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        return self._first(client_order_id, lambda b: b.cancel(client_order_id, broker_order_id))

    def modify_stop(self, client_order_id: str, new_stop: Decimal, broker_order_id: str | None = None) -> BrokerOrderStatus:
        return self._first(client_order_id, lambda b: b.modify_stop(client_order_id, new_stop, broker_order_id))

    def open_stop_orders(self) -> list[BrokerOrderStatus]:
        out: list[BrokerOrderStatus] = []
        for _, b in self.venues.values():
            out.extend(b.open_stop_orders())
        return out
