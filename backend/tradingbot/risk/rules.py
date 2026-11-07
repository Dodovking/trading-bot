"""Risikomodul (Abschnitt 4): unabhängig von der Strategie, hat Veto-Recht.

Die Prüfungen laufen in fester Reihenfolge (4.3). Schlägt eine fehl, wird abgelehnt und
Regel, Grenzwert und Istwert festgehalten (FA-25). Nur eine Freigabe mit gültigem
Freigabestempel wird vom Order-Management angenommen.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from ..core.crypto import sign, verify
from ..core.state import NEW_ORDERS_ALLOWED, STATE_LABELS
from ..data.quality import round_step
from .sizing import position_size

D = Decimal


@dataclass
class OpenPos:
    symbol: str
    qty: Decimal
    value: Decimal


@dataclass
class RiskContext:
    user_id: int
    kind: str  # einstieg | ausstieg
    symbol: str
    side: str  # kauf | verkauf
    state: str
    now: datetime
    risk: dict
    costs: dict
    feed_ok: bool
    feed_reason: str
    broker_ok: bool
    reconcile_ok: bool
    reconcile_note: str
    tradable: bool
    blackouts: list
    equity: Decimal
    cash: Decimal
    day_start_equity: Decimal
    peak_equity: Decimal
    loss_streak: int
    positions: list[OpenPos]
    pending_orders_symbol: int
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume_24h: Decimal | None = None
    stop: Decimal | None = None
    min_qty: Decimal = D(0)
    step: Decimal = D("0.00000001")
    last_range_atr: float | None = None
    exit_qty: Decimal | None = None
    forced: bool = False  # Not-Aus / manueller Eingriff
    strategy_name: str = ""
    strategy_weight: float = 1.0  # Anteil am Gesamtrisiko laut Meta-Controller (0 = nicht aktiv)
    strategy_open_risk: Decimal = D(0)
    total_open_risk: Decimal = D(0)
    risk_factor: float = 1.0  # z. B. 0,5 bei hoher Volatilität, 0,25 bei Live-klein
    risk_factor_note: str = ""
    module: str = ""  # Ertragsmodul (kind="modul")
    module_value: Decimal = D(0)  # bereits gebundenes Kapital des Moduls
    amount: Decimal = D(0)  # gewünschter Kaufbetrag (Module)
    hours: str = "24/7"  # Handelszeiten des Markts
    venue_note: str = ""  # gesetzt, wenn der verbundene Broker diesen Markt nicht anbietet


@dataclass
class Check:
    nr: int
    name: str
    ok: bool
    rule: str = ""
    limit: str = ""
    actual: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class RiskResult:
    result: str  # freigegeben | verkleinert | abgelehnt
    qty: Decimal
    checks: list[Check] = field(default_factory=list)
    rule: str = ""
    limit: str = ""
    actual: str = ""
    client_order_id: str | None = None
    stamp: str = ""

    @property
    def approved(self) -> bool:
        return self.result in ("freigegeben", "verkleinert")


def _pct(x: Decimal | float) -> str:
    return f"{float(x):.2f} %".replace(".", ",")


def stamp_message(user_id: int, client_order_id: str, symbol: str, side: str, qty: Decimal, stop: Decimal | None) -> str:
    return f"{user_id}|{client_order_id}|{symbol}|{side}|{format(qty.normalize(), 'f')}|{format(stop.normalize(), 'f') if stop else '-'}"


def make_stamp(user_id: int, client_order_id: str, symbol: str, side: str, qty: Decimal, stop: Decimal | None) -> str:
    return sign(stamp_message(user_id, client_order_id, symbol, side, qty, stop))


def verify_stamp(user_id: int, client_order_id: str, symbol: str, side: str, qty: Decimal, stop: Decimal | None, stamp: str) -> bool:
    return verify(stamp_message(user_id, client_order_id, symbol, side, qty, stop), stamp)


def _in_blackout(blackouts: list, now: datetime) -> str | None:
    for b in blackouts or []:
        try:
            start = datetime.fromisoformat(b["start"])
            end = datetime.fromisoformat(b["end"])
        except (KeyError, ValueError):
            continue
        if start.tzinfo is None:
            from zoneinfo import ZoneInfo
            start = start.replace(tzinfo=ZoneInfo("Europe/Berlin"))
            end = end.replace(tzinfo=ZoneInfo("Europe/Berlin"))
        if start <= now <= end:
            return b.get("label") or "Sperrzeitraum"
    return None


def _counterparty(ctx: RiskContext) -> Check | None:
    r = ctx.risk
    total = D(str(r.get("total_capital_eur", 0) or 0))
    if total <= 0:
        return None
    share = ctx.equity / total * 100
    if share > D(str(r["counterparty_limit_pct"])):
        return Check(6, "Gegenparteilimit eingehalten", False, "Gegenparteilimit", _pct(r["counterparty_limit_pct"]), _pct(share))
    return None


def _free_cash(ctx: RiskContext) -> Decimal:
    """Verfügbares Guthaben abzüglich Liquiditätsreserve und Gebühr."""
    fee = D(str(ctx.costs.get("fee_pct", 0))) / 100
    reserve = ctx.equity * D(str(ctx.risk.get("liquidity_reserve_pct", 0))) / 100
    return max(D(0), (ctx.cash - reserve) / (1 + fee) * D("0.995"))


def evaluate(ctx: RiskContext) -> RiskResult:
    if ctx.kind == "ausstieg":
        return _evaluate_exit(ctx)
    if ctx.kind == "modul":
        return _evaluate_module(ctx)
    r = ctx.risk
    checks: list[Check] = []

    def fail(c: Check) -> RiskResult:
        checks.append(c)
        return RiskResult("abgelehnt", D(0), checks, c.rule, c.limit, c.actual)

    # 1 Bot-Zustand
    c = Check(1, "Bot-Zustand erlaubt neue Orders", ctx.state in NEW_ORDERS_ALLOWED, "Bot-Zustand", "Bot läuft",
              STATE_LABELS.get(ctx.state, ctx.state))
    if not c.ok:
        return fail(c)
    checks.append(c)
    # 2 Daten und Broker-Verbindung
    if not ctx.feed_ok:
        return fail(Check(2, "Kursdaten aktuell und plausibel", False, "Datenqualität/Datenalter", "aktuell", ctx.feed_reason))
    if not ctx.broker_ok:
        return fail(Check(2, "Broker-Verbindung gesund", False, "Broker-Verbindung", "verbunden", "getrennt"))
    if ctx.bid is None or ctx.ask is None or ctx.bid <= 0 or ctx.ask < ctx.bid:
        return fail(Check(2, "Kursdaten plausibel", False, "Geld/Brief", "plausibel", "unplausibel"))
    checks.append(Check(2, "Kursdaten aktuell, Broker verbunden", True))
    # 3 Abgleich
    if not ctx.reconcile_ok:
        return fail(Check(3, "Letzter Abgleich erfolgreich", False, "Abgleich mit Broker", "übereinstimmend", ctx.reconcile_note or "fehlgeschlagen"))
    checks.append(Check(3, "Abgleich mit Broker erfolgreich", True))
    # 4 Markt/Handelszeit/Sperrzeit
    if not ctx.tradable:
        return fail(Check(4, "Markt handelbar", False, "Markt", "handelbar", "nur Analyse"))
    if ctx.venue_note:
        return fail(Check(4, "Markt beim Broker handelbar", False, "Markt beim Broker", "bietet Markt an", ctx.venue_note))
    bl = _in_blackout(ctx.blackouts, ctx.now)
    if bl:
        return fail(Check(4, "Kein Sperrzeitraum", False, "Sperrzeitraum", "keiner", bl))
    vp = float(r.get("volatility_pause_atr", 0) or 0)
    if vp and ctx.last_range_atr is not None and ctx.last_range_atr > vp:
        return fail(Check(4, "Keine außergewöhnliche Marktbewegung", False, "Volatilitätsbremse", f"{vp:g}× ATR",
                          f"{ctx.last_range_atr:.1f}× ATR"))
    checks.append(Check(4, "Markt geöffnet, kein Sperrzeitraum", True, note=ctx.hours))
    # 5 Tagesverlust, Drawdown, Verlustserie
    if ctx.day_start_equity > 0:
        day_loss = (ctx.day_start_equity - ctx.equity) / ctx.day_start_equity * 100
        if day_loss >= D(str(r["daily_loss_limit_pct"])):
            return fail(Check(5, "Tagesverlustlimit nicht erreicht", False, "Tagesverlustlimit", _pct(r["daily_loss_limit_pct"]), _pct(day_loss)))
    if ctx.peak_equity > 0:
        dd = (ctx.peak_equity - ctx.equity) / ctx.peak_equity * 100
        if dd >= D(str(r["max_drawdown_pct"])):
            return fail(Check(5, "Drawdown-Limit nicht erreicht", False, "Maximaler Drawdown", _pct(r["max_drawdown_pct"]), _pct(dd)))
    if ctx.loss_streak >= int(r["loss_streak_limit"]):
        return fail(Check(5, "Verlustserie nicht erreicht", False, "Verlustserie", f"{r['loss_streak_limit']} Trades", f"{ctx.loss_streak} Trades"))
    checks.append(Check(5, "Tagesverlust, Drawdown, Verlustserie im Rahmen", True))
    # 6 Positionslimit / Exposure (vorläufig, endgültig nach Größenberechnung)
    if len(ctx.positions) >= int(r["max_positions"]):
        return fail(Check(6, "Positionslimit", False, "Max. offene Positionen", str(r["max_positions"]), str(len(ctx.positions))))
    exposure = sum((p.value for p in ctx.positions), D(0))
    max_exp = ctx.equity * D(str(r["max_exposure_pct"])) / 100
    if exposure >= max_exp:
        return fail(Check(6, "Gesamt-Exposure", False, "Max. Gesamt-Exposure", _pct(r["max_exposure_pct"]), _pct(exposure / ctx.equity * 100)))
    cp = _counterparty(ctx)
    if cp:
        return fail(cp)
    if ctx.strategy_weight <= 0:
        return fail(Check(6, "Strategie-Budget", False, "Strategie-Budget", "> 0 %", f"{ctx.strategy_name or 'Strategie'} nicht aktiv"))
    total_cap = ctx.equity * D(str(r["max_total_risk_pct"])) / 100
    strat_cap = total_cap * D(str(ctx.strategy_weight))
    if ctx.total_open_risk >= total_cap:
        return fail(Check(6, "Gesamtrisiko", False, "Max. Gesamtrisiko", _pct(r["max_total_risk_pct"]),
                          _pct(ctx.total_open_risk / ctx.equity * 100)))
    if ctx.strategy_open_risk >= strat_cap:
        return fail(Check(6, "Strategie-Budget", False, "Strategie-Budget", f"{ctx.strategy_weight * 100:.0f} % des Gesamtrisikos",
                          "ausgeschöpft"))
    # 7 Stop-Loss und Positionsgröße
    entry = ctx.ask
    if ctx.stop is None or ctx.stop <= 0 or ctx.stop >= entry:
        return fail(Check(7, "Stop-Loss vorhanden und sinnvoll", False, "Stop-Loss Pflicht", "unter Einstieg", str(ctx.stop)))
    dist_pct = (entry - ctx.stop) / entry * 100
    if dist_pct < D(str(r["min_stop_distance_pct"])) or dist_pct > D(str(r["max_stop_distance_pct"])):
        return fail(Check(7, "Stop-Abstand sinnvoll", False, "Stop-Abstand",
                          f"{_pct(r['min_stop_distance_pct'])}–{_pct(r['max_stop_distance_pct'])}", _pct(dist_pct)))
    eff_risk = D(str(r["risk_per_trade_pct"])) * D(str(ctx.risk_factor))
    qty = position_size(ctx.equity, eff_risk, entry, ctx.stop, ctx.step, D(str(ctx.costs.get("slippage_pct", 0))))
    result = "freigegeben"
    notes = [ctx.risk_factor_note] if ctx.risk_factor < 1 and ctx.risk_factor_note else []
    if ctx.risk_factor < 1:
        result = "verkleinert"
    per_unit_risk = entry - ctx.stop
    budget_left = min(total_cap - ctx.total_open_risk, strat_cap - ctx.strategy_open_risk)
    if qty * per_unit_risk > budget_left:
        qty = round_step(max(budget_left, D(0)) / per_unit_risk, ctx.step)
        result = "verkleinert"
        notes.append("verkleinert wegen Strategie-/Gesamtrisiko-Budget")
    max_pos_value = ctx.equity * D(str(r["max_position_pct"])) / 100
    fee = D(str(ctx.costs.get("fee_pct", 0))) / 100
    caps = [(max_pos_value, f"max. {_pct(r['max_position_pct'])} je Position"),
            (max_exp - exposure, "Gesamt-Exposure"),
            (_free_cash(ctx), "verfügbares Guthaben abzüglich Liquiditätsreserve")]
    for cap_value, label in caps:
        if qty * entry > cap_value:
            qty = round_step(max(cap_value, D(0)) / entry, ctx.step)
            result = "verkleinert"
            notes.append(f"verkleinert wegen {label}")
    if qty <= 0 or qty < ctx.min_qty:
        return fail(Check(7, "Positionsgröße über Mindestmenge", False, "Mindestmenge", format(ctx.min_qty.normalize(), "f"),
                          format(qty.normalize(), "f")))
    risk_amount = qty * (entry - ctx.stop)
    checks.append(Check(6, "Positionslimit und Exposure eingehalten", True, actual=f"{len(ctx.positions) + 1} Pos."))
    checks.append(Check(7, "Stop-Loss vorhanden, Größe berechnet", True, actual=f"{format(qty.normalize(), 'f')} Stück",
                        note="; ".join(notes) or f"Risiko {risk_amount.quantize(D('0.01'))} €"))
    # 8 Liquidität, Spread, Kosten
    spread_pct = (ctx.ask - ctx.bid) / ((ctx.ask + ctx.bid) / 2) * 100
    if spread_pct > D(str(r["max_spread_pct"])):
        return fail(Check(8, "Spread innerhalb der Grenze", False, "Max. Spread", _pct(r["max_spread_pct"]), _pct(spread_pct)))
    if ctx.volume_24h is not None and ctx.volume_24h < D(str(r["min_volume_24h"])):
        return fail(Check(8, "Liquidität ausreichend", False, "Mindestumsatz 24 h", f"{r['min_volume_24h']:,.0f} €".replace(",", "."),
                          f"{ctx.volume_24h:,.0f} €".replace(",", ".")))
    slip = D(str(ctx.costs.get("slippage_pct", 0))) / 100
    value = qty * entry
    expected_costs = value * (2 * fee + 2 * slip) + qty * (ctx.ask - ctx.bid)
    if risk_amount > 0 and expected_costs / risk_amount * 100 > D(str(r["max_cost_share_pct"])):
        return fail(Check(8, "Kosten vertretbar", False, "Max. Kostenanteil am Risiko", _pct(r["max_cost_share_pct"]),
                          _pct(expected_costs / risk_amount * 100)))
    checks.append(Check(8, "Liquidität, Spread und Kosten im Rahmen", True, actual=f"Spread {_pct(spread_pct)}"))
    # 9 Keine doppelte/widersprüchliche Order
    if ctx.pending_orders_symbol > 0 or any(p.symbol == ctx.symbol for p in ctx.positions):
        return fail(Check(9, "Keine doppelte Order", False, "Doppelte Order", "keine offene Order/Position", "bereits vorhanden"))
    coid = str(uuid.uuid4())
    checks.append(Check(9, "Keine doppelte Order, Client-Order-ID vergeben", True, actual=coid[:8]))
    # 10 Freigabe mit Stempel
    qty = qty.quantize(ctx.step, rounding=ROUND_DOWN) if ctx.step < 1 else qty
    stamp = make_stamp(ctx.user_id, coid, ctx.symbol, "kauf", qty, ctx.stop)
    checks.append(Check(10, "Freigabe erteilt (Freigabestempel)", True))
    return RiskResult(result, qty, checks, client_order_id=coid, stamp=stamp,
                      rule="; ".join(notes) if notes else "", limit="", actual="")


def _evaluate_module(ctx: RiskContext) -> RiskResult:
    """Kauf eines Ertragsmoduls (Sparplan/Rebalancing): ohne Stop, begrenzt durch Modulbudget und Reserve (Abschnitt 15.3)."""
    r = ctx.risk
    checks: list[Check] = []

    def fail(c: Check) -> RiskResult:
        checks.append(c)
        return RiskResult("abgelehnt", D(0), checks, c.rule, c.limit, c.actual)

    if ctx.state not in NEW_ORDERS_ALLOWED:
        return fail(Check(1, "Bot-Zustand erlaubt neue Orders", False, "Bot-Zustand", "Bot läuft", STATE_LABELS.get(ctx.state, ctx.state)))
    checks.append(Check(1, "Bot-Zustand erlaubt neue Orders", True))
    if not ctx.feed_ok:
        return fail(Check(2, "Kursdaten aktuell und plausibel", False, "Datenqualität/Datenalter", "aktuell", ctx.feed_reason))
    if not ctx.broker_ok or ctx.bid is None or ctx.ask is None or ctx.bid <= 0 or ctx.ask < ctx.bid:
        return fail(Check(2, "Broker verbunden, Kurs plausibel", False, "Broker/Kurs", "ok", "nicht ok"))
    checks.append(Check(2, "Kursdaten aktuell, Broker verbunden", True))
    if not ctx.reconcile_ok:
        return fail(Check(3, "Letzter Abgleich erfolgreich", False, "Abgleich mit Broker", "übereinstimmend", ctx.reconcile_note or "fehlgeschlagen"))
    checks.append(Check(3, "Abgleich mit Broker erfolgreich", True))
    if not ctx.tradable:
        return fail(Check(4, "Markt handelbar", False, "Markt", "handelbar", "nur Analyse"))
    if ctx.venue_note:
        return fail(Check(4, "Markt beim Broker handelbar", False, "Markt beim Broker", "bietet Markt an", ctx.venue_note))
    bl = _in_blackout(ctx.blackouts, ctx.now)
    if bl:
        return fail(Check(4, "Kein Sperrzeitraum", False, "Sperrzeitraum", "keiner", bl))
    checks.append(Check(4, "Markt handelbar, kein Sperrzeitraum", True))
    if ctx.peak_equity > 0:
        dd = (ctx.peak_equity - ctx.equity) / ctx.peak_equity * 100
        if dd >= D(str(r["max_drawdown_pct"])):
            return fail(Check(5, "Drawdown-Limit nicht erreicht", False, "Maximaler Drawdown", _pct(r["max_drawdown_pct"]), _pct(dd)))
    checks.append(Check(5, "Drawdown im Rahmen", True))
    cp = _counterparty(ctx)
    if cp:
        return fail(cp)
    amount = ctx.amount
    result, notes = "freigegeben", []
    budget = ctx.equity * D(str(r["module_budget_pct"])) / 100 - ctx.module_value
    if budget <= 0:
        return fail(Check(6, "Modulbudget", False, "Budget je Ertragsmodul", _pct(r["module_budget_pct"]),
                          _pct(ctx.module_value / ctx.equity * 100) if ctx.equity else "–"))
    for cap, label in ((budget, "Modulbudget"), (_free_cash(ctx), "Liquiditätsreserve")):
        if amount > cap:
            amount, result = max(cap, D(0)), "verkleinert"
            notes.append(f"verkleinert wegen {label}")
    qty = round_step(amount / ctx.ask, ctx.step)
    if qty <= 0 or qty < ctx.min_qty:
        return fail(Check(7, "Menge über Mindestmenge", False, "Mindestmenge", format(ctx.min_qty.normalize(), "f"), format(qty.normalize(), "f")))
    checks.append(Check(6, "Modulbudget und Liquiditätsreserve eingehalten", True, actual=f"{(qty * ctx.ask).quantize(D('0.01'))} €",
                        note="; ".join(notes)))
    checks.append(Check(7, "Bestand ohne Stop (Ertragsmodul, begrenzt durch Modulbudget)", True))
    spread_pct = (ctx.ask - ctx.bid) / ((ctx.ask + ctx.bid) / 2) * 100
    if spread_pct > D(str(r["max_spread_pct"])):
        return fail(Check(8, "Spread innerhalb der Grenze", False, "Max. Spread", _pct(r["max_spread_pct"]), _pct(spread_pct)))
    if ctx.volume_24h is not None and ctx.volume_24h < D(str(r["min_volume_24h"])):
        return fail(Check(8, "Liquidität ausreichend", False, "Mindestumsatz 24 h", str(r["min_volume_24h"]), str(ctx.volume_24h)))
    checks.append(Check(8, "Liquidität und Spread im Rahmen", True, actual=f"Spread {_pct(spread_pct)}"))
    if ctx.pending_orders_symbol > 0:
        return fail(Check(9, "Keine doppelte Order", False, "Doppelte Order", "keine offene Order", "bereits vorhanden"))
    coid = str(uuid.uuid4())
    checks.append(Check(9, "Client-Order-ID vergeben", True, actual=coid[:8]))
    stamp = make_stamp(ctx.user_id, coid, ctx.symbol, "kauf", qty, None)
    checks.append(Check(10, "Freigabe erteilt (Freigabestempel)", True))
    return RiskResult(result, qty, checks, client_order_id=coid, stamp=stamp, rule="; ".join(notes))


def _evaluate_exit(ctx: RiskContext) -> RiskResult:
    """Risikoreduzierende Orders: auch im Pause-/Sperrzustand erlaubt, aber nie doppelt."""
    checks = [Check(1, "Ausstieg reduziert Risiko – in jedem Zustand erlaubt", True, actual=STATE_LABELS.get(ctx.state, ctx.state))]
    if not ctx.forced and not ctx.feed_ok:
        checks.append(Check(2, "Kursdaten aktuell", False, "Datenalter", "aktuell", ctx.feed_reason))
        return RiskResult("abgelehnt", D(0), checks, "Datenalter", "aktuell", ctx.feed_reason)
    checks.append(Check(2, "Kursdaten geprüft", True, note="Not-Aus/manuell" if ctx.forced else ""))
    if ctx.pending_orders_symbol > 0:
        checks.append(Check(9, "Keine doppelte Order", False, "Doppelte Order", "keine", "Ausstieg läuft bereits"))
        return RiskResult("abgelehnt", D(0), checks, "Doppelte Order", "keine", "Ausstieg läuft bereits")
    qty = ctx.exit_qty or D(0)
    if qty <= 0:
        checks.append(Check(7, "Menge vorhanden", False, "Menge", "> 0", "0"))
        return RiskResult("abgelehnt", D(0), checks, "Menge", "> 0", "0")
    coid = str(uuid.uuid4())
    checks.append(Check(9, "Client-Order-ID vergeben", True, actual=coid[:8]))
    stamp = make_stamp(ctx.user_id, coid, ctx.symbol, "verkauf", qty, None)
    checks.append(Check(10, "Freigabe erteilt (Freigabestempel)", True))
    return RiskResult("freigegeben", qty, checks, client_order_id=coid, stamp=stamp)
