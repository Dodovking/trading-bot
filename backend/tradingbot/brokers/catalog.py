"""Anbieter-Katalog mit Schritt-für-Schritt-Anleitung zum Verbinden (deutsch).

status: verfuegbar (Adapter vorhanden) | in_vorbereitung (Anleitung, Adapter folgt)
"""
from __future__ import annotations

COMMON_RULES = [
    "Auszahlungs- bzw. Überweisungsrechte NIE aktivieren – der Bot braucht sie nicht.",
    "Schlüssel nur in dieser App eintragen, nicht per Chat/E-Mail weitergeben.",
    "Wenn möglich: Schlüssel auf die IP-Adresse des Servers beschränken (wird unten angezeigt).",
    "Erst „Verbindung testen“, dann mit Live-klein (¼ Risiko) beginnen.",
]

PROVIDERS = [
    {
        "id": "paper", "name": "Paper-Simulation", "markets": ["krypto", "aktien"], "status": "verfuegbar",
        "beschreibung": "Spielgeld-Konto mit echten Live-Kursen. Kein Konto und kein Schlüssel nötig.",
        "felder": [], "schritte": ["Nichts zu tun – das Paper-Konto ist sofort aktiv (10.000 € Startkapital, zurücksetzbar)."],
        "rechte": [], "links": [],
    },
    {
        "id": "kraken", "name": "Kraken", "markets": ["krypto"], "status": "verfuegbar", "region": "EU-reguliert (MiCA)",
        "beschreibung": "Große Krypto-Börse mit Euro-Paaren. Kursdaten des Bots kommen ebenfalls von Kraken.",
        "felder": [{"id": "key", "label": "API-Key"}, {"id": "secret", "label": "Private Key (Secret)"}],
        "schritte": [
            "Bei kraken.com anmelden und das Konto vollständig verifizieren (Ausweis).",
            "Oben rechts auf das Profil → „Einstellungen“ → „API“ (bzw. „Connections & API“).",
            "„API-Schlüssel erstellen“ wählen und einen Namen vergeben, z. B. „Trading-Bot“.",
            "Rechte setzen: „Guthaben abfragen“, „Offene/geschlossene Orders und Trades abfragen“, "
            "„Orders erstellen und ändern“, „Orders stornieren“. NICHT: „Guthaben auszahlen“, „Einzahlen“, „Staking“.",
            "Optional: Unter „IP-Whitelist“ die Server-IP eintragen.",
            "„Schlüssel generieren“ – API-Key und Private Key werden nur einmal angezeigt. Beide hier einfügen.",
            "„Verbindung testen“ klicken: Der Bot liest das Guthaben und prüft, dass keine Auszahlungsrechte bestehen.",
        ],
        "rechte": ["Query Funds", "Query Open/Closed Orders & Trades", "Create & Modify Orders", "Cancel/Close Orders"],
        "links": [{"label": "Kraken: API-Schlüssel erstellen", "url": "https://support.kraken.com/articles/360000919966"}],
    },
    {
        "id": "binance", "name": "Binance", "markets": ["krypto"], "status": "in_vorbereitung",
        "beschreibung": "Größte Krypto-Börse weltweit. Nur Spot-Handel (kein Hebel, keine Futures).",
        "felder": [{"id": "key", "label": "API Key"}, {"id": "secret", "label": "Secret Key"}],
        "schritte": [
            "Bei binance.com anmelden; Identitätsprüfung und 2FA müssen aktiv sein.",
            "Profil → „Kontoverwaltung“ → „API-Verwaltung“ → „API erstellen“ → „Vom System generiert“.",
            "Namen vergeben, Sicherheitsprüfung bestätigen.",
            "Unter „Einschränkungen bearbeiten“: „Lesen aktivieren“ und „Spot- und Margin-Handel aktivieren“ anhaken. "
            "NICHT anhaken: „Auszahlungen aktivieren“, „Margin-Kredit“, „Futures“, „Universal Transfer“.",
            "„Zugriff nur auf vertrauenswürdige IPs beschränken“ wählen und die Server-IP eintragen (Binance verlangt das für Handelsrechte).",
            "API Key und Secret Key hier einfügen und „Verbindung testen“.",
        ],
        "rechte": ["Enable Reading", "Enable Spot & Margin Trading (nur Spot genutzt)"],
        "links": [{"label": "Binance: API-Schlüssel erstellen", "url": "https://www.binance.com/de/support/faq/detail/360002502072"}],
    },
    {
        "id": "coinbase", "name": "Coinbase (Advanced Trade)", "markets": ["krypto"], "status": "in_vorbereitung",
        "beschreibung": "Bekannte Krypto-Börse, in der EU reguliert. Handel über die Advanced-Trade-API.",
        "felder": [{"id": "key", "label": "API-Key-Name (organizations/…/apiKeys/…)"}, {"id": "secret", "label": "Private Key (-----BEGIN EC PRIVATE KEY-----…)"}],
        "schritte": [
            "Bei coinbase.com anmelden und das Developer-Portal öffnen (portal.cdp.coinbase.com) → „API Keys“.",
            "„Create API key“ wählen, Portfolio auswählen, Name vergeben.",
            "Rechte: „View“ und „Trade“. NICHT: „Transfer“.",
            "Unter „Advanced Settings“ als Signaturverfahren „ECDSA“ wählen und optional die Server-IP freigeben.",
            "Den Key-Namen und den Private Key (inkl. BEGIN/END-Zeilen) hier einfügen und „Verbindung testen“.",
        ],
        "rechte": ["View", "Trade"],
        "links": [{"label": "Coinbase: API-Schlüssel", "url": "https://docs.cdp.coinbase.com/coinbase-app/docs/getting-started"}],
    },
    {
        "id": "bitvavo", "name": "Bitvavo", "markets": ["krypto"], "status": "in_vorbereitung", "region": "EU (Niederlande)",
        "beschreibung": "Europäische Krypto-Börse mit Euro-Paaren und niedrigen Gebühren.",
        "felder": [{"id": "key", "label": "API-Key"}, {"id": "secret", "label": "API-Secret"}],
        "schritte": [
            "Bei bitvavo.com anmelden → Profil → „Einstellungen“ → „API“.",
            "„Neuen API-Schlüssel anfordern“, Namen vergeben.",
            "Rechte: „Anzeigen“ und „Handeln“. NICHT: „Auszahlen“.",
            "Die Server-IP als vertrauenswürdige IP eintragen.",
            "Bestätigung per E-Mail abschließen, dann Key und Secret hier einfügen und „Verbindung testen“.",
        ],
        "rechte": ["View", "Trade"],
        "links": [{"label": "Bitvavo: API", "url": "https://support.bitvavo.com/hc/de"}],
    },
    {
        "id": "alpaca", "name": "Alpaca", "markets": ["aktien"], "status": "verfuegbar", "region": "US-Aktien und ETFs",
        "beschreibung": "Aktien-/ETF-Broker mit offizieller API und kostenlosem Paper-Konto (Spielgeld). Liefert auch die Aktienkurse "
                        "für den Bot. Handel zu US-Börsenzeiten (15:30–22:00 Uhr deutscher Zeit); das Risikomodul beachtet die "
                        "Handelszeiten automatisch. Kurse werden in Euro umgerechnet. Der Bot kauft auch Bruchteile von Aktien (ab ca. 1 €), "
                        "dafür muss im Alpaca-Konto „Fractional Trading“ aktiv sein (Standard).",
        "felder": [{"id": "key", "label": "API Key ID"}, {"id": "secret", "label": "Secret Key"},
                   {"id": "umgebung", "label": "Umgebung", "optionen": ["paper", "live"]}],
        "schritte": [
            "Auf alpaca.markets oben rechts „Sign Up“ wählen, mit E-Mail registrieren und die E-Mail bestätigen. Für das Paper-Konto "
            "(Spielgeld) ist keine Ausweisprüfung nötig; für Echtgeld ist eine Kontoeröffnung mit Identitätsprüfung nötig.",
            "Nach dem Login oben links „Paper“ auswählen (für Echtgeld „Live“) – jede Umgebung hat eigene Schlüssel.",
            "Rechts auf der Übersichtsseite im Kasten „API Keys“ auf „Generate New Keys“ klicken.",
            "„API Key ID“ (Paper beginnt mit PK…) und „Secret Key“ hier einfügen. Das Secret zeigt Alpaca nur einmal an.",
            "Die passende Umgebung wählen (Paper oder Live) und „Speichern und Verbindung testen“ drücken.",
            "Ab dann bekommt der Bot Aktienkurse: Unter Einstellungen → Märkte die gewünschten Aktien einschalten. "
            "Dein Paper-Konto hier in der App handelt sie dann automatisch mit.",
        ],
        "rechte": ["Trading API (Konto, Orders, Positionen) – Alpaca-Schlüssel können keine Auszahlungen auslösen"],
        "links": [{"label": "Alpaca: Registrieren", "url": "https://app.alpaca.markets/signup"},
                  {"label": "Alpaca: Erste Schritte", "url": "https://docs.alpaca.markets/docs/getting-started"}],
    },
    {
        "id": "ibkr", "name": "Interactive Brokers", "markets": ["aktien"], "status": "in_vorbereitung",
        "region": "Weltweite Aktien/ETFs, in DE nutzbar",
        "beschreibung": "Großer Broker mit Zugang zu fast allen Börsen. Die API verlangt eine dauerhaft angemeldete Gateway-Software "
                        "mit regelmäßiger 2FA-Bestätigung – Direktanbindung folgt in einem späteren Ausbauschritt.",
        "felder": [],
        "schritte": [
            "Konto bei interactivebrokers.eu eröffnen und ein Paper-Trading-Konto aktivieren (Kontoverwaltung → Einstellungen → Paper Trading).",
            "Für den späteren Anschluss wird das „IB Gateway“ oder die „Client Portal API“ benötigt.",
            "Sobald der Adapter fertig ist, erscheint hier das Eingabefeld.",
        ],
        "rechte": [], "links": [{"label": "IBKR: API", "url": "https://www.interactivebrokers.com/en/trading/ib-api.php"}],
    },
]

BY_ID = {p["id"]: p for p in PROVIDERS}
