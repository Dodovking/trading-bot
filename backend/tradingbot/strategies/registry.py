"""Strategiebibliothek (Abschnitt 6.1): 14 Familien, davon die für Spot-Handel ohne Hebel/Short umgesetzten."""
from __future__ import annotations

from .base import Strategy
from .breakout import Breakout
from .mean_reversion import MeanReversion
from .momentum import Momentum
from .pullback import Pullback
from .range import RangeTrading
from .trend import TrendFollowing

STRATEGY_TYPES: dict[str, Strategy] = {
    s.type_id: s for s in (TrendFollowing(), Momentum(), MeanReversion(), Breakout(), Pullback(), RangeTrading())
}

# Familie, Prinzip, passt zu, Hauptrisiko, Einsatz laut PDF, umgesetzter Typ oder Sperrgrund
FAMILIES = [
    ("trendfolge", "Trendfolge", "Einstieg in Trendrichtung: gleitende Durchschnitte, Donchian, ADX", "Klare Auf- oder Abwärtstrends",
     "Fehlsignale in Seitwärtsphasen, später Ausstieg", "Start", "trendfolge", ""),
    ("momentum", "Momentum", "Werte mit starker jüngster Entwicklung: Rate of Change, relative Stärke", "Anhaltende Marktphasen",
     "Abrupte Trendumkehr", "Start", "momentum", ""),
    ("mean_reversion", "Mean Reversion", "Rückkehr zum Mittelwert: RSI, Bollinger-Bänder, Z-Score", "Seitwärts, ruhige Märkte",
     "Gegen echte Trends wachsen Verluste ohne Stop", "Start", "mean_reversion", ""),
    ("ausbruch", "Ausbruch (Breakout)", "Durchbruch einer Handelsspanne oder Volatilitätsschwelle", "Ende ruhiger Phasen",
     "Fehlausbrüche", "Später", "ausbruch", ""),
    ("range_grid", "Range-/Grid-Trading", "Kaufen und Verkaufen innerhalb einer Preisspanne", "Stabile Seitwärtsbereiche",
     "Verlässt der Kurs die Spanne, häufen sich Verluste", "Später", "range", ""),
    ("swing", "Swing-Trading", "Mehrtägige Schwünge, z. B. Rücksetzer im Trend kaufen", "Märkte mit klaren Schwüngen",
     "Kurslücken über Nacht und Wochenende", "Später", "ruecksetzer", ""),
    ("pairs", "Pairs Trading / stat. Arbitrage", "Abweichung des Preisverhältnisses zweier Werte", "Stabile Beziehung",
     "Beziehung bricht; Leerverkauf nötig", "Später", None, "Benötigt Leerverkäufe – laut Grundregeln ausgeschlossen"),
    ("arbitrage", "Arbitrage", "Preisunterschiede zwischen Börsen oder Paaren", "Fragmentierte Märkte",
     "Gebühren, Latenz, Transferzeiten", "Spezial", None, "Benötigt mehrere Börsenkonten und sehr geringe Latenz"),
    ("market_making", "Market Making", "Gleichzeitig Kauf- und Verkaufskurse stellen", "Sehr liquide Märkte",
     "Lagerrisiko, hohe Technikanforderungen", "Nicht für den Start", None, "Laut PDF nicht für den Start"),
    ("scalping", "Scalping / Hochfrequenz", "Sehr kurze Trades mit kleinen Gewinnen", "Sehr liquide Märkte, niedrige Kosten",
     "Gebühren und Slippage fressen den Vorteil", "Nicht empfohlen", None, "Laut PDF nicht empfohlen (Nicht-Ziel)"),
    ("sparplan", "Sparplan / Rebalancing", "Regelmäßig investieren, Zielgewichte wiederherstellen", "Langfristige Anlage",
     "Kaum Verlustbegrenzung im Crash", "Später", None, "Kein Handelssignal mit Stop – läuft als Ertragsmodul (Bereich „Ertragsmodule“)"),
    ("sentiment", "Sentiment / News / Ereignisse", "Handel auf Nachrichten, Stimmung, Termine", "Ereignisreiche Phasen",
     "Datenqualität, Fehlinterpretation", "Später", None, "Nachrichtenquelle fehlt; Sperrzeiträume für Termine sind möglich"),
    ("ki_ml", "KI / Machine Learning", "Prognosemodelle, Regime-Klassifikation", "Große, saubere Datenmengen",
     "Overfitting, schwer erklärbar", "Später", None, "Erst nach stabiler Grundversion und Beleg für Mehrwert"),
    ("volatilitaet_carry", "Volatilitäts-/Carry-Strategien", "Volatility Targeting, Funding-Rate-Carry", "Spezielle Marktstrukturen",
     "Seltene, sehr große Verluste", "Spezial", None, "Benötigt Derivate (Funding) – ausgeschlossen"),
]


def get_strategy(type_id: str) -> Strategy:
    return STRATEGY_TYPES[type_id]


def library() -> list[dict]:
    out = []
    for fid, name, principle, fits, risk, use, type_id, blocked in FAMILIES:
        s = STRATEGY_TYPES.get(type_id) if type_id else None
        out.append({"family": fid, "name": name, "principle": principle, "fits": fits, "risk": risk, "use": use,
                    "type": type_id, "available": s is not None, "blocked_reason": blocked,
                    "version": s.version if s else None, "description": s.description if s else "",
                    "regimes": list(s.regimes) if s else [],
                    "params": [p.to_dict() for p in s.params] if s else []})
    return out
