"""Ausführbare Ertragsmodule: Sparplan und Rebalancing (Abschnitt 15).

Laufen wie Strategien über Risikoprüfung (kind="modul") und Order-Manager; der Bestand trägt keinen Stop,
wird aber durch Modulbudget, Liquiditätsreserve und Not-Aus begrenzt.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from ..core.config import LIVE_SMALL_RISK_FACTOR, ORDER_STATUSES
from ..core.db import utcnow
from ..core.events import log_event
from ..core.models import ModuleRun, Position, RiskDecision
from ..risk.rules import RiskContext, evaluate

D = Decimal
SPARPLAN = "modul:sparplan"


def period_key(rhythm: str, local: datetime) -> str:
    if rhythm == "woechentlich":
        iso = local.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return f"{local:%Y-%m}"


def _due_time(rhythm: str, day: int, local: datetime) -> bool:
    if local.hour < 9:  # Ausführung tagsüber, nicht exakt zur Tageswende
        return False
    if rhythm == "woechentlich":
        return local.weekday() >= min(max(day, 0), 6)
    return local.day >= min(max(day, 1), 28)


def _done(runner, module: str, period: str) -> bool:
    return runner.db.scalars(select(ModuleRun.id).where(ModuleRun.user_id == runner.user_id, ModuleRun.module == module,
                                                        ModuleRun.period == period, ModuleRun.account_kind == runner.acct.kind)).first() \
        is not None


def holdings(runner) -> list[Position]:
    return [p for p in runner.positions() if p.side == "bestand" and p.strategy_id == SPARPLAN]


def _ctx(runner, inst, side: str, amount: Decimal = D(0), qty: Decimal | None = None) -> RiskContext:
    r = runner.cfg["risk"]
    t = runner.e.market.ticker(inst.symbol)
    health = runner.e.market.health(inst.symbol, None, r["max_tick_age_s"], r["max_data_age_candles"])
    equity, cash = runner.equity()
    pending = sum(1 for o in runner.om.open_orders() if o.instrument_id == inst.id and o.purpose == "modul")
    module_value = sum((p.qty * runner.mark(p) for p in holdings(runner)), D(0))
    if side == "verkauf":
        return RiskContext(user_id=runner.user_id, kind="ausstieg", symbol=inst.symbol, side="verkauf", state=runner.rt.state,
                           now=utcnow(), risk=r, costs=runner.cfg["costs"], feed_ok=health.ok, feed_reason=health.reason,
                           broker_ok=runner.rt.broker_ok, reconcile_ok=True, reconcile_note="", tradable=True, blackouts=[],
                           equity=equity, cash=cash, day_start_equity=D(0), peak_equity=D(0), loss_streak=0, positions=[],
                           pending_orders_symbol=pending, exit_qty=qty)
    return RiskContext(user_id=runner.user_id, kind="modul", symbol=inst.symbol, side="kauf", state=runner.rt.state, now=utcnow(),
                       risk=r, costs=runner.cfg["costs"], feed_ok=health.ok, feed_reason=health.reason, broker_ok=runner.rt.broker_ok,
                       reconcile_ok=runner.rt.last_reconcile_ok, reconcile_note=runner.rt.last_reconcile_note, tradable=inst.tradable,
                       blackouts=r.get("blackouts", []), equity=equity, cash=cash, day_start_equity=runner.rt.day_start_equity or equity,
                       peak_equity=runner.rt.peak_equity or equity, loss_streak=runner.rt.loss_streak, positions=[],
                       pending_orders_symbol=pending, bid=t.bid if t else None, ask=t.ask if t else None,
                       volume_24h=t.volume_24h_quote if t else None, min_qty=inst.min_qty, step=inst.step_size, module=SPARPLAN,
                       module_value=module_value, amount=amount, hours=inst.trading_hours, venue_note=runner.venue_note(inst))


def _record(runner, ctx: RiskContext, rr) -> None:
    runner.db.add(RiskDecision(user_id=runner.user_id, kind="modul" if ctx.kind == "modul" else "ausstieg", result=rr.result,
                               rule=rr.rule[:80], limit_value=rr.limit[:60], actual_value=rr.actual[:60], position_size=rr.qty,
                               checks=[c.to_dict() for c in rr.checks], client_order_id=rr.client_order_id))


def buy(runner, inst, amount: Decimal, label: str) -> str:
    ctx = _ctx(runner, inst, "kauf", amount)
    rr = evaluate(ctx)
    _record(runner, ctx, rr)
    if not rr.approved:
        return f"{inst.symbol}: abgelehnt ({rr.rule}: {rr.actual})"
    pos = runner.om.buy_holding(rr, inst, SPARPLAN, label)
    return f"{inst.symbol}: gekauft {rr.qty.normalize():f}" if pos else f"{inst.symbol}: nicht ausgeführt"


def run_modules(runner, local: datetime) -> None:
    cfg = runner.cfg
    mods = cfg.get("modules") or {}
    allowed = ORDER_STATUSES[cfg["account"]]
    if runner.rt.state != "AKTIV":
        return
    sp = mods.get("sparplan") or {}
    weights = {k: float(v) for k, v in (sp.get("weights") or {}).items() if float(v) > 0 and k in runner.insts}
    if sp.get("status") in allowed and weights:
        period = period_key(sp["rhythm"], local)
        if _due_time(sp["rhythm"], int(sp.get("day", 1)), local) and not _done(runner, "sparplan", period):
            factor = LIVE_SMALL_RISK_FACTOR if sp["status"] == "live_klein" and runner.acct.kind == "live" else 1.0
            total_w = sum(weights.values())
            results = [buy(runner, runner.insts[sym], D(str(sp["amount"] * factor * w / total_w)).quantize(D("0.01")), "Sparplan")
                       for sym, w in weights.items()]
            runner.db.add(ModuleRun(user_id=runner.user_id, module="sparplan", period=period, account_kind=runner.acct.kind,
                                    result="ausgefuehrt", details={"ergebnisse": results}))
            log_event(runner.user_id, "info", "modul", "Sparplan ausgeführt: " + "; ".join(results), kind="modul", db=runner.db)
    rb = mods.get("rebalancing") or {}
    if rb.get("status") in allowed and weights:
        period = period_key(rb["rhythm"], local)
        if _due_time(rb["rhythm"], 1, local) and not _done(runner, "rebalancing", period):
            results = rebalance(runner, weights, float(rb.get("threshold_pct", 5)))
            runner.db.add(ModuleRun(user_id=runner.user_id, module="rebalancing", period=period, account_kind=runner.acct.kind,
                                    result="ausgefuehrt", details={"ergebnisse": results}))
            log_event(runner.user_id, "info", "modul", "Rebalancing: " + ("; ".join(results) or "Gewichte im Rahmen"), kind="modul",
                      db=runner.db)


def rebalance(runner, weights: dict[str, float], threshold_pct: float) -> list[str]:
    hold = {runner.inst_by_id(p.instrument_id).symbol: p for p in holdings(runner)}
    values = {sym: (hold[sym].qty * runner.mark(hold[sym]) if sym in hold else D(0)) for sym in weights}
    total = sum(values.values(), D(0))
    if total <= 0:
        return []
    total_w = sum(weights.values())
    out = []
    # Erst verkaufen (setzt Guthaben frei), dann kaufen
    for sym, w in weights.items():
        target = total * D(str(w / total_w))
        diff = values[sym] - target
        if diff > 0 and diff / total * 100 > D(str(threshold_pct)) and sym in hold:
            inst = runner.insts[sym]
            price = runner.mark(hold[sym])
            qty = (diff / price).quantize(inst.step_size, rounding="ROUND_DOWN")
            ctx = _ctx(runner, inst, "verkauf", qty=qty)
            rr = evaluate(ctx)
            _record(runner, ctx, rr)
            if rr.approved and runner.om.sell_holding(rr, hold[sym], inst, "Rebalancing"):
                out.append(f"{sym}: {qty.normalize():f} verkauft")
    for sym, w in weights.items():
        target = total * D(str(w / total_w))
        diff = target - values[sym]
        if diff > 0 and diff / total * 100 > D(str(threshold_pct)):
            out.append(buy(runner, runner.insts[sym], diff.quantize(D("0.01")), "Rebalancing"))
    return out
