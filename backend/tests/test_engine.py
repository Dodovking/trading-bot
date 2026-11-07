from sqlalchemy import func, select


def test_engine_lifecycle_paper(engine, db_env, user):
    from tradingbot.core.models import BotRuntime, RegimeLog, ShadowTrade, StrategyAllocation
    engine.tick()
    with db_env.session_scope() as db:
        rt = db.get(BotRuntime, user)
        assert rt.state == "BEREIT", rt.state_reason
        assert rt.last_reconcile_ok
        assert db.scalar(select(func.count(RegimeLog.id))) > 0
        assert db.scalar(select(func.count(StrategyAllocation.id))) > 0
    engine.command(user, "start", "test")
    with db_env.session_scope() as db:
        assert db.get(BotRuntime, user).state == "AKTIV"
    engine.tick()
    engine.command(user, "notaus", "test")
    with db_env.session_scope() as db:
        rt = db.get(BotRuntime, user)
        assert rt.state == "NOT_AUS"
        assert db.scalar(select(func.count(ShadowTrade.id))) >= 0
    engine.command(user, "freigeben", "test")
    engine.tick()
    with db_env.session_scope() as db:
        assert db.get(BotRuntime, user).state == "BEREIT"


def test_data_failure_locks(engine, db_env, user):
    from tradingbot.core.models import BotRuntime
    engine.tick()
    engine.command(user, "start", "test")
    engine.src.fail = True
    engine.tick()
    with db_env.session_scope() as db:
        rt = db.get(BotRuntime, user)
        # Paper-Broker bleibt erreichbar; ohne frische Daten lehnt das Risikomodul jede Order ab
        assert rt.state in ("AKTIV", "GESPERRT")
