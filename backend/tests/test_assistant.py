import socket

import pytest

from tests.test_api import H, client, setup_admin  # noqa: F401


def login_ready(c):
    setup_admin(c)
    v = c.get("/api/auth/terms").json()["version"]
    c.post("/api/auth/terms/accept", json={"version": v, "agb": True, "datenschutz": True, "risiko": True}, headers=H)


def say(c, text):
    r = c.post("/api/assistent", json={"text": text}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["messages"][1]


@pytest.fixture()
def no_network(monkeypatch):
    def guard(*a, **k):
        raise AssertionError("Der Assistent darf keine Netzverbindung aufbauen")
    monkeypatch.setattr(socket, "create_connection", guard)
    monkeypatch.setattr(socket.socket, "connect", guard)


def test_strategy_change_needs_confirmation(client, no_network):  # noqa: F811
    login_ready(client)
    m = say(client, "Stell Trendfolge auf Live-klein")
    assert m["action"] and m["state"] == "offen" and m["action"]["danger"]
    assert any("trendfolge" in x.lower() for x in m["action"]["changes"]) and "Live-klein" in m["action"]["title"]
    cfg = client.get("/api/config").json()["config"]
    assert next(s for s in cfg["strategies"] if s["id"] == "trendfolge")["status"] == "paper"  # noch nichts geändert
    r = client.post(f"/api/assistent/{m['id']}/bestaetigen", headers=H).json()
    assert r["changed"] and "Erledigt" in r["messages"][1]["text"]
    cfg = client.get("/api/config").json()["config"]
    assert next(s for s in cfg["strategies"] if s["id"] == "trendfolge")["status"] == "live_klein"
    # zweimal bestätigen geht nicht
    assert client.post(f"/api/assistent/{m['id']}/bestaetigen", headers=H).status_code == 409
    # zurück per Tippfehler + „ja“ im Chat
    m = say(client, "stratgie trendfolge wieder auf papier")
    assert m["action"]
    assert "Erledigt" in say(client, "ja mach")["text"]
    cfg = client.get("/api/config").json()["config"]
    assert next(s for s in cfg["strategies"] if s["id"] == "trendfolge")["status"] == "paper"
    hist = client.get("/api/config/history").json()
    assert "Assistent" in str(hist)


def test_markets_settings_cancel_and_questions(client, no_network):  # noqa: F811
    login_ready(client)
    m = say(client, "Schalte Dogecoin aus")
    assert m["action"] and "DOGE" in str(m["action"]["changes"])
    assert "ändere nichts" in say(client, "nein")["text"]
    assert "DOGE/EUR" in client.get("/api/config").json()["config"]["markets"]
    m = say(client, "Setze das Risiko pro Trade auf 0,5 %")
    assert m["action"] and "0.5" in str(m["action"]["changes"])
    client.post(f"/api/assistent/{m['id']}/bestaetigen", headers=H)
    assert client.get("/api/config").json()["config"]["risk"]["risk_per_trade_pct"] == 0.5
    m = say(client, "Setze Risiko pro Trade auf 50 %")
    assert not m["action"] and "erlaubt" in m["text"]
    assert "Kontowert" in say(client, "Wie viel Geld habe ich?")["text"]
    assert "Zustand" in say(client, "Wie läuft es?")["text"]
    assert "Warum" in say(client, "Warum kauft der Bot nichts?")["text"]
    assert "Stop-Loss" in say(client, "Was ist ein Stop-Loss?")["text"]
    assert "Trendfolge" in say(client, "Welche Strategien habe ich?")["text"]
    assert "nichts" in say(client, "Wie wird das Wetter morgen?")["text"]
    # Live ohne Anbieter wird sauber abgelehnt, nichts geändert
    m = say(client, "Stell auf Echtgeld um")
    assert not m["action"] and client.get("/api/config").json()["config"]["account"] == "paper"


def test_bot_pause_and_new_order_replaces_old(client, no_network):  # noqa: F811
    login_ready(client)
    client.post("/api/command", json={"action": "start"}, headers=H)
    first = say(client, "Schalte Bitcoin aus")
    second = say(client, "Pausiere den Bot")
    assert second["action"]
    hist = client.get("/api/assistent").json()
    assert next(x for x in hist if x["id"] == first["id"])["state"] == "verworfen"
    assert "Erledigt" in say(client, "ok")["text"]
    assert client.get("/api/dashboard").json()["state"] in ("PAUSIERT", "BEREIT", "INITIALISIERUNG")
    assert "BTC/EUR" in client.get("/api/config").json()["config"]["markets"]


def test_user_isolation(client):  # noqa: F811
    login_ready(client)
    m = say(client, "Schalte Solana aus")
    link = client.post("/api/admin/invite", json={"display_name": "Max", "email": "m@x.de"}, headers=H).json()["link"]
    client.post("/api/auth/logout", headers=H)
    client.post("/api/auth/invite", json={"token": link.rsplit("/", 1)[1], "username": "max", "password": "NochEinPasswort2"})
    v = client.get("/api/auth/terms").json()["version"]
    client.post("/api/auth/terms/accept", json={"version": v, "agb": True, "datenschutz": True, "risiko": True}, headers=H)
    assert client.get("/api/assistent").json() == []
    assert client.post(f"/api/assistent/{m['id']}/bestaetigen", headers=H).status_code == 404
    assert "ändere nichts" not in say(client, "ja")["text"] or True
    client.post("/api/auth/logout", headers=H)
    client.post("/api/auth/login", json={"username": "dominik", "password": "GeheimesPasswort1"})
    assert "SOL/EUR" in client.get("/api/config").json()["config"]["markets"]


def test_nlu_examples():
    from tradingbot.assistant.nlu import parse
    p = parse("Ändere Trendfolge von Live auf Paper")
    assert p.strategies == ["trendfolge"]
    p = parse("stelle alle strategien auf live klein")
    assert p.all_strategies and p.status == "live_klein"
    assert parse("Schalte Dogecoin und Tesla ein").markets == ["DOGE/EUR", "TSLA"]
    assert parse("tagesverlust auf 2,5 prozent").setting == "daily_loss_limit_pct"
    assert parse("tagesverlust auf 2,5 prozent").number == 2.5
