"""Rücksetzer: Kauf nach kurzer Korrektur im Aufwärtstrend (RSI erholt sich)."""
from __future__ import annotations

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView
from .base import Cols, Param, Strategy, common_filters, r


class Pullback(Strategy):
    type_id = "ruecksetzer"
    family = "swing"
    regimes = ("trend_auf",)
    name = "Swing (Rücksetzer)"
    version = "1.0"
    description = "Kauft nach kurzen Korrekturen im Aufwärtstrend: RSI steigt wieder über die Einstiegsschwelle, Kurs über EMA 200."
    params = (
        Param("ema_trend", "Trendfilter (EMA)", 200, 50, 400, 1),
        Param("ema_mid", "Mittlerer Durchschnitt (EMA)", 50, 10, 200, 1),
        Param("rsi_period", "RSI-Periode", 14, 2, 50, 1),
        Param("rsi_entry", "RSI-Einstiegsschwelle", 35.0, 5, 50, 1),
        Param("rsi_exit", "RSI-Ausstieg (überkauft)", 70.0, 50, 95, 1),
        Param("atr_period", "ATR-Periode", 14, 5, 50, 1),
        Param("stop_atr", "Stop-Abstand (× ATR)", 2.0, 0.5, 6, 0.1),
        Param("take_profit_atr", "Take-Profit (× ATR, 0 = aus)", 3.0, 0, 15, 0.5),
        Param("trailing", "Stop nachziehen (Trailing)", False),
        Param("trailing_atr", "Trailing-Abstand (× ATR)", 2.5, 0.5, 6, 0.1),
        Param("min_volume_factor", "Mindestvolumen (× Ø 20)", 0.0, 0, 3, 0.1),
        Param("atr_pct_min", "ATR mindestens (% vom Kurs)", 0.1, 0, 10, 0.05),
        Param("atr_pct_max", "ATR höchstens (% vom Kurs)", 8.0, 0.5, 30, 0.5),
    )

    def warmup(self, p):
        return int(max(p["ema_trend"], p["rsi_period"] + 1, p["atr_period"] + 1))

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        c = Cols(bars)
        i = len(bars) - 1
        trend = ind.ema(c.c, int(p["ema_trend"]))
        mid = ind.ema(c.c, int(p["ema_mid"]))
        rs = ind.rsi(c.c, int(p["rsi_period"]))
        a = ind.atr(c.h, c.l, c.c, int(p["atr_period"]))[i]
        info = {"kurs": r(c.c[i]), f"ema{p['ema_trend']}": r(trend[i]), f"ema{p['ema_mid']}": r(mid[i]),
                "rsi": r(rs[i], 2), "rsi_vorher": r(rs[i - 1], 2), "atr": r(a)}
        if position is not None:
            if rs[i] is not None and rs[i] >= p["rsi_exit"]:
                return Decision("verkauf", 1.0, reasoning={**info, "grund": f"RSI {rs[i]:.1f} ≥ {p['rsi_exit']:.0f} (überkauft)"})
            if trend[i] is not None and c.c[i] < trend[i]:
                return Decision("verkauf", 0.8, reasoning={**info, "grund": "Kurs unter Trendfilter gefallen"})
            return Decision("halten", reasoning={**info, "grund": "Position offen, kein Ausstiegssignal"})
        if trend[i] is None or mid[i] is None or rs[i] is None or rs[i - 1] is None:
            return Decision("halten", reasoning={**info, "grund": "Indikatoren noch nicht bereit"})
        if not (c.c[i] > trend[i] and mid[i] > trend[i]):
            return Decision("halten", reasoning={**info, "grund": "Kein Aufwärtstrend"})
        if not (rs[i - 1] < p["rsi_entry"] <= rs[i]):
            return Decision("halten", reasoning={**info, "grund": "Keine Erholung aus der Korrektur"})
        ok, finfo = common_filters(c, i, p, a)
        info.update(finfo)
        if not ok or a is None:
            return Decision("halten", reasoning={**info, "grund": "Filter nicht erfüllt"})
        stop = c.c[i] - p["stop_atr"] * a
        tp = c.c[i] + p["take_profit_atr"] * a if p["take_profit_atr"] else None
        return Decision(
            "kauf", 0.6, stop=stop, take_profit=tp,
            trailing_atr_mult=p["trailing_atr"] if p["trailing"] else None,
            reasoning={**info, "grund": f"Aufwärtstrend, RSI steigt über {p['rsi_entry']:.0f} (Korrektur beendet)",
                       "stop_regel": f"Kurs − {p['stop_atr']}× ATR"},
        )
