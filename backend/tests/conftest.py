from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("MASTER_KEY", "dGVzdC1tYXN0ZXIta2V5LWZvci10ZXN0cy0wMDAwMDA=")


class FakeSource:
    """Deterministische Kursdaten: Aufwärtstrend mit Rauschen, Uhr steuerbar."""

    name = "Test"

    def __init__(self, start_price: float = 30000, drift: float = 0.0008, seed: int = 1):
        self.now = datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0)
        self.start_price, self.drift, self.seed = start_price, drift, seed
        self.fail = False
        self.price_override: dict[str, Decimal] = {}

    def _series(self, sym: str, hours: int = 900):
        key = (sym, self.now, hours)
        if getattr(self, "_cache_key", None) == key:
            return self._cache
        self._cache_key, self._cache = key, self._series_calc(sym, hours)
        return self._cache

    def _series_calc(self, sym: str, hours: int):
        rnd = random.Random(f"{self.seed}{sym}")
        end = self.now.replace(minute=0)
        p = self.start_price
        out = []
        for i in range(hours):
            t = end - timedelta(hours=hours - i)
            o = p
            p = p * (1 + self.drift + 0.006 * math.sin(i / 7) + rnd.gauss(0, 0.004))
            h, lo = max(o, p) * (1 + abs(rnd.gauss(0, 0.002))), min(o, p) * (1 - abs(rnd.gauss(0, 0.002)))
            out.append((t, o, h, lo, p))
        return out

    def tickers(self, broker_symbols):
        from tradingbot.data.sources import DataSourceError, Ticker
        if self.fail:
            raise DataSourceError("Testausfall")
        res = {}
        for sym, bsym in broker_symbols.items():
            last = self.price_override.get(sym) or Decimal(str(round(self._series(sym)[-1][4], 2)))
            res[sym] = Ticker(sym, last * Decimal("0.9998"), last * Decimal("1.0002"), last, Decimal("5000000"),
                              datetime.now(timezone.utc))
        return res

    def candles(self, broker_symbol, timeframe, since=None):
        from tradingbot.data.sources import DataSourceError, RawCandle
        if self.fail:
            raise DataSourceError("Testausfall")
        s = self._series(broker_symbol)
        step = {"1h": 1, "4h": 4, "1d": 24, "15m": 1}[timeframe]
        rows = []
        for j in range(len(s) % step, len(s) - step + 1, step):
            chunk = s[j:j + step]
            t = chunk[0][0]
            if step == 4 and t.hour % 4:
                continue
            rows.append(RawCandle(t, *(Decimal(str(round(x, 2))) for x in (chunk[0][1], max(c[2] for c in chunk),
                                                                             min(c[3] for c in chunk), chunk[-1][4])),
                                  Decimal("100")))
        rows = [r for r in rows if r.time + timedelta(hours=step) <= self.now]
        forming = rows[-1].time + timedelta(hours=step) if rows else None
        return rows[-720:], forming

    def pair_info(self, broker_symbols):
        return {}


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from tradingbot.core import db as dbm
    from tradingbot.core.settings import settings
    settings.data_dir = tmp_path
    dbm.init_engine(f"sqlite:///{tmp_path / 't.db'}")
    yield dbm


@pytest.fixture()
def user(db_env):
    from tradingbot.core.models import User
    with db_env.session_scope() as db:
        u = User(username="dominik", email="d@example.com", display_name="Dominik", role="admin")
        db.add(u)
        db.flush()
        return u.id


@pytest.fixture()
def engine(db_env, user):
    from tradingbot.data.instruments import seed_instruments
    from tradingbot.data.market import MarketData
    from tradingbot.engine import Engine
    with db_env.session_scope() as db:
        seed_instruments(db)
    src = FakeSource()
    e = Engine(MarketData(src))
    e.src = src
    return e
