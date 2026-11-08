"""Antworten und Aufträge des Assistenten. Liest nur Daten des angemeldeten Nutzers; Änderungen werden nur vorgeschlagen."""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import ORDER_STATUSES, RISK_FIELDS, current_config
from ..core.models import BotRuntime, Position, RiskDecision, SignalRow, User, utcnow
from ..core.state import STATE_LABELS
from ..data.instruments import NAMES
from .nlu import Parsed, any_word, norm, parse, stem_in

STATUS_LABEL = {"entwurf": "Entwurf", "backtest": "Backtest", "paper": "Paper", "live_klein": "Live-klein", "live": "Live",
                "pausiert": "Pausiert", "ausgemustert": "Ausgemustert"}
AUTOMATION_LABEL = {"signale": "Nur Signale", "halbautomatisch": "Halbautomatisch", "automatisch": "Automatisch"}
YES = {"ja", "jo", "jap", "jawohl", "ok", "okay", "mach", "machen", "mach das", "ja mach", "ja machen", "ja bitte", "bitte", "passt",
       "klar", "gerne", "ja gerne", "bestaetigen", "bestaetigt", "los", "go", "yes", "genau", "ja genau", "mach es", "ja mach das"}
NO = {"nein", "ne", "nee", "no", "abbrechen", "abbruch", "stopp nein", "lieber nicht", "doch nicht", "nicht machen", "nein danke", "vergiss es"}
QUESTION_STARTS = ("wie", "was", "warum", "wieso", "weshalb", "welche", "welcher", "welches", "wann", "wo", "wer", "kann", "ist", "sind",
                   "hat", "habe", "hab", "gibt", "zeig", "sag", "erklaer", "erklaere", "bedeutet", "darf", "muss", "soll ich", "lohnt")
WISSEN = json.loads((Path(__file__).parent / "wissen.json").read_text(encoding="utf-8"))
WISSEN += [
    {"q": ["paper live unterschied", "spielgeld echtgeld unterschied", "was ist live", "was ist paper"],
     "a": "Paper = Spielgeld (10.000 € in der App, echte Kurse, kein Risiko). Live = dein echtes Guthaben bei Kraken/Alpaca. "
          "Im Paper-Modus handeln Strategien mit Status Paper, Live-klein und Live; im Echtgeld-Modus nur Live-klein und Live."},
    {"q": ["live klein", "was ist live klein", "live-klein"],
     "a": "Live-klein heißt: die Strategie handelt mit echtem Geld, aber nur mit einem Viertel des normalen Risikos. Gut für den Anfang."},
    {"q": ["strategie status stufen", "lebenszyklus"],
     "a": "Stufen einer Strategie: Entwurf → Backtest → Paper → Live-klein → Live. Daneben Pausiert und Ausgemustert. "
          "Nur Paper/Live-klein/Live handeln; welche davon, hängt vom Modus ab."},
    {"q": ["automatisierungsgrad", "automatisch halbautomatisch signale"],
     "a": "Nur Signale: Bot meldet nur. Halbautomatisch: jeder Kauf muss im Dashboard bestätigt werden. Automatisch: Bot kauft und verkauft "
          "selbst – immer nach bestandener Risikoprüfung."},
    {"q": ["gebuehren kosten", "was kostet"], "a": "Die App selbst kostet nichts. Es fallen nur die Gebühren deines Anbieters an "
                                                  "(Kraken etwa 0,25–0,40 % je Order, Alpaca bei US-Aktien keine Provision)."},
    {"q": ["hebel", "leverage", "short", "futures"], "a": "Hebel, Futures und Leerverkäufe sind in dieser Version absichtlich gesperrt – "
                                                           "damit kann man mehr verlieren als eingesetzt."},
    {"q": ["trust wallet", "wallet"], "a": "Trust Wallet ist keine Börse und hat keine Handels-Schnittstelle. Der Bot bräuchte deine Geheimwörter – "
                                            "das ist zu gefährlich. Gib nie jemandem deine Seed-Phrase. Zum Handeln Coins selbst zu Kraken schicken."},
    {"q": ["api schluessel anlegen kraken verbinden", "wie verbinde ich kraken"],
     "a": "Kraken: kraken.com → Einstellungen → API → Neuer Schlüssel. Rechte: Abfragen + Orders erstellen/ändern/stornieren, NIE Auszahlen. "
          "Dann in der App Einstellungen → Konto & Börse → Kraken eintragen und „Verbinden“."},
    {"q": ["wie verbinde ich alpaca", "alpaca verbinden"],
     "a": "Alpaca: alpaca.markets → API Keys → Generate. In der App Einstellungen → Konto & Börse → Alpaca, Umgebung wählen (Paper oder Live), "
          "Schlüssel eintragen, „Verbinden“."},
    {"q": ["bestand uebergeben", "dem bot uebergeben", "eigene coins"],
     "a": "Eigene Coins beim Anbieter rührt der Bot nicht an. Mit „Dem Bot übergeben“ (Dashboard → Weitere Bestände) wird ein Coin zur "
          "Bot-Position mit Stop-Loss; der Bot verkauft ihn dann nach seiner Strategie. Das kann ich auch hier für dich vorbereiten."},
    {"q": ["wer bist du", "was bist du", "welche ki", "chatgpt", "openai"],
     "a": "Ich bin der eingebaute Assistent dieses Bots. Ich laufe komplett auf deinem eigenen Server – nichts geht an OpenAI, Google oder andere."},
]
MAX_PENDING_AGE = timedelta(minutes=30)


