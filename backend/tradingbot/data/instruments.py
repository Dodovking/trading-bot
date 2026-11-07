"""Stammdaten der handelbaren Werte."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.models import Instrument
from .stocks import STOCKS

NAMES = {"BTC/EUR": "Bitcoin", "ETH/EUR": "Ethereum", "SOL/EUR": "Solana", "XRP/EUR": "XRP", "ADA/EUR": "Cardano",
         "DOT/EUR": "Polkadot", "LINK/EUR": "Chainlink", "LTC/EUR": "Litecoin", "AVAX/EUR": "Avalanche", "DOGE/EUR": "Dogecoin",
         "EUR/USD": "Euro / US-Dollar", **{s: n for s, n, _ in STOCKS}}
STOCK_NOTE = "US-Börse (Mo–Fr 15:30–22:00 Uhr), Kurs in € umgerechnet, ganze Stück"

# Kraken-Asset-Codes für Kontostände
KRAKEN_ASSETS = {"BTC": ["XXBT", "XBT"], "ETH": ["XETH", "ETH"], "SOL": ["SOL"], "XRP": ["XXRP", "XRP"], "ADA": ["ADA"],
                 "DOT": ["DOT"], "LINK": ["LINK"], "LTC": ["XLTC", "LTC"], "AVAX": ["AVAX"], "DOGE": ["XXDG", "XDG"],
                 "EUR": ["ZEUR", "EUR"], "USD": ["ZUSD", "USD"]}

# symbol, markt, base, quote, kraken-altname, tick, min_menge, schrittgröße (Fallback, wird von Kraken aktualisiert)
SEED = [
    ("BTC/EUR", "krypto", "BTC", "EUR", "XBTEUR", "0.1", "0.00005", "0.00000001"),
    ("ETH/EUR", "krypto", "ETH", "EUR", "ETHEUR", "0.01", "0.002", "0.00000001"),
    ("SOL/EUR", "krypto", "SOL", "EUR", "SOLEUR", "0.01", "0.02", "0.00000001"),
    ("XRP/EUR", "krypto", "XRP", "EUR", "XRPEUR", "0.00001", "2", "0.00000001"),
    ("ADA/EUR", "krypto", "ADA", "EUR", "ADAEUR", "0.000001", "5", "0.00000001"),
    ("DOT/EUR", "krypto", "DOT", "EUR", "DOTEUR", "0.0001", "0.5", "0.00000001"),
    ("LINK/EUR", "krypto", "LINK", "EUR", "LINKEUR", "0.00001", "0.2", "0.00000001"),
    ("LTC/EUR", "krypto", "LTC", "EUR", "LTCEUR", "0.01", "0.05", "0.00000001"),
    ("AVAX/EUR", "krypto", "AVAX", "EUR", "AVAXEUR", "0.01", "0.1", "0.00000001"),
    ("DOGE/EUR", "krypto", "DOGE", "EUR", "XDGEUR", "0.0000001", "20", "0.00000001"),
    ("EUR/USD", "devisen", "EUR", "USD", "EURUSD", "0.00001", "5", "0.00000001"),
]


def seed_instruments(db: Session) -> None:
    existing = {i.symbol for i in db.scalars(select(Instrument))}
    for sym, market, base, quote, alt, tick, mn, step in SEED:
        if sym not in existing:
            db.add(Instrument(symbol=sym, market=market, base=base, quote=quote, broker_symbol=alt,
                              tick_size=Decimal(tick), min_qty=Decimal(mn), step_size=Decimal(step),
                              tradable=market != "devisen",
                              note="Nur Analyse/Signale: Long braucht ein USD-Konto, Short ist ausgeschlossen" if market == "devisen" else ""))
    for sym, _, _ in STOCKS:
        if sym not in existing:
            # Ganze Stück: Stop-Orders beim Broker sind nur für ganze Aktien dauerhaft (GTC) möglich
            db.add(Instrument(symbol=sym, market="aktie", base=sym, quote="EUR", broker_symbol=sym, tick_size=Decimal("0.01"),
                              min_qty=Decimal(1), step_size=Decimal(1), tradable=True, note=STOCK_NOTE,
                              trading_hours="US-Börse"))
    db.flush()


def instruments_by_symbol(db: Session) -> dict[str, Instrument]:
    return {i.symbol: i for i in db.scalars(select(Instrument).where(Instrument.active.is_(True)))}
