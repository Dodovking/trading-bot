"""Bot-API: Dashboard, Steuerung, Einstellungen (mit Änderungsvorschau), Strategien, Module, Konten, Backtest, Export."""
from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..brokers.catalog import BY_ID, COMMON_RULES, PROVIDERS
from ..core.config import (LIFECYCLE_LABELS, RISK_FIELDS, ConfigError, current_config, diff_config, save_config,
                           validate_config)
from ..core.crypto import encrypt
from ..core.db import utcnow
from ..core.events import log_event
from ..core.models import (AccountSnapshot, AppSetting, BotEvent, BotRuntime, BrokerLink, IncomeEntry, Instrument, Order, Position, RegimeLog,
                           RiskDecision, SignalRow, StrategyPerformance, TradingAccount, User)
from ..core.state import STATE_LABELS
from ..earn.catalog import CATALOG, WARNSIGNALE
from ..engine import get_engine
from ..execution.accounts import (ensure_live_account, ensure_user_setup, get_account, get_link, get_links, link_broker,
                                  make_broker, trading_links)
from ..selection import controller
from ..selection.regime import REGIME_HINT, REGIMES
from ..strategies.registry import STRATEGY_TYPES, library
from .deps import get_db, user

router = APIRouter(prefix="/api")


def f(x) -> float | None:
    return None if x is None else float(x)


def _symbols(db: Session) -> dict[int, str]:
    return {i.id: i.symbol for i in db.scalars(select(Instrument))}


def _broker_label(db: Session, user_id: int, acct) -> str | None:
    if acct is None:
        return None
    if acct.kind == "paper":
        return "paper"
    return " + ".join(BY_ID[lk.broker]["name"] for lk in trading_links(db, user_id) if lk.broker in BY_ID) or None


def foreign_live_allowed(db: Session) -> bool:
    row = db.get(AppSetting, "fremd_live")
    return bool(row and row.value.get("enabled"))