def eur(x) -> str:
    x = float(x or 0)
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if x < 0 else "") + s + " €"


def num(x, digits=2) -> str:
    return f"{float(x):.{digits}f}".rstrip("0").rstrip(".").replace(".", ",")


def mname(sym: str) -> str:
    n = NAMES.get(sym)
    return f"{n} ({sym})" if n and n != sym else sym


def is_question(text: str, p: Parsed) -> bool:
    return "?" in text or p.text.startswith(QUESTION_STARTS)


class Ctx:
    """Alles, was eine Antwort braucht – lazy geladen, nur für diesen Nutzer."""

    def __init__(self, db: Session, u: User):
        self.db, self.u = db, u
        self.cfg, self.vid = current_config(db, u.id)
        self._dash = None

    @property
    def dash(self) -> dict:
        if self._dash is None:
            from ..api.bot_routes import dashboard
            self._dash = dashboard(u=self.u, db=self.db)
        return self._dash

    def strategies_for(self, p: Parsed) -> list[dict]:
        if p.all_strategies:
            return list(self.cfg["strategies"])
        out = []
        for s in self.cfg["strategies"]:
            n = norm(s["name"])
            if s["type"] in p.strategies or s["id"] in p.strategies or (len(n) > 3 and n in p.text):
                out.append(s)
        return out


# --- Aufträge (nur Vorschläge, ausgeführt erst nach Bestätigung) ----------------------------------------------
def config_action(c: Ctx, new: dict, title: str) -> dict:
    from ..api.bot_routes import config_preview
    _, norm_new, changes, warnings = config_preview(c.db, c.u, new)
    if not changes:
        return {"none": True}
    changes = pretty_changes(c.cfg, norm_new, changes)
    danger = norm_new["account"] == "live" or any(s["status"] in ("live", "live_klein") for s in norm_new["strategies"]
                                                  if s not in c.cfg["strategies"])
    return {"kind": "config", "title": title, "config": new, "base_version_id": c.vid, "changes": changes,
            "warnings": warnings, "danger": bool(danger)}


def pretty_changes(old: dict, new: dict, changes: list[str]) -> list[str]:
    names = {s["id"]: s["name"] for s in new["strategies"]}
    out = []
    for line in changes:
        m = re.match(r"Strategie › (.+?) › status: (\w+) → (\w+)$", line)
        if m:
            out.append(f"Strategie {names.get(m[1], m[1])}: {STATUS_LABEL.get(m[2], m[2])} → {STATUS_LABEL.get(m[3], m[3])}")
        elif line.startswith("Märkte:"):
            on = [mname(x) for x in new["markets"] if x not in old["markets"]]
            off = [mname(x) for x in old["markets"] if x not in new["markets"]]
            out += ([f"Einschalten: {', '.join(on)}"] if on else []) + ([f"Ausschalten: {', '.join(off)}"] if off else [])
        else:
            out.append(line)
    return out


def command_action(action: str, title: str, lines: list[str], danger=False, **kw) -> dict:
    return {"kind": "command", "title": title, "command": action, "args": kw, "changes": lines, "warnings": [], "danger": danger}


def act_strategy_status(c: Ctx, p: Parsed):
    targets = c.strategies_for(p)
    if not targets:
        names = ", ".join(s["name"] for s in c.cfg["strategies"])
        return f"Welche Strategie meinst du? Du hast: {names}. Oder sag „alle Strategien auf …“.", None
    status = p.status
    if status is None:
        if stem_in(p.words, "aus", "deaktiv", "abschalt", "stopp", "anhalt"):
            status = "pausiert"
        elif stem_in(p.words, "ein", "aktiv", "anschalt", "an"):
            status = "paper" if c.cfg["account"] == "paper" else "live_klein"
    if status is None:
        lines = [f"- {s['name']}: {STATUS_LABEL[s['status']]}" for s in targets]
        return "Aktueller Status:\n" + "\n".join(lines) + "\n\nAuf welche Stufe soll ich sie stellen? (Paper, Live-klein, Live, Pausiert …)", None
    new = copy.deepcopy(c.cfg)
    ids = {s["id"] for s in targets}
    for s in new["strategies"]:
        if s["id"] in ids:
            s["status"] = status
    names = ", ".join(s["name"] for s in targets)
    act = config_action(c, new, f"{names} → {STATUS_LABEL[status]}")
    if act.get("none"):
        return f"{names} steht schon auf {STATUS_LABEL[status]}.", None
    msg = f"Ich stelle {names} auf **{STATUS_LABEL[status]}**."
    if status in ("live", "live_klein"):
        act["danger"] = True
        msg += " Achtung: Im Echtgeld-Modus handelt die Strategie dann mit echtem Geld."
        if status == "live":
            msg += " „Live-klein“ wäre vorsichtiger (ein Viertel des Risikos)."
    if c.cfg["account"] == "live" and status not in ORDER_STATUSES["live"]:
        msg += " Im Echtgeld-Modus kauft sie damit nichts mehr; offene Positionen bleiben mit Stop-Loss geschützt."
    return msg, act


