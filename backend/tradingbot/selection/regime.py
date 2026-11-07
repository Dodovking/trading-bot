"""Marktregime-Erkennung (FA-16, Abschnitt 6.2): Trend, Seitwärts, hohe Volatilität, ruhig vor Ausbruch, unklar."""
from __future__ import annotations

from typing import Sequence

from ..analysis import indicators as ind
from ..core.types import Bar

REGIMES = {
    "trend_auf": "Aufwärtstrend",
    "trend_ab": "Abwärtstrend",
    "seitwaerts": "Seitwärts",
    "hohe_volatilitaet": "Hohe Volatilität",
    "ruhig": "Ruhig vor Ausbruch",
    "unklar": "Unklar / Übergang",
}
# Abwärtstrend: passende Strategien bräuchten Leerverkäufe → bei long-only „keine Strategie“.
REGIME_HINT = {
    "trend_auf": "Trendfolge, Momentum, Swing",
    "trend_ab": "Long-only: außerhalb des Marktes bleiben",
    "seitwaerts": "Mean Reversion, Range",
    "hohe_volatilitaet": "Positionsgrößen halbiert, nur bewährte Strategien",
    "ruhig": "Ausbruch vorbereiten, Mean Reversion vorsichtig",
    "unklar": "Keine neuen Positionen",
}


def classify(bars: Sequence[Bar], adx_trend: float = 25, adx_range: float = 20, vol_factor: float = 1.8) -> tuple[str, dict]:
    if len(bars) < 220:
        return "unklar", {"grund": f"Zu wenig Kerzen ({len(bars)} von 220)"}
    h = [b.high for b in bars]
    lo = [b.low for b in bars]
    c = [b.close for b in bars]
    i = len(c) - 1
    ax, pdi, mdi = ind.adx(h, lo, c, 14)
    ema200 = ind.ema(c, 200)
    a = ind.atr(h, lo, c, 14)
    bw = ind.bandwidth(c, 20, 2.0)
    atr_hist = [x for x in a[-100:] if x is not None]
    atr_norm = sorted(atr_hist)[len(atr_hist) // 2] if atr_hist else None
    atr_ratio = a[i] / atr_norm if a[i] and atr_norm else None
    bw_hist = sorted(x for x in bw[-120:] if x is not None)
    bw_rank = (sum(1 for x in bw_hist if x <= bw[i]) / len(bw_hist)) if bw_hist and bw[i] is not None else None
    slope = (ema200[i] / ema200[i - 20] - 1) * 100 if ema200[i] and ema200[i - 20] else None
    gap = max(abs(b.open - p.close) / p.close * 100 for p, b in zip(bars[-20:], bars[-19:]))
    v = {"adx": round(ax[i], 1) if ax[i] else None, "plus_di": round(pdi[i], 1) if pdi[i] else None,
         "minus_di": round(mdi[i], 1) if mdi[i] else None, "ema200_steigung_prozent": round(slope, 2) if slope is not None else None,
         "kurs_ueber_ema200": bool(ema200[i] and c[i] > ema200[i]), "atr_verhaeltnis": round(atr_ratio, 2) if atr_ratio else None,
         "bollinger_breite_rang": round(bw_rank, 2) if bw_rank is not None else None, "max_kursluecke_prozent": round(gap, 2)}
    if None in (ax[i], ema200[i], atr_ratio, bw_rank, slope):
        return "unklar", {**v, "grund": "Indikatoren nicht bereit"}
    if atr_ratio >= vol_factor or gap > 5:
        return "hohe_volatilitaet", {**v, "grund": f"ATR {atr_ratio:.1f}× über Normal" if atr_ratio >= vol_factor else "Große Kurslücke"}
    if ax[i] >= adx_trend:
        if c[i] > ema200[i] and slope > 0 and pdi[i] > mdi[i]:
            return "trend_auf", {**v, "grund": f"ADX {ax[i]:.0f}, Kurs über steigendem EMA 200"}
        if c[i] < ema200[i] and slope < 0 and mdi[i] > pdi[i]:
            return "trend_ab", {**v, "grund": f"ADX {ax[i]:.0f}, Kurs unter fallendem EMA 200"}
        return "unklar", {**v, "grund": "Starker ADX, aber Richtung widersprüchlich"}
    if ax[i] < adx_range:
        if bw_rank <= 0.15 and atr_ratio < 0.9:
            return "ruhig", {**v, "grund": "Bollinger-Squeeze, niedrige ATR"}
        return "seitwaerts", {**v, "grund": f"ADX {ax[i]:.0f} niedrig, Kurs pendelt"}
    return "unklar", {**v, "grund": f"ADX {ax[i]:.0f} im Übergangsbereich"}
