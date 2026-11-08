"""Marktdatenquellen hinter einer einheitlichen Schnittstelle (FA-01)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

import httpx

KRAKEN_INTERVAL = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
BINANCE_INTERVAL = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}


@dataclass
class RawCandle:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class Ticker:
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h_quote: Decimal
    fetched_at: datetime

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> Decimal:
        m = self.mid
        return (self.ask - self.bid) / m * 100 if m else Decimal(0)


@dataclass
class PairInfo:
    broker_symbol: str
    tick_size: Decimal
    min_qty: Decimal
    step_size: Decimal
    min_notional: Decimal = Decimal(0)


class DataSourceError(RuntimeError):
    pass


class MarketDataSource(Protocol):
    name: str

    def tickers(self, broker_symbols: dict[str, str]) -> dict[str, Ticker]: ...

    def candles(self, broker_symbol: str, timeframe: str, since: datetime | None = None) -> tuple[list[RawCandle], datetime | None]:
        """Liefert abgeschlossene Kerzen und den Beginn der laufenden (unfertigen) Kerze."""
        ...

    def pair_info(self, broker_symbols: list[str]) -> dict[str, PairInfo]: ...


def _ts(sec: float) -> datetime:
    return datetime.fromtimestamp(sec, tz=timezone.utc)


class KrakenPublic:
    name = "Kraken"
    base = "https://api.kraken.com/0/public"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15, headers={"User-Agent": "tradingbot/1.0"})

    def _get(self, path: str, params: dict) -> dict:
        try:
            r = self.client.get(f"{self.base}/{path}", params=params)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise DataSourceError(f"Kraken nicht erreichbar: {e}") from e
        if data.get("error"):
            raise DataSourceError("Kraken: " + "; ".join(data["error"]))
        return data["result"]

    def tickers(self, broker_symbols: dict[str, str]) -> dict[str, Ticker]:
        """broker_symbols: Symbol -> Kraken-Altname."""
        res = self._get("Ticker", {"pair": ",".join(broker_symbols.values())})
        now = datetime.now(timezone.utc)
        out: dict[str, Ticker] = {}
        by_alt = {v: k for k, v in broker_symbols.items()}
        info = self._altnames(list(res.keys()))
        for key, t in res.items():
            sym = by_alt.get(info.get(key, key)) or by_alt.get(key)
            if not sym:
                continue
            vol = Decimal(t["v"][1]) * Decimal(t["p"][1])
            out[sym] = Ticker(sym, Decimal(t["b"][0]), Decimal(t["a"][0]), Decimal(t["c"][0]), vol, now)
        return out

    _alt_cache: dict[str, str] = {}

    def _altnames(self, keys: list[str]) -> dict[str, str]:
        missing = [k for k in keys if k not in self._alt_cache]
        if missing:
            res = self._get("AssetPairs", {"pair": ",".join(missing)})
            for k, v in res.items():
                self._alt_cache[k] = v.get("altname", k)
        return self._alt_cache

    def pair_info(self, broker_symbols: list[str]) -> dict[str, PairInfo]:
        res = self._get("AssetPairs", {"pair": ",".join(broker_symbols)})
        out = {}
        for k, v in res.items():
            alt = v.get("altname", k)
            self._alt_cache[k] = alt
            out[alt] = PairInfo(alt, Decimal(v.get("tick_size") or "1e-%d" % v["pair_decimals"]),
                                Decimal(v.get("ordermin") or "0"), Decimal(1).scaleb(-int(v["lot_decimals"])),
                                Decimal(v.get("costmin") or "0"))
        return out

    def candles(self, broker_symbol: str, timeframe: str, since: datetime | None = None):
        params = {"pair": broker_symbol, "interval": KRAKEN_INTERVAL[timeframe]}
        if since:
            params["since"] = int(since.timestamp()) - 1
        res = self._get("OHLC", params)
        rows = next(v for k, v in res.items() if k != "last")
        out = [RawCandle(_ts(r[0]), Decimal(r[1]), Decimal(r[2]), Decimal(r[3]), Decimal(r[4]), Decimal(r[6])) for r in rows]
        if not out:
            return [], None
        # Der letzte Eintrag ist die laufende Kerze.
        return out[:-1], out[-1].time


class BinanceHistory:
    """Öffentliche Binance-Kursdaten für lange Historien im Backtest (kein Konto nötig)."""

    name = "Binance (Historie)"
    base = "https://data-api.binance.vision/api/v3"
    SYMBOLS = {"BTC/EUR": "BTCEUR", "ETH/EUR": "ETHEUR", "SOL/EUR": "SOLEUR", "XRP/EUR": "XRPEUR",
               "ADA/EUR": "ADAEUR", "DOT/EUR": "DOTEUR", "LINK/EUR": "LINKEUR", "LTC/EUR": "LTCEUR",
               "AVAX/EUR": "AVAXEUR", "DOGE/EUR": "DOGEEUR", "EUR/USD": "EURUSDT"}

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=20)

    def history(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[RawCandle]:
        sym = self.SYMBOLS.get(symbol)
        if not sym:
            raise DataSourceError(f"Keine Historie für {symbol}")
        out: list[RawCandle] = []
        cur = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        while cur < end_ms:
            try:
                r = self.client.get(f"{self.base}/klines", params={
                    "symbol": sym, "interval": BINANCE_INTERVAL[timeframe], "startTime": cur, "endTime": end_ms, "limit": 1000})
                r.raise_for_status()
                rows = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise DataSourceError(f"Historische Daten nicht abrufbar: {e}") from e
            if not rows:
                break
            for k in rows:
                close_time = k[6] / 1000
                if close_time * 1000 > end_ms or close_time > time.time():
                    continue  # nur abgeschlossene Kerzen
                out.append(RawCandle(_ts(k[0] / 1000), Decimal(k[1]), Decimal(k[2]), Decimal(k[3]), Decimal(k[4]), Decimal(k[5])))
            nxt = rows[-1][0] + 1
            if nxt <= cur:
                break
            cur = nxt
            if len(rows) < 1000:
                break
        return out
