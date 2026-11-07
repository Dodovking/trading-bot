"""Range-Handel: Kauf am unteren Rand einer stabilen Seitwärtsspanne, Verkauf am oberen Rand.

Long-only-Variante des Range-/Grid-Trading (kein Leerverkauf). Bricht der Kurs aus der Spanne
nach unten aus, greift der Stop unter der Spanne.
"""
from __future__ import annotations

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView
from .base import Cols, Param, Strategy, common_filters, r


class RangeTrading(Strategy):
    type_id = "range"
    family = "range_grid"
    name = "Range-Handel"
    version = "1.0"
    regimes = ("seitwaerts",)
    description = "Erkennt eine stabile Spanne (niedriger ADX) und kauft im unteren Viertel; Ziel ist der obere Rand, Stop unter der Spanne."
    params = (
        Param("lookback", "Spanne über (Kerzen)", 48, 10, 300, 1),
        Param("max_width_pct", "Max. Spannenbreite (%)", 8.0, 1, 40, 0.5),
        Param("min_width_pct", "Min. Spannenbreite (%)", 2.0, 0.3, 20, 0.1),
        Param("entry_zone", "Einstiegszone (unterer Anteil)", 0.25, 0.05, 0.5, 0.05),
        Param("exit_zone", "Ausstiegszone (oberer Anteil)", 0.2, 0.05, 0.5, 0.05),
        Param("adx_max", "Max. ADX", 20.0, 5, 50, 1),
        Param("stop_buffer_atr", "Stop unter Spanne (× ATR)", 1.0, 0.2, 5, 0.1),
        Param("atr_period", "ATR-Periode", 14, 5, 50, 1),
        Param("trailing", "Stop nachziehen (Trailing)", False),
        Param("trailing_atr", "Trailing-Abstand (× ATR)", 2.0, 0.5, 6, 0.1),
        Param("min_volume_factor", "Mindestvolumen (× Ø 20)", 0.0, 0, 3, 0.1),
        Param("atr_pct_min", "ATR mindestens (% vom Kurs)", 0.05, 0, 10, 0.05),
        Param("atr_pct_max", "ATR höchstens (% vom Kurs)", 5.0, 0.5, 30, 0.5),
    )

    def warmup(self, p):
        return int(max(p["lookback"] + 1, 30, p["atr_period"] + 1))

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        c = Cols(bars)
        i = len(bars) - 1
        n = int(p["lookback"])
        hi = max(c.h[i - n:i])
        lo = min(c.l[i - n:i])
        width = (hi - lo) / lo * 100 if lo else 0
        ax, _, _ = ind.adx(c.h, c.l, c.c, 14)
        a = ind.atr(c.h, c.l, c.c, int(p["atr_period"]))[i]
        pos_in_range = (c.c[i] - lo) / (hi - lo) if hi > lo else 0.5
        info = {"kurs": r(c.c[i]), "spanne_hoch": r(hi), "spanne_tief": r(lo), "spannenbreite_prozent": r(width, 2),
                "lage_in_spanne": r(pos_in_range, 3), "adx": r(ax[i], 1), "atr": r(a)}
        if position is not None:
            if pos_in_range >= 1 - p["exit_zone"]:
                return Decision("verkauf", 1.0, reasoning={**info, "grund": "Oberer Rand der Spanne erreicht"})
            return Decision("halten", reasoning={**info, "grund": "Innerhalb der Spanne"})
        if None in (ax[i], a):
            return Decision("halten", reasoning={**info, "grund": "Indikatoren noch nicht bereit"})
        if not (p["min_width_pct"] <= width <= p["max_width_pct"]) or ax[i] > p["adx_max"]:
            return Decision("halten", reasoning={**info, "grund": "Keine stabile Seitwärtsspanne"})
        if not (0 <= pos_in_range <= p["entry_zone"]) or c.c[i] <= c.c[i - 1]:
            return Decision("halten", reasoning={**info, "grund": "Kurs nicht im unteren Bereich oder fällt noch"})
        ok, finfo = common_filters(c, i, p, a)
        info.update(finfo)
        if not ok:
            return Decision("halten", reasoning={**info, "grund": "Filter nicht erfüllt"})
        stop = lo - p["stop_buffer_atr"] * a
        tp = hi - (hi - lo) * p["exit_zone"]
        return Decision("kauf", 0.5, stop=stop, take_profit=tp,
                        trailing_atr_mult=p["trailing_atr"] if p["trailing"] else None,
                        reasoning={**info, "grund": f"Stabile Spanne {width:.1f} %, Kurs im unteren Bereich und dreht",
                                   "stop_regel": f"Spannentief − {p['stop_buffer_atr']}× ATR"})
