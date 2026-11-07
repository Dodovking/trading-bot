"""Strategie-Schnittstelle. Strategien sind rein funktional (FA-14):
gleiche Kerzen + gleiche Parameter => gleiches Signal. Ausgewertet wird immer
die letzte *abgeschlossene* Kerze; ausgeführt wird frühestens danach.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Sequence

from ..analysis import indicators as ind
from ..core.types import Bar, Decision, PositionView


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float | int | bool
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(float(x), nd)


class Strategy:
    type_id: str = ""
    family: str = ""
    regimes: tuple[str, ...] = ()  # Marktregime, zu denen die Strategie typischerweise passt
    name: str = ""
    version: str = "1.0"
    description: str = ""
    params: tuple[Param, ...] = ()

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params}

    def clean_params(self, params: dict | None) -> dict[str, Any]:
        out = self.defaults()
        for p in self.params:
            if params and p.key in params:
                v = params[p.key]
                if isinstance(p.default, bool):
                    v = bool(v)
                else:
                    v = float(v)
                    if p.min is not None:
                        v = max(p.min, v)
                    if p.max is not None:
                        v = min(p.max, v)
                    if isinstance(p.default, int):
                        v = int(round(v))
                out[p.key] = v
        return out

    def warmup(self, params: dict) -> int:
        return 50

    # --- öffentliche API -------------------------------------------------
    def evaluate(self, bars: Sequence[Bar], position: PositionView | None, params: dict | None,
                 timeframe: timedelta | None = None) -> Decision:
        p = self.clean_params(params)
        need = self.warmup(p) + 2
        if len(bars) < need:
            return Decision("halten", reasoning={"grund": f"Zu wenig Kerzen ({len(bars)} von {need})"})
        window = bars[-need:]
        gap = _data_problem(window, timeframe)
        if gap and position is None:
            return Decision("halten", reasoning={"grund": gap, "filter": "Datenqualität"})
        return self._evaluate(list(bars), position, p)

    def trailing_stop(self, bars: Sequence[Bar], position: PositionView, params: dict | None) -> float | None:
        """Neuer (nur steigender) Stop für Trailing; None = unverändert."""
        p = self.clean_params(params)
        mult = p.get("trailing_atr")
        if not p.get("trailing", False) or not mult or len(bars) < p.get("atr_period", 14) + 2:
            return None
        a = ind.atr([b.high for b in bars], [b.low for b in bars], [b.close for b in bars], int(p.get("atr_period", 14)))[-1]
        if a is None:
            return None
        candidate = position.highest - float(mult) * a
        if position.stop is None or candidate > position.stop:
            return candidate
        return None

    def _evaluate(self, bars: list[Bar], position: PositionView | None, p: dict) -> Decision:
        raise NotImplementedError


def _data_problem(bars: Sequence[Bar], timeframe: timedelta | None) -> str | None:
    for b in bars:
        if not b.ok:
            return f"Fehlerhafte Kerze {b.time:%d.%m. %H:%M} (Datenqualität)"
    if timeframe:
        for a, b in zip(bars, bars[1:]):
            if b.time - a.time != timeframe:
                return f"Datenlücke zwischen {a.time:%d.%m. %H:%M} und {b.time:%d.%m. %H:%M}"
    return None


class Cols:
    """Spalten der Kerzen als Listen."""

    def __init__(self, bars: Sequence[Bar]):
        self.o = [b.open for b in bars]
        self.h = [b.high for b in bars]
        self.l = [b.low for b in bars]
        self.c = [b.close for b in bars]
        self.v = [b.volume for b in bars]


def common_filters(c: Cols, i: int, p: dict, atr_val: float | None) -> tuple[bool, dict]:
    """Volumen- und Volatilitätsfilter (FA-12, FA-04)."""
    info: dict = {}
    ok = True
    if atr_val is not None and c.c[i] > 0:
        atr_pct = atr_val / c.c[i] * 100
        info["atr_prozent"] = r(atr_pct, 3)
        lo, hi = p.get("atr_pct_min", 0), p.get("atr_pct_max", 100)
        if atr_pct < lo or atr_pct > hi:
            ok = False
            info["filter_volatilitaet"] = f"ATR {atr_pct:.2f} % außerhalb {lo}–{hi} %"
    vf = p.get("min_volume_factor", 0)
    if vf:
        avg = ind.sma(c.v, 20)[i]
        info["volumen"] = r(c.v[i], 4)
        info["volumen_schnitt20"] = r(avg, 4)
        if avg is not None and c.v[i] < vf * avg:
            ok = False
            info["filter_volumen"] = f"Volumen unter {vf}× Durchschnitt"
    return ok, info
