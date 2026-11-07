"""Momentum: Kauft Märkte mit starker, anhaltender jüngster Entwicklung (Rate of Change)."""
from __future__ import annotations

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView
from .base import Cols, Param, Strategy, common_filters, r


class Momentum(Strategy):
    type_id = "momentum"
    family = "momentum"
    name = "Momentum"
    version = "1.0"
    regimes = ("trend_auf",)
    description = "Kauft bei starker Kursentwicklung (Rate of Change über Schwelle) mit bestätigendem ADX; Ausstieg, wenn das Momentum dreht."
    params = (
        Param("roc_period", "Momentum-Zeitraum (Kerzen)", 24, 5, 200, 1),
        Param("roc_entry", "Einstieg ab (% Anstieg)", 4.0, 0.5, 50, 0.5),
        Param("roc_exit", "Ausstieg unter (%)", 0.0, -20, 20, 0.5),
        Param("adx_min", "Mindest-ADX (Trendstärke)", 20.0, 0, 60, 1),
        Param("ema_trend", "Trendfilter (EMA)", 100, 20, 400, 1),
        Param("atr_period", "ATR-Periode", 14, 5, 50, 1),
        Param("stop_atr", "Stop-Abstand (× ATR)", 2.5, 0.5, 6, 0.1),
        Param("take_profit_atr", "Take-Profit (× ATR, 0 = aus)", 0.0, 0, 15, 0.5),
        Param("trailing", "Stop nachziehen (Trailing)", True),
        Param("trailing_atr", "Trailing-Abstand (× ATR)", 3.0, 0.5, 6, 0.1),
        Param("min_volume_factor", "Mindestvolumen (× Ø 20)", 0.0, 0, 3, 0.1),
        Param("atr_pct_min", "ATR mindestens (% vom Kurs)", 0.1, 0, 10, 0.05),
        Param("atr_pct_max", "ATR höchstens (% vom Kurs)", 8.0, 0.5, 30, 0.5),
    )

    def warmup(self, p):
        return int(max(p["roc_period"] + 1, p["ema_trend"], 2 * p["atr_period"] + 2, 30))

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        c = Cols(bars)
        i = len(bars) - 1
        mom = ind.roc(c.c, int(p["roc_period"]))
        trend = ind.ema(c.c, int(p["ema_trend"]))
        ax, pdi, mdi = ind.adx(c.h, c.l, c.c, 14)
        a = ind.atr(c.h, c.l, c.c, int(p["atr_period"]))[i]
        info = {"kurs": r(c.c[i]), "momentum_prozent": r(mom[i], 2), "momentum_vorher": r(mom[i - 1], 2),
                f"ema{p['ema_trend']}": r(trend[i]), "adx": r(ax[i], 1), "plus_di": r(pdi[i], 1), "minus_di": r(mdi[i], 1),
                "atr": r(a)}
        if position is not None:
            if mom[i] is not None and mom[i] < p["roc_exit"]:
                return Decision("verkauf", 1.0, reasoning={**info, "grund": f"Momentum {mom[i]:.1f} % unter {p['roc_exit']:.1f} %"})
            return Decision("halten", reasoning={**info, "grund": "Momentum hält an"})
        if None in (mom[i], mom[i - 1], trend[i], ax[i], a):
            return Decision("halten", reasoning={**info, "grund": "Indikatoren noch nicht bereit"})
        if not (mom[i - 1] < p["roc_entry"] <= mom[i]):
            return Decision("halten", reasoning={**info, "grund": f"Momentum nicht frisch über {p['roc_entry']:.1f} %"})
        if c.c[i] <= trend[i] or ax[i] < p["adx_min"] or pdi[i] <= mdi[i]:
            return Decision("halten", reasoning={**info, "grund": "Trendbestätigung fehlt (EMA/ADX/DI)"})
        ok, finfo = common_filters(c, i, p, a)
        info.update(finfo)
        if not ok:
            return Decision("halten", reasoning={**info, "grund": "Filter nicht erfüllt"})
        stop = c.c[i] - p["stop_atr"] * a
        tp = c.c[i] + p["take_profit_atr"] * a if p["take_profit_atr"] else None
        return Decision("kauf", min(1.0, mom[i] / (2 * p["roc_entry"])), stop=stop, take_profit=tp,
                        trailing_atr_mult=p["trailing_atr"] if p["trailing"] else None,
                        reasoning={**info, "grund": f"Momentum {mom[i]:.1f} % ≥ {p['roc_entry']:.1f} %, ADX {ax[i]:.0f}, Kurs über Trend",
                                   "stop_regel": f"Kurs − {p['stop_atr']}× ATR"})
