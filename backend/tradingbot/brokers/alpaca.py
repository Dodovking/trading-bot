"""Alpaca-Adapter für US-Aktien/ETFs (Paper- oder Live-Konto). Nur offizielle REST-API.

Der Bot rechnet in Euro: Kontostand und Ausführungspreise werden mit dem aktuellen EUR/USD-Kurs
umgerechnet, Stop-Preise vor dem Senden in US-Dollar. Nur ganze Stück (dauerhafte GTC-Stops),
keine Leerverkäufe. Alpaca-API-Schlüssel können keine Auszahlungen auslösen.
"""
from __future__ import annotations

import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

import httpx

from .base import BrokerError, BrokerFill, BrokerOrderStatus, BrokerRejected, OrderRequest

D = Decimal
STATUS = {"new": "offen", "accepted": "offen", "pending_new": "offen", "accepted_for_bidding": "offen", "held": "offen",
          "pending_replace": "offen", "pending_cancel": "offen", "calculated": "offen", "partially_filled": "teilausgefuehrt",
          "filled": "ausgefuehrt", "done_for_day": "offen", "canceled": "storniert", "expired": "storniert",
          "replaced": "storniert", "stopped": "offen", "suspended": "offen", "rejected": "abgelehnt"}
URLS = {"paper": "https://paper-api.alpaca.markets", "live": "https://api.alpaca.markets"}


def root_id(client_order_id: str) -> str:
    """Nachgezogene Stops erhalten bei Alpaca eine neue ID „<ursprung>-r<zeit>“."""
    return client_order_id.split("-r")[0]


class AlpacaBroker:
    def __init__(self, api_key: str, api_secret: str, environment: str, usd_per_eur: Callable[[], Decimal],
                 client: httpx.Client | None = None):
        self.env = "live" if environment == "live" else "paper"
        self.name = "Alpaca" + (" (Paper)" if self.env == "paper" else "")
        self.base = URLS[self.env]
        self.key, self.secret = api_key, api_secret
        self.fx = usd_per_eur
        self.client = client or httpx.Client(timeout=15)

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self.client.request(method, self.base + path, headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}, **kw)
        except httpx.HTTPError as e:
            raise BrokerError(f"Alpaca nicht erreichbar: {e.__class__.__name__}") from e
        if r.status_code in (401, 403):
            raise BrokerRejected("Alpaca: Schlüssel ungültig oder falsche Umgebung (Paper/Live)")
        if r.status_code >= 500 or r.status_code == 429:
            raise BrokerError(f"Alpaca vorübergehend nicht verfügbar ({r.status_code})")
        return r

    def _json(self, r: httpx.Response):
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise BrokerRejected(f"Alpaca: {msg[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise BrokerError("Alpaca: ungültige Antwort") from e

    def _eur(self, usd) -> Decimal:
        return D(str(usd)) / self.fx()

    def _usd(self, eur: Decimal) -> Decimal:
        return (eur * self.fx()).quantize(D("0.01"), ROUND_HALF_UP)

    # --------------------------------------------------------------- Konto
    def check_connection(self) -> str:
        a = self._json(self._req("GET", "/v2/account"))
        if a.get("trading_blocked") or a.get("account_blocked"):
            raise BrokerRejected("Alpaca: Konto für den Handel gesperrt")
        return f"{self.name} verbunden · Konto {a.get('status', '?')} · {a.get('currency', 'USD')}"

    def balances(self) -> dict[str, Decimal]:
        a = self._json(self._req("GET", "/v2/account"))
        out = {"EUR": self._eur(a.get("cash") or 0)}
        for p in self._json(self._req("GET", "/v2/positions")):
            if p.get("asset_class", "us_equity") == "us_equity":
                out[p["symbol"]] = D(str(p["qty"]))
        return out

    # --------------------------------------------------------------- Orders
    def _parse(self, o: dict, client_order_id: str | None = None) -> BrokerOrderStatus:
        filled = D(str(o.get("filled_qty") or 0))
        avg = self._eur(o["filled_avg_price"]) if o.get("filled_avg_price") else None
        fills = [BrokerFill(f"{o['id']}:{filled}", avg, filled, D(0))] if filled and avg is not None and o.get("status") == "filled" else []
        return BrokerOrderStatus(client_order_id or root_id(o.get("client_order_id") or ""), o.get("id"),
                                 STATUS.get(o.get("status", ""), "offen"), filled, avg, D(0), fills, o.get("status", ""))

    def submit(self, req: OrderRequest) -> BrokerOrderStatus:
        if req.qty != req.qty.to_integral_value():
            raise BrokerRejected("Alpaca: nur ganze Stück")
        body = {"symbol": req.broker_symbol, "qty": str(int(req.qty)), "side": "buy" if req.side == "kauf" else "sell",
                "client_order_id": req.client_order_id}
        if req.type == "stop":
            body.update(type="stop", time_in_force="gtc", stop_price=str(self._usd(req.stop_price)))
        else:
            body.update(type="market", time_in_force="day")
        r = self._req("POST", "/v2/orders", json=body)
        if r.status_code == 422 and "client_order_id" in r.text:
            return self.query(req.client_order_id)  # schon vorhanden (Idempotenz)
        return self._parse(self._json(r), req.client_order_id)

    def _latest(self, client_order_id: str) -> dict | None:
        r = self._req("GET", "/v2/orders:by_client_order_id", params={"client_order_id": root_id(client_order_id)})
        if r.status_code == 404:
            return None
        o = self._json(r)
        for _ in range(20):  # nachgezogene Stops: Ersetzungskette bis zur aktuellen Order folgen
            if o.get("status") != "replaced" or not o.get("replaced_by"):
                break
            o = self._json(self._req("GET", f"/v2/orders/{o['replaced_by']}"))
        return o

    def query(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        o = self._latest(client_order_id)
        if o is None:
            return BrokerOrderStatus(client_order_id, None, "unbekannt")
        return self._parse(o, client_order_id)

    def cancel(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        o = self._latest(client_order_id)
        if o is None:
            return BrokerOrderStatus(client_order_id, None, "unbekannt")
        if STATUS.get(o.get("status", "")) in ("offen", "teilausgefuehrt"):
            r = self._req("DELETE", f"/v2/orders/{o['id']}")
            if r.status_code not in (200, 204, 404, 422):
                self._json(r)
        return self.query(client_order_id)

    def modify_stop(self, client_order_id: str, new_stop: Decimal, broker_order_id: str | None = None) -> BrokerOrderStatus:
        o = self._latest(client_order_id)
        if o is None:
            return BrokerOrderStatus(client_order_id, None, "unbekannt")
        new_id = f"{root_id(client_order_id)}-r{int(time.time() * 1000)}"
        self._json(self._req("PATCH", f"/v2/orders/{o['id']}", json={"stop_price": str(self._usd(new_stop)), "client_order_id": new_id}))
        return self.query(client_order_id)

    def open_stop_orders(self) -> list[BrokerOrderStatus]:
        rows = self._json(self._req("GET", "/v2/orders", params={"status": "open", "limit": 500}))
        return [self._parse(o) for o in rows if o.get("type") == "stop"]
