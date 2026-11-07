"""Indikatoren als reine Funktionen (gegen Referenzwerte getestet).

Rückgabe: Liste gleicher Länge wie die Eingabe, None solange zu wenig Daten vorliegen.
"""
from __future__ import annotations

from typing import Sequence

Series = list[float | None]


def sma(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    if period <= 0:
        return out
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= period:
            acc -= values[i - period]
        if i >= period - 1:
            out[i] = acc / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """EMA mit SMA-Startwert (wie TA-Lib)."""
    out: Series = [None] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    tr = []
    for i in range(len(closes)):
        if i == 0:
            tr.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            tr.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return tr


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> Series:
    """Average True Range nach Wilder (TA-Lib-kompatibel: Start bei Index `period`)."""
    n = len(closes)
    out: Series = [None] * n
    if n <= period:
        return out
    tr = true_range(highs, lows, closes)
    prev = sum(tr[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> Series:
    """Relative Strength Index nach Wilder."""
    n = len(closes)
    out: Series = [None] * n
    if n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / period, losses / period

    def val(g: float, lo: float) -> float:
        if lo == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / lo)

    out[period] = val(ag, al)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + max(-d, 0)) / period
        out[i] = val(ag, al)
    return out


def highest(values: Sequence[float], period: int) -> Series:
    """Höchstwert der letzten `period` Werte inkl. aktuellem."""
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = max(values[i - period + 1 : i + 1])
    return out


def lowest(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = min(values[i - period + 1 : i + 1])
    return out


def crossed_above(fast: Series, slow: Series, i: int) -> bool:
    if i < 1 or None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
        return False
    return fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]  # type: ignore[operator]


def crossed_below(fast: Series, slow: Series, i: int) -> bool:
    if i < 1 or None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
        return False
    return fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]  # type: ignore[operator]


def trend_direction(closes: Sequence[float], ema_fast: Series, ema_slow: Series, i: int) -> str:
    """Einfache Trendbestimmung (FA-03)."""
    f, s = ema_fast[i], ema_slow[i]
    if f is None or s is None:
        return "unklar"
    if f > s and closes[i] > s:
        return "aufwärts"
    if f < s and closes[i] < s:
        return "abwärts"
    return "seitwärts"


def support_resistance(highs: Sequence[float], lows: Sequence[float], close: float, lookback: int = 100, width: int = 3):
    """Nächste Unterstützung unter / Widerstand über dem Kurs aus lokalen Extrempunkten (FA-03)."""
    n = len(highs)
    start = max(width, n - lookback)
    res, sup = [], []
    for i in range(start, n - width):
        if highs[i] == max(highs[i - width : i + width + 1]) and highs[i] > close:
            res.append(highs[i])
        if lows[i] == min(lows[i - width : i + width + 1]) and lows[i] < close:
            sup.append(lows[i])
    return (max(sup) if sup else None), (min(res) if res else None)


def stdev(values: Sequence[float], period: int) -> Series:
    """Standardabweichung (Grundgesamtheit) über `period` Werte."""
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        w = values[i - period + 1:i + 1]
        m = sum(w) / period
        out[i] = (sum((x - m) ** 2 for x in w) / period) ** 0.5
    return out


def bollinger(values: Sequence[float], period: int = 20, mult: float = 2.0) -> tuple[Series, Series, Series]:
    mid = sma(values, period)
    sd = stdev(values, period)
    up = [None if m is None else m + mult * s for m, s in zip(mid, sd)]
    lo = [None if m is None else m - mult * s for m, s in zip(mid, sd)]
    return lo, mid, up


def bandwidth(values: Sequence[float], period: int = 20, mult: float = 2.0) -> Series:
    lo, mid, up = bollinger(values, period, mult)
    return [None if m in (None, 0) else (u - l) / m * 100 for l, m, u in zip(lo, mid, up)]


def zscore(values: Sequence[float], period: int = 20) -> Series:
    mid = sma(values, period)
    sd = stdev(values, period)
    return [None if m is None or not s else (v - m) / s for v, m, s in zip(values, mid, sd)]


def roc(values: Sequence[float], period: int) -> Series:
    """Rate of Change in Prozent."""
    out: Series = [None] * len(values)
    for i in range(period, len(values)):
        if values[i - period]:
            out[i] = (values[i] / values[i - period] - 1) * 100
    return out


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> tuple[Series, Series, Series]:
    """ADX, +DI, −DI nach Wilder."""
    n = len(closes)
    adx_out: Series = [None] * n
    pdi: Series = [None] * n
    mdi: Series = [None] * n
    if n < 2 * period + 1:
        return adx_out, pdi, mdi
    tr = true_range(highs, lows, closes)
    pdm = [0.0] * n
    mdm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
    atr_s = sum(tr[1:period + 1])
    p_s = sum(pdm[1:period + 1])
    m_s = sum(mdm[1:period + 1])
    dx: list[float] = []
    for i in range(period, n):
        if i > period:
            atr_s = atr_s - atr_s / period + tr[i]
            p_s = p_s - p_s / period + pdm[i]
            m_s = m_s - m_s / period + mdm[i]
        pd_ = 100 * p_s / atr_s if atr_s else 0.0
        md_ = 100 * m_s / atr_s if atr_s else 0.0
        pdi[i], mdi[i] = pd_, md_
        dx.append(100 * abs(pd_ - md_) / (pd_ + md_) if pd_ + md_ else 0.0)
        k = len(dx)
        if k == period:
            adx_out[i] = sum(dx) / period
        elif k > period:
            adx_out[i] = (adx_out[i - 1] * (period - 1) + dx[-1]) / period
    return adx_out, pdi, mdi