def act_markets(c: Ctx, p: Parsed, on: bool, only: bool):
    from ..data.instruments import STOCKS
    stock_syms = {s for s, _, _ in STOCKS}
    syms = list(p.markets)
    for g in p.groups:
        syms += [m for m in (MARKET_ALL(c)) if (m in stock_syms) == (g == "aktie")]
    if not syms:
        return None
    syms = list(dict.fromkeys(syms))
    if not only:
        syms = [x for x in syms if (x in c.cfg["markets"]) != on] or syms
    new = copy.deepcopy(c.cfg)
    if only:
        new["markets"] = list(dict.fromkeys(syms))
    elif on:
        new["markets"] = list(dict.fromkeys(new["markets"] + syms))
    else:
        new["markets"] = [m for m in new["markets"] if m not in syms]
    if not new["markets"]:
        return "Mindestens ein Markt muss eingeschaltet bleiben.", None
    names = ", ".join(mname(s) for s in dict.fromkeys(syms))
    title = ("Nur noch " if only else "Einschalten: " if on else "Ausschalten: ") + names
    act = config_action(c, new, title)
    if act.get("none"):
        return f"{names} ist schon {'eingeschaltet' if on else 'ausgeschaltet'}.", None
    extra = "" if on else " Offene Positionen darin bleiben mit Stop-Loss bestehen und werden normal beendet."
    return f"{'Ich schalte nur noch ' + names + ' ein' if only else ('Ich schalte ' + names + (' ein' if on else ' aus'))}.{extra}", act


def MARKET_ALL(c: Ctx) -> list[str]:
    from ..core.models import Instrument
    return [i.symbol for i in c.db.scalars(select(Instrument).where(Instrument.active.is_(True))) if i.symbol != "EUR/USD"]


def act_setting(c: Ctx, p: Parsed):
    spec = RISK_FIELDS[p.setting]
    cur = c.cfg["risk"][p.setting]
    if p.number is None:
        return f"{spec['label']}: aktuell **{num(cur)}{(' ' + spec['unit']) if spec['unit'] else ''}**. {spec['help']}. Erlaubt {num(spec['min'])}–{num(spec['max'])}.", None
    val = p.number
    if not spec["min"] <= val <= spec["max"]:
        return f"{spec['label']}: erlaubt sind {num(spec['min'])}–{num(spec['max'])} {spec['unit']}.", None
    new = copy.deepcopy(c.cfg)
    new["risk"][p.setting] = val
    unit = f" {spec['unit']}" if spec["unit"] else ""
    act = config_action(c, new, f"{spec['label']} → {num(val)}{unit}")
    if act.get("none"):
        return f"{spec['label']} steht schon auf {num(cur)}{unit}.", None
    msg = f"Ich ändere {spec['label']} von {num(cur)} auf **{num(val)}{unit}**."
    if val > cur and p.setting in ("risk_per_trade_pct", "daily_loss_limit_pct", "max_drawdown_pct", "max_position_pct"):
        msg += " Das erhöht dein Risiko."
        act["danger"] = True
    return msg, act


def act_automation(c: Ctx, mode: str):
    new = copy.deepcopy(c.cfg)
    new["automation"] = mode
    act = config_action(c, new, f"Automatisierung → {AUTOMATION_LABEL[mode]}")
    if act.get("none"):
        return f"Der Bot steht schon auf {AUTOMATION_LABEL[mode]}.", None
    return f"Ich stelle den Bot auf **{AUTOMATION_LABEL[mode]}**.", act


def act_account(c: Ctx, target: str):
    if c.cfg["account"] == target:
        return f"Du bist schon im {'Echtgeld' if target == 'live' else 'Spielgeld'}-Modus.", None
    new = copy.deepcopy(c.cfg)
    new["account"] = target
    try:
        act = config_action(c, new, "Auf Echtgeld umstellen" if target == "live" else "Zurück auf Spielgeld (Paper)")
    except Exception as e:  # z. B. kein Anbieter verbunden
        return f"Das geht gerade nicht: {getattr(e, 'detail', e)}", None
    if target == "live":
        act["danger"] = True
        live = [s["name"] for s in c.cfg["strategies"] if s["status"] in ORDER_STATUSES["live"]]
        msg = ("Ich stelle auf **ECHTGELD** um. Ab dann handelt der Bot mit deinem echten Guthaben. "
               + (f"Mit echtem Geld handeln dürfen: {', '.join(live)}." if live else
                  "Keine Strategie steht auf Live-klein/Live – er würde also noch nichts kaufen."))
    else:
        msg = "Ich stelle zurück auf **Spielgeld (Paper)**. Positionen beim echten Anbieter bleiben dort mit Stop-Loss bestehen."
    return msg, act


