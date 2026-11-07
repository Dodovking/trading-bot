"""Einheitliche Broker-Schnittstelle. Dieselbe Logik läuft gegen Simulation und echten Broker."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass
class OrderRequest:
    client_order_id: str
    symbol: str
    broker_symbol: str
    side: str  # kauf | verkauf
    type: str  # market | stop
    qty: Decimal
    stop_price: Decimal | None = None


@dataclass
class BrokerFill:
    fill_id: str
    price: Decimal
    qty: Decimal
    fee: Decimal


@dataclass
class BrokerOrderStatus:
    client_order_id: str
    broker_order_id: str | None
    status: str  # offen | teilausgefuehrt | ausgefuehrt | storniert | abgelehnt | unbekannt
    filled_qty: Decimal = Decimal(0)
    avg_price: Decimal | None = None
    fee: Decimal = Decimal(0)
    fills: list[BrokerFill] = field(default_factory=list)
    note: str = ""


class BrokerError(RuntimeError):
    """Technischer Fehler (Verbindung, Timeout) – Status unklar, nicht blind wiederholen."""


class BrokerRejected(RuntimeError):
    """Broker hat die Order abgelehnt."""


class Broker(Protocol):
    name: str

    def check_connection(self) -> str: ...

    def submit(self, req: OrderRequest) -> BrokerOrderStatus: ...

    def query(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus: ...

    def cancel(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus: ...

    def balances(self) -> dict[str, Decimal]: ...

    def open_stop_orders(self) -> list[BrokerOrderStatus]: ...
