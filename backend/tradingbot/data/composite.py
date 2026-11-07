"""Kursquelle je Markt: Krypto/Devisen über Kraken, Aktien/ETFs über Alpaca."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .sources import DataSourceError, KrakenPublic, Ticker
from .stocks import STOCK_SYMBOLS, AlpacaData, Fx


class CompositeSource:
    name = "Kraken + Alpaca"

    def __init__(self, kraken: KrakenPublic | None = None, alpaca: AlpacaData | None = None):
        self.kraken = kraken or KrakenPublic()
        self.fx = alpaca.fx if alpaca else Fx(live_fn=self._kraken_eurusd)
        self.alpaca = alpaca or AlpacaData(self.fx)
        self.stock_error = ""

    def _kraken_eurusd(self) -> Decimal | None:
        t = self.kraken.tickers({"EUR/USD": "EURUSD"}).get("EUR/USD")
        return t.mid if t else None

    def stocks_ready(self) -> bool:
        return self.alpaca.ready()

    def tickers(self, broker_symbols: dict[str, str]) -> dict[str, Ticker]:
        stocks = {s: b for s, b in broker_symbols.items() if b in STOCK_SYMBOLS}
        rest = {s: b for s, b in broker_symbols.items() if s not in stocks}
        out: dict[str, Ticker] = {}
        if stocks:
            try:
                by_b = {b: s for s, b in stocks.items()}
                for b, t in self.alpaca.tickers(list(stocks.values())).items():
                    if b in by_b:
                        t.symbol = by_b[b]
                        out[by_b[b]] = t
                self.stock_error = ""
            except DataSourceError as e:
                self.stock_error = str(e)
        if rest:
            out.update(self.kraken.tickers(rest))
        return out

    def candles(self, broker_symbol: str, timeframe: str, since: datetime | None = None):
        if broker_symbol in STOCK_SYMBOLS:
            return self.alpaca.candles(broker_symbol, timeframe, since)
        return self.kraken.candles(broker_symbol, timeframe, since)

    def pair_info(self, broker_symbols: list[str]):
        return self.kraken.pair_info([b for b in broker_symbols if b not in STOCK_SYMBOLS])
