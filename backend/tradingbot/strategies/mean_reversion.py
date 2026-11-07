"""Mean Reversion: Rückkehr zum Mittelwert nach Überverkauf (Bollinger-Band + RSI)."""
from __future__ import annotations

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView
from .base import Cols, Param, Strategy, common_filters, r


class MeanReversion(Strategy):
    type_id = "mean_reversion"
    family = "mean_reversion"
    name = "Mean Reversion"
    version = "1.0"
    regimes = ("seitwaerts", "ruhig")
    description = "Kauft, wenn der Kurs unter das untere Bollinger-Band fällt und wieder zurückkehrt (RSI überverkauft); Ziel ist der Mittelwert."
    params = (
        Param("bb_period", "Bollinger-Periode", 20, 5, 100, 1),
        Param("bb_mult", "Bandbreite (× Standardabw.)", 2.0, 1, 4, 0.1),
        Param("rsi_period", "RSI-Periode", 14, 2, 50, 1),
        Param("rsi_max", "RSI höchstens (überverkauft)", 35.0, 5, 50, 1),
        Param("adx_max", "Max. ADX (kein starker Trend)", 25.0, 10, 60, 1),
        Param("atr_period", "ATR-Periode", 14, 5, 50, 1),
        Param("stop_atr", "Stop-Abstand (× ATR)", 1.5, 0.5, 6, 0.1),
        Param("take_profit_atr", "Take-Profit (× ATR, 0 = Mittelwert)", 0.0, 0, 15, 0.5),
        Param("trailing", "Stop nachziehen (Trailing)", False),
        Param("trailing_atr", "Trailing-Abstand (× ATR)", 2.0, 0.5, 6, 0.1),
        Param("min_volume_factor", "Mindestvolumen (× Ø 20)", 0.0, 0, 3, 0.1),
        Param("atr_pct_min", "ATR mindestens (% vom Kurs)", 0.1, 0, 10, 0.05),
        Param("atr_pct_max", "ATR höchstens (% vom Kurs)", 6.0, 0.5, 30, 0.5),
    )

    def warmup(self, p):
        return int(max(p["bb_period"], p["rsi_period"] + 1, 2 * 14 + 2, p["atr_period"] + 1))

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        c = Cols(bars)
        i = len(bars) - 1
        lo, mid, up = ind.bollinger(c.c, int(p["bb_period"]), p["bb_mult"])
        rs = ind.rsi(c.c, int(p["rsi_period"]))
        ax, _, _ = ind.adx(c.h, c.l, c.c, 14)
        a = ind.atr(c.h, c.l, c.c, int(p["atr_period"]))[i]
        info = {"kurs": r(c.c[i]), "band_unten": r(lo[i]), "mittelwert": r(mid[i]), "band_oben": r(up[i]),
                "rsi": r(rs[i], 2), "adx": r(ax[i], 1), "atr": r(a)}
        if position is not None:
            if mid[i] is not None and c.c[i] >= mid[i] and not p["take_profit_atr"]:
                return Decision("verkauf", 1.0, reasoning={**info, "grund": "Mittelwert erreicht"})
            if up[i] is not None and c.c[i] >= up[i]:
                return Decision("verkauf", 1.0, reasoning={**info, "grund": "Oberes Band erreicht"})
            return Decision("halten", reasoning={**info, "grund": "Rückkehr zum Mittelwert läuft"})
        if None in (lo[i], lo[i - 1], rs[i], ax[i], a):
            return Decision("halten", reasoning={**info, "grund": "Indikatoren noch nicht bereit"})
        if not (c.c[i - 1] < lo[i - 1] and c.c[i] > lo[i]):
            return Decision("halten", reasoning={**info, "grund": "Keine Rückkehr ins Band nach Überverkauf"})
        if rs[i] > p["rsi_max"] + 10 or ax[i] > p["adx_max"]:
            return Decision("halten", reasoning={**info, "grund": "RSI nicht überverkauft oder Trend zu stark"})
        ok, finfo = common_filters(c, i, p, a)
        info.update(finfo)
        if not ok:
            return Decision("halten", reasoning={**info, "grund": "Filter nicht erfüllt"})
        stop = min(c.l[i], c.l[i - 1]) - p["stop_atr"] * a
        tp = c.c[i] + p["take_profit_atr"] * a if p["take_profit_atr"] else mid[i]
        return Decision("kauf", 0.6, stop=stop, take_profit=tp,
                        trailing_atr_mult=p["trailing_atr"] if p["trailing"] else None,
                        reasoning={**info, "grund": "Rückkehr ins Bollinger-Band nach Überverkauf, kein starker Trend",
                                   "stop_regel": f"Tief − {p['stop_atr']}× ATR", "ziel": "Mittelwert"})
