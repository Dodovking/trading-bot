from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import httpx
import pytest

from tradingbot.brokers.alpaca import AlpacaBroker, root_id
from tradingbot.brokers.base import OrderRequest
from tradingbot.data import sessions
from tradingbot.data.composite import CompositeSource
from tradingbot.data.sources import DataSourceError
from tradingbot.data.stocks import AlpacaData, Fx

UTC = timezone.utc


def test_sessions_regular_day_and_dst():
    s = sessions.session(date(2026, 11, 9))  # Montag, Winterzeit New York
    assert s[0] == datetime(2026, 11, 9, 14, 30, tzinfo=UTC) and s[1] == datetime(2026, 11, 9, 21, 0, tzinfo=UTC)
    s = sessions.session(date(2026, 7, 6))  # Sommerzeit
    assert s[0] == datetime(2026, 7, 6, 13, 30, tzinfo=UTC)


def test_sessions_weekend_holiday_early_close():
    assert sessions.session(date(2026, 11, 7)) is None  # Samstag
    assert sessions.session(date(2026, 11, 26)) is None  # Thanksgiving
    assert sessions.session(date(2026, 11, 27))[1] == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)  # 13:00 ET
    sat = datetime(2026, 11, 7, 12, tzinfo=UTC)
    assert not sessions.is_open(sat)
    assert sessions.next_open(sat) == datetime(2026, 11, 9, 14, 30, tzinfo=UTC)
    assert "Mo" in sessions.open_label(sat) and "15:30" in sessions.open_label(sat)
    assert sessions.is_open(datetime(2026, 11, 9, 15, tzinfo=UTC))
    assert sessions.tradable(datetime(2026, 11, 9, 21, 10, tzinfo=UTC)) and not sessions.is_open(datetime(2026, 11, 9, 21, 10, tzinfo=UTC))


def test_session_seconds_skips_weekend():
    a, b = datetime(2026, 11, 6, 20, 0, tzinfo=UTC), datetime(2026, 11, 9, 15, 30, tzinfo=UTC)
    assert sessions.session_seconds(a, b) == 3600 + 3600


def _fx():
    fx = Fx(live_fn=lambda: D("1.10"), client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"rates": {"2026-11-05": {"EUR": 0.9}, "2026-11-06": {"EUR": 0.8}}}))))
    return fx


def test_alpaca_requires_keys():
    a = AlpacaData(_fx(), keys_fn=lambda: None)
    assert not a.ready()
    with pytest.raises(DataSourceError, match="Alpaca-Schlüssel"):
        a.tickers(["AAPL"])