# ------------------------------------------------------------------ Dashboard
@router.get("/dashboard")
def dashboard(u: User = Depends(user), db: Session = Depends(get_db)):
    ensure_user_setup(db, u.id)
    e = get_engine()
    cfg, _ = current_config(db, u.id)
    rt = db.get(BotRuntime, u.id)
    acct = get_account(db, u.id, cfg["account"])
    syms = _symbols(db)
    positions, exposure, unreal = [], Decimal(0), Decimal(0)
    if acct:
        for p in db.scalars(select(Position).where(Position.user_id == u.id, Position.account_id == acct.id, Position.status == "offen")):
            t = e.market.ticker(syms[p.instrument_id])
            mark = t.bid if t else p.avg_entry
            value = p.qty * mark
            pnl = value - p.entry_value - p.fees
            exposure += value
            unreal += pnl
            positions.append({"id": p.id, "symbol": syms[p.instrument_id], "strategy": p.strategy_name, "kind": p.side, "qty": f(p.qty),
                              "entry": f(p.avg_entry), "price": f(mark), "stop": f(p.stop), "take_profit": f(p.take_profit),
                              "value": f(value), "pnl": f(pnl), "pnl_pct": f(pnl / p.entry_value * 100) if p.entry_value else 0,
                              "opened_at": p.opened_at, "protected": bool(p.stop_client_order_id) or p.side == "bestand"})
    snap = db.scalars(select(AccountSnapshot).where(AccountSnapshot.user_id == u.id, AccountSnapshot.account_kind == cfg["account"])
                      .order_by(AccountSnapshot.id.desc()).limit(1)).first()
    equity = f(snap.equity) if snap else f(acct.start_capital) if acct else 0
    since = utcnow() - timedelta(days=90)
    curve = [[s.time, f(s.equity)] for s in db.scalars(select(AccountSnapshot).where(
        AccountSnapshot.user_id == u.id, AccountSnapshot.account_kind == cfg["account"], AccountSnapshot.time >= since)
        .order_by(AccountSnapshot.time))]
    if len(curve) > 500:
        curve = curve[:: len(curve) // 500 + 1] + [curve[-1]]
    closed = list(db.scalars(select(Position).where(Position.user_id == u.id, Position.account_id == (acct.id if acct else -1),
                                                    Position.status == "geschlossen").order_by(Position.closed_at.desc()).limit(500)))
    day_pnl = (Decimal(str(equity)) - rt.day_start_equity) if rt.day_start_equity and equity is not None else Decimal(0)
    realized = sum((p.realized for p in closed), Decimal(0))
    wins = [p for p in closed if p.realized > 0]
    events = [{"id": ev.id, "time": ev.time, "severity": ev.severity, "module": ev.module, "kind": ev.kind, "message": ev.message}
              for ev in db.scalars(select(BotEvent).where((BotEvent.user_id == u.id) | (BotEvent.user_id.is_(None)))
                                   .order_by(BotEvent.id.desc()).limit(30))]
    pending = [{"id": s.id, "symbol": syms[s.instrument_id], "strategy": s.strategy_name, "price": f(s.price), "stop": f(s.stop_suggestion),
                "time": s.time, "reason": s.reasoning.get("grund", "")}
               for s in db.scalars(select(SignalRow).where(SignalRow.user_id == u.id, SignalRow.status == "wartet_bestaetigung"))]
    rtf = cfg["selection"]["regime_timeframe"]
    regimes = [{"symbol": m, "regime": e.regime_of(m, rtf), "label": REGIMES[e.regime_of(m, rtf)],
                "hint": REGIME_HINT[e.regime_of(m, rtf)], "values": e.regimes.get((m, rtf), ("", {}))[1]} for m in cfg["markets"]]
    weights = controller.current_weights(db, u.id, cfg)
    proposal = controller.latest_batch(db, u.id, None)
    heartbeat_age = (utcnow() - rt.heartbeat_at).total_seconds() if rt.heartbeat_at else None
    return {
        "state": rt.state, "state_label": STATE_LABELS[rt.state], "state_reason": rt.state_reason, "state_since": rt.state_since,
        "lock_kind": rt.lock_kind, "want_running": rt.want_running, "mode": cfg["account"], "automation": cfg["automation"],
        "broker": _broker_label(db, u.id, acct), "broker_ok": rt.broker_ok, "reconcile_ok": rt.last_reconcile_ok,
        "reconcile_note": rt.last_reconcile_note, "last_reconcile_at": rt.last_reconcile_at, "heartbeat_age_s": heartbeat_age,
        "engine_error": e.tick_error, "data_ok": e.market.healthy if hasattr(e.market, "healthy") else True,
        "equity": equity, "start_capital": f(acct.start_capital) if acct else None, "exposure": f(exposure), "unrealized": f(unreal),
        "day_pnl": f(day_pnl), "realized_total": f(realized), "trades_total": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "drawdown_pct": f(snap.drawdown_pct) if snap else 0, "loss_streak": rt.loss_streak, "positions": positions, "curve": curve,
        "events": events, "pending_signals": pending, "regimes": regimes,
        "weights": weights, "selection_mode": cfg["selection"]["mode"],
        "proposal_open": bool(proposal) and not proposal[0].applied,
        "tickers": {m: {"bid": f(t.bid), "ask": f(t.ask), "last": f(t.last)} for m in cfg["markets"] if (t := e.market.ticker(m))},
        "external": (rt.external or []) if cfg["account"] == "live" else [],
    }


class CommandIn(BaseModel):
    action: str
    position_id: int | None = None
    signal_id: int | None = None
    bestaetigt: bool = False
    asset: str | None = None


@router.post("/command")
def command(body: CommandIn, u: User = Depends(user)):
    allowed = {"start", "pause", "stop", "wartung", "notaus", "freigeben", "position_schliessen", "signal_bestaetigen",
               "signal_verwerfen", "auswahl_neu", "auswahl_bestaetigen", "bestand_uebernehmen"}
    if body.action not in allowed:
        raise HTTPException(400, "Unbekannter Befehl")
    try:
        msg = get_engine().command(u.id, body.action, u.display_name, position_id=body.position_id, signal_id=body.signal_id,
                                   bestaetigt=body.bestaetigt, asset=body.asset)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "message": msg}


