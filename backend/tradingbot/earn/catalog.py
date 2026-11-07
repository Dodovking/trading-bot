"""Ertragswege (Abschnitt 15) – Katalog mit Einordnung und Freigabestatus."""
from __future__ import annotations

# status: verfuegbar (ausführbar) | vergleich (nur Empfehlung) | spaeter | nicht_empfohlen
CATALOG = [
    {"id": "sparplan", "name": "Sparplan", "status": "verfuegbar", "einsatz": "Start",
     "funktion": "Regelmäßig einen festen Betrag nach Zielgewichten investieren.",
     "risiken": "Kursschwankungen; Rendite kommt langsam", "quelle": "Kursentwicklung"},
    {"id": "rebalancing", "name": "Rebalancing", "status": "verfuegbar", "einsatz": "Start",
     "funktion": "Zielgewichte des Sparplan-Bestands automatisch wiederherstellen (übergewichtete Werte verkaufen, untergewichtete kaufen).",
     "risiken": "Kursschwankungen, Gebühren je Umschichtung", "quelle": "Kursentwicklung"},
    {"id": "zins", "name": "Zins- und Staking-Optimierung", "status": "vergleich", "einsatz": "Start (nur große, regulierte Anbieter)",
     "funktion": "Zinssätze (Tagesgeld, Geldmarkt, Staking) vergleichen und das beste zulässige Angebot empfehlen.",
     "risiken": "Ausfall oder Sperrung der Plattform, Sperrfristen, Kursverlust des gesperrten Werts", "quelle": "Zinsen",
     "grund": "Automatisches Verschieben zwischen Plattformen bräuchte Auszahlungsrechte – diese bleiben laut Sicherheitsregeln deaktiviert. "
              "Der Bot zeigt deshalb nur Vergleich und Empfehlung."},
    {"id": "funding", "name": "Funding-Rate-/Basis-Arbitrage", "status": "spaeter", "einsatz": "Später, nur mit Erfahrung",
     "funktion": "Kassa kaufen und per Future absichern; Finanzierungsgebühr oder Kursdifferenz vereinnahmen.",
     "risiken": "Zwangsliquidation bei Hebel, wechselnde Gebühren, Börsenrisiko", "quelle": "Gebühren",
     "grund": "Braucht Futures/Derivate – in der ersten Version ausgeschlossen."},
    {"id": "arbitrage", "name": "Börsen-/Dreiecks-Arbitrage", "status": "spaeter", "einsatz": "Spezial",
     "funktion": "Kleine Preisunterschiede zwischen Börsen oder Paaren gleichzeitig ausnutzen.",
     "risiken": "Gebühren, Latenz, Transferzeiten, Gegenparteirisiko", "quelle": "Preisunterschiede",
     "grund": "Braucht Konten bei mehreren Börsen gleichzeitig und sehr niedrige Latenz."},
    {"id": "market_making", "name": "Market Making", "status": "nicht_empfohlen", "einsatz": "Nicht für den Start",
     "funktion": "Gleichzeitig Kauf- und Verkaufskurse stellen und den Spread verdienen.",
     "risiken": "Lagerrisiko bei Trends, hohe Technikanforderungen", "quelle": "Spread",
     "grund": "Technische Anforderungen (Orderbuch in Echtzeit, Latenz) für dieses Projekt zu hoch."},
    {"id": "optionen", "name": "Optionsprämien (Covered Call, Cash-Secured Put)", "status": "spaeter", "einsatz": "Später",
     "funktion": "Optionen verkaufen und die Prämie vereinnahmen, gedeckt durch vorhandene Werte oder Bargeld.",
     "risiken": "Gewinn begrenzt, Verluste bei starken Kursbewegungen; Optionskonto nötig", "quelle": "Prämien",
     "grund": "Braucht ein Optionskonto beim Broker – Derivate sind in der ersten Version ausgeschlossen."},
    {"id": "defi", "name": "Liquiditätsbereitstellung (DeFi)", "status": "nicht_empfohlen", "einsatz": "Spezial, hohes Risiko",
     "funktion": "Werte in einen Liquiditätspool einzahlen und Gebührenanteile erhalten.",
     "risiken": "Impermanent Loss, Smart-Contract-Fehler, Hacks, Transaktionsgebühren", "quelle": "Gebühren",
     "grund": "Laut Einordnung nicht empfohlen ohne Erfahrung; bräuchte ein separates Wallet."},
    {"id": "wiederverkauf", "name": "Preisvergleich und Wiederverkauf", "status": "spaeter", "einsatz": "Später",
     "funktion": "Preise in Shops/Marktplätzen überwachen, Angebote melden, günstig kaufen und teurer verkaufen.",
     "risiken": "Lagerhaltung, Rückgaben, Marktplatzgebühren, Plattformregeln", "quelle": "Preisunterschiede",
     "grund": "Eigenes Geschäftsfeld außerhalb der Börse; Bots, die Plattformregeln umgehen, werden nicht unterstützt."},
    {"id": "wetten", "name": "Wetten- und Prognosemärkte", "status": "nicht_empfohlen", "einsatz": "Nicht empfohlen",
     "funktion": "Quotenunterschiede (Arbitrage) oder Value Betting.",
     "risiken": "Kontosperrung, Glücksspielrecht, Steuer; in vielen Ländern eingeschränkt", "quelle": "Quoten",
     "grund": "Laut Einordnung nicht empfohlen (Glücksspielrecht)."},
    {"id": "dienste", "name": "Nicht-Handel: Dienste und Inhalte", "status": "spaeter", "einsatz": "Optional",
     "funktion": "Preisalarme, Datenaufbereitung, Berichte oder Inhalte, für die Kunden bezahlen.",
     "risiken": "Aufwand, Nachfrage, Haftung", "quelle": "Eigenes Geschäft",
     "grund": "Kein Handelsmodul – die Preisalarme der App sind ein erster Baustein."},
]

WARNSIGNALE = ("Vorsicht bei Anbietern, die feste hohe Renditen versprechen, „garantierte“ Bot-Gewinne verkaufen, Einzahlungen auf "
               "fremde Plattformen verlangen oder Kunden anwerben lassen – typische Merkmale von Betrug und Schneeballsystemen.")

MODULE_LIFECYCLE = ("entwurf", "paper", "live_klein", "live", "pausiert")

MODULE_DEFAULTS = {
    "sparplan": {"status": "entwurf", "amount": 100.0, "rhythm": "monatlich", "day": 1, "weights": {"BTC/EUR": 60.0, "ETH/EUR": 40.0}},
    "rebalancing": {"status": "entwurf", "rhythm": "monatlich", "threshold_pct": 5.0},
}
