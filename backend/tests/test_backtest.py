import math
from datetime import datetime, timedelta, timezone

from tradingbot.backtest.engine import BtParams, run
from tradingbot.core.types import Bar
from tradingbot.selection.simulate import Costs
from tradingbot.strategies.registry import STRATEGY_TYPES


def _bars(n=3000):
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out, p = [], 100.0
    for i in range(n):
        drift = 0.003 if (i // 500) % 2 == 0 else -0.0025
        o = p
        p = max(1.0, p * (1 + drift + 0.012 * math.sin(i / 3.0)))
        out.append(Bar(t0 + timedelta(hours=i), o, max(o, p) * 1.003, min(o, p) * 0.997, p, 1000.0))
    return out


def test_backtest_runs_and_is_consistent():
    bars = _bars()
    res = run(STRATEGY_TYPES["momentum"], {}, bars, timedelta(hours=1), BtParams(costs=Costs(0.26, 0.05, 0.1)))
    g = res["gesamt"]
    assert g["trades"] == len(res["trades_liste"]) > 0
    assert abs(g["endkapital"] - (10000 + sum(t["pnl"] for t in res["trades_liste"]))) < 1.0
    assert res["in_sample"]["trades"] + res["out_of_sample"]["trades"] == g["trades"]
    for t in res["trades_liste"]:
        assert t["eroeffnet"] < t["geschlossen"]
        assert (t["pnl"] > 0) == (t["r"] > 0) or abs(t["pnl"]) < 1


def test_costs_reduce_result():
    bars = _bars()
    cheap = run(STRATEGY_TYPES["momentum"], {}, bars, timedelta(hours=1), BtParams(costs=Costs(0.0, 0.0, 0.0)))
    dear = run(STRATEGY_TYPES["momentum"], {}, bars, timedelta(hours=1), BtParams(costs=Costs(0.5, 0.2, 0.1)))
    assert dear["gesamt"]["endkapital"] <= cheap["gesamt"]["endkapital"]