# ------------------------------------------------------------------ Verlauf
@router.get("/trades")
def trades(limit: int = 200, u: User = Depends(user), db: Session = Depends(get_db)):
    syms = _symbols(db)
    accts = {a.id: a.kind for a in db.scalars(select(TradingAccount).where(TradingAccount.user_id == u.id))}
    rows = db.scalars(select(Position).where(Position.user_id == u.id, Position.status == "geschlossen")
                      .order_by(Position.closed_at.desc()).limit(min(limit, 2000)))
    return [{"id": p.id, "symbol": syms[p.instrument_id], "strategy": p.strategy_name, "mode": accts.get(p.account_id), "kind": p.side,
             "qty": f(p.qty), "entry": f(p.avg_entry), "exit": f(p.exit_price), "pnl": f(p.realized), "fees": f(p.fees),
             "pnl_pct": f(p.realized / p.entry_value * 100) if p.entry_value else 0, "reason": p.exit_reason,
             "opened_at": p.opened_at, "closed_at": p.closed_at, "initial_stop": f(p.initial_stop)} for p in rows]


@router.get("/events")
def events(limit: int = 200, severity: str | None = None, before: int | None = None, u: User = Depends(user),
           db: Session = Depends(get_db)):
    q = select(BotEvent).where((BotEvent.user_id == u.id) | (BotEvent.user_id.is_(None)))
    if severity:
        q = q.where(BotEvent.severity == severity)
    if before:
        q = q.where(BotEvent.id < before)
    return [{"id": ev.id, "time": ev.time, "severity": ev.severity, "module": ev.module, "kind": ev.kind, "message": ev.message,
             "data": ev.data} for ev in db.scalars(q.order_by(BotEvent.id.desc()).limit(min(limit, 1000)))]


@router.get("/signals")
def signals(limit: int = 200, u: User = Depends(user), db: Session = Depends(get_db)):
    syms = _symbols(db)
    sigs = list(db.scalars(select(SignalRow).where(SignalRow.user_id == u.id).order_by(SignalRow.id.desc()).limit(min(limit, 1000))))
    dec = {d.signal_id: d for d in db.scalars(select(RiskDecision).where(RiskDecision.signal_id.in_([s.id for s in sigs])))}
    out = []
    for s in sigs:
        d = dec.get(s.id)
        out.append({"id": s.id, "time": s.time, "candle_time": s.candle_time, "symbol": syms[s.instrument_id], "strategy": s.strategy_name,
                    "timeframe": s.timeframe, "direction": s.direction, "price": f(s.price), "stop": f(s.stop_suggestion),
                    "status": s.status, "reasoning": s.reasoning,
                    "risk": {"result": d.result, "rule": d.rule, "limit": d.limit_value, "actual": d.actual_value,
                             "qty": f(d.position_size), "checks": d.checks} if d else None})
    return out


@router.get("/orders")
def orders(limit: int = 200, u: User = Depends(user), db: Session = Depends(get_db)):
    syms = _symbols(db)
    return [{"id": o.id, "client_order_id": o.client_order_id, "symbol": syms[o.instrument_id], "side": o.side, "type": o.type,
             "purpose": o.purpose, "qty": f(o.qty), "stop_price": f(o.stop_price), "status": o.status, "filled": f(o.filled_qty),
             "avg_price": f(o.avg_fill_price), "fees": f(o.fees), "note": o.note, "created_at": o.created_at}
            for o in db.scalars(select(Order).where(Order.user_id == u.id).order_by(Order.id.desc()).limit(min(limit, 1000)))]


