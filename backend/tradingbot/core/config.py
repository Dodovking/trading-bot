"""Bot-Konfiguration je Benutzer: Standardwerte (Abschnitt 4.1 / 13), Validierung, Versionierung."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..earn.catalog import MODULE_DEFAULTS, MODULE_LIFECYCLE
from ..strategies.registry import STRATEGY_TYPES
from .models import ConfigVersion
from .types import TIMEFRAMES

DEFAULT_MARKETS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "ADA/EUR", "LINK/EUR", "AVAX/EUR", "DOGE/EUR",
                   "AAPL", "MSFT", "NVDA", "SPY"]
OLD_DEFAULT_MARKETS = ["BTC/EUR", "ETH/EUR", "SOL/EUR"]

RISK_FIELDS: dict[str, dict[str, Any]] = {
    "risk_per_trade_pct": {"label": "Maximales Risiko pro Trade", "unit": "%", "min": 0.05, "max": 5, "step": 0.05, "default": 1.0,
                           "help": "Anteil des Kontos, der beim Auslösen des Stop-Loss verloren gehen darf"},
    "daily_loss_limit_pct": {"label": "Tägliches Verlustlimit", "unit": "%", "min": 0.5, "max": 20, "step": 0.5, "default": 3.0,
                             "help": "Bot sperrt neue Trades bis zum nächsten Tag"},
    "max_drawdown_pct": {"label": "Maximaler Drawdown", "unit": "%", "min": 1, "max": 50, "step": 0.5, "default": 10.0,
                         "help": "Rückgang vom Höchststand – danach Sperre und manuelle Prüfung"},
    "max_positions": {"label": "Max. offene Positionen", "unit": "", "min": 1, "max": 20, "step": 1, "default": 3,
                      "help": "Gleichzeitig erlaubt"},
    "max_position_pct": {"label": "Max. Größe je Position", "unit": "%", "min": 1, "max": 100, "step": 1, "default": 25.0,
                         "help": "Anteil des Kontos je Position"},
    "max_exposure_pct": {"label": "Max. Gesamt-Exposure", "unit": "%", "min": 5, "max": 100, "step": 5, "default": 100.0,
                         "help": "Summe aller Positionen im Verhältnis zum Konto"},
    "loss_streak_limit": {"label": "Pause nach Verlustserie", "unit": "Trades", "min": 1, "max": 20, "step": 1, "default": 5,
                          "help": "Nach so vielen Verlusttrades in Folge pausiert der Bot"},
    "max_spread_pct": {"label": "Max. Spread", "unit": "%", "min": 0.01, "max": 3, "step": 0.01, "default": 0.5,
                       "help": "Keine Order bei größerem Abstand zwischen Kauf- und Verkaufskurs"},
    "min_volume_24h": {"label": "Mindestumsatz 24 h", "unit": "€", "min": 0, "max": 100000000, "step": 10000, "default": 100000,
                       "help": "Liquiditätsfilter: Mindesthandelsvolumen der letzten 24 Stunden"},
    "max_data_age_candles": {"label": "Max. Datenalter", "unit": "× Kerze", "min": 1, "max": 5, "step": 0.5, "default": 2.0,
                             "help": "Ab diesem Alter der letzten Kerze keine Order"},
    "max_tick_age_s": {"label": "Max. Alter des Kurses", "unit": "s", "min": 30, "max": 900, "step": 30, "default": 180,
                       "help": "Ab diesem Alter des letzten Live-Kurses keine Order"},
    "min_stop_distance_pct": {"label": "Min. Stop-Abstand", "unit": "%", "min": 0.05, "max": 10, "step": 0.05, "default": 0.3,
                              "help": "Engere Stops sind nicht sinnvoll (Rauschen, Kosten)"},
    "max_stop_distance_pct": {"label": "Max. Stop-Abstand", "unit": "%", "min": 1, "max": 50, "step": 0.5, "default": 15.0,
                              "help": "Weitere Stops werden abgelehnt"},
    "max_cost_share_pct": {"label": "Max. Kostenanteil am Risiko", "unit": "%", "min": 5, "max": 100, "step": 5, "default": 35.0,
                           "help": "Gebühren + Spread + Slippage im Verhältnis zum geplanten Risiko"},
    "max_total_risk_pct": {"label": "Max. Gesamtrisiko offener Positionen", "unit": "%", "min": 0.25, "max": 20, "step": 0.25,
                           "default": 5.0, "help": "Summe der Verluste aller offenen Positionen, falls alle Stops greifen"},
    "strategy_budget_pct": {"label": "Strategie-Budget", "unit": "%", "min": 5, "max": 100, "step": 5, "default": 30.0,
                            "help": "Höchstanteil einer Strategie am Gesamtrisiko"},
    "strategy_drawdown_r": {"label": "Strategie-Abschaltung bei Drawdown", "unit": "× Risiko", "min": 2, "max": 30, "step": 1,
                            "default": 8, "help": "Verliert eine Strategie so viele Risikoeinheiten vom Höchststand, wird sie pausiert"},
    "liquidity_reserve_pct": {"label": "Liquiditätsreserve", "unit": "%", "min": 0, "max": 90, "step": 1, "default": 10.0,
                              "help": "Dieser Anteil des Kontos bleibt immer frei verfügbar (Notfälle, Gebühren)"},
    "module_budget_pct": {"label": "Budget je Ertragsmodul", "unit": "%", "min": 0, "max": 100, "step": 5, "default": 30.0,
                          "help": "Höchstanteil des Kontos, den ein Ertragsmodul (z. B. Sparplan) binden darf"},
    "counterparty_limit_pct": {"label": "Gegenparteilimit je Anbieter", "unit": "%", "min": 5, "max": 100, "step": 5, "default": 50.0,
                               "help": "Höchstanteil des Gesamtkapitals bei einem Anbieter (nur mit Angabe des Gesamtkapitals)"},
    "total_capital_eur": {"label": "Gesamtkapital (alle Anbieter)", "unit": "€", "min": 0, "max": 100000000, "step": 100, "default": 0,
                          "help": "Für das Gegenparteilimit; 0 = nicht prüfen"},
    "min_order_risk_pct": {"label": "Kleines Konto: Risiko bei Mindestorder", "unit": "%", "min": 0, "max": 5, "step": 0.5,
                           "default": 2.0,
                           "help": "Ist die berechnete Menge kleiner als die kleinste Order des Anbieters, darf der Bot auf diese "
                                   "Mindestorder aufrunden – aber nur, wenn das Risiko dabei höchstens so viel Prozent des Kontos "
                                   "beträgt (0 = nie aufrunden)"},
    "volatility_pause_atr": {"label": "Volatilitätsbremse", "unit": "× ATR", "min": 0, "max": 10, "step": 0.5, "default": 4.0,
                             "help": "Kein Einstieg, wenn die letzte Kerze größer als so viele ATR war (0 = aus)"},
}

# Strategie-Lebenszyklus (FA-1A)
LIFECYCLE = ("entwurf", "backtest", "paper", "live_klein", "live", "pausiert", "ausgemustert")
LIFECYCLE_LABELS = {"entwurf": "Entwurf", "backtest": "Backtest", "paper": "Paper", "live_klein": "Live-klein", "live": "Live",
                    "pausiert": "Pausiert", "ausgemustert": "Ausgemustert"}
SHADOW_STATUSES = {"backtest", "paper", "live_klein", "live", "pausiert"}
ORDER_STATUSES = {"paper": {"paper", "live_klein", "live"}, "live": {"live_klein", "live"}}
LIVE_SMALL_RISK_FACTOR = 0.25

DEFAULT_STRATEGIES = [
    {"id": "trendfolge", "type": "trendfolge", "status": "paper", "timeframe": "1h"},
    {"id": "momentum", "type": "momentum", "status": "paper", "timeframe": "1h"},
    {"id": "mean_reversion", "type": "mean_reversion", "status": "paper", "timeframe": "1h"},
    {"id": "ausbruch", "type": "ausbruch", "status": "backtest", "timeframe": "4h"},
    {"id": "ruecksetzer", "type": "ruecksetzer", "status": "backtest", "timeframe": "1h"},
    {"id": "range", "type": "range", "status": "backtest", "timeframe": "1h"},
]

SELECTION_DEFAULTS = {
    "mode": "vorschlag",  # manuell | vorschlag | automatisch
    "rhythm": "taeglich",  # taeglich | woechentlich
    "regime_timeframe": "4h",
    "min_trades": 30,
    "min_days": 14,
    "hysteresis": 0.15,
    "min_hold_days": 7,
}


def default_config() -> dict:
    return {
        "automation": "automatisch",  # signale | halbautomatisch | automatisch
        "account": "paper",  # paper | live
        "markets": list(DEFAULT_MARKETS),
        "risk": {k: v["default"] for k, v in RISK_FIELDS.items()} | {
            "on_limit": "halten",  # halten (mit Stop) | schliessen
            "on_emergency": "schliessen",  # schliessen | halten
            "blackouts": [],  # [{"start": "2026-11-07T13:00", "end": "...", "label": "US-Arbeitsmarkt"}]
        },
        "costs": {"fee_pct": 0.40, "slippage_pct": 0.05},
        "strategies": [{"name": STRATEGY_TYPES[d["type"]].name, "markets": [], "params": {}, **d} for d in DEFAULT_STRATEGIES],
        "selection": dict(SELECTION_DEFAULTS),
        "modules": copy.deepcopy(MODULE_DEFAULTS),
        "notifications": {"push": True, "ntfy_topic": "", "on_trade": True, "on_warning": True,
                          "daily_report": True, "weekly_report": True},
    }


class ConfigError(ValueError):
    pass


def _num(v: Any, spec: dict) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ConfigError(f"{spec['label']}: Zahl erwartet")
    if x < spec["min"] or x > spec["max"]:
        raise ConfigError(f"{spec['label']}: erlaubt {spec['min']}–{spec['max']}")
    return int(x) if isinstance(spec["default"], int) else x


def validate_config(raw: dict, known_markets: set[str] | None = None) -> dict:
    """Prüft und normalisiert eine Konfiguration. Unbekannte Felder werden verworfen."""
    base = default_config()
    cfg: dict = copy.deepcopy(base)
    if raw.get("automation") not in ("signale", "halbautomatisch", "automatisch"):
        raise ConfigError("Automatisierungsgrad ungültig")
    cfg["automation"] = raw["automation"]
    if raw.get("account") not in ("paper", "live"):
        raise ConfigError("Konto ungültig")
    cfg["account"] = raw["account"]
    markets = [m for m in raw.get("markets", []) if isinstance(m, str)]
    if known_markets is not None:
        unknown = [m for m in markets if m not in known_markets]
        if unknown:
            raise ConfigError(f"Unbekannte Märkte: {', '.join(unknown)}")
    cfg["markets"] = sorted(set(markets), key=markets.index)
    risk_in = raw.get("risk", {})
    for k, spec in RISK_FIELDS.items():
        cfg["risk"][k] = _num(risk_in.get(k, spec["default"]), spec)
    if cfg["risk"]["min_stop_distance_pct"] >= cfg["risk"]["max_stop_distance_pct"]:
        raise ConfigError("Min. Stop-Abstand muss kleiner als der maximale sein")
    cfg["risk"]["on_limit"] = "schliessen" if risk_in.get("on_limit") == "schliessen" else "halten"
    cfg["risk"]["on_emergency"] = "halten" if risk_in.get("on_emergency") == "halten" else "schliessen"
    blackouts = []
    for b in risk_in.get("blackouts", []) or []:
        if isinstance(b, dict) and b.get("start") and b.get("end"):
            blackouts.append({"start": str(b["start"])[:25], "end": str(b["end"])[:25], "label": str(b.get("label", ""))[:80]})
    cfg["risk"]["blackouts"] = blackouts
    costs = raw.get("costs", {})
    cfg["costs"] = {
        "fee_pct": _num(costs.get("fee_pct", 0.4), {"label": "Gebühr", "min": 0, "max": 2, "default": 0.0}),
        "slippage_pct": _num(costs.get("slippage_pct", 0.05), {"label": "Slippage", "min": 0, "max": 2, "default": 0.0}),
    }
    strategies = []
    ids = set()
    for s in raw.get("strategies", []):
        t = s.get("type")
        if t not in STRATEGY_TYPES:
            raise ConfigError(f"Unbekannter Strategietyp: {t}")
        sid = str(s.get("id") or t)[:40]
        if sid in ids:
            raise ConfigError(f"Doppelte Strategie-ID: {sid}")
        ids.add(sid)
        tf = s.get("timeframe", "1h")
        if tf not in TIMEFRAMES:
            raise ConfigError(f"Zeitrahmen ungültig: {tf}")
        smarkets = [m for m in s.get("markets", []) or [] if m in cfg["markets"]]
        strategies.append({
            "id": sid, "type": t, "name": str(s.get("name") or STRATEGY_TYPES[t].name)[:60],
            "status": s.get("status") if s.get("status") in LIFECYCLE else "entwurf", "timeframe": tf, "markets": smarkets,
            "params": STRATEGY_TYPES[t].clean_params(s.get("params") or {}),
        })
    cfg["strategies"] = strategies
    sel = raw.get("selection", {}) or {}
    cfg["selection"] = {
        "mode": sel.get("mode") if sel.get("mode") in ("manuell", "vorschlag", "automatisch") else "vorschlag",
        "rhythm": "woechentlich" if sel.get("rhythm") == "woechentlich" else "taeglich",
        "regime_timeframe": sel.get("regime_timeframe") if sel.get("regime_timeframe") in TIMEFRAMES else "4h",
        "min_trades": int(_num(sel.get("min_trades", 30), {"label": "Mindestanzahl Trades", "min": 5, "max": 500, "default": 0})),
        "min_days": int(_num(sel.get("min_days", 14), {"label": "Mindestdauer", "min": 1, "max": 365, "default": 0})),
        "hysteresis": _num(sel.get("hysteresis", 0.15), {"label": "Hysterese", "min": 0, "max": 1, "default": 0.0}),
        "min_hold_days": int(_num(sel.get("min_hold_days", 7), {"label": "Mindesthaltedauer", "min": 0, "max": 90, "default": 0})),
    }
    mods = raw.get("modules", {}) or {}
    sp, rb = mods.get("sparplan", {}) or {}, mods.get("rebalancing", {}) or {}
    weights = {}
    for k, v in (sp.get("weights") or {}).items():
        if k in cfg["markets"] or (known_markets is None or k in known_markets):
            w = _num(v, {"label": f"Zielgewicht {k}", "min": 0, "max": 100, "default": 0.0})
            if w > 0:
                weights[str(k)] = w
    if weights and abs(sum(weights.values()) - 100) > 0.01:
        raise ConfigError("Zielgewichte des Sparplans müssen zusammen 100 % ergeben")
    rhythm = "woechentlich" if sp.get("rhythm") == "woechentlich" else "monatlich"
    cfg["modules"] = {
        "sparplan": {"status": sp.get("status") if sp.get("status") in MODULE_LIFECYCLE else "entwurf",
                     "amount": _num(sp.get("amount", 100), {"label": "Sparplan-Betrag", "min": 1, "max": 1000000, "default": 0.0}),
                     "rhythm": rhythm, "day": int(_num(sp.get("day", 1), {"label": "Ausführungstag", "min": 0, "max": 28, "default": 0})),
                     "weights": weights},
        "rebalancing": {"status": rb.get("status") if rb.get("status") in MODULE_LIFECYCLE else "entwurf",
                        "rhythm": "woechentlich" if rb.get("rhythm") == "woechentlich" else "monatlich",
                        "threshold_pct": _num(rb.get("threshold_pct", 5), {"label": "Rebalancing-Schwelle", "min": 1, "max": 50,
                                                                          "default": 0.0})},
    }
    n = raw.get("notifications", {})
    topic = str(n.get("ntfy_topic", "") or "").strip()
    if topic and (len(topic) > 64 or not all(ch.isalnum() or ch in "-_" for ch in topic)):
        raise ConfigError("ntfy-Thema: nur Buchstaben, Ziffern, - und _ (max. 64)")
    cfg["notifications"] = {
        "push": bool(n.get("push", True)), "ntfy_topic": topic, "on_trade": bool(n.get("on_trade", True)),
        "on_warning": bool(n.get("on_warning", True)), "daily_report": bool(n.get("daily_report", True)),
        "weekly_report": bool(n.get("weekly_report", True)),
    }
    return cfg


def current_config(db: Session, user_id: int) -> tuple[dict, int | None]:
    row = db.scalars(
        select(ConfigVersion).where(ConfigVersion.user_id == user_id).order_by(ConfigVersion.id.desc()).limit(1)
    ).first()
    if row is None:
        return default_config(), None
    return copy.deepcopy(row.content), row.id


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "an" if v else "aus"
    if isinstance(v, (list, tuple)) and all(not isinstance(x, (dict, list)) for x in v):
        return ", ".join(str(x) for x in v) or "–"
    return repr(v) if isinstance(v, (dict, list)) else str(v)


SECTION_LABELS = {"risk": "Risiko", "strategies": "Strategie", "modules": "Ertragsmodul", "selection": "Strategieauswahl",
                  "notifications": "Meldungen", "costs": "Kosten", "markets": "Märkte", "automation": "Handelsmodus",
                  "account": "Konto", "params": "Parameter", "markets_": "Märkte"}


def diff_config(old: dict, new: dict) -> list[str]:
    """Lesbare Änderungsliste, z. B. „Risiko › Maximales Risiko pro Trade: 1.0 → 1.5“."""
    out = []
    for line in _diff(old, new):
        key, _, rest = line.partition(": ")
        parts = [SECTION_LABELS.get(x, x) for x in key.split("\x1f")]
        out.append(" › ".join(parts) + ": " + rest)
    return out


def _diff(old: dict, new: dict, prefix: str = "") -> list[str]:
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        label = RISK_FIELDS[k]["label"] if prefix == "risk\x1f" and k in RISK_FIELDS else k
        key = f"{prefix}{label}"
        if isinstance(a, dict) and isinstance(b, dict):
            out += _diff(a, b, key + "\x1f")
        elif isinstance(a, list) and isinstance(b, list) and all(isinstance(x, dict) and "id" in x for x in a + b):
            ao, bo = {x["id"]: x for x in a}, {x["id"]: x for x in b}
            for i in sorted(set(ao) | set(bo)):
                if i not in ao:
                    out.append(f"{key}: „{i}“ hinzugefügt")
                elif i not in bo:
                    out.append(f"{key}: „{i}“ entfernt")
                else:
                    out += _diff(ao[i], bo[i], f"{key}\x1f{i}\x1f")
        elif a != b:
            out.append(f"{key}: {_fmt(a) if a is not None else '–'} → {_fmt(b) if b is not None else '–'}")
    return out


def save_config(db: Session, user_id: int, new_cfg: dict, changed_by: str) -> ConfigVersion:
    old, _ = current_config(db, user_id)
    changes = diff_config(old, new_cfg)
    row = ConfigVersion(user_id=user_id, changed_by=changed_by, content=new_cfg, summary="\n".join(changes[:50]))
    db.add(row)
    db.flush()
    return row


def migrate_default_markets(db: Session) -> int:
    """Einmalig: Benutzer mit der alten Standard-Marktliste bekommen die erweiterte Liste (weitere Kryptos und Aktien)."""
    from sqlalchemy import select

    from .db import utcnow
    from .models import AppSetting, User
    if db.get(AppSetting, "migration_maerkte_v2") is not None:
        return 0
    n = 0
    for uid in db.scalars(select(User.id)):
        cfg, vid = current_config(db, uid)
        if vid is not None and cfg["markets"] == OLD_DEFAULT_MARKETS:
            new = {**cfg, "markets": list(DEFAULT_MARKETS)}
            save_config(db, uid, new, "System-Update (weitere Kryptos und Aktien)")
            n += 1
    db.add(AppSetting(key="migration_maerkte_v2", value={"users": n}, updated_at=utcnow()))
    db.flush()
    return n
