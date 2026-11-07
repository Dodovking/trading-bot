"""Aktien/ETFs (US-Börsen) über die Alpaca-Marktdaten-API, Kurse in Euro umgerechnet.

Der Bot rechnet intern durchgehend in Euro. Aktienkurse kommen in US-Dollar und werden
mit dem aktuellen EUR/USD-Kurs (Kraken) bzw. für historische Kerzen mit dem
EZB-Referenzkurs des Tages (frankfurter.dev) umgerechnet.
"""
from __future__ import annotations

import logging
import threading
import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx

from . import sessions
from .sources import DataSourceError, RawCandle, Ticker

log = logging.getLogger(__name__)
D = Decimal

# Symbol, Name, Art
STOCKS = [
    ("AAPL", "Apple", "Aktie"), ("MSFT", "Microsoft", "Aktie"), ("NVDA", "Nvidia", "Aktie"), ("AMZN", "Amazon", "Aktie"),
    ("GOOGL", "Alphabet (Google)", "Aktie"), ("META", "Meta (Facebook)", "Aktie"), ("TSLA", "Tesla", "Aktie"),
    ("AMD", "AMD", "Aktie"), ("NFLX", "Netflix", "Aktie"),
    ("SPY", "S&P 500 (ETF)", "ETF"), ("QQQ", "Nasdaq-100 (ETF)", "ETF"),
]
STOCK_SYMBOLS = {s for s, _, _ in STOCKS}
ALPACA_TF = {"15m": "15Min", "1h": "1Hour", "4h": "1Hour", "1d": "1Day"}
INITIAL_DAYS = {"15m": 45, "1h": 150, "4h": 400, "1d": 1100}
NO_KEYS = "Für Aktienkurse fehlt ein Alpaca-Schlüssel (Einstellungen → Konto & Börse → Alpaca)"


# ---------------------------------------------------------------------- Schlüssel
_keys_lock = threading.Lock()
_keys_cache: tuple[float, tuple[str, str] | None] = (0.0, None)


def reset_keys_cache() -> None:
    global _keys_cache
    with _keys_lock:
        _keys_cache = (0.0, None)


def alpaca_keys() -> tuple[str, str] | None:
    """Schlüssel für Kursdaten: Umgebungsvariablen, sonst ein verbundenes Alpaca-Konto (Admins zuerst)."""
    global _keys_cache
    import os
    if os.environ.get("ALPACA_KEY_ID") and os.environ.get("ALPACA_SECRET_KEY"):
        return os.environ["ALPACA_KEY_ID"], os.environ["ALPACA_SECRET_KEY"]
    with _keys_lock:
        ts, val = _keys_cache
        if ts and time.monotonic() - ts < (120 if val else 10):
            return val
    val = None
    try:
        from sqlalchemy import select

        from ..core.crypto import decrypt
        from ..core.db import session_scope
        from ..core.models import TradingAccount, User
        with session_scope() as db:
            rows = db.execute(select(TradingAccount, User.role).join(User, User.id == TradingAccount.user_id)
                              .where(TradingAccount.broker == "alpaca", TradingAccount.connected.is_(True))).all()
            rows.sort(key=lambda r: (r[1] != "admin", r[0].id))
            for acct, _ in rows:
                k, s = decrypt(acct.api_key_enc), decrypt(acct.api_secret_enc)
                if k and s:
                    val = (k, s)
                    break
    except Exception:  # noqa: BLE001 – ohne Datenbank (Tests) einfach keine Schlüssel
        log.debug("Alpaca-Schlüssel nicht lesbar", exc_info=True)
    with _keys_lock:
        _keys_cache = (time.monotonic(), val)
    return val