def act_adopt(c: Ctx, p: Parsed):
    if c.cfg["account"] != "live":
        return "Übergeben geht nur im Echtgeld-Modus mit verbundenem Anbieter.", None
    ext = [x for x in c.dash["external"] if not x.get("staking")]
    if not ext:
        return "Ich sehe bei deinen Anbietern keine freien Bestände, die du übergeben könntest.", None
    want = set(p.assets) | {w.upper() for w in p.words}
    pick = [x for x in ext if x["asset"] in want] or (ext if len(ext) == 1 and "alle" not in p.words else [])
    if not pick:
        return "Welchen Bestand soll ich übergeben? Frei verfügbar: " + ", ".join(x["asset"] for x in ext) + ".", None
    x = pick[0]
    val = f" (etwa {eur(x['value'])})" if x.get("value") else ""
    lines = [f"{num(x['qty'], 8)} {x['asset']}{val} wird Bot-Position", "Stop-Loss wird sofort beim Anbieter gesetzt",
             "Der Bot verkauft nach seiner Strategie; Gewinn/Verlust zählt ab jetzt"]
    return (f"Ich übergebe deine {x['asset']} an den Bot.", command_action("bestand_uebernehmen", f"{x['asset']} dem Bot übergeben", lines,
                                                                          danger=True, asset=x["asset"]))


def act_close(c: Ctx, p: Parsed):
    pos = c.dash["positions"]
    if not pos:
        return "Es sind gerade keine Positionen offen.", None
    if "alle" in p.words or stem_in(p.words, "notbrems"):
        return ("Ich schließe **alle** Positionen und stoppe den Bot (Notbremse).",
                command_action("notaus", "Not-Aus: alles schließen", [f"{len(pos)} Position(en) werden verkauft", "Bot geht auf Not-Aus"],
                               danger=c.cfg["account"] == "live"))
    pick = [x for x in pos if x["symbol"] in p.markets]
    if not pick:
        return "Welche Position soll ich schließen? Offen: " + ", ".join(x["symbol"] for x in pos) + ".", None
    x = pick[0]
    lines = [f"Verkauf von {num(x['qty'], 8)} {x['symbol']} zum Marktpreis (etwa {eur(x['value'])})",
             f"Aktuelles Ergebnis: {eur(x['pnl'])}"]
    return (f"Ich verkaufe die Position {mname(x['symbol'])}.",
            command_action("position_schliessen", f"{x['symbol']} schließen", lines, danger=c.cfg["account"] == "live", position_id=x["id"]))


BOT_COMMANDS = {
    "start": ("Bot starten", "Der Bot handelt dann wieder selbst nach seinen Regeln."),
    "pause": ("Bot pausieren", "Keine neuen Käufe; offene Positionen bleiben mit Stop-Loss geschützt."),
    "stop": ("Bot stoppen", "Keine neuen Käufe; offene Positionen bleiben mit Stop-Loss geschützt."),
    "freigeben": ("Sperre aufheben", "Der Bot prüft das Konto neu und geht danach auf „Bereit“."),
    "auswahl_bestaetigen": ("Strategie-Vorschlag übernehmen", "Die vorgeschlagene Gewichtung der Strategien wird übernommen."),
    "auswahl_neu": ("Strategien neu bewerten", "Der Meta-Controller berechnet einen neuen Vorschlag."),
}


def act_bot(c: Ctx, action: str):
    st = c.dash["state"]
    if action == "start" and st == "AKTIV":
        return "Der Bot läuft schon.", None
    if action in ("pause", "stop") and st in ("PAUSIERT", "BEREIT") and not c.dash["want_running"]:
        return f"Der Bot steht schon auf „{STATE_LABELS[st]}“.", None
    if action == "auswahl_bestaetigen" and not c.dash["proposal_open"]:
        return "Es gibt gerade keinen offenen Strategie-Vorschlag.", None
    title, line = BOT_COMMANDS[action]
    if action == "start" and c.cfg["account"] == "live":
        line += " Achtung: Echtgeld-Modus."
    return f"{title}?", command_action(action, title, [line], danger=action == "start" and c.cfg["account"] == "live")


