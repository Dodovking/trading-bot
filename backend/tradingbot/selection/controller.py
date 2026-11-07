"""Meta-Controller (FA-18/FA-19): bestimmt aktive Strategien und Gewichte. Keine Orderhoheit.

Methode A+B aus Abschnitt 6.2: regelbasiert nach Regime (Filter je Signal in der Engine)
plus Leistungs-Ranking aus dem Schattenbetrieb. Schutzregeln: Mindestdaten, Hysterese,
Mindesthaltedauer, fester Rhythmus, Maximalgewicht, Strategie-Abschaltung, „keine Strategie“.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import ORDER_STATUSES, SHADOW_STATUSES, save_config
from ..core.events import log_event
from ..core.models import ShadowTrade, StrategyAllocation, StrategyPerformance
from ..strategies.registry import STRATEGY_TYPES
from .regime import REGIMES
from .scorecard import compute, max_drawdown

D = Decimal


def latest_batch(db: Session, user_id: int, applied: bool | None = True) -> list[StrategyAllocation]:
    q = select(StrategyAllocation).where(StrategyAllocation.user_id == user_id)
    if applied is not None:
        q = q.where(StrategyAllocation.applied.is_(applied))
    last = db.scalars(q.order_by(StrategyAllocation.id.desc()).limit(1)).first()
    if last is None:
        return []
    return list(db.scalars(select(StrategyAllocation).where(StrategyAllocation.batch == last.batch)))


def current_weights(db: Session, user_id: int, cfg: dict) -> dict[str, float]:
    """Gültige Gewichte (Anteil am Gesamtrisiko, 0–1) je Strategie-ID."""
    max_w = cfg["risk"]["strategy_budget_pct"] / 100
    allowed = ORDER_STATUSES[cfg["account"]]
    eligible = {s["id"] for s in cfg["strategies"] if s["status"] in allowed}
    if cfg["selection"]["mode"] == "manuell":
        return {sid: max_w for sid in eligible}
    out = {}
    for a in latest_batch(db, user_id, True):
        if a.strategy_id in eligible and a.status == "aktiv":
            out[a.strategy_id] = min(float(a.weight), max_w)
    return out


def _trades(db: Session, user_id: int, sid: str, since: datetime | None) -> list[ShadowTrade]:
    q = select(ShadowTrade).where(ShadowTrade.user_id == user_id, ShadowTrade.strategy_id == sid, ShadowTrade.status == "geschlossen")
    if since:
        q = q.where(ShadowTrade.closed_at >= since)
    return list(db.scalars(q.order_by(ShadowTrade.closed_at)))


def due(db: Session, user_id: int, cfg: dict, now: datetime) -> bool:
    last = db.scalars(select(StrategyAllocation).where(StrategyAllocation.user_id == user_id)
                      .order_by(StrategyAllocation.id.desc()).limit(1)).first()
    if last is None:
        return True
    return now - last.time >= (timedelta(days=7) if cfg["selection"]["rhythm"] == "woechentlich" else timedelta(days=1))


def run(db: Session, user_id: int, cfg: dict, regimes: dict[str, str], now: datetime, trigger: str = "Rhythmus") -> list[StrategyAllocation]:
    sel = cfg["selection"]
    risk = cfg["risk"]
    max_w = risk["strategy_budget_pct"] / 100
    allowed = ORDER_STATUSES[cfg["account"]]
    prev = {a.strategy_id: a for a in latest_batch(db, user_id, True)}
    batch = f"{now:%Y%m%d%H%M}-{uuid.uuid4().hex[:6]}"
    since = now - timedelta(days=90)
    rows: list[StrategyAllocation] = []
    raw: dict[str, tuple[float, dict]] = {}
    new_cfg = None
    for s in cfg["strategies"]:
        sid, st = s["id"], s["status"]
        if st not in SHADOW_STATUSES:
            continue
        strat = STRATEGY_TYPES[s["type"]]
        all_tr = _trades(db, user_id, sid, None)
        tr = [t for t in all_tr if t.closed_at >= since]
        rs = [float(t.r_multiple or 0) for t in tr]
        sc = compute(rs, [float(t.pnl_pct or 0) for t in tr], sel["min_trades"])
        for regime in ["alle", *REGIMES]:
            sub = tr if regime == "alle" else [t for t in tr if t.regime == regime]
            if regime != "alle" and not sub:
                continue
            ssc = sc if regime == "alle" else compute([float(t.r_multiple or 0) for t in sub], [float(t.pnl_pct or 0) for t in sub],
                                                     sel["min_trades"])
            db.add(StrategyPerformance(user_id=user_id, strategy_id=sid, version=strat.version, window="90t", mode="shadow",
                                       regime=regime, trades=ssc.trades, expectancy_r=_d(ssc.expectancy_r),
                                       expectancy_pct=_d(ssc.expectancy_pct), profit_factor=_d(ssc.profit_factor),
                                       win_rate=_d(ssc.win_rate), drawdown_r=_d(ssc.drawdown_r), stability=_d(ssc.stability),
                                       score=_d(ssc.score)))
        markets = s["markets"] or cfg["markets"]
        fit = [m for m in markets if regimes.get(m) in strat.regimes]
        span_days = (now - all_tr[0].closed_at).days if all_tr else 0
        info = {"scorecard": sc.to_dict(), "regime_passend": fit, "regime_je_markt": {m: regimes.get(m, "unklar") for m in markets},
                "lebenszyklus": st, "datenbasis_tage": span_days}
        # Strategie-Abschaltung bei eigenem Drawdown (sofort, unabhängig vom Rhythmus)
        dd_now = max_drawdown([float(t.r_multiple or 0) for t in all_tr[-200:]])
        if st != "pausiert" and dd_now >= risk["strategy_drawdown_r"]:
            new_cfg = new_cfg or copy.deepcopy(cfg)
            for ns in new_cfg["strategies"]:
                if ns["id"] == sid:
                    ns["status"] = "pausiert"
            log_event(user_id, "warnung", "auswahl", f"Strategie {s['name']} automatisch pausiert: Drawdown {dd_now:.1f} R ≥ "
                      f"{risk['strategy_drawdown_r']} R", kind="strategie_pausiert", db=db)
            raw[sid] = (0.0, {**info, "grund": f"Automatisch pausiert (Drawdown {dd_now:.1f} R)", "status": "pausiert"})
            continue
        if st == "pausiert" or st not in allowed:
            raw[sid] = (0.0, {**info, "grund": "Pausiert" if st == "pausiert" else
                              f"Lebenszyklus „{st}“ – nur Schattenbetrieb", "status": "pausiert" if st == "pausiert" else "inaktiv"})
            continue
        enough = sc.trades >= sel["min_trades"] and span_days >= sel["min_days"]
        if not fit:
            w, why = 0.0, "Aktuelles Regime passt auf keinem Markt zur Strategie"
        elif not enough:
            w = max_w * 0.5
            why = f"Anlaufphase ({sc.trades}/{sel['min_trades']} Trades, {span_days}/{sel['min_days']} Tage): halbes Budget nach Regime-Regel"
        elif (sc.expectancy_r or 0) <= 0:
            w, why = 0.0, f"Erwartungswert nach Kosten {sc.expectancy_r:+.2f} R ≤ 0"
        else:
            w, why = None, f"Score {sc.score:.3f}, Erwartungswert {sc.expectancy_r:+.2f} R, Profit Factor {sc.profit_factor}"
        raw[sid] = (w if w is not None else -1.0, {**info, "grund": why, "score": sc.score})
    # Leistungs-Ranking: Gewichte proportional zum Score, gedeckelt
    scored = {sid: v[1]["score"] for sid, v in raw.items() if v[0] == -1.0}
    total = sum(scored.values())
    for sid, sco in scored.items():
        w = min(max_w, sco / total * len(scored) * max_w) if total > 0 else 0.0
        raw[sid] = (w, raw[sid][1])
    for sid, (w, info) in raw.items():
        status = info.get("status") or ("aktiv" if w > 0 else "inaktiv")
        p = prev.get(sid)
        if p is not None and status in ("aktiv", "inaktiv") and trigger != "Notfall":
            old = float(p.weight)
            held = (now - p.time).days
            if abs(w - old) < sel["hysteresis"] * max_w and p.status in ("aktiv", "inaktiv"):
                info["hysterese"] = f"Änderung {w - old:+.3f} unter Schwelle – Gewicht bleibt {old:.3f}"
                w, status = old, p.status
            elif w == 0 and p.status == "aktiv" and held < sel["min_hold_days"] and "Erwartungswert" not in info["grund"]:
                info["mindesthaltedauer"] = f"Aktiv seit {held} Tagen (< {sel['min_hold_days']})"
                w, status = old, "aktiv"
        rows.append(StrategyAllocation(user_id=user_id, time=now, strategy_id=sid, weight=_d(round(w, 4)), status=status,
                                       applied=sel["mode"] != "vorschlag", reasoning={**info, "ausloeser": trigger}, batch=batch))
    db.add_all(rows)
    if new_cfg is not None:
        save_config(db, user_id, new_cfg, "Meta-Controller")
    active = [r.strategy_id for r in rows if r.status == "aktiv"]
    log_event(user_id, "info", "auswahl",
              f"Strategieauswahl ({'Vorschlag' if sel['mode'] == 'vorschlag' else 'angewendet'}): "
              f"{', '.join(active) if active else 'keine Strategie aktiv'}", kind="auswahl", data={"batch": batch}, db=db)
    db.flush()
    return rows


def apply_proposal(db: Session, user_id: int) -> int:
    rows = latest_batch(db, user_id, None)
    for r in rows:
        r.applied = True
    db.flush()
    return len(rows)


def _d(x) -> Decimal | None:
    return None if x is None else D(str(x))
