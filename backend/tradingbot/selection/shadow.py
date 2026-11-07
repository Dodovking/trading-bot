"""Schattenbetrieb (FA-17): Jede zugelassene Strategie handelt simuliert mit Live-Daten.

Die Schatten-Trades erreichen nie den Broker; sie liefern ehrliche Daten für Scorecard und Auswahl.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.models import ShadowTrade
from ..core.types import Bar, Decision, PositionView
from ..strategies.base import Strategy
from .simulate import Costs, SimTrade, check_exit_intrabar

D = Decimal


def _d(x: float | None) -> Decimal | None:
    return None if x is None else D(str(round(x, 10)))


def open_trade(db: Session, user_id: int, strategy_id: str, strat: Strategy, inst_id: int, timeframe: str) -> ShadowTrade | None:
    return db.scalars(select(ShadowTrade).where(ShadowTrade.user_id == user_id, ShadowTrade.strategy_id == strategy_id,
                                                ShadowTrade.instrument_id == inst_id, ShadowTrade.timeframe == timeframe,
                                                ShadowTrade.status == "offen")).first()


def _close(t: ShadowTrade, price: float, when: datetime, reason: str, costs: Costs) -> None:
    sim = SimTrade(t.opened_at, float(t.entry), float(t.stop), float(t.initial_stop), None, None, float(t.highest))
    sim.exit_price = price
    pct, r = sim.result(costs)
    t.status, t.closed_at, t.exit_price, t.exit_reason = "geschlossen", when, _d(price), reason
    t.pnl_pct, t.r_multiple = _d(pct), _d(r)


def step(db: Session, user_id: int, strategy_id: str, strat: Strategy, params: dict, inst_id: int, timeframe: str,
         bars: list[Bar], decision: Decision | None, regime: str, costs: Costs, signal_id: int | None = None) -> str | None:
    """Verarbeitet die zuletzt abgeschlossene Kerze. Rückgabe: Ereignis (eroeffnet/geschlossen) oder None."""
    last = bars[-1]
    t = open_trade(db, user_id, strategy_id, strat, inst_id, timeframe)
    if t is not None and last.time > t.opened_at:
        sim = SimTrade(t.opened_at, float(t.entry), float(t.stop), float(t.initial_stop),
                       float(t.take_profit) if t.take_profit is not None else None, None, float(t.highest))
        hit = check_exit_intrabar(sim, last.open, last.high, last.low)
        if hit:
            _close(t, hit[0], last.time, hit[1], costs)
            return "geschlossen"
        t.highest = _d(max(float(t.highest), last.high))
        if decision is not None and decision.direction == "verkauf":
            _close(t, last.close, last.time, str(decision.reasoning.get("grund", "Ausstiegssignal"))[:60], costs)
            return "geschlossen"
        new = strat.trailing_stop(bars, PositionView(float(t.entry), float(t.stop), float(t.highest), t.opened_at), params)
        if new is not None and new > float(t.stop):
            t.stop = _d(new)
        return None
    if t is None and decision is not None and decision.direction == "kauf" and decision.stop and decision.stop < last.close:
        db.add(ShadowTrade(user_id=user_id, strategy_id=strategy_id, strategy_version=strat.version, instrument_id=inst_id,
                           timeframe=timeframe, regime=regime, opened_at=last.time, entry=_d(last.close), stop=_d(decision.stop),
                           initial_stop=_d(decision.stop), take_profit=_d(decision.take_profit), highest=_d(last.close),
                           trailing_atr_mult=_d(decision.trailing_atr_mult), signal_id=signal_id))
        return "eroeffnet"
    return None