# --- Antworten mit echten Daten ---------------------------------------------------------------------------
def ans_status(c: Ctx) -> str:
    d = c.dash
    mode = "Echtgeld (Live)" if d["mode"] == "live" else "Spielgeld (Paper)"
    out = [f"Zustand: **{d['state_label']}**" + (f" – {d['state_reason']}" if d["state_reason"] else ""),
           f"Modus: {mode}, {AUTOMATION_LABEL[d['automation']]}",
           f"Kontowert: {eur(d['equity'])}, heute {eur(d['day_pnl'])}",
           f"Offene Positionen: {len(d['positions'])}"]
    if d["mode"] == "live":
        out.append(f"Anbieter: {d['broker']} – Abgleich {'ok' if d['reconcile_ok'] else 'mit Abweichung'}")
    if d["engine_error"]:
        out.append(f"Letzter Fehler: {d['engine_error']}")
    if d["pending_signals"]:
        out.append(f"{len(d['pending_signals'])} Signal(e) warten auf deine Bestätigung (Dashboard).")
    return "\n".join(out)


def ans_money(c: Ctx) -> str:
    d = c.dash
    out = [f"Kontowert: **{eur(d['equity'])}**" + (f" (davon {eur(d['exposure'])} in Positionen)" if d["exposure"] else ""),
           f"Heute: {eur(d['day_pnl'])}", f"Gewinn/Verlust der offenen Positionen: {eur(d['unrealized'])}",
           f"Abgeschlossene Trades: {d['trades_total']}, zusammen {eur(d['realized_total'])}"
           + (f", Trefferquote {num(d['win_rate'], 1)} %" if d["win_rate"] is not None else "")]
    if d["mode"] == "paper":
        out.append(f"(Spielgeld, Start mit {eur(d['start_capital'])})")
    ext = d["external"]
    if ext:
        out.append("Weitere Bestände beim Anbieter (nicht vom Bot verwaltet): " +
                   ", ".join(f"{num(x['qty'], 8)} {x['asset']}" + (f" ≈ {eur(x['value'])}" if x.get("value") else "") for x in ext))
    return "\n".join(out)


def ans_positions(c: Ctx) -> str:
    pos = c.dash["positions"]
    if not pos:
        return "Gerade ist nichts gekauft – keine offenen Positionen."
    lines = [f"- {mname(x['symbol'])}: {num(x['qty'], 8)} zu {eur(x['entry'])}, jetzt {eur(x['price'])}, Ergebnis {eur(x['pnl'])} "
             f"({num(x['pnl_pct'], 1)} %), Stop-Loss {eur(x['stop']) if x['stop'] else 'keiner'} ({x['strategy']})" for x in pos]
    return "Offene Positionen:\n" + "\n".join(lines)


def ans_why(c: Ctx) -> str:
    d, cfg = c.dash, c.cfg
    out = []
    if d["state"] != "AKTIV":
        out.append(f"Der Bot steht auf „{d['state_label']}“" + (f" ({d['state_reason']})" if d["state_reason"] else "")
                   + " – nur im Zustand „Bot läuft“ kauft er. " + ("Sag „Starte den Bot“." if d["state"] in ("BEREIT", "PAUSIERT") else ""))
    allowed = [s for s in cfg["strategies"] if s["status"] in ORDER_STATUSES[cfg["account"]]]
    if not allowed:
        out.append("Keine Strategie darf im aktuellen Modus handeln" + (" – im Echtgeld-Modus nur Live-klein/Live." if cfg["account"] == "live" else "."))
    if cfg["automation"] == "signale":
        out.append("Automatisierung steht auf „Nur Signale“ – der Bot kauft nie selbst.")
    if d["pending_signals"]:
        out.append(f"{len(d['pending_signals'])} Kauf-Signal(e) warten im Dashboard auf deine Bestätigung.")
    if len(d["positions"]) >= cfg["risk"]["max_positions"]:
        out.append(f"Schon {len(d['positions'])} Positionen offen – das Maximum ist {cfg['risk']['max_positions']}.")
    reg = Counter(r["label"] for r in d["regimes"])
    if reg:
        out.append("Marktlage: " + ", ".join(f"{n}× {lbl}" for lbl, n in reg.most_common())
                   + ". Bei Abwärtstrend und unklarer Lage kauft er absichtlich nicht.")
    since = utcnow() - timedelta(hours=24)
    rows = list(c.db.execute(select(RiskDecision.rule, RiskDecision.limit_value, RiskDecision.actual_value).where(
        RiskDecision.user_id == c.u.id, RiskDecision.time >= since, RiskDecision.result == "abgelehnt", RiskDecision.kind == "einstieg")))
    nsig = c.db.query(SignalRow).filter(SignalRow.user_id == c.u.id, SignalRow.time >= since, SignalRow.direction == "kauf").count()
    if nsig == 0:
        out.append("In den letzten 24 Stunden hat keine Strategie ein Kauf-Signal gegeben – die Einstiegsregeln waren nicht erfüllt.")
    elif rows:
        top = Counter(r.rule for r in rows).most_common(3)
        ex = {r.rule: r for r in rows}
        out.append(f"{nsig} Kauf-Signal(e) in 24 h, davon {len(rows)} von der Risikoprüfung abgelehnt. Häufigste Gründe: " +
                   "; ".join(f"{rule} ({n}×" + (f", Grenze {ex[rule].limit_value}, war {ex[rule].actual_value}" if ex[rule].actual_value else "")
                             + ")" for rule, n in top))
    if not out:
        out.append("Ich sehe keinen Hinderungsgrund – der Bot wartet einfach auf ein passendes Signal.")
    return "Warum der Bot gerade nicht (mehr) kauft:\n" + "\n".join(f"- {x}" for x in out)


