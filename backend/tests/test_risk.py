from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from tradingbot.core.config import default_config
from tradingbot.risk.rules import OpenPos, RiskContext, evaluate, verify_stamp
from tradingbot.risk.sizing import position_size


def ctx(**kw) -> RiskContext:
    cfg = default_config()
    base = dict(user_id=1, kind="einstieg", symbol="BTC/EUR", side="kauf", state="AKTIV", now=datetime.now(timezone.utc),
                risk=cfg["risk"], costs={"fee_pct": 0.1, "slippage_pct": 0.0}, feed_ok=True, feed_reason="", broker_ok=True,
                reconcile_ok=True, reconcile_note="", tradable=True, blackouts=[], equity=D(10000), cash=D(10000),
                day_start_equity=D(10000), peak_equity=D(10000), loss_streak=0, positions=[], pending_orders_symbol=0,
                bid=D("99.99"), ask=D(100), volume_24h=D(10**7), stop=D(95), min_qty=D("0.001"), step=D("0.0001"))
    base.update(kw)
    return RiskContext(**base)


def test_position_size_formula():
    assert position_size(D(10000), D(1), D(100), D(95), D("0.0001")) == D(20)
    assert position_size(D(10000), D(1), D(100), D(100), D("0.0001")) == 0


def test_approved_with_stamp_and_caps():
    r = evaluate(ctx())
    assert r.approved
    # 20 Stück × 100 € = 2000 € ≤ 25 % des Kontos; Risiko 1 % = 100 €, aber Gesamtrisiko-Budget 5 % → 30 % = 150 €
    assert r.qty == D(20)
    assert verify_stamp(1, r.client_order_id, "BTC/EUR", "kauf", r.qty, D(95), r.stamp)
    assert not verify_stamp(1, r.client_order_id, "BTC/EUR", "kauf", r.qty + 1, D(95), r.stamp)


@pytest.mark.parametrize("kw,rule", [
    ({"state": "PAUSIERT"}, "Bot-Zustand"),
    ({"feed_ok": False, "feed_reason": "alt"}, "Datenqualität/Datenalter"),
    ({"broker_ok": False}, "Broker-Verbindung"),
    ({"reconcile_ok": False}, "Abgleich mit Broker"),
    ({"tradable": False}, "Markt"),
    ({"venue_note": "Kraken bietet AAPL nicht an"}, "Markt beim Broker"),
    ({"equity": D(9600)}, "Tagesverlustlimit"),
    ({"loss_streak": 5}, "Verlustserie"),
    ({"stop": None}, "Stop-Loss Pflicht"),
    ({"stop": D("99.9")}, "Stop-Abstand"),
    ({"bid": D(98), "ask": D(100)}, "Max. Spread"),
    ({"volume_24h": D(10)}, "Mindestumsatz 24 h"),
    ({"pending_orders_symbol": 1}, "Doppelte Order"),
    ({"strategy_weight": 0.0}, "Strategie-Budget"),
    ({"positions": [OpenPos("ETH/EUR", D(1), D(100))] * 3}, "Max. offene Positionen"),
])
def test_rejections(kw, rule):
    r = evaluate(ctx(**kw))
    assert not r.approved
    assert r.rule == rule
    assert r.stamp == ""


def test_peak_drawdown():
    r = evaluate(ctx(equity=D(9000), day_start_equity=D(9000), peak_equity=D(10000)))
    assert r.rule == "Maximaler Drawdown"


def test_reduced_by_reserve_and_budget():
    r = evaluate(ctx(cash=D(1500)))
    assert r.result == "verkleinert"
    assert r.qty * 100 <= D(500)  # 1500 − 10 % Reserve von 10 000
    r = evaluate(ctx(strategy_weight=0.1))  # 10 % von 5 % = 50 € Risiko → 10 Stück
    assert r.qty == D(10)
    r = evaluate(ctx(risk_factor=0.5, risk_factor_note="hohe Volatilität"))
    assert r.result == "verkleinert" and r.qty == D(10)


def test_exit_allowed_when_paused():
    r = evaluate(ctx(kind="ausstieg", side="verkauf", state="GESPERRT", exit_qty=D(1)))
    assert r.approved


def test_module_budget():
    r = evaluate(ctx(kind="modul", stop=None, amount=D(1000), module_value=D(2500)))
    assert r.approved and r.qty == D(5)  # Budget 30 % = 3000 €, gebunden 2500 €
    r = evaluate(ctx(kind="modul", stop=None, amount=D(1000), module_value=D(3000)))
    assert not r.approved and r.rule == "Budget je Ertragsmodul"


def test_counterparty_limit():
    risk = {**default_config()["risk"], "total_capital_eur": 15000}
    r = evaluate(ctx(risk=risk))
    assert r.rule == "Gegenparteilimit"