# ------------------------------------------------------------------ Einstellungen
@router.get("/config")
def get_config(u: User = Depends(user), db: Session = Depends(get_db)):
    cfg, vid = current_config(db, u.id)
    from ..data.instruments import NAMES
    ready = get_engine().market.stocks_ready()
    markets = [{"symbol": i.symbol, "name": NAMES.get(i.symbol, ""), "market": i.market, "tradable": i.tradable, "note": i.note,
                "data_ok": i.market != "aktie" or ready}
               for i in db.scalars(select(Instrument).where(Instrument.active.is_(True)))]
    return {"config": cfg, "version_id": vid, "risk_fields": RISK_FIELDS, "markets": markets, "lifecycle": LIFECYCLE_LABELS,
            "strategy_types": {k: {"name": s.name, "params": [p.to_dict() for p in s.params], "family": s.family}
                               for k, s in STRATEGY_TYPES.items()},
            "foreign_live_allowed": foreign_live_allowed(db) or u.role == "admin"}


class ConfigIn(BaseModel):
    config: dict
    base_version_id: int | None = None
    confirm: bool = False


@router.post("/config")
def put_config(body: ConfigIn, u: User = Depends(user), db: Session = Depends(get_db)):
    """Ohne confirm: nur Vorschau der Änderungen. Mit confirm: speichern (neue Konfigurationsversion)."""
    old, vid = current_config(db, u.id)
    known = {i.symbol for i in db.scalars(select(Instrument).where(Instrument.active.is_(True)))}
    try:
        new = validate_config(body.config, known)
    except ConfigError as e:
        raise HTTPException(400, str(e)) from e
    try:  # gespeicherte Version gleich normalisieren, damit nur echte Änderungen erscheinen
        old = validate_config(old, known)
    except ConfigError:
        pass
    if new["account"] == "live":
        if u.role != "admin" and not foreign_live_allowed(db):
            raise HTTPException(403, "Echtgeld-Handel ist für dieses Konto noch nicht freigegeben (Administrator)")
        if not trading_links(db, u.id):
            raise HTTPException(400, "Zuerst einen Echtgeld-Anbieter verbinden und testen (Alpaca Paper zählt nicht als Echtgeld)")
    changes = diff_config(old, new)
    warnings = []
    if old["account"] != new["account"]:
        warnings.append("Kontowechsel: " + ("ECHTGELD wird aktiviert!" if new["account"] == "live" else "zurück zu Paper"))
    for k in ("risk_per_trade_pct", "daily_loss_limit_pct", "max_drawdown_pct"):
        if new["risk"][k] > old["risk"][k]:
            warnings.append(f"{RISK_FIELDS[k]['label']} wird erhöht ({old['risk'][k]} → {new['risk'][k]} %)")
    if not body.confirm:
        return {"preview": True, "changes": changes, "warnings": warnings}
    if body.base_version_id != vid:
        raise HTTPException(409, "Die Einstellungen wurden inzwischen auf einem anderen Gerät geändert – bitte neu laden")
    if not changes:
        return {"preview": False, "changes": [], "version_id": vid}
    with get_engine().lock:
        row = save_config(db, u.id, new, u.display_name)
        if old["account"] != new["account"]:
            from ..engine import switch_account
            switch_account(db, db.get(BotRuntime, u.id), old["account"], new["account"])
        db.commit()
    log_event(u.id, "warnung" if warnings else "info", "einstellungen", f"Einstellungen geändert ({len(changes)} Änderungen)",
              kind="konfiguration", data={"changes": changes[:50], "version_id": row.id}, db=db)
    return {"preview": False, "changes": changes, "version_id": row.id}


@router.get("/config/history")
def config_history(u: User = Depends(user), db: Session = Depends(get_db)):
    from ..core.models import ConfigVersion
    return [{"id": c.id, "time": c.created_at, "by": c.changed_by, "summary": c.summary}
            for c in db.scalars(select(ConfigVersion).where(ConfigVersion.user_id == u.id).order_by(ConfigVersion.id.desc()).limit(100))]


