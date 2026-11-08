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
STOCK_NOTE = "US-Börse (Mo–Fr 15:30–22:00 Uhr), Kurs in € umgerechnet, Bruchteile ab 1 €"
OLD_STOCK_NOTE = "US-Börse (Mo–Fr 15:30–22:00 Uhr), Kurs in € umgerechnet, ganze Stück"
# Alpaca: Bruchteile mit bis zu 9 Nachkommastellen, Mindestorderwert 1 US-Dollar (hier mit Puffer in Euro)
STOCK_MIN_QTY, STOCK_STEP, STOCK_MIN_NOTIONAL = Decimal("0.000001"), Decimal("0.000001"), Decimal("1")
CRYPTO_MIN_NOTIONAL = Decimal("0.5")

# Kraken-Asset-Codes für Kontostände
KRAKEN_ASSETS = {"BTC": ["XXBT", "XBT"], "ETH": ["XETH", "ETH"], "SOL": ["SOL"], "XRP": ["XXRP", "XRP"], "ADA": ["ADA"],
                 "DOT": ["DOT"], "LINK": ["LINK"], "LTC": ["XLTC", "LTC"], "AVAX": ["AVAX"], "DOGE": ["XXDG", "XDG"],
                 "EUR": ["ZEUR", "EUR"], "USD": ["ZUSD", "USD"]}

# symbol, markt, base, quote, kraken-altname, tick, min_menge, schrittgröße (Fallback, wird von Kraken aktualisiert)
SEED = [
    ("BTC/EUR", "krypto", "BTC", "EUR", "XBTEUR", "0.1", "0.00006", "0.00000001"),
    ("ETH/EUR", "krypto", "ETH", "EUR", "ETHEUR", "0.01", "0.002", "0.00000001"),
    ("SOL/EUR", "krypto", "SOL", "EUR", "SOLEUR", "0.01", "0.05", "0.00000001"),
    ("XRP/EUR", "krypto", "XRP", "EUR", "XRPEUR", "0.00001", "4", "0.00000001"),
    ("ADA/EUR", "krypto", "ADA", "EUR", "ADAEUR", "0.000001", "20", "0.00000001"),
    ("DOT/EUR", "krypto", "DOT", "EUR", "DOTEUR", "0.0001", "3.9", "0.00000001"),
    ("LINK/EUR", "krypto", "LINK", "EUR", "LINKEUR", "0.00001", "0.35", "0.00000001"),
    ("LTC/EUR", "krypto", "LTC", "EUR", "LTCEUR", "0.01", "0.08", "0.00000001"),
    ("AVAX/EUR", "krypto", "AVAX", "EUR", "AVAXEUR", "0.01", "0.5", "0.00000001"),
    ("DOGE/EUR", "krypto", "DOGE", "EUR", "XDGEUR", "0.0000001", "50", "0.00000001"),
    ("EUR/USD", "devisen", "EUR", "USD", "EURUSD", "0.00001", "5", "0.00000001"),
]


def seed_instruments(db: Session) -> None:
    existing = {i.symbol for i in db.scalars(select(Instrument))}
    for sym, market, base, quote, alt, tick, mn, step in SEED:
        if sym not in existing:
            db.add(Instrument(symbol=sym, market=market, base=base, quote=quote, broker_symbol=alt,
                              tick_size=Decimal(tick), min_qty=Decimal(mn), step_size=Decimal(step),
                              min_notional=CRYPTO_MIN_NOTIONAL if market == "krypto" else None, tradable=market != "devisen",
                              note="Nur Analyse/Signale: Long braucht ein USD-Konto, Short ist ausgeschlossen" if market == "devisen" else ""))
    for sym, _, _ in STOCKS:
        if sym not in existing:
            db.add(Instrument(symbol=sym, market="aktie", base=sym, quote="EUR", broker_symbol=sym, tick_size=Decimal("0.01"),
                              min_qty=STOCK_MIN_QTY, step_size=STOCK_STEP, min_notional=STOCK_MIN_NOTIONAL, tradable=True,
                              note=STOCK_NOTE, trading_hours="US-Börse"))
    for inst in db.scalars(select(Instrument).where(Instrument.market == "aktie")):
        if inst.step_size < 1:
            continue
        inst.min_qty, inst.step_size, inst.min_notional = STOCK_MIN_QTY, STOCK_STEP, STOCK_MIN_NOTIONAL
        if inst.note == OLD_STOCK_NOTE:
            inst.note = STOCK_NOTE
    for inst in db.scalars(select(Instrument).where(Instrument.market == "krypto", Instrument.min_notional.is_(None))):
        inst.min_notional = CRYPTO_MIN_NOTIONAL
    db.flush()


def refresh_limits(db: Session, source) -> int:
    """Mindestmengen, Schrittgrößen und Mindestorderwerte von Kraken übernehmen (ändern sich gelegentlich)."""
    insts = list(db.scalars(select(Instrument).where(Instrument.market == "krypto")))
    info = source.pair_info([i.broker_symbol for i in insts])
    n = 0
    for i in insts:
        pi = info.get(i.broker_symbol)
        if pi is None:
            continue
        if (i.min_qty, i.step_size, i.tick_size, i.min_notional) != (pi.min_qty, pi.step_size, pi.tick_size, pi.min_notional):
            i.min_qty, i.step_size, i.tick_size, i.min_notional = pi.min_qty, pi.step_size, pi.tick_size, pi.min_notional
            n += 1
    db.flush()
    return n


def instruments_by_symbol(db: Session) -> dict[str, Instrument]:
    return {i.symbol: i for i in db.scalars(select(Instrument).where(Instrument.active.is_(True)))}