# ---------------------------------------------------------------------- Wechselkurs
class Fx:
    """USD → EUR. Live: Kraken EUR/USD; historisch: EZB-Referenzkurse."""

    def __init__(self, live_fn=None, client: httpx.Client | None = None):
        self.live_fn = live_fn  # () -> Decimal | None (USD je EUR)
        self.client = client or httpx.Client(timeout=15, follow_redirects=True)
        self._live: tuple[float, Decimal] | None = None
        self._days: list[date] = []
        self._rates: dict[date, Decimal] = {}  # EUR je USD
        self._covered: tuple[date, date] | None = None
        self.lock = threading.Lock()

    def usd_per_eur(self) -> Decimal:
        if self._live and time.monotonic() - self._live[0] < 120:
            return self._live[1]
        rate = None
        if self.live_fn:
            try:
                rate = self.live_fn()
            except Exception:  # noqa: BLE001
                rate = None
        if not rate:
            rate = self._latest_ecb()
        self._live = (time.monotonic(), rate)
        return rate

    def _latest_ecb(self) -> Decimal:
        today = datetime.now(timezone.utc).date()
        self.ensure(today - timedelta(days=10), today)
        if not self._days:
            raise DataSourceError("Kein EUR/USD-Kurs verfügbar")
        return 1 / self._rates[self._days[-1]]

    def ensure(self, start: date, end: date) -> None:
        with self.lock:
            if self._covered and self._covered[0] <= start and self._covered[1] >= end:
                return
            lo = min(start, self._covered[0]) if self._covered else start
            hi = max(end, self._covered[1]) if self._covered else end
            try:
                r = self.client.get(f"https://api.frankfurter.dev/v1/{(lo - timedelta(days=7)).isoformat()}..{hi.isoformat()}",
                                    params={"base": "USD", "symbols": "EUR"})
                r.raise_for_status()
                data = r.json()["rates"]
            except (httpx.HTTPError, ValueError, KeyError) as e:
                raise DataSourceError(f"EZB-Wechselkurse nicht abrufbar: {e}") from e
            for k, v in data.items():
                self._rates[date.fromisoformat(k)] = D(str(v["EUR"]))
            self._days = sorted(self._rates)
            self._covered = (lo, hi)

    def eur_per_usd_on(self, d: date) -> Decimal:
        i = bisect_right(self._days, d)
        if i == 0:
            raise DataSourceError(f"Kein Wechselkurs für {d}")
        return self._rates[self._days[i - 1]]


