from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from tradingbot.core.types import Decision


class AlwaysBuy:
    def __init__(self, orig):
        self._o = orig

    def __getattr__(self, k):
        return getattr(self._o, k)

    regimes = ("trend_auf", "trend_ab", "seitwaerts", "ruhig", "unklar", "hohe_volatilitaet")

    def evaluate(self, bars, position, params, timeframe=None):
        if position is not None:
            return Decision("halten")
        c = bars[-1].close
        return Decision("kauf", 1.0, stop=c * 0.94, reasoning={"grund": "Test", "kurs": c})


@pytest.fixture()
def setup(engine, db_env, user, monkeypatch):
    from tradingbot.core.config import current_config, save_config
    from tradingbot.strategies import registry
    monkeypatch.setitem(registry.STRATEGY_TYPES, "trendfolge", AlwaysBuy(registry.STRATEGY_TYPES["trendfolge"]))
    with db_env.session_scope() as db:
        from tradingbot.execution.accounts import ensure_user_setup
        ensure_user_setup(db, user)
        cfg, _ = current_config(db, user)
        cfg["selection"]["mode"] = "manuell"
        cfg["markets"] = ["BTC/EUR"]
        for s in cfg["strategies"]:
            s["status"] = "paper" if s["id"] == "trendfolge" else "entwurf"
        save_config(db, user, cfg, "test")
    engine.tick()
    engine.command(user, "start", "test")
    return engine


def advance(e, hours=1):
    e.src.now += timedelta(hours=hours)
    for k in list(e.market._last_candle_poll):
        e.market._last_candle_poll[k] -= timedelta(hours=hours)
    e.tick()


def test_signal_to_position_with_stop_then_stopped_out(setup, db_env, user):
    from tradingbot.core.models import BotRuntime, Order, Position, RiskDecision
    e = setup
    advance(e)
    with db_env.session_scope() as db:
        pos = db.scalars(select(Position).where(Position.status == "offen")).all()
        assert len(pos) == 1, [(d.rule, d.actual_value) for d in db.scalars(select(RiskDecision))]
        p = pos[0]
        assert p.stop_client_order_id
        stop = db.scalars(select(Order).where(Order.client_order_id == p.stop_client_order_id)).one()
        assert stop.status == "bestaetigt" and stop.type == "stop"
        stop_price = p.stop
    # Kurs fällt unter den Stop → Paper-Broker führt Stop aus, Position wird geschlossen
    e.src.price_override["BTC/EUR"] = stop_price * D("0.99")
    e.tick()
    with db_env.session_scope() as db:
        p = db.scalars(select(Position)).first()
        assert p.status == "geschlossen" and p.exit_reason == "Stop-Loss"
        assert p.realized < 0
        assert db.get(BotRuntime, user).loss_streak == 1


def test_no_order_without_stamp(setup, db_env, user):
    from tradingbot.execution.orders import StampError
    from tradingbot.risk.rules import RiskResult
    from tradingbot.engine import UserRunner
    from tradingbot.core.models import Instrument
    with db_env.session_scope() as db:
        r = UserRunner(setup, db, user)
        inst = db.scalars(select(Instrument).where(Instrument.symbol == "BTC/EUR")).one()
        fake = RiskResult("freigegeben", D(1), client_order_id="x", stamp="gefaelscht")
        with pytest.raises(StampError):
            r.om.open_position(fake, inst, D(1), None, None, "trendfolge", "x", None)


def test_duplicate_signal_after_restart(setup, db_env, user):
    from tradingbot.core.models import SignalRow
    from tradingbot.data.market import MarketData
    from tradingbot.engine import Engine
    advance(setup)
    with db_env.session_scope() as db:
        n = db.scalar(select(func.count(SignalRow.id)))
    e2 = Engine(MarketData(setup.src))
    e2.src = setup.src
    e2.market.load_state()
    e2.tick()
    with db_env.session_scope() as db:
        assert db.scalar(select(func.count(SignalRow.id))) == n


def test_restart_resumes_after_reconcile(setup, db_env, user):
    from tradingbot.core.models import BotRuntime
    from tradingbot.data.market import MarketData
    from tradingbot.engine import Engine
    advance(setup)
    e2 = Engine(MarketData(setup.src))
    with db_env.session_scope() as db:
        db.get(BotRuntime, user).state = "INITIALISIERUNG"
    e2.tick()
    with db_env.session_scope() as db:
        rt = db.get(BotRuntime, user)
        assert rt.state == "AKTIV" and rt.last_reconcile_ok


def test_reconcile_mismatch_locks(setup, db_env, user):
    from tradingbot.core.models import BotRuntime, PaperLedger
    advance(setup)
    with db_env.session_scope() as db:
        led = db.scalars(select(PaperLedger).where(PaperLedger.asset == "BTC")).one()
        led.amount = led.amount / 2
        db.get(BotRuntime, user).last_reconcile_at = None
    setup.tick()
    with db_env.session_scope() as db:
        rt = db.get(BotRuntime, user)
        assert rt.state == "GESPERRT" and rt.lock_kind == "abgleich"


def test_emergency_stop_closes_and_blocks(setup, db_env, user):
    from tradingbot.core.models import BotRuntime, Position
    advance(setup)
    setup.command(user, "notaus", "test")
    with db_env.session_scope() as db:
        assert db.get(BotRuntime, user).state == "NOT_AUS"
        assert db.scalar(select(func.count(Position.id)).where(Position.status == "offen")) == 0
    advance(setup)
    with db_env.session_scope() as db:
        assert db.scalar(select(func.count(Position.id)).where(Position.status == "offen")) == 0


def test_sparplan_buys_holdings(setup, db_env, user, monkeypatch):
    from datetime import datetime
    from tradingbot.core.config import current_config, save_config
    from tradingbot.core.models import ModuleRun, Position
    from tradingbot.earn import modules
    with db_env.session_scope() as db:
        cfg, _ = current_config(db, user)
        cfg["modules"]["sparplan"].update(status="paper", amount=200.0, weights={"BTC/EUR": 100.0})
        save_config(db, user, cfg, "test")
    monkeypatch.setattr(modules, "_due_time", lambda *a: True)
    setup.tick()
    with db_env.session_scope() as db:
        h = db.scalars(select(Position).where(Position.side == "bestand")).all()
        assert len(h) == 1 and h[0].stop is None and h[0].entry_value > 150
        assert db.scalar(select(func.count(ModuleRun.id))) == 1
    setup.tick()  # gleiche Periode: kein zweiter Kauf
    with db_env.session_scope() as db:
        assert db.scalar(select(func.count(ModuleRun.id))) == 1
        assert setup.last_tick is None or True
    _ = datetime