# ------------------------------------------------------------------ Strategien und Auswahl
@router.get("/strategies")
def strategies(u: User = Depends(user), db: Session = Depends(get_db)):
    cfg, _ = current_config(db, u.id)
    perf = {}
    for p in db.scalars(select(StrategyPerformance).where(StrategyPerformance.user_id == u.id, StrategyPerformance.regime == "alle")
                        .order_by(StrategyPerformance.id.desc()).limit(200)):
        perf.setdefault(p.strategy_id, {"trades": p.trades, "expectancy_r": f(p.expectancy_r), "profit_factor": f(p.profit_factor),
                                        "win_rate": f(p.win_rate), "drawdown_r": f(p.drawdown_r), "stability": f(p.stability),
                                        "score": f(p.score), "time": p.time})
    batch = controller.latest_batch(db, u.id, None)
    applied = controller.current_weights(db, u.id, cfg)
    return {"library": library(), "configured": cfg["strategies"], "scorecards": perf, "weights": applied,
            "selection": cfg["selection"],
            "last_batch": [{"strategy_id": a.strategy_id, "weight": f(a.weight), "status": a.status, "applied": a.applied,
                            "time": a.time, "reasoning": a.reasoning} for a in batch]}


@router.get("/regimes")
def regimes(symbol: str, timeframe: str = "4h", u: User = Depends(user), db: Session = Depends(get_db)):
    inst = db.scalars(select(Instrument).where(Instrument.symbol == symbol)).first()
    if inst is None:
        raise HTTPException(404, "Markt unbekannt")
    return [{"time": r.candle_time, "regime": r.regime, "label": REGIMES[r.regime], "values": r.values}
            for r in db.scalars(select(RegimeLog).where(RegimeLog.instrument_id == inst.id, RegimeLog.timeframe == timeframe)
                                .order_by(RegimeLog.candle_time.desc()).limit(200))]


@router.get("/candles")
def candles(symbol: str, timeframe: str = "1h", limit: int = 300, u: User = Depends(user), db: Session = Depends(get_db)):
    inst = db.scalars(select(Instrument).where(Instrument.symbol == symbol)).first()
    if inst is None:
        raise HTTPException(404, "Markt unbekannt")
    bars = get_engine().market.bars(db, inst.id, timeframe, min(limit, 1000))
    return [[b.time, b.open, b.high, b.low, b.close, b.volume] for b in bars]


# ------------------------------------------------------------------ Ertragsmodule
@router.get("/earn")
def earn(u: User = Depends(user), db: Session = Depends(get_db)):
    cfg, _ = current_config(db, u.id)
    income = [{"time": i.time, "mode": i.account_kind, "source": i.source, "kind": i.kind, "asset": i.asset, "amount": f(i.amount),
               "note": i.note} for i in db.scalars(select(IncomeEntry).where(IncomeEntry.user_id == u.id)
                                                   .order_by(IncomeEntry.id.desc()).limit(300))]
    return {"catalog": CATALOG, "warning": WARNSIGNALE, "modules": cfg["modules"], "income": income}


# ------------------------------------------------------------------ Konten und Anbieter
@router.get("/providers")
def providers(u: User = Depends(user), db: Session = Depends(get_db)):
    ensure_user_setup(db, u.id)
    accts = [{"id": a.id, "kind": a.kind, "broker": a.broker, "currency": a.currency, "connected": a.connected,
              "note": a.connection_note, "start_capital": f(a.start_capital)}
             for a in db.scalars(select(TradingAccount).where(TradingAccount.user_id == u.id))]
    links = [{"broker": lk.broker, "name": BY_ID[lk.broker]["name"] if lk.broker in BY_ID else lk.broker,
              "markets": BY_ID[lk.broker]["markets"] if lk.broker in BY_ID else [], "environment": lk.environment,
              "connected": lk.connected, "note": lk.connection_note, "key_hint": lk.api_key_hint,
              "trades_live": lk.connected and lk.environment == "live"} for lk in get_links(db, u.id) if lk.api_key_enc]
    return {"providers": PROVIDERS, "rules": COMMON_RULES, "accounts": accts, "links": links,
            "live_allowed": foreign_live_allowed(db) or u.role == "admin"}


