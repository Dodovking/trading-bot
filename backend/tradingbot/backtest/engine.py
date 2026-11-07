"""Backtest (FA-50): dieselbe Strategie-Logik wie live, keine Vorausschau, Kosten pessimistisch.

Pro Kerze: Stop/Take-Profit innerhalb der Kerze prüfen (Stop zuerst), dann Signal auf Basis abgeschlossener
Kerzen, Einstieg zum Schlusskurs + Kosten. Positionsgröße nach Risiko je Trade wie im Risikomodul.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from ..core.types import Bar, PositionView
from ..selection.regime import classify
from ..selection.simulate import Costs, SimTrade, check_exit_intrabar
from ..strategies.base import Strategy


@dataclass
class BtParams:
    capital: float = 10000.0
    risk_pct: float = 1.0
    max_position_pct: float = 25.0
    costs: Costs = None  # type: ignore[assignment]
    oos_share: float = 0.3  # letzter Anteil als Out-of-Sample


def metrics(trades: list[dict], equity: list[tuple], capital: float, bars: Sequence[Bar], tf: timedelta) -> dict:
    n = len(trades)
    pnl = [t["pnl"] for t in trades]
    wins = [x for x in pnl if x > 0]
    losses = [-x for x in pnl if x < 0]
    end = equity[-1][1] if equity else capital
    peak, mdd = capital, 0.0
    for _, v in equity:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100 if peak else 0)
    years = max((bars[-1].time - bars[0].time).days / 365.25, 1 / 365) if bars else 1
    cagr = ((end / capital) ** (1 / years) - 1) * 100 if end > 0 else -100
    rets = [(equity[i][1] / equity[i - 1][1] - 1) for i in range(1, len(equity)) if equity[i - 1][1] > 0]
    per_year = timedelta(days=365.25) / tf
    sharpe = None
    if len(rets) > 2:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
        sharpe = round(mu / sd * math.sqrt(per_year), 2) if sd > 0 else None
    bh = (bars[-1].close / bars[0].close - 1) * 100 if bars else 0
    return {
        "trades": n, "endkapital": round(end, 2), "rendite_prozent": round((end / capital - 1) * 100, 2),
        "cagr_prozent": round(cagr, 2), "max_drawdown_prozent": round(mdd, 2),
        "trefferquote_prozent": round(len(wins) / n * 100, 1) if n else None,
        "profit_factor": round(sum(wins) / sum(losses), 2) if losses else None,
        "erwartungswert_r": round(sum(t["r"] for t in trades) / n, 3) if n else None,
        "durchschnitt_gewinn": round(sum(wins) / len(wins), 2) if wins else None,
        "durchschnitt_verlust": round(-sum(losses) / len(losses), 2) if losses else None,
        "sharpe": sharpe, "kaufen_halten_prozent": round(bh, 2),
        "zeit_im_markt_prozent": round(sum(t["bars"] for t in trades) / max(1, len(bars)) * 100, 1),
    }


def run(strategy: Strategy, params: dict, bars: list[Bar], tf: timedelta, p: BtParams) -> dict:
    costs = p.costs or Costs()
    params = strategy.clean_params(params)
    warm = strategy.warmup(params) + 2
    cash = p.capital
    pos: SimTrade | None = None
    qty = 0.0
    entry_i = 0
    trades: list[dict] = []
    equity: list[tuple] = []
    regimes_seen: dict[str, int] = {}
    for i in range(warm, len(bars)):
        b = bars[i]
        if pos is not None:
            hit = check_exit_intrabar(pos, b.open, b.high, b.low)
            if hit:
                pos.exit_price, pos.exit_reason, pos.closed_at = hit[0], hit[1], b.time
        window = bars[: i + 1]
        if pos is not None and pos.exit_price is None:
            pos.highest = max(pos.highest, b.high)
            view = PositionView(pos.entry, pos.stop, pos.highest, pos.opened_at)
            d = strategy.evaluate(window, view, params, tf)
            if d.direction == "verkauf":
                pos.exit_price, pos.exit_reason, pos.closed_at = b.close, str(d.reasoning.get("grund", "Signal"))[:60], b.time
            else:
                new = strategy.trailing_stop(window, view, params)
                if new is not None and new > pos.stop:
                    pos.stop = new
        if pos is not None and pos.exit_price is not None:
            proceeds = qty * pos.exit_price * (1 - costs.side_cost)
            cost = qty * pos.entry * (1 + costs.side_cost)
            cash += proceeds
            pct, r = pos.result(costs)
            trades.append({"eroeffnet": pos.opened_at.isoformat(), "geschlossen": b.time.isoformat(), "einstieg": round(pos.entry, 6),
                           "ausstieg": round(pos.exit_price, 6), "grund": pos.exit_reason, "pnl": round(proceeds - cost, 2),
                           "prozent": round(pct, 2), "r": round(r, 3), "bars": i - entry_i, "regime": pos.regime})
            pos, qty = None, 0.0
        if pos is None and i < len(bars) - 1:
            d = strategy.evaluate(window, None, params, tf)
            if d.direction == "kauf" and d.stop and d.stop < b.close:
                equity_now = cash
                dist = b.close * (1 + costs.slippage_pct / 100) - d.stop * (1 - costs.slippage_pct / 100)
                q = equity_now * p.risk_pct / 100 / dist if dist > 0 else 0
                q = min(q, equity_now * p.max_position_pct / 100 / b.close, cash / (b.close * (1 + costs.side_cost)) * 0.995)
                if q > 0:
                    regime = classify(window[-400:])[0] if i % 1 == 0 and len(window) >= 220 else "unklar"
                    regimes_seen[regime] = regimes_seen.get(regime, 0) + 1
                    pos = SimTrade(b.time, b.close, d.stop, d.stop, d.take_profit, d.trailing_atr_mult, b.close, regime)
                    qty = q
                    cash -= q * b.close * (1 + costs.side_cost)
                    entry_i = i
        value = cash + (qty * b.close * (1 - costs.side_cost) if pos else 0)
        equity.append((b.time, value))
    split = int(len(bars) * (1 - p.oos_share))
    split_time = bars[split].time if bars and split < len(bars) else None
    out = {"gesamt": metrics(trades, equity, p.capital, bars[warm:], tf), "trades_liste": trades[-500:],
           "kapitalkurve": [[t.isoformat(), round(v, 2)] for t, v in equity[:: max(1, len(equity) // 400)]],
           "einstiege_je_regime": regimes_seen, "kerzen": len(bars), "aufwaermphase": warm}
    if split_time:
        iso = split_time.isoformat()
        is_tr = [t for t in trades if t["eroeffnet"] < iso]
        oos_tr = [t for t in trades if t["eroeffnet"] >= iso]
        eq_is = [e for e in equity if e[0] < split_time]
        eq_oos = [e for e in equity if e[0] >= split_time]
        out["in_sample"] = metrics(is_tr, eq_is or [(bars[0].time, p.capital)], p.capital, bars[warm:split], tf)
        start_oos = eq_is[-1][1] if eq_is else p.capital
        out["out_of_sample"] = metrics(oos_tr, eq_oos or [(split_time, start_oos)], start_oos, bars[split:], tf)
        out["aufteilung"] = iso
    return out
