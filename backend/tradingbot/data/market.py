"""Marktdaten-Dienst: lädt Kurse, prüft Qualität, speichert Kerzen und überwacht das Datenalter (FA-01/02/05)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..core.db import session_scope, utcnow
from ..core.events import log_event
from ..core.models import Candle, Instrument
from ..core.types import TIMEFRAMES, Bar
from . import sessions
from .quality import check_candles
from .sources import DataSourceError, MarketDataSource, RawCandle, Ticker
from .stocks import NO_KEYS, STOCK_SYMBOLS

log = logging.getLogger(__name__)


@dataclass
class FeedHealth:
    ok: bool
    tick_age_s: float | None
    candle_age_s: float | None
    reason: str = ""


class MarketData:
    def __init__(self, source: MarketDataSource):
        self.source = source
        self.tickers: dict[str, Ticker] = {}
        self.forming: dict[tuple[str, str], datetime] = {}  # Beginn der laufenden Kerze
        self.last_closed: dict[tuple[str, str], datetime] = {}
        self.errors = 0
        self.last_error = ""
        self.last_success: datetime | None = None
        self.lock = threading.RLock()
        self._last_candle_poll: dict[tuple[str, str], datetime] = {}

    # ------------------------------------------------------------------ Ticker
    def refresh_tickers(self, instruments: list[Instrument]) -> None:
        if not instruments:
            return
        try:
            res = self.source.tickers({i.symbol: i.broker_symbol for i in instruments})
        except DataSourceError as e:
            self._fail(str(e))
            return
        with self.lock:
            self.tickers.update(res)
        self._ok()

    def _fail(self, msg: str, db: Session | None = None) -> None:
        self.errors += 1
        if self.errors in (1, 3) or self.errors % 20 == 0:
            log_event(None, "warnung", "marktdaten", f"Marktdaten-Abruf fehlgeschlagen ({self.errors}×): {msg}", kind="daten_fehler", db=db)
        self.last_error = msg

    def _ok(self, db: Session | None = None) -> None:
        if self.errors >= 3:
            log_event(None, "info", "marktdaten", "Marktdaten wieder verfügbar", kind="daten_ok", db=db)
        self.errors = 0
        self.last_error = ""
        self.last_success = utcnow()

    # ------------------------------------------------------------------ Kerzen
    def due(self, symbol: str, timeframe: str, now: datetime) -> bool:
        key = (symbol, timeframe)
        forming = self.forming.get(key)
        last_poll = self._last_candle_poll.get(key)
        if forming is None or last_poll is None:
            return True
        if now >= forming + TIMEFRAMES[timeframe] + timedelta(seconds=5) and now - last_poll > timedelta(seconds=20):
            return True
        return now - last_poll > timedelta(minutes=10)

    def refresh_candles(self, db: Session, inst: Instrument, timeframe: str) -> list[datetime]:
        """Lädt neue abgeschlossene Kerzen. Rückgabe: Zeiten neu gespeicherter Kerzen."""
        key = (inst.symbol, timeframe)
        self._last_candle_poll[key] = utcnow()
        last = db.scalars(select(Candle.time).where(Candle.instrument_id == inst.id, Candle.timeframe == timeframe)
                          .order_by(Candle.time.desc()).limit(1)).first()
        try:
            raw, forming = self.source.candles(inst.broker_symbol, timeframe, since=last)
        except DataSourceError as e:
            self._fail(str(e), db)
            return []
        self._ok(db)
        if forming:
            self.forming[key] = forming
        if last is not None:
            raw = [c for c in raw if c.time > last]
        if not raw:
            return []
        prev = self._prev_raw(db, inst.id, timeframe)
        stock = inst.symbol in STOCK_SYMBOLS
        # Aktien: Nacht/Wochenende sind keine Lücken; Kurssprünge über Nacht (z. B. Quartalszahlen) sind echt
        rows, rep = check_candles(raw, TIMEFRAMES[timeframe], prev, outlier_min_pct=25.0 if stock else 8.0)
        if stock:
            rep.gaps = []
        if rep.problems:
            log_event(None, "warnung", "marktdaten",
                      f"{inst.symbol} {timeframe}: {len(rep.flags)} fehlerhafte Kerze(n), {rep.duplicates} Duplikat(e), {len(rep.gaps)} Lücke(n)",
                      kind="datenqualitaet", data={"flags": {k.isoformat(): v for k, v in rep.flags.items()},
                                                    "gaps": [[a.isoformat(), b.isoformat()] for a, b in rep.gaps]}, db=db)
        new_times = []
        for c in rows:
            stmt = sqlite_insert(Candle).values(
                instrument_id=inst.id, timeframe=timeframe, time=c.time, open=c.open, high=c.high, low=c.low,
                close=c.close, volume=c.volume, quality_flag=rep.flags.get(c.time, "ok"),
            ).on_conflict_do_nothing()
            if db.execute(stmt).rowcount:
                new_times.append(c.time)
        if rows:
            self.last_closed[key] = rows[-1].time
        return new_times

    def _prev_raw(self, db: Session, instrument_id: int, timeframe: str) -> list[RawCandle]:
        rows = db.scalars(select(Candle).where(Candle.instrument_id == instrument_id, Candle.timeframe == timeframe,
                                               Candle.quality_flag == "ok").order_by(Candle.time.desc()).limit(200)).all()
        return [RawCandle(r.time, r.open, r.high, r.low, r.close, r.volume) for r in reversed(rows)]

    @staticmethod
    def bars(db: Session, instrument_id: int, timeframe: str, limit: int = 400, until: datetime | None = None) -> list[Bar]:
        q = select(Candle).where(Candle.instrument_id == instrument_id, Candle.timeframe == timeframe)
        if until is not None:
            q = q.where(Candle.time <= until)
        rows = db.scalars(q.order_by(Candle.time.desc()).limit(limit)).all()
        return [Bar(r.time, float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume),
                    r.quality_flag == "ok", r.quality_flag) for r in reversed(rows)]

    # ------------------------------------------------------------------ Gesundheit
    def ticker(self, symbol: str) -> Ticker | None:
        with self.lock:
            return self.tickers.get(symbol)

    def price(self, symbol: str) -> Decimal | None:
        t = self.ticker(symbol)
        return t.mid if t else None

    def health(self, symbol: str, timeframe: str | None, max_tick_age_s: float, max_candle_factor: float,
               now: datetime | None = None) -> FeedHealth:
        now = now or utcnow()
        stock = symbol in STOCK_SYMBOLS
        t = self.ticker(symbol)
        if t is None:
            if stock and not self.stocks_ready():
                return FeedHealth(False, None, None, NO_KEYS)
            return FeedHealth(False, None, None, "Noch kein Kurs empfangen")
        tick_age = (now - t.fetched_at).total_seconds()
        if stock and not sessions.tradable(now):
            return FeedHealth(False, tick_age, None, "US-Börse geschlossen – " + sessions.open_label(now))
        candle_age = None
        if timeframe:
            lc = self.last_closed.get((symbol, timeframe))
            if lc is None:
                return FeedHealth(False, tick_age, None, "Noch keine Kerzen geladen")
            # Alter der letzten abgeschlossenen Kerze ab ihrem Ende (Aktien: nur Handelszeit zählt)
            tf_s = TIMEFRAMES[timeframe].total_seconds()
            if stock:
                candle_age = sessions.session_seconds(lc + TIMEFRAMES[timeframe], now)
                tf_s = min(tf_s, 6.5 * 3600)
            else:
                candle_age = (now - (lc + TIMEFRAMES[timeframe])).total_seconds()
            if candle_age > max_candle_factor * tf_s:
                return FeedHealth(False, tick_age, candle_age, f"Letzte Kerze zu alt ({candle_age / 60:.0f} min)")
        if tick_age > max_tick_age_s:
            return FeedHealth(False, tick_age, candle_age, f"Kurs zu alt ({tick_age:.0f} s)")
        if t.bid <= 0 or t.ask <= 0 or t.ask < t.bid:
            return FeedHealth(False, tick_age, candle_age, "Kurs unplausibel (Geld/Brief)")
        return FeedHealth(True, tick_age, candle_age)

    def stocks_ready(self) -> bool:
        fn = getattr(self.source, "stocks_ready", None)
        return bool(fn and fn())

    def usable(self, symbol: str) -> bool:
        """Aktien nur abfragen, wenn Alpaca-Schlüssel vorhanden sind (sonst nur Fehlermeldungen)."""
        return symbol not in STOCK_SYMBOLS or self.stocks_ready()

    def load_state(self) -> None:
        """Nach Neustart: letzte gespeicherte Kerzen je Markt/Zeitrahmen merken."""
        with session_scope() as db:
            rows = db.execute(select(Instrument.symbol, Candle.timeframe, func.max(Candle.time)).join(Instrument)
                              .group_by(Instrument.symbol, Candle.timeframe)).all()
            for sym, tf, t in rows:
                self.last_closed[(sym, tf)] = t
