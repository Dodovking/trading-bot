"""Datenqualitätsprüfung (FA-02): Lücken, Duplikate, Ausreißer, Null- und Inkonsistenzwerte."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from statistics import median

from .sources import RawCandle


@dataclass
class QualityReport:
    flags: dict = field(default_factory=dict)  # time -> flag
    duplicates: int = 0
    gaps: list = field(default_factory=list)  # [(von, bis)]

    @property
    def problems(self) -> int:
        return len(self.flags) + self.duplicates + len(self.gaps)


def check_candles(candles: list[RawCandle], timeframe: timedelta, previous: list[RawCandle] | None = None,
                  outlier_factor: float = 12.0, outlier_min_pct: float = 8.0) -> tuple[list[RawCandle], QualityReport]:
    """Sortiert, entfernt Duplikate und markiert fehlerhafte Kerzen (Rückgabe: bereinigt + Bericht)."""
    rep = QualityReport()
    seen: dict = {}
    for c in candles:
        if c.time in seen:
            rep.duplicates += 1
            if seen[c.time] != c:
                rep.flags[c.time] = "doppelt_abweichend"
            continue
        seen[c.time] = c
    rows = sorted(seen.values(), key=lambda c: c.time)
    hist = list(previous or [])[-200:]
    returns = [abs(float(b.close / a.close - 1)) for a, b in zip(hist, hist[1:]) if a.close > 0]
    for idx, c in enumerate(rows):
        if any(v is None for v in (c.open, c.high, c.low, c.close, c.volume)) or min(c.open, c.high, c.low, c.close) <= 0:
            rep.flags[c.time] = "nullwert"
            continue
        if c.volume < 0 or c.high < max(c.open, c.close) or c.low > min(c.open, c.close) or c.high < c.low:
            rep.flags[c.time] = "inkonsistent"
            continue
        prev = rows[idx - 1] if idx > 0 else (hist[-1] if hist else None)
        if prev is not None:
            gap = c.time - prev.time
            if gap > timeframe:
                rep.gaps.append((prev.time, c.time))
            if prev.close > 0 and len(returns) >= 30:
                ret = abs(float(c.close / prev.close - 1))
                med = median(returns[-100:]) or 1e-9
                if ret * 100 > outlier_min_pct and ret > outlier_factor * med:
                    rep.flags[c.time] = "ausreisser"
            if prev.close > 0:
                returns.append(abs(float(c.close / prev.close - 1)))
    return rows, rep


def round_step(value: Decimal, step: Decimal) -> Decimal:
    """Auf erlaubte Schrittgröße abrunden."""
    if step <= 0:
        return value
    return (value // step) * step


def round_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        return value
    return ((value / tick).quantize(Decimal(1)) * tick).normalize()