class KeysIn(BaseModel):
    broker: str
    key: str
    secret: str
    umgebung: str = "live"


class BrokerIn(BaseModel):
    broker: str | None = None


def _link_in_use(db: Session, u: User, link) -> bool:
    cfg, _ = current_config(db, u.id)
    return cfg["account"] == "live" and link.connected and link.environment == "live"


@router.post("/accounts/live")
def set_live_keys(body: KeysIn, u: User = Depends(user), db: Session = Depends(get_db)):
    p = BY_ID.get(body.broker)
    if p is None or p["id"] == "paper":
        raise HTTPException(400, "Anbieter unbekannt")
    if p["status"] != "verfuegbar":
        raise HTTPException(400, f"{p['name']}: Anbindung ist in Vorbereitung – die Anleitung kannst du schon nutzen")
    env = "paper" if p["id"] == "alpaca" and body.umgebung == "paper" else "live"
    if env == "live" and u.role != "admin" and not foreign_live_allowed(db):
        raise HTTPException(403, "Echtgeld-Handel ist für dieses Konto noch nicht freigegeben (Administrator)")
    key, secret = body.key.strip(), body.secret.strip()
    if len(key) < 10 or len(secret) < 10:
        raise HTTPException(400, "Schlüssel unvollständig")
    link = get_link(db, u.id, p["id"])
    if link is None:
        link = BrokerLink(user_id=u.id, broker=p["id"])
        db.add(link)
    elif _link_in_use(db, u, link):
        raise HTTPException(409, f"{p['name']} handelt gerade mit Echtgeld – Schlüssel nur im Paper-Modus austauschen")
    link.api_key_enc, link.api_secret_enc = encrypt(key), encrypt(secret)
    link.environment = env
    link.api_key_hint = key[:4] + "…" + key[-3:]
    link.connected, link.connection_note = False, "Noch nicht getestet"
    ensure_live_account(db, u.id)
    db.flush()
    log_event(u.id, "warnung", "konto", f"API-Schlüssel für {p['name']} hinterlegt", kind="konto", db=db)
    return test_live(BrokerIn(broker=p["id"]), u, db)


@router.post("/accounts/live/test")
def test_live(body: BrokerIn | None = None, u: User = Depends(user), db: Session = Depends(get_db)):
    links = [lk for lk in get_links(db, u.id) if lk.api_key_enc and (not body or not body.broker or lk.broker == body.broker)]
    if not links:
        raise HTTPException(404, "Kein Anbieter verbunden")
    notes, cash = [], Decimal(0)
    for link in links:
        try:
            broker = link_broker(link, get_engine().market.ticker)
            note = broker.check_connection()
            bal = broker.balances()
            perm = getattr(broker, "check_no_withdrawal", None)
            if perm:
                perm()
            link.connected, link.connection_note = True, note
            if link.environment == "live":
                cash += bal.get("EUR", Decimal(0))
        except Exception as e:  # noqa: BLE001
            link.connected, link.connection_note = False, f"Fehler: {str(e)[:250]}"
        if link.broker == "alpaca":
            from ..data.stocks import reset_keys_cache
            db.flush()
            reset_keys_cache()
            if link.connected:
                link.connection_note += " · liefert auch die Aktienkurse"
        notes.append(link.connection_note if len(links) == 1 else f"{BY_ID.get(link.broker, {}).get('name', link.broker)}: "
                     f"{link.connection_note}")
    acct = ensure_live_account(db, u.id)
    acct.connected = bool(trading_links(db, u.id))
    if not acct.start_capital and cash:
        acct.start_capital = cash
    return {"connected": all(lk.connected for lk in links), "note": " | ".join(notes)}


