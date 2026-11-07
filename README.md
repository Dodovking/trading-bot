# Trading-Bot

Eigenständiger Trading-Bot mit einer gemeinsamen Oberfläche für PC (Windows/Mac) und iPhone.
Ein zentraler Server (FastAPI + SQLite) führt den Bot rund um die Uhr aus; alle Geräte sehen über
REST/WebSocket denselben Stand. Fachliche Grundlage: „Trading-Bot – Anforderungen und Architektur“ v2.5.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `backend/tradingbot/data` | Marktdaten (Kraken), Datenqualität |
| `backend/tradingbot/strategies` | Strategiebibliothek (Trendfolge, Momentum, Mean Reversion, Ausbruch, Swing, Range) |
| `backend/tradingbot/selection` | Regime-Erkennung, Schattenbetrieb, Scorecards, Meta-Controller |
| `backend/tradingbot/risk` | Risikomodul (feste Prüfreihenfolge, Veto, Positionsgröße) |
| `backend/tradingbot/execution` | Order-Manager, Abgleich (Reconciliation) |
| `backend/tradingbot/brokers` | Paper-Broker, Kraken, Anbieterkatalog mit Anleitungen |
| `backend/tradingbot/earn` | Ertragsmodule (Sparplan, Rebalancing, Zins-Vergleich) |
| `backend/tradingbot/backtest` | Backtest mit Kosten, In-/Out-of-Sample |
| `backend/tradingbot/api` | Login/2FA/AGB, REST, WebSocket, Admin |
| `backend/tradingbot/legal` | AGB, Datenschutz, Impressum (Entwürfe) |
| `frontend/` | React/Vite-PWA (Desktop + iPhone) |

## Lokal starten

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt pytest
(cd frontend && npm ci && npm run build)
cd backend && DATA_DIR=../data ../.venv/bin/uvicorn tradingbot.main:app --port 8000
```

Tests: `.venv/bin/pytest -q backend/tests`

## Fly.io

`fly.toml` startet genau **eine** Maschine (der Bot läuft im Prozess, nicht skalieren) mit Volume `tbdata` unter `/data`.
Secrets: `MASTER_KEY` (Verschlüsselung der API-Schlüssel), `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` (Push),
`SETUP_CODE` (schützt die Ersteinrichtung des Admin-Kontos).

```bash
fly deploy --remote-only
```

## Sicherheit

- Start immer im Paper-Modus; Echtgeld nur nach Verbindungstest und ausdrücklicher Bestätigung.
- API-Schlüssel ohne Auszahlungsrechte; verschlüsselt gespeichert.
- Kein Hebel, keine Derivate, keine Leerverkäufe.
- AGB/Datenschutz sind Entwürfe und vor der Nutzung durch Dritte anwaltlich zu prüfen.