def test_alpaca_tickers_converted_to_eur():
    seen = {}

    def handler(r: httpx.Request):
        seen["h"] = r.headers.get("APCA-API-KEY-ID")
        return httpx.Response(200, json={"AAPL": {"latestTrade": {"p": 220.0}, "latestQuote": {"bp": 219.98, "ap": 220.02},
                                                  "dailyBar": {"c": 220.0, "v": 1000}}, "MSFT": None})
    a = AlpacaData(_fx(), keys_fn=lambda: ("k", "s"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    t = a.tickers(["AAPL", "MSFT"])
    assert seen["h"] == "k" and set(t) == {"AAPL"}
    assert t["AAPL"].last == D("220.0") / D("1.10") and t["AAPL"].bid < t["AAPL"].ask


def test_alpaca_bad_keys():
    a = AlpacaData(_fx(), keys_fn=lambda: ("k", "s"), client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    with pytest.raises(DataSourceError, match="ungültig"):
        a.tickers(["AAPL"])


def test_alpaca_hourly_candles_regular_hours_and_fx():
    bars = [{"t": "2026-11-06T13:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},  # 8:00 ET vorbörslich
            {"t": "2026-11-06T14:00:00Z", "o": 100, "h": 110, "l": 90, "c": 105, "v": 10},  # 9:00 ET (enthält 9:30)
            {"t": "2026-11-06T20:00:00Z", "o": 105, "h": 106, "l": 104, "c": 105, "v": 5},  # 15:00 ET
            {"t": "2026-11-06T21:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]  # nachbörslich
    a = AlpacaData(_fx(), keys_fn=lambda: ("k", "s"),
                   client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"bars": bars}))))
    rows, due = a.candles("AAPL", "1h", now=datetime(2026, 11, 7, 12, tzinfo=UTC))
    assert [r.time.hour for r in rows] == [14, 20]
    assert rows[0].close == D(105) * D("0.8")
    rows4, _ = a.candles("AAPL", "4h", now=datetime(2026, 11, 7, 12, tzinfo=UTC))
    assert len(rows4) == 2 and rows4[0].high == D(110) * D("0.8")
    assert due + timedelta(hours=1) > datetime(2026, 11, 9, 14, 30, tzinfo=UTC)


class _K:
    name = "k"

    def tickers(self, m):
        return {s: f"kraken:{b}" for s, b in m.items()}

    def candles(self, b, tf, since=None):
        return ("kraken", b)

    def pair_info(self, bs):
        return bs


def test_composite_routes_by_market():
    al = AlpacaData(_fx(), keys_fn=lambda: None)
    c = CompositeSource(kraken=_K(), alpaca=al)
    out = c.tickers({"BTC/EUR": "BTCEUR", "AAPL": "AAPL"})
    assert out == {"BTC/EUR": "kraken:BTCEUR"} and "Alpaca" in c.stock_error
    assert c.pair_info(["BTCEUR", "AAPL"]) == ["BTCEUR"]
    assert c.candles("ETHEUR", "1h") == ("kraken", "ETHEUR")
    assert not c.stocks_ready()


def test_alpaca_broker_orders():
    calls = []

    def handler(r: httpx.Request):
        calls.append((r.method, r.url.path, r.content))
        if r.url.path == "/v2/account":
            return httpx.Response(200, json={"status": "ACTIVE", "currency": "USD", "cash": "1100"})
        if r.url.path == "/v2/positions":
            return httpx.Response(200, json=[{"symbol": "AAPL", "qty": "3", "asset_class": "us_equity"}])
        if r.method == "POST":
            return httpx.Response(200, json={"id": "o1", "client_order_id": "abc", "status": "filled", "filled_qty": "2",
                                             "filled_avg_price": "220"})
        return httpx.Response(404)
    b = AlpacaBroker("k", "s", "paper", lambda: D("1.10"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert "Paper" in b.check_connection()
    assert b.balances() == {"EUR": D(1000), "AAPL": D(3)}
    st = b.submit(OrderRequest("abc", "AAPL", "AAPL", "kauf", "market", D(2)))
    assert st.status == "ausgefuehrt" and st.avg_price == D(200) and st.fills[0].qty == D(2)
    assert calls[-1][1] == "/v2/orders" and b'"qty":"2"' in calls[-1][2].replace(b" ", b"")
    b.submit(OrderRequest("f1", "AAPL", "AAPL", "kauf", "market", D("0.0456789")))
    assert b'"qty":"0.0456789"' in calls[-1][2].replace(b" ", b"")
    b.submit(OrderRequest("f2", "AAPL", "AAPL", "verkauf", "stop", D("0.0456789"), D(190)))
    body = calls[-1][2].replace(b" ", b"")
    assert b'"time_in_force":"day"' in body and b'"stop_price":"209.00"' in body  # Bruchteil: Tages-Stop
    b.submit(OrderRequest("f3", "AAPL", "AAPL", "verkauf", "stop", D(2), D(190)))
    assert b'"time_in_force":"gtc"' in calls[-1][2].replace(b" ", b"")
    with pytest.raises(Exception, match="zu klein"):
        b.submit(OrderRequest("x", "AAPL", "AAPL", "kauf", "market", D("0.0000000001")))
    assert root_id("abc-r123") == "abc" and b.query("zzz").status == "unbekannt"


def test_stock_health_needs_keys_and_open_market():
    from tradingbot.data.market import MarketData
    from tradingbot.data.sources import Ticker

    class Src:
        name = "x"
        ready = False

        def stocks_ready(self):
            return self.ready
    src = Src()
    m = MarketData(src)
    assert not m.usable("AAPL") and m.usable("BTC/EUR")
    h = m.health("AAPL", None, 60, 3)
    assert not h.ok and "Alpaca" in h.reason
    src.ready = True
    sat = datetime(2026, 11, 7, 15, tzinfo=UTC)
    m.tickers["AAPL"] = Ticker("AAPL", D(199), D(200), D(200), D(10**7), sat)
    h = m.health("AAPL", None, 60, 3, now=sat)
    assert not h.ok and "geschlossen" in h.reason
    mon = datetime(2026, 11, 9, 16, tzinfo=UTC)
    m.tickers["AAPL"] = Ticker("AAPL", D(199), D(200), D(200), D(10**7), mon)
    m.last_closed[("AAPL", "1h")] = datetime(2026, 11, 6, 20, tzinfo=UTC)  # Freitag 15:00 ET
    assert m.health("AAPL", "1h", 60, 3, now=mon).ok  # Wochenende zählt nicht als Datenalter


def test_router_routes_by_market_and_cash_per_venue():
    from tradingbot.brokers.base import BrokerOrderStatus, BrokerRejected, OrderRequest
    from tradingbot.brokers.router import RouterBroker

    class B:
        def __init__(self, name, bal):
            self.name, self.bal, self.sent = name, bal, []

        def balances(self):
            return dict(self.bal)

        def submit(self, req):
            self.sent.append(req.symbol)
            return BrokerOrderStatus(req.client_order_id, self.name, "offen")

        def query(self, coid, boid=None):
            return BrokerOrderStatus(coid, self.name, "offen" if coid.startswith(self.name) else "unbekannt")

        def open_stop_orders(self):
            return [BrokerOrderStatus(self.name + "-stop", None, "offen")]

    k, a = B("k", {"EUR": D(4), "BTC": D("0.001")}), B("a", {"EUR": D(500), "AAPL": D(2)})
    r = RouterBroker({"krypto": ("Kraken", k), "aktie": ("Alpaca", a)}, lambda coid: None)
    assert r.balances() == {"EUR": D(504), "BTC": D("0.001"), "AAPL": D(2)}
    assert r.cash("krypto") == D(4) and r.cash("aktie") == D(500)
    r.submit(OrderRequest("x1", "AAPL", "AAPL", "kauf", "market", D(1)))
    r.submit(OrderRequest("x2", "BTC/EUR", "XBTEUR", "kauf", "market", D("0.0001")))
    assert a.sent == ["AAPL"] and k.sent == ["BTC/EUR"]
    assert r.query("a-123").broker_order_id == "a" and r.query("k-1").broker_order_id == "k"
    assert len(r.open_stop_orders()) == 2
    only = RouterBroker({"krypto": ("Kraken", k)})
    try:
        only.submit(OrderRequest("x3", "AAPL", "AAPL", "kauf", "market", D(1)))
        raise AssertionError
    except BrokerRejected as e:
        assert "Aktien" in str(e)