def ans_strategies(c: Ctx, p: Parsed) -> str:
    targets = c.strategies_for(p) or c.cfg["strategies"]
    w = c.dash["weights"]
    allowed = ORDER_STATUSES[c.cfg["account"]]
    lines = [f"- {s['name']} ({s['timeframe']}): **{STATUS_LABEL[s['status']]}**"
             + (f", Anteil {num(w.get(s['id'], 0) * 100, 0)} %" if s["status"] in allowed else ", handelt im aktuellen Modus nicht")
             for s in targets]
    return "Deine Strategien:\n" + "\n".join(lines) + "\n\nÄndern: z. B. „Stell Trendfolge auf Live-klein“."


def ans_markets(c: Ctx, p: Parsed) -> str:
    d = c.dash
    regs = {r["symbol"]: r for r in d["regimes"]}
    if p.markets:
        out = []
        for m in p.markets:
            t = d["tickers"].get(m)
            r = regs.get(m)
            on = m in c.cfg["markets"]
            out.append(f"{mname(m)}: " + (f"Kurs {eur(t['last'] or t['bid'])}, " if t else "")
                       + (f"Marktlage {r['label']} ({r['hint']})" if r else "") + ("" if on else "ausgeschaltet – sag „Schalte … ein“"))
        return "\n".join(out)
    lines = [f"- {mname(m)}: {regs[m]['label'] if m in regs else '—'}" for m in c.cfg["markets"]]
    return "Eingeschaltete Märkte:\n" + "\n".join(lines)


def ans_risk(c: Ctx) -> str:
    r, d = c.cfg["risk"], c.dash
    return "\n".join([f"Risiko pro Trade: {num(r['risk_per_trade_pct'])} %", f"Tagesverlust-Grenze: {num(r['daily_loss_limit_pct'])} %",
                      f"Max. Drawdown: {num(r['max_drawdown_pct'])} % (aktuell {num(d['drawdown_pct'])} %)",
                      f"Max. Positionen: {r['max_positions']} (offen {len(d['positions'])})",
                      f"Verlustserie: {d['loss_streak']} von {r['loss_streak_limit']}",
                      "Ändern: z. B. „Setze Risiko pro Trade auf 0,5 %“."])


def ans_events(c: Ctx) -> str:
    ev = [e for e in c.dash["events"] if e["severity"] in ("warnung", "fehler", "kritisch")][:5] or c.dash["events"][:5]
    if not ev:
        return "Keine Meldungen."
    return "Letzte Meldungen:\n" + "\n".join(f"- {e['time']:%d.%m. %H:%M} {e['message']}" for e in ev)


def ans_settings(c: Ctx) -> str:
    cfg = c.cfg
    return "\n".join([f"Modus: {'Echtgeld' if cfg['account'] == 'live' else 'Spielgeld (Paper)'}",
                      f"Automatisierung: {AUTOMATION_LABEL[cfg['automation']]}",
                      f"Märkte: {len(cfg['markets'])} eingeschaltet", ans_risk(c)])


def ans_knowledge(p: Parsed) -> str | None:
    qw = {x for w in p.words for x in w.split("-") if len(x) >= 3} - {"was", "ist", "der", "die", "das", "wie", "bedeutet", "heisst", "ein", "eine", "mir", "erklaer",
                                                "erklaere", "kannst", "du", "bitte", "und", "mit", "den", "dem", "von", "beim", "bot", "warum"}
    if not qw:
        return None
    best, score = None, 0.0
    for e in WISSEN:
        for q in e["q"]:
            kw = {w for w in norm(q).replace("-", " ").split() if len(w) >= 3}
            if not kw:
                continue
            hit = sum(1 for w in qw if any(w == k or (len(w) >= 5 and (k.startswith(w) or w.startswith(k))) for k in kw))
            s = hit / len(kw) + hit * 0.2
            if s > score:
                best, score = e["a"], s
    return best if score >= 0.7 else None


HELP = ("Ich kenne deinen Bot und kann für dich:\n"
        "- **Fragen beantworten**: „Wie läuft es?“, „Wie viel Gewinn heute?“, „Warum kauft der Bot nichts?“, „Was ist ein Stop-Loss?“\n"
        "- **Einstellen**: „Stell Trendfolge auf Paper“, „Schalte Dogecoin aus“, „Setze Risiko pro Trade auf 0,5 %“, „Halbautomatisch“\n"
        "- **Steuern**: „Pausiere den Bot“, „Starte den Bot“, „Verkaufe Bitcoin“, „Übergib meine ETH dem Bot“, „Zurück auf Spielgeld“\n"
        "Bevor ich etwas ändere, zeige ich dir genau, was passiert, und du bestätigst mit „Ja, machen“.")