@router.delete("/accounts/live")
def delete_live(broker: str | None = None, u: User = Depends(user), db: Session = Depends(get_db)):
    for link in get_links(db, u.id):
        if broker and link.broker != broker:
            continue
        if _link_in_use(db, u, link):
            raise HTTPException(409, f"{BY_ID.get(link.broker, {}).get('name', link.broker)} handelt gerade mit Echtgeld – "
                                     "erst auf Paper umstellen")
        db.delete(link)
    db.flush()
    from ..data.stocks import reset_keys_cache
    reset_keys_cache()
    acct = get_account(db, u.id, "live")
    if acct:
        acct.connected = bool(trading_links(db, u.id))
    return {"ok": True}


class ResetIn(BaseModel):
    capital: float = 10000


@router.post("/accounts/paper/reset")
def reset_paper(body: ResetIn, u: User = Depends(user), db: Session = Depends(get_db)):
    cfg, _ = current_config(db, u.id)
    acct = get_account(db, u.id, "paper")
    rt = db.get(BotRuntime, u.id)
    if cfg["account"] == "paper" and rt.state == "AKTIV":
        raise HTTPException(409, "Bot zuerst stoppen")
    if not (100 <= body.capital <= 10_000_000):
        raise HTTPException(400, "Startkapital 100 € – 10 Mio. €")
    for p in db.scalars(select(Position).where(Position.account_id == acct.id, Position.status == "offen")):
        p.status, p.exit_reason, p.closed_at, p.realized = "geschlossen", "Konto zurückgesetzt", utcnow(), Decimal(0)
    for o in db.scalars(select(Order).where(Order.account_id == acct.id, Order.status.in_(("erstellt", "freigegeben", "gesendet",
                                                                                            "bestaetigt", "teilweise")))):
        o.status = "storniert"
    broker = make_broker(db, acct, cfg, get_engine().market.ticker)
    broker.reset(Decimal(str(body.capital)))
    acct.start_capital = Decimal(str(body.capital))
    if cfg["account"] == "paper":
        rt.peak_equity = rt.day_start_equity = Decimal(str(body.capital))
        rt.loss_streak = 0
        rt.last_reconcile_at = None
    log_event(u.id, "info", "konto", f"Paper-Konto auf {body.capital:,.0f} € zurückgesetzt".replace(",", "."), kind="konto", db=db)
    return {"ok": True}


# ------------------------------------------------------------------ Backtest
class BacktestIn(BaseModel):
    strategy_type: str
    params: dict = {}
    symbol: str = "BTC/EUR"
    timeframe: str = "1h"
    days: int = 365
    capital: float = 10000
    risk_pct: float = 1.0


@router.post("/backtest")
def backtest(body: BacktestIn, u: User = Depends(user), db: Session = Depends(get_db)):
    from ..backtest.engine import BtParams, run
    from ..core.models import BacktestRun
    from ..core.types import TIMEFRAMES, Bar
    from ..data.sources import BinanceHistory, DataSourceError
    from ..selection.simulate import Costs
    if body.strategy_type not in STRATEGY_TYPES or body.timeframe not in TIMEFRAMES:
        raise HTTPException(400, "Strategie oder Zeitrahmen ungültig")
    if not (30 <= body.days <= 1500):
        raise HTTPException(400, "Zeitraum 30–1500 Tage")
    cfg, _ = current_config(db, u.id)
    end = utcnow()
    from ..data.stocks import STOCK_SYMBOLS
    stock = body.symbol in STOCK_SYMBOLS
    try:
        if stock:
            src = get_engine().market.source
            if not hasattr(src, "alpaca"):
                raise DataSourceError("Aktien-Historie nicht verfügbar")
            raw = src.alpaca.history(body.symbol, body.timeframe, end - timedelta(days=body.days), end)
        else:
            raw = BinanceHistory().history(body.symbol, body.timeframe, end - timedelta(days=body.days), end)
    except DataSourceError as e:
        raise HTTPException(502, str(e)) from e
    bars = [Bar(c.time, float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume)) for c in raw]
    if len(bars) < 300:
        raise HTTPException(400, f"Zu wenig historische Daten ({len(bars)} Kerzen) – längeren Zeitraum oder kleineren Zeitrahmen wählen")
    strat = STRATEGY_TYPES[body.strategy_type]
    res = run(strat, body.params, bars, TIMEFRAMES[body.timeframe],
              BtParams(body.capital, body.risk_pct, cfg["risk"]["max_position_pct"],
                       Costs(cfg["costs"]["fee_pct"], cfg["costs"]["slippage_pct"], 0.1)))
    row = BacktestRun(user_id=u.id, status="fertig", params=body.model_dump(), result={k: v for k, v in res.items() if k != "trades_liste"})
    db.add(row)
    log_event(u.id, "info", "backtest", f"Backtest {strat.name} {body.symbol} {body.timeframe} ({body.days} Tage): "
              f"{res['gesamt']['rendite_prozent']:+.1f} %, {res['gesamt']['trades']} Trades", kind="backtest", db=db)
    return {"strategy": strat.name, "params": strat.clean_params(body.params), **res,
            "hinweis": ("Daten: Alpaca (IEX), in € umgerechnet mit EZB-Kursen. " if stock else "Daten: Binance-Historie. ")
            + "Vergangene Ergebnisse sind keine Garantie für die Zukunft."}


