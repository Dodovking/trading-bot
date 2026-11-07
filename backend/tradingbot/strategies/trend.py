"""Referenzstrategie (Abschnitt 6): Trendfolge mit EMA-Kreuzung, nur Long."""
from __future__ import annotations

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView
from .base import Cols, Param, Strategy, common_filters, r


class TrendFollowing(Strategy):
    type_id = "trendfolge"
    family = "trendfolge"
    regimes = ("trend_auf",)
    name = "Trendfolge"
    version = "1.0"
    description = "Folgt starken Kursbewegungen: EMA 20 kreuzt EMA 50 von unten, Kurs über EMA 200. Stop 2× ATR, nachgezogen."
    params = (
        Param("ema_fast", "Schneller Durchschnitt (EMA)", 20, 5, 100, 1),
        Param("ema_slow", "Langsamer Durchschnitt (EMA)", 50, 10, 200, 1),
        Param("ema_trend", "Trendfilter (EMA)", 200, 50, 400, 1),
        Param("atr_period", "ATR-Periode", 14, 5, 50, 1),
        Param("stop_atr", "Stop-Abstand (× ATR)", 2.0, 0.5, 6, 0.1),
        Param("trailing", "Stop nachziehen (Trailing)", True),
        Param("trailing_atr", "Trailing-Abstand (× ATR)", 2.0, 0.5, 6, 0.1),
        Param("take_profit_r", "Take-Profit (× Risiko, 0 = aus)", 0.0, 0, 10, 0.5),
        Param("min_volume_factor", "Mindestvolumen (× Ø 20)", 0.0, 0, 3, 0.1),
        Param("atr_pct_min", "ATR mindestens (% vom Kurs)", 0.1, 0, 10, 0.05),
        Param("atr_pct_max", "ATR höchstens (% vom Kurs)", 8.0, 0.5, 30, 0.5),
    )

    def warmup(self, p):
        return int(max(p["ema_trend"], p["ema_slow"], p["atr_period"] + 1))

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        c = Cols(bars)
        i = len(bars) - 1
        fast = ind.ema(c.c, int(p["ema_fast"]))
        slow = ind.ema(c.c, int(p["ema_slow"]))
        trend = ind.ema(c.c, int(p["ema_trend"]))
        a = ind.atr(c.h, c.l, c.c, int(p["atr_period"]))[i]
        info = {
            "kurs": r(c.c[i]), f"ema{p['ema_fast']}": r(fast[i]), f"ema{p['ema_slow']}": r(slow[i]),
            f"ema{p['ema_trend']}": r(trend[i]), "atr": r(a), "trend": ind.trend_direction(c.c, fast, slow, i),
        }
        if position is not None:
            if ind.crossed_below(fast, slow, i):
                return Decision("verkauf", 1.0, reasoning={**info, "grund": "Gegenkreuzung: schneller EMA unter langsamen"})
            return Decision("halten", reasoning={**info, "grund": "Position offen, kein Ausstiegssignal"})
        if not ind.crossed_above(fast, slow, i):
            return Decision("halten", reasoning={**info, "grund": "Keine Aufwärtskreuzung"})
        if trend[i] is None or c.c[i] <= trend[i]:
            return Decision("halten", reasoning={**info, "grund": "Kurs nicht über Trendfilter"})
        ok, finfo = common_filters(c, i, p, a)
        info.update(finfo)
        if not ok or a is None:
            return Decision("halten", reasoning={**info, "grund": "Filter nicht erfüllt"})
        stop = c.c[i] - p["stop_atr"] * a
        tp = c.c[i] + p["take_profit_r"] * (c.c[i] - stop) if p["take_profit_r"] else None
        strength = min(1.0, (c.c[i] - trend[i]) / (3 * a)) if a else 0.5
        return Decision(
            "kauf", round(max(0.1, strength), 3), stop=stop, take_profit=tp,
            trailing_atr_mult=p["trailing_atr"] if p["trailing"] else None,
            reasoning={**info, "grund": f"EMA {p['ema_fast']} kreuzt EMA {p['ema_slow']} von unten, Kurs über EMA {p['ema_trend']}",
                       "stop_regel": f"Kurs − {p['stop_atr']}× ATR"},
        )
