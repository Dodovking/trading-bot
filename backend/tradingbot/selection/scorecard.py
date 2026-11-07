"""Scorecard je Strategie (Abschnitt 6.2): Kennzahlen nach Kosten über rollierende Zeitfenster."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Score:
    trades: int
    expectancy_r: float | None
    expectancy_pct: float | None
    profit_factor: float | None
    win_rate: float | None
    drawdown_r: float
    stability: float | None
    score: float | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def max_drawdown(rs: list[float]) -> float:
    peak = cur = dd = 0.0
    for x in rs:
        cur += x
        peak = max(peak, cur)
        dd = max(dd, peak - cur)
    return dd


def compute(rs: list[float], pcts: list[float], min_trades: int = 30) -> Score:
    n = len(rs)
    if n == 0:
        return Score(0, None, None, None, None, 0.0, None, None)
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x < 0]
    exp_r = sum(rs) / n
    pf = (sum(wins) / sum(losses)) if losses else (None if not wins else 99.0)
    dd = max_drawdown(rs)
    # Stabilität: Anteil positiver Teilfenster (4 gleich große Abschnitte)
    stability = None
    if n >= 8:
        k = n // 4
        parts = [rs[j * k:(j + 1) * k] for j in range(4)]
        stability = sum(1 for p in parts if sum(p) > 0) / 4
    # Score: Erwartungswert, gewichtet nach Datenmenge und Stabilität, abzüglich Drawdown-Strafe
    confidence = min(1.0, n / max(1, min_trades))
    score = exp_r * confidence * (0.5 + 0.5 * (stability if stability is not None else 0.5)) - 0.02 * dd
    return Score(n, round(exp_r, 4), round(sum(pcts) / n, 4), round(pf, 3) if pf is not None else None,
                 round(len(wins) / n * 100, 1), round(dd, 3), stability, round(score, 4))
