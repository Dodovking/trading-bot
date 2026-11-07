"""Gemeinsame Trade-Simulation für Schattenbetrieb und Backtest (gleiche Logik, keine Vorausschau).

Ablauf je abgeschlossener Kerze t: zuerst Stop/Take-Profit innerhalb von t prüfen, dann Signal aus Kerzen ≤ t;
Einstieg zum Schluss­kurs von t plus Kosten (pessimistisch: Spread/2 + Slippage + Gebühr).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Costs:
    fee_pct: float = 0.4
    slippage_pct: float = 0.05
    spread_pct: float = 0.1

    @property
    def side_cost(self) -> float:
        return (self.fee_pct + self.slippage_pct + self.spread_pct / 2) / 100


@dataclass
class SimTrade:
    opened_at: datetime
    entry: float
    stop: float
    initial_stop: float
    take_profit: float | None
    trailing_atr_mult: float | None
    highest: float
    regime: str = "unklar"
    closed_at: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    extra: dict = field(default_factory=dict)

    def result(self, costs: Costs) -> tuple[float, float]:
        """(Ergebnis in %, Ergebnis in R) nach Kosten."""
        buy = self.entry * (1 + costs.side_cost)
        sell = self.exit_price * (1 - costs.side_cost)
        risk = self.entry - self.initial_stop
        pnl_pct = (sell / buy - 1) * 100
        r = (sell - buy) / risk if risk > 0 else 0.0
        return pnl_pct, r


def check_exit_intrabar(t: SimTrade, o: float, h: float, low: float) -> tuple[float, str] | None:
    """Stop zuerst (pessimistisch), Kurslücke unter den Stop wird zum Eröffnungskurs ausgeführt."""
    if low <= t.stop:
        return (min(o, t.stop), "Stop-Loss")
    if t.take_profit is not None and h >= t.take_profit:
        return (max(o, t.take_profit), "Take-Profit")
    return None
