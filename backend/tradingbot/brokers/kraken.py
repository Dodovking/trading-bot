"""Kraken-Adapter für Echtgeld (Stufe 5). Nur offizielle REST-API (FA-30).

Sicherheitsregeln: API-Schlüssel nur mit Rechten „Abfragen“ + „Orders erstellen/ändern/stornieren“,
OHNE Auszahlungsrecht; wenn möglich IP-Freigabeliste. Schlüssel liegen verschlüsselt in der Datenbank
und werden nie protokolliert.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
import urllib.parse
from decimal import Decimal

import httpx

from ..data.instruments import KRAKEN_ASSETS
from .base import BrokerError, BrokerFill, BrokerOrderStatus, BrokerRejected, OrderRequest

_ASSET_TO_SYMBOL = {code: name for name, codes in KRAKEN_ASSETS.items() for code in codes}
_nonce_lock = threading.Lock()
_last_nonce = 0


def _nonce() -> int:
    global _last_nonce
    with _nonce_lock:
        n = max(int(time.time() * 1000), _last_nonce + 1)
        _last_nonce = n
        return n


class KrakenBroker:
    name = "Kraken"
    base = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str, client: httpx.Client | None = None):
        self.key = api_key
        self.secret = api_secret
        self.client = client or httpx.Client(timeout=15)

    def _private(self, method: str, params: dict | None = None) -> dict:
        path = f"/0/private/{method}"
        data = {"nonce": str(_nonce()), **(params or {})}
        body = urllib.parse.urlencode(data)
        sha = hashlib.sha256((data["nonce"] + body).encode()).digest()
        try:
            secret = base64.b64decode(self.secret)
        except (ValueError, TypeError) as e:
            raise BrokerRejected("API-Secret ist kein gültiger Kraken-Schlüssel") from e
        sig = base64.b64encode(hmac.new(secret, path.encode() + sha, hashlib.sha512).digest()).decode()
        try:
            r = self.client.post(self.base + path, content=body, headers={
                "API-Key": self.key, "API-Sign": sig, "Content-Type": "application/x-www-form-urlencoded"})
            r.raise_for_status()
            res = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise BrokerError(f"Kraken nicht erreichbar: {e.__class__.__name__}") from e
        errs = res.get("error") or []
        if errs:
            msg = "; ".join(errs)
            if any(x.startswith(("EGeneral:Internal", "EService", "EAPI:Rate")) for x in errs):
                raise BrokerError(f"Kraken: {msg}")
            raise BrokerRejected(f"Kraken: {msg}")
        return res.get("result", {})

    def check_connection(self) -> str:
        bal = self.balances()
        return f"Verbunden – {len(bal)} Guthabenposten"

    def balances(self) -> dict[str, Decimal]:
        res = self._private("Balance")
        out: dict[str, Decimal] = {}
        for code, amount in res.items():
            name = _ASSET_TO_SYMBOL.get(code, code.split(".")[0])
            out[name] = out.get(name, Decimal(0)) + Decimal(amount)
        return out

    def submit(self, req: OrderRequest) -> BrokerOrderStatus:
        params = {"pair": req.broker_symbol, "type": "buy" if req.side == "kauf" else "sell",
                  "volume": format(req.qty, "f"), "cl_ord_id": req.client_order_id}
        if req.type == "market":
            params["ordertype"] = "market"
        elif req.type == "stop":
            params["ordertype"] = "stop-loss"
            params["price"] = format(req.stop_price, "f")
        else:
            raise BrokerRejected(f"Ordertyp {req.type} nicht unterstützt")
        res = self._private("AddOrder", params)
        txid = (res.get("txid") or [None])[0]
        return BrokerOrderStatus(req.client_order_id, txid, "offen")

    def _parse(self, client_order_id: str, txid: str, o: dict) -> BrokerOrderStatus:
        vol, exe = Decimal(o.get("vol", "0")), Decimal(o.get("vol_exec", "0"))
        st = o.get("status")
        if st in ("pending", "open"):
            status = "teilausgefuehrt" if exe > 0 else "offen"
        elif st == "closed":
            status = "ausgefuehrt" if exe >= vol else "teilausgefuehrt"
        elif st in ("canceled", "expired"):
            status = "storniert"
        else:
            status = "unbekannt"
        price = Decimal(o["price"]) if o.get("price") and Decimal(o["price"]) > 0 else None
        fee = Decimal(o.get("fee", "0"))
        fills = [BrokerFill(txid, price, exe, fee)] if exe > 0 and price else []
        return BrokerOrderStatus(client_order_id, txid, status, exe, price, fee, fills, o.get("reason") or "")

    def query(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        if broker_order_id:
            res = self._private("QueryOrders", {"txid": broker_order_id})
            for txid, o in res.items():
                return self._parse(client_order_id, txid, o)
        for method in ("OpenOrders", "ClosedOrders"):
            res = self._private(method, {"cl_ord_id": client_order_id})
            orders = res.get("open") or res.get("closed") or {}
            for txid, o in orders.items():
                return self._parse(client_order_id, txid, o)
        return BrokerOrderStatus(client_order_id, None, "unbekannt")

    def cancel(self, client_order_id: str, broker_order_id: str | None = None) -> BrokerOrderStatus:
        params = {"txid": broker_order_id} if broker_order_id else {"cl_ord_id": client_order_id}
        self._private("CancelOrder", params)
        return self.query(client_order_id, broker_order_id)

    def modify_stop(self, client_order_id: str, new_stop: Decimal, broker_order_id: str | None = None) -> BrokerOrderStatus:
        params = {"trigger_price": format(new_stop, "f")}
        params.update({"txid": broker_order_id} if broker_order_id else {"cl_ord_id": client_order_id})
        self._private("AmendOrder", params)
        return self.query(client_order_id, broker_order_id)

    def open_stop_orders(self) -> list[BrokerOrderStatus]:
        res = self._private("OpenOrders")
        out = []
        for txid, o in (res.get("open") or {}).items():
            if (o.get("descr") or {}).get("ordertype") == "stop-loss":
                out.append(self._parse(o.get("cl_ord_id") or "", txid, o))
        return out