def respond(db: Session, u: User, text: str) -> tuple[str, dict | None]:
    c = Ctx(db, u)
    p = parse(text)
    w, q = p.words, is_question(text, p)
    if not w:
        return HELP, None
    if p.text in ("hallo", "hi", "hey", "moin", "servus", "guten morgen", "guten abend", "guten tag", "hallo bot"):
        return "Hallo! " + HELP, None
    if stem_in(w, "dank") and len(w) <= 4:
        return "Gern! Sag Bescheid, wenn ich noch etwas tun soll.", None
    if any_word(w, {"hilfe", "help"}) or "was kannst du" in p.text:
        return HELP, None
    if is_no(text) or is_yes(text):
        return "Gerade wartet kein Vorschlag auf deine Antwort. Was soll ich tun?", None
    if p.text.startswith(("was ist", "was sind", "was bedeutet", "was heisst", "was heißt", "erklaer", "was macht", "wofuer")):
        k = ans_knowledge(p)
        if k:
            if p.setting:
                spec = RISK_FIELDS[p.setting]
                k += f"\n\nBei dir eingestellt – {spec['label']}: {num(c.cfg['risk'][p.setting])}{(' ' + spec['unit']) if spec['unit'] else ''}."
            return k, None

    # Aufträge
    if not q or p.text.startswith(("kannst du", "koenntest du", "kann man")):
        if stem_in(w, "notaus", "not-aus", "notbrems") or "not aus" in p.text:
            return act_close(c, Parsed(p.text, w + ["alle"])) if c.dash["positions"] else (
                "Not-Aus stoppt sofort alles.", command_action("notaus", "Not-Aus", ["Bot stoppt sofort, offene Orders werden storniert"]))
        if stem_in(w, "uebergib", "uebergeb", "uebernimm") and not stem_in(w, "vorschlag"):
            return act_adopt(c, p)
        if stem_in(w, "verkauf", "schliess", "schließ") and (p.markets or "alle" in w) and not p.setting:
            return act_close(c, p)
        if stem_in(w, "vorschlag") and stem_in(w, "uebernehm", "annehm", "bestaetig", "akzeptier"):
            return act_bot(c, "auswahl_bestaetigen")
        if (stem_in(w, "neu") and stem_in(w, "bewert", "auswahl", "vorschlag")):
            return act_bot(c, "auswahl_neu")
        if (p.strategies or p.all_strategies) and (p.status or stem_in(w, "stell", "setz", "aender", "schalt", "mach", "wechsel", "pausier",
                                                                       "aktivier", "deaktivier", "ausschalt", "einschalt")):
            return act_strategy_status(c, p)
        if p.automation and stem_in(w, "stell", "setz", "aender", "schalt", "mach", "wechsel", "auf", "modus") and not p.markets:
            return act_automation(c, p.automation)
        if p.setting and (p.number is not None or stem_in(w, "stell", "setz", "aender")):
            return act_setting(c, p)
        if p.markets or p.groups:
            only = "nur" in w and stem_in(w, "handel", "markt", "noch", "kauf")
            off = any_word(w, {"kein", "keine", "keinen", "ohne", "aus", "ausschalten", "abschalten", "deaktivieren", "deaktiviere", "entfernen", "entferne", "raus", "weg",
                               "rausnehmen", "streichen", "nicht"})
            on = any_word(w, {"an", "ein", "einschalten", "anschalten", "aktivieren", "aktiviere", "hinzufuegen", "dazu", "dazunehmen",
                              "aufnehmen", "freischalten", "rein"}) or (stem_in(w, "handel") and not off)
            if only or on or off:
                r = act_markets(c, p, on=not off, only=only)
                if r:
                    return r
        switch = stem_in(w, "umstell", "stell", "wechsel", "schalt", "zurueck", "geh", "aktivier", "mach", "auf", "starte")
        if switch and not p.strategies and not p.markets:
            if any_word(w, {"spielgeld", "paper", "papier", "demo"}):
                return act_account(c, "paper")
            if any_word(w, {"echtgeld", "live", "echt", "echtem"}):
                return act_account(c, "live")
        if stem_in(w, "pausier") or (any_word(w, {"pause"}) and len(w) <= 4):
            return act_bot(c, "pause")
        if stem_in(w, "stopp", "stoppe", "anhalt", "halt") and "bot" in w or p.text in ("stopp", "stop", "stoppen", "halt"):
            return act_bot(c, "stop")
        if stem_in(w, "start", "weitermach", "fortsetz", "losleg", "laufen") and ("bot" in w or len(w) <= 3):
            return act_bot(c, "start")
        if stem_in(w, "sperre", "freigeb", "entsperr") and stem_in(w, "aufheb", "freigeb", "entsperr", "loes"):
            return act_bot(c, "freigeben")

    # Fragen
    if (stem_in(w, "warum", "wieso", "weshalb") and stem_in(w, "kauf", "handel", "trade", "nichts", "passiert")) or \
            ("kauft" in w and "nichts" in w) or ("keine" in w and stem_in(w, "trade", "kaeuf")):
        return ans_why(c), None
    if stem_in(w, "gewinn", "verlust", "verdien", "plus", "minus", "ergebnis", "rendite", "performance", "guthaben", "kontostand",
               "kontowert", "geld", "eur", "euro", "bilanz", "vermoegen", "bestand", "bestaende"):
        if not p.setting:
            return ans_money(c), None
    if stem_in(w, "position", "gekauft", "offen", "besitz", "halte", "portfolio", "depot"):
        return ans_positions(c), None
    if (p.strategies or stem_in(w, "strateg")) and not stem_in(w, "erklaer") and not (p.strategies and stem_in(w, "was", "bedeut")):
        return ans_strategies(c, p), None
    if p.setting:
        return act_setting(c, p)
    if stem_in(w, "zustand", "status", "laeuft", "lauft", "stand", "ueberblick", "uebersicht") or p.text in ("und", "wie gehts", "na"):
        return ans_status(c), None
    if p.markets and not stem_in(w, "bedeut", "erklaer"):
        return ans_markets(c, p), None
    if stem_in(w, "markt", "maerkte", "marktlage", "regime", "kurs", "kurse"):
        return ans_markets(c, p), None
    if stem_in(w, "risiko", "grenze", "limit", "sicherheit") and not stem_in(w, "was"):
        return ans_risk(c), None
    if stem_in(w, "meldung", "fehler", "warnung", "problem", "passiert"):
        return ans_events(c), None
    if stem_in(w, "einstellung"):
        return ans_settings(c), None
    if p.status and q:
        return ans_knowledge(Parsed(p.text, ["live", "klein"] if p.status == "live_klein" else ["paper", "live", "unterschied"])) or HELP, None
    k = ans_knowledge(p)
    if k:
        return k, None
    if not q and (p.strategies or p.markets or p.status or p.setting):
        return "Das habe ich nicht ganz verstanden. Sag es bitte etwas genauer, z. B. „Stell Trendfolge auf Paper“ oder „Schalte Dogecoin aus“.", None
    return ("Dazu weiß ich leider nichts. Ich kenne mich mit deinem Bot aus: Status, Gewinn, Positionen, Strategien, Märkte, Risiko und alle "
            "Begriffe aus der Anleitung. Schreib „Hilfe“ für Beispiele."), None