# ---------------------------------------------------------------------- Kursdaten
def _parse_t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class AlpacaData:
    name = "Alpaca (IEX)"
    base = "https://data.alpaca.markets/v2"

    def __init__(self, fx: Fx, keys_fn=alpaca_keys, client: httpx.Client | None = None):
        self.fx = fx
        self.keys_fn = keys_fn
        self.client = client or httpx.Client(timeout=20)
        self.last_error = ""

    def ready(self) -> bool:
        return self.keys_fn() is not None

    def _get(self, path: str, params: dict) -> dict:
        keys = self.keys_fn()
        if not keys:
            raise DataSourceError(NO_KEYS)
        try:
            r = self.client.get(self.base + path, params=params,
                                headers={"APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1]})
        except httpx.HTTPError as e:
            raise DataSourceError(f"Alpaca nicht erreichbar: {e.__class__.__name__}") from e
        if r.status_code in (401, 403):
            raise DataSourceError("Alpaca-Schlüssel ungültig oder ohne Datenzugriff")
        if r.status_code == 429:
            raise DataSourceError("Alpaca: zu viele Anfragen")
        if r.status_code >= 400:
            raise DataSourceError(f"Alpaca-Fehler {r.status_code}: {r.text[:120]}")
        try:
            return r.json()
        except ValueError as e:
            raise DataSourceError("Alpaca: ungültige Antwort") from e

    # -------------------------------------------------------------- Ticker
    def tickers(self, symbols: list[str]) -> dict[str, Ticker]:
        if not symbols:
            return {}
        data = self._get("/stocks/snapshots", {"symbols": ",".join(symbols), "feed": "iex"})
        data = data.get("snapshots", data)
        rate = self.fx.usd_per_eur()
        now = datetime.now(timezone.utc)
        out = {}
        for sym, s in data.items():
            if not s:
                continue
            last = D(str((s.get("latestTrade") or {}).get("p") or 0)) or D(str((s.get("dailyBar") or {}).get("c") or 0))
            if last <= 0:
                continue
            q = s.get("latestQuote") or {}
            bid, ask = D(str(q.get("bp") or 0)), D(str(q.get("ap") or 0))
            if not (bid > 0 and ask >= bid and (ask - bid) / last < D("0.005") and abs((bid + ask) / 2 / last - 1) < D("0.01")):
                # IEX-Kurse sind außerhalb der Handelszeit oft leer – dann letzter Preis mit typischem Spread
                bid, ask = last * D("0.9999"), last * D("1.0001")
            bar = s.get("dailyBar") or {}
            vol = D(str(bar.get("v") or 0)) * D(str(bar.get("c") or last))
            out[sym] = Ticker(sym, bid / rate, ask / rate, last / rate, vol / rate, now)
        return out

    # -------------------------------------------------------------- Kerzen
    def _bars(self, symbol: str, timeframe: str, start: datetime, end: datetime | None = None) -> list[dict]:
        params = {"timeframe": ALPACA_TF[timeframe], "start": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "limit": 10000, "feed": "iex", "adjustment": "all", "sort": "asc"}
        if end:
            params["end"] = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows: list[dict] = []
        for _ in range(50):
            data = self._get(f"/stocks/{symbol}/bars", params)
            rows.extend(data.get("bars") or [])
            tok = data.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
        return rows

    def _regular(self, rows: list[dict], timeframe: str) -> list[tuple[datetime, dict]]:
        """Nur regulärer Handel (ohne vor-/nachbörslich)."""
        out = []
        for b in rows:
            t = _parse_t(b["t"])
            if timeframe == "1d":
                out.append((t, b))
                continue
            s = sessions.session(t.astimezone(sessions.ET).date())
            if s is None:
                continue
            if timeframe == "15m":
                ok = s[0] <= t < s[1]
            else:  # Stundenkerzen beginnen zur vollen Stunde (9:00 enthält 9:30–10:00)
                ok = s[0] - timedelta(minutes=30) <= t < s[1]
            if ok:
                out.append((t, b))
        return out

    @staticmethod
    def _half(t: datetime) -> datetime:
        """4h-Kerzen: zwei je Handelstag (9:00–13:00 und 13:00–Schluss, New Yorker Zeit)."""
        et = t.astimezone(sessions.ET)
        h = 9 if et.hour < 13 else 13
        return et.replace(hour=h, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def _closed_until(self, t: datetime, timeframe: str) -> datetime:
        """Zeitpunkt, ab dem die Kerze mit Beginn t abgeschlossen ist."""
        et_day = t.astimezone(sessions.ET).date()
        s = sessions.session(et_day)
        close = s[1] if s else t + timedelta(days=1)
        if timeframe == "1d":
            return close
        if timeframe == "4h":
            return min(t + timedelta(hours=4), close)
        step = timedelta(minutes=15) if timeframe == "15m" else timedelta(hours=1)
        return min(t + step, close)

    def _convert(self, items: list[tuple[datetime, dict]]) -> list[RawCandle]:
        if not items:
            return []
        self.fx.ensure(items[0][0].date(), items[-1][0].date())
        out = []
        for t, b in items:
            k = self.fx.eur_per_usd_on(t.astimezone(sessions.ET).date())
            out.append(RawCandle(t, D(str(b["o"])) * k, D(str(b["h"])) * k, D(str(b["l"])) * k, D(str(b["c"])) * k, D(str(b["v"]))))
        return out

    def _aggregate(self, items: list[tuple[datetime, dict]]) -> list[tuple[datetime, dict]]:
        groups: dict[datetime, dict] = {}
        for t, b in items:
            h = self._half(t)
            g = groups.get(h)
            if g is None:
                groups[h] = {"o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
            else:
                g["h"], g["l"], g["c"], g["v"] = max(g["h"], b["h"]), min(g["l"], b["l"]), b["c"], g["v"] + b["v"]
        return sorted(groups.items())

    def candles(self, symbol: str, timeframe: str, since: datetime | None = None, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        start = (since - timedelta(days=1)) if since else now - timedelta(days=INITIAL_DAYS[timeframe])
        items = self._regular(self._bars(symbol, timeframe, start), timeframe)
        if timeframe == "4h":
            items = self._aggregate(items)
        closed = [(t, b) for t, b in items if self._closed_until(t, timeframe) <= now]
        return self._convert(closed), self._next_due(timeframe, now)

    def _bar_start(self, t: datetime, timeframe: str) -> datetime:
        et = t.astimezone(sessions.ET)
        if timeframe == "1d":
            return et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        if timeframe == "4h":
            return self._half(t)
        if timeframe == "1h":
            return et.replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return et.replace(minute=et.minute - et.minute % 15, second=0, microsecond=0).astimezone(timezone.utc)

    def _next_due(self, timeframe: str, now: datetime) -> datetime:
        """„Beginn der laufenden Kerze“ so gewählt, dass Beginn + Zeitrahmen = Schluss der Kerze
        (Aktienkerzen enden oft früher, z. B. die Tageskerze um 16:00 New Yorker Zeit)."""
        from ..core.types import TIMEFRAMES
        ref = now if sessions.is_open(now) else sessions.next_open(now)
        end = self._closed_until(self._bar_start(ref, timeframe), timeframe)
        if end <= now:
            end = self._closed_until(self._bar_start(sessions.next_open(now), timeframe), timeframe)
        return end - TIMEFRAMES[timeframe]

    def history(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[RawCandle]:
        items = self._regular(self._bars(symbol, timeframe, start, end), timeframe)
        if timeframe == "4h":
            items = self._aggregate(items)
        now = datetime.now(timezone.utc)
        return self._convert([(t, b) for t, b in items if self._closed_until(t, timeframe) <= min(now, end)])
