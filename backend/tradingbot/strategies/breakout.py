"""Ausbruch: Kauf beim Ausbruch über das Hoch der letzten N Kerzen (Donchian) mit Volumen."""
from __future__ import annotations

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView
from .base import Cols, Param, Strategy, common_filters, r


class Breakout(Strategy):
    type_id = "ausbruch"
    family = "ausbruch"
    regimes = ("ruhig", "trend_auf")
    name = "Ausbruch"
    version = "1.0"
    description = "Handelt Ausbrüche aus Kursspannen: Schluss über dem Hoch der letzten 20 Kerzen bei erhöhtem Volumen."
    params = (
        Param("channel", "Ausbruchskanal (Kerzen)", 20, 5, 100, 1),
        Param("exit_channel", "Ausstiegskanal (Kerzen)", 10, 3, 60, 1),
        Param("volume_factor", "Volumen mindestens (× Ø 20)", 1.5, 0, 5, 0.1),
        Param("use_trend_filter", "Nur über Trendfilter", True),
        Param("ema_trend", "Trendfilter (EMA)", 200, 50, 400, 1),
        Param("atr_period", "ATR-Periode", 14, 5, 50, 1),
        Param("stop_atr", "Stop-Abstand (× ATR)", 2.0, 0.5, 6, 0.1),
        Param("trailing", "Stop nachziehen (Trailing)", True),
        Param("trailing_atr", "Trailing-Abstand (× ATR)", 3.0, 0.5, 6, 0.1),
        Param("atr_pct_min", "ATR mindestens (% vom Kurs)", 0.1, 0, 10, 0.05),
        Param("atr_pct_max", "ATR höchstens (% vom Kurs)", 8.0, 0.5, 30, 0.5),
    )

    def warmup(self, p):
        return int(max(p["ema_trend"] if p["use_trend_filter"] else 0, p["channel"] + 1, p["atr_period"] + 1, 21))

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        c = Cols(bars)
        i = len(bars) - 1
        n, m = int(p["channel"]), int(p["exit_channel"])
        prev_high = max(c.h[i - n : i])
        prev_low = min(c.l[i - m : i])
        a = ind.atr(c.h, c.l, c.c, int(p["atr_period"]))[i]
        trend = ind.ema(c.c, int(p["ema_trend"]))[i]
        avg_vol = ind.sma(c.v, 20)[i]
        info = {"kurs": r(c.c[i]), f"hoch{n}": r(prev_high), f"tief{m}": r(prev_low), "atr": r(a),
                f"ema{p['ema_trend']}": r(trend), "volumen": r(c.v[i], 4), "volumen_schnitt20": r(avg_vol, 4)}
        if position is not None:
            if c.c[i] < prev_low:
                return Decision("verkauf", 1.0, reasoning={**info, "grund": f"Schluss unter dem Tief der letzten {m} Kerzen"})
            return Decision("halten", reasoning={**info, "grund": "Position offen, kein Ausstiegssignal"})
        if c.c[i] <= prev_high:
            return Decision("halten", reasoning={**info, "grund": "Kein Ausbruch"})
        if p["use_trend_filter"] and (trend is None or c.c[i] <= trend):
            return Decision("halten", reasoning={**info, "grund": "Ausbruch unter Trendfilter"})
        if p["volume_factor"] and avg_vol is not None and c.v[i] < p["volume_factor"] * avg_vol:
            return Decision("halten", reasoning={**info, "grund": "Ausbruch ohne Volumen"})
        ok, finfo = common_filters(c, i, {**p, "min_volume_factor": 0}, a)
        info.update(finfo)
        if not ok or a is None:
            return Decision("halten", reasoning={**info, "grund": "Filter nicht erfüllt"})
        stop = c.c[i] - p["stop_atr"] * a
        strength = min(1.0, (c.c[i] - prev_high) / a) if a else 0.5
        return Decision(
            "kauf", round(max(0.1, strength), 3), stop=stop,
            trailing_atr_mult=p["trailing_atr"] if p["trailing"] else None,
            reasoning={**info, "grund": f"Schluss über dem Hoch der letzten {n} Kerzen mit Volumen",
                       "stop_regel": f"Kurs − {p['stop_atr']}× ATR"},
        )