def execute(db: Session, u: User, action: dict) -> str:
    """Führt einen bestätigten Vorschlag über dieselben Wege aus wie die App-Knöpfe (Prüfung, Versionierung, Protokoll)."""
    from fastapi import HTTPException

    from ..api.bot_routes import config_commit, config_preview
    from ..engine import get_engine
    by = f"{u.display_name} (Assistent)"
    if action["kind"] == "config":
        _, vid = current_config(db, u.id)
        if vid != action["base_version_id"]:
            raise HTTPException(409, "Die Einstellungen wurden inzwischen geändert – bitte den Auftrag nochmal schreiben")
        old, new, changes, warnings = config_preview(db, u, action["config"])
        if not changes:
            return "Nichts zu ändern – war schon so eingestellt."
        config_commit(db, u, old, new, changes, warnings, by=by)
        return "Erledigt – gespeichert: " + "; ".join(pretty_changes(old, new, changes))
    if action["kind"] == "command":
        cmd = action["command"]
        if cmd not in {"start", "pause", "stop", "freigeben", "notaus", "position_schliessen", "bestand_uebernehmen",
                       "auswahl_neu", "auswahl_bestaetigen"}:
            raise HTTPException(400, "Unbekannter Auftrag")
        if cmd == "position_schliessen":
            pos = db.get(Position, action["args"].get("position_id"))
            if pos is None or pos.user_id != u.id or pos.status != "offen":
                raise HTTPException(404, "Position ist nicht (mehr) offen")
        if cmd == "start" and db.get(BotRuntime, u.id) is None:
            raise HTTPException(400, "Bot nicht eingerichtet")
        try:
            msg = get_engine().command(u.id, cmd, by, bestaetigt=True, **action["args"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return "Erledigt." + (f" {msg}" if msg and msg != "OK" else "")
    raise HTTPException(400, "Unbekannter Auftrag")


def is_yes(text: str) -> bool:
    t = norm(text).strip(" .!")
    return t in YES or bool(re.fullmatch(r"(ja|ok|okay)[ ,]*(bitte|mach(en)?|mach das|gerne|los)?( bitte)?", t))


def is_no(text: str) -> bool:
    return norm(text).strip(" .!") in NO


