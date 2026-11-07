import pytest
from fastapi.testclient import TestClient

H = {"x-requested-with": "tradingbot"}


@pytest.fixture()
def client(db_env, monkeypatch):
    from tradingbot.core.settings import settings
    monkeypatch.setattr(settings, "engine_enabled", False)
    monkeypatch.setattr(dbm_init := db_env, "init_engine", lambda *a, **k: None)
    from tradingbot.main import app
    with TestClient(app) as c:
        yield c
    _ = dbm_init


def setup_admin(c):
    r = c.post("/api/auth/setup", json={"username": "dominik", "display_name": "Dominik", "email": "d@x.de",
                                        "password": "GeheimesPasswort1"})
    assert r.status_code == 200, r.text
    return r


def test_terms_gate_and_flow(client):
    assert client.get("/api/auth/status").json()["needs_setup"]
    setup_admin(client)
    # Ohne AGB-Zustimmung keine Nutzung
    assert client.get("/api/dashboard").status_code == 451
    t = client.get("/api/auth/terms").json()
    assert "Totalverlust" in t["agb"] and "Gewinnbeteiligung" in t["agb"]
    assert client.post("/api/auth/terms/accept", json={"version": t["version"], "agb": True, "datenschutz": True, "risiko": False},
                       headers=H).status_code == 400
    r = client.post("/api/auth/terms/accept", json={"version": t["version"], "agb": True, "datenschutz": True, "risiko": True}, headers=H)
    assert r.json()["terms_accepted"]
    d = client.get("/api/dashboard")
    assert d.status_code == 200 and d.json()["mode"] == "paper"


def test_csrf_and_login(client):
    setup_admin(client)
    assert client.post("/api/auth/logout").status_code == 403  # ohne Header
    assert client.post("/api/auth/logout", headers=H).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "dominik", "password": "falsch"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "dominik", "password": "GeheimesPasswort1"})
    assert r.status_code == 200 and r.json()["token"]


def test_config_preview_then_confirm(client):
    setup_admin(client)
    v = client.get("/api/auth/terms").json()["version"]
    client.post("/api/auth/terms/accept", json={"version": v, "agb": True, "datenschutz": True, "risiko": True}, headers=H)
    c = client.get("/api/config").json()
    cfg = c["config"]
    cfg["risk"]["risk_per_trade_pct"] = 2.0
    p = client.post("/api/config", json={"config": cfg, "base_version_id": c["version_id"]}, headers=H).json()
    assert p["preview"] and any("Risiko pro Trade" in x and "1.0 → 2.0" in x for x in p["changes"]) and p["warnings"]
    assert client.get("/api/config").json()["config"]["risk"]["risk_per_trade_pct"] == 1.0
    s = client.post("/api/config", json={"config": cfg, "base_version_id": c["version_id"], "confirm": True}, headers=H).json()
    assert not s["preview"]
    assert client.get("/api/config").json()["config"]["risk"]["risk_per_trade_pct"] == 2.0
    # veraltete Version (anderes Gerät) wird abgelehnt
    r = client.post("/api/config", json={"config": cfg | {"automation": "signale"}, "base_version_id": c["version_id"], "confirm": True},
                    headers=H)
    assert r.status_code == 409


def test_invited_user_needs_own_terms_and_no_live(client):
    setup_admin(client)
    v = client.get("/api/auth/terms").json()["version"]
    client.post("/api/auth/terms/accept", json={"version": v, "agb": True, "datenschutz": True, "risiko": True}, headers=H)
    link = client.post("/api/admin/invite", json={"display_name": "Max", "email": "m@x.de"}, headers=H).json()["link"]
    token = link.rsplit("/", 1)[1]
    client.post("/api/auth/logout", headers=H)
    r = client.post("/api/auth/invite", json={"token": token, "username": "max", "password": "NochEinPasswort2"})
    assert r.status_code == 200
    assert client.get("/api/dashboard").status_code == 451
    client.post("/api/auth/terms/accept", json={"version": v, "agb": True, "datenschutz": True, "risiko": True}, headers=H)
    assert client.get("/api/dashboard").status_code == 200
    r = client.post("/api/accounts/live", json={"broker": "kraken", "key": "k" * 20, "secret": "s" * 20}, headers=H)
    assert r.status_code == 403
    assert client.get("/api/admin/users").status_code == 403


def test_setup_code_required(client, monkeypatch):
    from tradingbot.core.settings import settings
    monkeypatch.setattr(settings, "setup_code", "abc123")
    assert client.get("/api/auth/status").json()["setup_code_required"]
    body = {"username": "dominik", "display_name": "Dominik", "email": "d@x.de", "password": "GeheimesPasswort1"}
    assert client.post("/api/auth/setup", json=body | {"code": "falsch"}).status_code == 403
    assert client.post("/api/auth/setup", json=body | {"code": "abc123"}).status_code == 200