# ------------------------------------------------------------------ Export (Steuer)
@router.get("/export/{what}.csv")
def export(what: str, u: User = Depends(user), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if what == "trades":
        w.writerow(["Eröffnet", "Geschlossen", "Modus", "Markt", "Strategie", "Menge", "Einstieg", "Ausstieg", "Gebühren", "Ergebnis €", "Grund"])
        for t in trades(5000, u, db):
            w.writerow([t["opened_at"], t["closed_at"], t["mode"], t["symbol"], t["strategy"], t["qty"], t["entry"], t["exit"],
                        t["fees"], t["pnl"], t["reason"]])
    elif what == "ertraege":
        w.writerow(["Zeit", "Modus", "Quelle", "Art", "Wert", "Betrag €", "Notiz"])
        for i in db.scalars(select(IncomeEntry).where(IncomeEntry.user_id == u.id).order_by(IncomeEntry.time)):
            w.writerow([i.time.isoformat(), i.account_kind, i.source, i.kind, i.asset, f"{i.amount:.2f}", i.note])
    elif what == "orders":
        w.writerow(["Zeit", "Client-Order-ID", "Markt", "Seite", "Typ", "Zweck", "Menge", "Status", "Ausgeführt", "Kurs", "Gebühren"])
        for o in orders(10000, u, db):
            w.writerow([o["created_at"], o["client_order_id"], o["symbol"], o["side"], o["type"], o["purpose"], o["qty"], o["status"],
                        o["filled"], o["avg_price"], o["fees"]])
    else:
        raise HTTPException(404, "Unbekannter Export")
    data = "\ufeff" + buf.getvalue()
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{what}.csv"'})


# ------------------------------------------------------------------ Push-Meldungen
class PushIn(BaseModel):
    endpoint: str
    keys: dict


@router.get("/push/key")
def push_key(u: User = Depends(user)):
    from ..core.settings import settings
    return {"key": settings.vapid_public}


@router.post("/push/subscribe")
def push_subscribe(body: PushIn, u: User = Depends(user), db: Session = Depends(get_db)):
    from ..core.models import PushSubscription
    if not body.endpoint.startswith("https://") or not {"p256dh", "auth"} <= set(body.keys):
        raise HTTPException(400, "Ungültiges Push-Abo")
    row = db.scalars(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first()
    if row is None:
        db.add(PushSubscription(user_id=u.id, endpoint=body.endpoint, keys=body.keys))
    else:
        row.user_id, row.keys = u.id, body.keys
    return {"ok": True}


@router.post("/push/test")
def push_test(u: User = Depends(user), db: Session = Depends(get_db)):
    log_event(u.id, "warnung", "meldungen", "Testmeldung – wenn du das siehst, funktionieren die Meldungen.", kind="test", db=db)
    return {"ok": True}
