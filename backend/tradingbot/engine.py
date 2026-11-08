"""Bot-Engine: läuft serverseitig rund um die Uhr, für alle Benutzer getrennt.

Je Takt: Kurse → (neue Kerzen) → Regime → Schattenbetrieb → Strategien → Risikoprüfung → Order-Management.
Positionen werden in jedem Zustand geschützt (Stops, Ausstiege); neue Einstiege nur im Zustand AKTIV.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .brokers.base import BrokerError
from .core import bus
from .core.config import LIVE_SMALL_RISK_FACTOR, ORDER_STATUSES, SHADOW_STATUSES, current_config, migrate_default_markets
from .core.db import session_scope, utcnow
from .core.events import log_event
from .core.models import (AccountSnapshot, BotRuntime, Instrument, Position, RegimeLog, RiskDecision, SignalRow,
                          TradingAccount, User)
from .core.state import STATE_LABELS, TransitionError, check_transition
from .core.types import TIMEFRAMES, Decision, PositionView
from .data.instruments import instruments_by_symbol, refresh_limits, seed_instruments
from .data.market import MarketData
from .data.composite import CompositeSource
from .execution.accounts import ensure_user_setup, get_account, make_broker, migrate_broker_links
from .execution.orders import OrderManager
from .earn.modules import run_modules
from .execution.reconcile import reconcile
from .risk.rules import OpenPos, RiskContext, evaluate
from .selection import controller, shadow
from .selection.regime import REGIMES, classify
from .selection.simulate import Costs
from .strategies.registry import STRATEGY_TYPES

log = logging.getLogger(__name__)
D = Decimal
BERLIN = ZoneInfo("Europe/Berlin")
RECONCILE_EVERY = timedelta(minutes=5)
SNAPSHOT_EVERY = timedelta(minutes=5)


def _d(x) -> Decimal | None:
    return None if x is None else D(str(round(float(x), 10)))


class Engine:
    def __init__(self, market: MarketData | None = None):
        self.market = market or MarketData(CompositeSource())
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.regimes: dict[tuple[str, str], tuple[str, dict]] = {}
        self.last_eval: dict[tuple[int, str, str, str], datetime] = {}
        self.started_at = utcnow()
        self.last_tick: datetime | None = None
        self.tick_error = ""
        self.limits_at: datetime | None = None

    # ------------------------------------------------------------------ Lebenszyklus
    def start(self) -> None:
        with session_scope() as db:
            seed_instruments(db)
            migrate_default_markets(db)
            migrate_broker_links(db)
            self._refresh_limits(db)
            for rt in db.scalars(select(BotRuntime)):
                # Nach Neustart immer erst abgleichen (Abschnitt 4.4)
                if rt.state not in ("NOT_AUS", "GESPERRT"):
                    rt.state, rt.state_reason, rt.state_since = "INITIALISIERUNG", "Neustart", utcnow()
        self.market.load_state()
        self._thread = threading.Thread(target=self._loop, name="engine", daemon=True)
        self._thread.start()

    def _refresh_limits(self, db: Session) -> None:
        if not hasattr(self.market.source, "pair_info"):
            return
        try:
            n = refresh_limits(db, self.market.source)
            if n:
                log.info("Mindestmengen von Kraken aktualisiert: %d Märkte", n)
        except Exception:  # noqa: BLE001 – ohne Netz gelten die gespeicherten Werte
            log.warning("Mindestmengen von Kraken nicht abrufbar – gespeicherte Werte gelten")
        self.limits_at = utcnow()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self.tick()
                self.tick_error = ""
            except Exception as e:  # noqa: BLE001 – Engine darf nie still sterben
                log.exception("Engine-Takt fehlgeschlagen")
                self.tick_error = str(e)[:300]
            self.last_tick = utcnow()
            self._stop.wait(max(1.0, 15 - (time.monotonic() - t0)))

    # ------------------------------------------------------------------ Takt
    def tick(self) -> None:
        with self.lock:
            with session_scope() as db:
                users = list(db.scalars(select(User).where(User.status == "aktiv")))
                if self.limits_at is None or (utcnow() - self.limits_at).total_seconds() > 86400:
                    self._refresh_limits(db)
                insts = instruments_by_symbol(db)
                cfgs = {}
                for u in users:
                    ensure_user_setup(db, u.id)
                    cfgs[u.id] = current_config(db, u.id)
            needed: set[tuple[str, str]] = set()
            for cfg, _ in cfgs.values():
                needed.update((m, "1h") for m in cfg["markets"])
                needed.update((m, cfg["selection"]["regime_timeframe"]) for m in cfg["markets"])
                for s in cfg["strategies"]:
                    if s["status"] in SHADOW_STATUSES:
                        needed.update((m, s["timeframe"]) for m in (s["markets"] or cfg["markets"]))
            needed = {(m, tf) for m, tf in needed if self.market.usable(m)}
            symbols = {m for m, _ in needed if m in insts}
            self.market.refresh_tickers([insts[s] for s in symbols])
            now = utcnow()
            new_candles: dict[tuple[str, str], datetime] = {}
            with session_scope() as db:
                insts = instruments_by_symbol(db)
                for sym, tf in sorted(needed):
                    if sym in insts and self.market.due(sym, tf, now):
                        times = self.market.refresh_candles(db, insts[sym], tf)
                        if times:
                            new_candles[(sym, tf)] = max(times)
            with session_scope() as db:
                insts = instruments_by_symbol(db)
                for (sym, tf) in needed:
                    if (sym, tf) in new_candles or (sym, tf) not in self.regimes:
                        self._update_regime(db, insts.get(sym), tf)
            for u in users:
                try:
                    with session_scope() as db:
                        UserRunner(self, db, u.id).tick(now)
                except Exception as e:  # noqa: BLE001
                    log.exception("Benutzer %s: Takt fehlgeschlagen", u.id)
                    with session_scope() as db:
                        rt = db.get(BotRuntime, u.id)
                        if rt and rt.state != "FEHLER" and rt.state != "NOT_AUS":
                            _set_state(db, rt, "FEHLER", f"Technischer Fehler: {e.__class__.__name__}: {str(e)[:150]}", "fehler",
                                       force=True)
                bus.publish(u.id)

    def _update_regime(self, db: Session, inst: Instrument | None, tf: str) -> None:
        if inst is None:
            return
        bars = self.market.bars(db, inst.id, tf, 400)
        if not bars:
            return
        regime, values = classify(bars)
        prev = self.regimes.get((inst.symbol, tf))
        self.regimes[(inst.symbol, tf)] = (regime, values)
        exists = db.scalars(select(RegimeLog.id).where(RegimeLog.instrument_id == inst.id, RegimeLog.timeframe == tf,
                                                       RegimeLog.candle_time == bars[-1].time)).first()
        if not exists:
            db.add(RegimeLog(candle_time=bars[-1].time, instrument_id=inst.id, timeframe=tf, regime=regime, values=values))
        if prev and prev[0] != regime:
            log_event(None, "info", "regime", f"{inst.symbol} ({tf}): Regime {REGIMES[prev[0]]} → {REGIMES[regime]}", kind="regime",
                      db=db)

    def regime_of(self, symbol: str, tf: str) -> str:
        return self.regimes.get((symbol, tf), ("unklar", {}))[0]

    # ------------------------------------------------------------------ Befehle (aus der API)
    def command(self, user_id: int, action: str, by: str, **kw) -> str:
        with self.lock, session_scope() as db:
            runner = UserRunner(self, db, user_id)
            return runner.command(action, by, **kw)


def _set_state(db: Session, rt: BotRuntime, target: str, reason: str, lock_kind: str = "", force: bool = False) -> None:
    if not force:
        check_transition(rt.state, target)
    if rt.state == target and rt.state_reason == reason:
        return
    old = rt.state
    rt.state, rt.state_reason, rt.state_since, rt.lock_kind = target, reason[:300], utcnow(), lock_kind
    sev = "kritisch" if target in ("NOT_AUS", "FEHLER") else "warnung" if target == "GESPERRT" else "info"
    log_event(rt.user_id, sev, "steuerung", f"Zustand {STATE_LABELS[old]} → {STATE_LABELS[target]}" + (f": {reason}" if reason else ""),
              kind="zustand", data={"von": old, "nach": target, "sperre": lock_kind}, db=db)


RISK_LOCKS = ("tagesverlust", "drawdown", "verlustserie")


def switch_account(db: Session, rt: BotRuntime, old: str, new: str) -> None:
    """Kontowechsel Paper ↔ Echtgeld: Kennzahlen (Tagesstart, Höchststand, Verlustserie, Risikosperren) je Konto getrennt."""
    if old == new:
        return
    today = utcnow().astimezone(BERLIN).date().isoformat()
    b = dict(rt.baselines or {})
    lock = rt.lock_kind if rt.state == "GESPERRT" and rt.lock_kind in RISK_LOCKS else ""
    b[old] = {"day": rt.day, "day_start": None if rt.day_start_equity is None else str(rt.day_start_equity),
              "peak": None if rt.peak_equity is None else str(rt.peak_equity), "loss_streak": rt.loss_streak,
              "lock": lock, "lock_reason": rt.state_reason if lock else ""}
    n = b.get(new) or {}
    same_day = n.get("day") == today
    rt.day = n.get("day", "") if same_day else ""
    rt.day_start_equity = D(n["day_start"]) if same_day and n.get("day_start") else None
    rt.peak_equity = D(n["peak"]) if n.get("peak") else None
    rt.loss_streak = int(n.get("loss_streak") or 0)
    rt.baselines = b
    rt.last_reconcile_at = rt.last_snapshot_at = None
    back = n.get("lock", "")
    if back == "tagesverlust" and not same_day:
        back = ""
    if back:
        _set_state(db, rt, "GESPERRT", n.get("lock_reason") or "Sperre dieses Kontos besteht weiter", back, force=True)
    elif lock:
        _set_state(db, rt, "SYNCHRONISIERUNG", f"Kontowechsel – Sperre gehört zum {'Paper' if old == 'paper' else 'Echtgeld'}-Konto",
                   force=True)
    log_event(rt.user_id, "warnung" if new == "live" else "info", "konto",
              "Auf ECHTGELD umgestellt" if new == "live" else "Zurück auf Paper (Spielgeld) umgestellt", kind="konto", db=db)


class UserRunner:
    def __init__(self, engine: Engine, db: Session, user_id: int):
        self.e = engine
        self.db = db
        self.user_id = user_id
        ensure_user_setup(db, user_id)
        self.rt: BotRuntime = db.get(BotRuntime, user_id)
        self.cfg, self.cfg_version = current_config(db, user_id)
        self.insts = instruments_by_symbol(db)
        self.acct: TradingAccount | None = get_account(db, user_id, self.cfg["account"])
        self.broker = None
        self.om: OrderManager | None = None
        self.broker_error = ""
        if self.acct is not None:
            try:
                self.broker = make_broker(db, self.acct, self.cfg, self.e.market.ticker)
                self.om = OrderManager(db, user_id, self.acct.id, self.broker, self.acct.kind)
            except ValueError as e:
                self.broker_error = str(e)

    # ------------------------------------------------------------------ Kennzahlen
    def trading_positions(self) -> list[Position]:
        return [p for p in self.positions() if p.side != "bestand"]

    def positions(self) -> list[Position]:
        if self.acct is None:
            return []
        return list(self.db.scalars(select(Position).where(Position.user_id == self.user_id, Position.account_id == self.acct.id,
                                                           Position.status == "offen")))

    def venue_note(self, inst: Instrument) -> str:
        """Leer, wenn das aktive Konto diesen Markt handeln kann (Paper: alle Märkte)."""
        if self.acct is None or self.acct.kind == "paper" or self.broker is None:
            return ""
        has = getattr(self.broker, "has", None)
        if has is None or has(inst.market):
            return ""
        return f"Kein Echtgeld-Konto für {'Aktien/ETFs' if inst.market == 'aktie' else 'Krypto'} verbunden"

    def venue_cash(self, inst: Instrument, cash: Decimal) -> Decimal:
        """Bei mehreren Anbietern zählt für einen Kauf nur das Guthaben beim zuständigen Anbieter."""
        fn = getattr(self.broker, "cash", None)
        return fn(inst.market, self.acct.currency) if fn and self.acct.kind == "live" else cash

    def inst_by_id(self, iid: int) -> Instrument:
        return self.db.get(Instrument, iid)

    def mark(self, p: Position) -> Decimal:
        t = self.e.market.ticker(self.inst_by_id(p.instrument_id).symbol)
        return t.bid if t else p.avg_entry

    def equity(self, balances: dict | None = None) -> tuple[Decimal, Decimal]:
        """(Kontowert, verfügbares Guthaben) in Kontowährung."""
        if self.broker is None:
            return D(0), D(0)
        bal = balances if balances is not None else self.broker.balances()
        cash = bal.get(self.acct.currency, D(0))
        return cash + sum((p.qty * self.mark(p) for p in self.positions()), D(0)), cash

    def external_holdings(self, balances: dict) -> list[dict] | None:
        """Bestände beim Anbieter, die der Bot nicht selbst gekauft hat (nur Anzeige, kein Bot-Kapital)."""
        if self.acct.kind != "live":
            return None
        bot: dict[str, Decimal] = {}
        for p in self.positions():
            base = self.inst_by_id(p.instrument_id).base
            bot[base] = bot.get(base, D(0)) + p.qty
        by_base = {i.base: i for i in self.db.scalars(select(Instrument).where(Instrument.quote == "EUR"))}
        out = []
        for key, amount in sorted(balances.items()):
            asset, _, suffix = key.partition(".")
            if asset == self.acct.currency and not suffix:
                continue
            qty = amount - (bot.get(asset, D(0)) if not suffix else D(0))
            if qty <= D("0.00000001"):
                continue
            inst = by_base.get(asset)
            t = self.e.market.ticker(inst.symbol) if inst else None
            value = qty * t.bid if t else (qty if asset == "EUR" else None)
            out.append({"asset": asset, "qty": format(qty.normalize(), "f"), "eur": None if value is None else str(value.quantize(D("0.01"))),
                        "staking": bool(suffix)})
        return out

    # ------------------------------------------------------------------ Takt
    def tick(self, now: datetime) -> None:
        rt = self.rt
        rt.heartbeat_at = now
        if self.broker is None:
            rt.broker_ok = False
            if rt.state not in ("NOT_AUS", "GESPERRT", "FEHLER"):
                _set_state(self.db, rt, "GESPERRT", self.broker_error or "Kein Handelskonto", "abgleich", force=True)
            return
        # Simulierte Stop-Orders gegen Live-Kurse prüfen
        if self.acct.kind == "paper":
            self.broker.on_prices()
        try:
            balances = self.broker.balances()
            rt.broker_ok = True
        except BrokerError as e:
            rt.broker_ok = False
            if rt.state in ("AKTIV", "PAUSIERT", "BEREIT"):
                _set_state(self.db, rt, "GESPERRT", f"Broker nicht erreichbar: {e}", "abgleich")
            return
        before = {p.id for p in self.positions()}
        self.om.refresh_open()
        self._after_closes(before)
        # Zustandsautomat
        if rt.state == "INITIALISIERUNG":
            _set_state(self.db, rt, "SYNCHRONISIERUNG", "Abgleich mit dem Broker")
        if rt.state == "SYNCHRONISIERUNG" or (rt.state == "GESPERRT" and rt.lock_kind == "abgleich") or \
                rt.last_reconcile_at is None or now - rt.last_reconcile_at >= RECONCILE_EVERY:
            self._reconcile(now)
        equity, cash = self.equity(balances)
        rt.external = self.external_holdings(balances)
        self._day_and_peak(now, equity)
        self._limits(equity)
        self._protect_positions(now)
        self._strategies(now, equity, cash)
        run_modules(self, now.astimezone(BERLIN))
        self._snapshot(now, equity, cash)
        self._reports(now)

    def _reconcile(self, now: datetime) -> None:
        rt = self.rt
        res = reconcile(self.om, self.acct.kind)
        rt.last_reconcile_at, rt.last_reconcile_ok, rt.last_reconcile_note = now, res.ok, res.note
        if not res.ok:
            if rt.state in ("SYNCHRONISIERUNG", "BEREIT", "AKTIV", "PAUSIERT"):
                _set_state(self.db, rt, "GESPERRT", f"Abgleich: {res.note}", "abgleich", force=rt.state == "SYNCHRONISIERUNG")
            return
        if rt.state == "SYNCHRONISIERUNG":
            _set_state(self.db, rt, "BEREIT", "Abgleich erfolgreich")
            if rt.want_running:
                _set_state(self.db, rt, "AKTIV", "Automatisch fortgesetzt")
        elif rt.state == "GESPERRT" and rt.lock_kind == "abgleich":
            # Automatische Wiederaufnahme nur bei technischer Sperre, nicht bei Risikogrenzen
            _set_state(self.db, rt, "SYNCHRONISIERUNG", "Abgleich wieder erfolgreich")
            _set_state(self.db, rt, "BEREIT", "Abgleich erfolgreich")
            if rt.want_running:
                _set_state(self.db, rt, "AKTIV", "Automatisch fortgesetzt")

    def _day_and_peak(self, now: datetime, equity: Decimal) -> None:
        rt = self.rt
        today = now.astimezone(BERLIN).date().isoformat()
        if rt.day != today:
            rt.day, rt.day_start_equity = today, equity
            if rt.state == "GESPERRT" and rt.lock_kind == "tagesverlust":
                _set_state(self.db, rt, "SYNCHRONISIERUNG", "Neuer Handelstag – Tagesverlustsperre aufgehoben")
        if rt.peak_equity is None or equity > rt.peak_equity:
            rt.peak_equity = equity

    def _limits(self, equity: Decimal) -> None:
        rt, r = self.rt, self.cfg["risk"]
        if rt.state not in ("AKTIV", "PAUSIERT", "BEREIT"):
            return
        hit = None
        if rt.day_start_equity and (rt.day_start_equity - equity) / rt.day_start_equity * 100 >= D(str(r["daily_loss_limit_pct"])):
            hit = ("tagesverlust", f"Tagesverlustlimit {r['daily_loss_limit_pct']} % erreicht – Sperre bis morgen")
        elif rt.peak_equity and (rt.peak_equity - equity) / rt.peak_equity * 100 >= D(str(r["max_drawdown_pct"])):
            hit = ("drawdown", f"Maximaler Drawdown {r['max_drawdown_pct']} % erreicht – manuelle Prüfung nötig")
        if hit:
            _set_state(self.db, rt, "GESPERRT", hit[1], hit[0])
            if r["on_limit"] == "schliessen":
                self.close_all("Limit erreicht", forced=True)
        elif rt.state == "AKTIV" and rt.loss_streak >= int(r["loss_streak_limit"]):
            _set_state(self.db, rt, "PAUSIERT", f"{rt.loss_streak} Verlusttrades in Folge", "verlustserie")

    def _after_closes(self, before: set[int]) -> None:
        for pid in before:
            p = self.db.get(Position, pid)
            if p and p.status == "geschlossen" and p.side != "bestand":
                self.rt.loss_streak = self.rt.loss_streak + 1 if p.realized < 0 else 0

    # ------------------------------------------------------------------ Positionsschutz
    def _protect_positions(self, now: datetime) -> None:
        strategies = {s["id"]: s for s in self.cfg["strategies"]}
        for p in self.trading_positions():
            inst = self.inst_by_id(p.instrument_id)
            t = self.e.market.ticker(inst.symbol)
            if t is None:
                continue
            if p.highest_price is None or t.bid > p.highest_price:
                p.highest_price = t.bid
            if not p.stop_client_order_id:
                self.om.place_stop(p, inst)
            if p.take_profit is not None and t.bid >= p.take_profit:
                self.exit_position(p, "Take-Profit", "ausstieg")
                continue
            s = strategies.get(p.strategy_id)
            if s and p.trailing_atr_mult:
                bars = self.e.market.bars(self.db, inst.id, s["timeframe"], 300)
                strat = STRATEGY_TYPES[s["type"]]
                new = strat.trailing_stop(bars, PositionView(float(p.avg_entry), float(p.stop or 0), float(p.highest_price), p.opened_at),
                                          {**s["params"], "trailing": True, "trailing_atr": float(p.trailing_atr_mult)})
                if new is not None and (p.stop is None or D(str(new)) > p.stop) and D(str(new)) < t.bid:
                    self.om.move_stop(p, inst, D(str(new)), "Trailing-Stop")

    # ------------------------------------------------------------------ Strategien
    def _strategies(self, now: datetime, equity: Decimal, cash: Decimal) -> None:
        rt, cfg = self.rt, self.cfg
        if rt.state in ("INITIALISIERUNG", "NOT_AUS", "FEHLER"):
            return
        regimes = {m: self.e.regime_of(m, cfg["selection"]["regime_timeframe"]) for m in cfg["markets"]}
        if controller.due(self.db, self.user_id, cfg, now):
            controller.run(self.db, self.user_id, cfg, regimes, now)
            self.cfg, self.cfg_version = current_config(self.db, self.user_id)
            cfg = self.cfg
        weights = controller.current_weights(self.db, self.user_id, cfg)
        costs = Costs(cfg["costs"]["fee_pct"], cfg["costs"]["slippage_pct"], 0.1)
        allowed = ORDER_STATUSES[cfg["account"]]
        for s in cfg["strategies"]:
            if s["status"] not in SHADOW_STATUSES:
                continue
            strat = STRATEGY_TYPES[s["type"]]
            tf = s["timeframe"]
            for sym in (s["markets"] or cfg["markets"]):
                inst = self.insts.get(sym)
                if inst is None:
                    continue
                last = self.e.market.last_closed.get((sym, tf))
                key = (self.user_id, s["id"], sym, tf)
                if last is None or self.e.last_eval.get(key) == last:
                    continue
                self.e.last_eval[key] = last
                bars = self.e.market.bars(self.db, inst.id, tf, 400)
                if not bars or bars[-1].time != last:
                    continue
                pos = next((p for p in self.trading_positions() if p.instrument_id == inst.id and p.strategy_id == s["id"]), None)
                pv = PositionView(float(pos.avg_entry), float(pos.stop or 0), float(pos.highest_price or pos.avg_entry),
                                  pos.opened_at) if pos else None
                st = shadow.open_trade(self.db, self.user_id, s["id"], strat, inst.id, tf)
                spv = PositionView(float(st.entry), float(st.stop), float(st.highest), st.opened_at) if st else None
                regime = regimes.get(sym) or self.e.regime_of(sym, cfg["selection"]["regime_timeframe"])
                # Schattenbetrieb: eigene (simulierte) Positionssicht der Strategie
                sdec = strat.evaluate(bars, spv, s["params"], TIMEFRAMES[tf])
                shadow.step(self.db, self.user_id, s["id"], strat, s["params"], inst.id, tf, bars, sdec, regime, costs)
                if s["status"] not in allowed:
                    continue
                dec = strat.evaluate(bars, pv, s["params"], TIMEFRAMES[tf]) if pv is not None or spv is not None else sdec
                if dec.direction == "halten":
                    continue
                if dec.direction == "verkauf" and pos is not None:
                    sig = self._signal(s, strat, inst, tf, bars[-1].time, dec, "freigegeben")
                    self.exit_position(pos, str(dec.reasoning.get("grund", "Ausstiegssignal"))[:60], "ausstieg", signal_id=sig.id)
                elif dec.direction == "kauf" and pos is None:
                    self._entry_signal(s, strat, inst, tf, bars[-1].time, dec, regime, weights.get(s["id"], 0.0), equity, cash)

    def _signal(self, s, strat, inst, tf, ctime, dec: Decision, status: str) -> SignalRow:
        sig = SignalRow(user_id=self.user_id, candle_time=ctime, instrument_id=inst.id, strategy_id=s["id"], strategy_name=s["name"],
                        strategy_version=strat.version, timeframe=tf, direction=dec.direction, strength=_d(dec.strength) or D(0),
                        price=_d(dec.reasoning.get("kurs") or 0) or D(0), stop_suggestion=_d(dec.stop), take_profit=_d(dec.take_profit),
                        reasoning=dec.reasoning, config_version_id=self.cfg_version, status=status)
        self.db.add(sig)
        self.db.flush()
        return sig

    def _entry_signal(self, s, strat, inst, tf, ctime, dec: Decision, regime: str, weight: float, equity, cash) -> None:
        dup = self.db.scalars(select(SignalRow.id).where(SignalRow.user_id == self.user_id, SignalRow.strategy_id == s["id"],
                                                         SignalRow.instrument_id == inst.id, SignalRow.candle_time == ctime,
                                                         SignalRow.direction == "kauf")).first()
        if dup:
            return  # doppeltes Signal (z. B. nach Neustart)
        sig = self._signal(s, strat, inst, tf, ctime, dec, "neu")
        sig.reasoning = {**dec.reasoning, "regime": regime, "gewicht": weight}
        if regime not in strat.regimes and regime != "hohe_volatilitaet":
            sig.status = "abgelehnt"
            self._log_reject(sig, "Strategieauswahl", f"Regime {', '.join(REGIMES[x] for x in strat.regimes)}", REGIMES.get(regime, regime))
            return
        auto = self.cfg["automation"]
        if auto == "signale":
            sig.status = "nur_signal"
            log_event(self.user_id, "info", "signal", f"Signal Kauf {inst.symbol} ({s['name']}): {dec.reasoning.get('grund', '')}",
                      kind="signal", data={"signal_id": sig.id}, db=self.db)
            return
        if auto == "halbautomatisch":
            sig.status = "wartet_bestaetigung"
            log_event(self.user_id, "info", "signal", f"Bestätigung nötig: Kauf {inst.symbol} ({s['name']})", kind="bestaetigung",
                      data={"signal_id": sig.id}, db=self.db)
            return
        self.execute_entry(sig, s, weight)

    def _log_reject(self, sig: SignalRow, rule: str, limit: str, actual: str) -> None:
        self.db.add(RiskDecision(user_id=self.user_id, signal_id=sig.id, kind="einstieg", result="abgelehnt", rule=rule,
                                 limit_value=limit[:60], actual_value=actual[:60], checks=[]))

    def execute_entry(self, sig: SignalRow, s: dict, weight: float, forced_regime: str | None = None) -> RiskDecision:
        inst = self.inst_by_id(sig.instrument_id)
        regime = forced_regime or sig.reasoning.get("regime", "unklar")
        equity, cash = self.equity()
        t = self.e.market.ticker(inst.symbol)
        r = self.cfg["risk"]
        health = self.e.market.health(inst.symbol, sig.timeframe, r["max_tick_age_s"], r["max_data_age_candles"])
        positions = self.trading_positions()
        open_risk = {p.id: max(D(0), p.qty * (self.mark(p) - (p.stop or D(0)))) for p in positions}
        factor, note = 1.0, ""
        if regime == "hohe_volatilitaet":
            factor, note = 0.5, "Risiko halbiert (hohe Volatilität)"
        if s["status"] == "live_klein" and self.acct.kind == "live":
            factor, note = factor * LIVE_SMALL_RISK_FACTOR, (note + "; " if note else "") + "Live-klein: Risiko ¼"
        bars = self.e.market.bars(self.db, inst.id, sig.timeframe, 30)
        last_range_atr = None
        if len(bars) >= 16:
            from .analysis.indicators import atr
            a = atr([b.high for b in bars], [b.low for b in bars], [b.close for b in bars], 14)[-1]
            if a:
                last_range_atr = (bars[-1].high - bars[-1].low) / a
        pending = sum(1 for o in self.om.open_orders() if o.instrument_id == inst.id and o.purpose != "stop")
        ctx = RiskContext(
            user_id=self.user_id, kind="einstieg", symbol=inst.symbol, side="kauf", state=self.rt.state, now=utcnow(), risk=r,
            costs=self.cfg["costs"], feed_ok=health.ok, feed_reason=health.reason, broker_ok=self.rt.broker_ok,
            reconcile_ok=self.rt.last_reconcile_ok, reconcile_note=self.rt.last_reconcile_note, tradable=inst.tradable,
            blackouts=r.get("blackouts", []), equity=equity, cash=self.venue_cash(inst, cash), day_start_equity=self.rt.day_start_equity or equity,
            peak_equity=self.rt.peak_equity or equity, loss_streak=self.rt.loss_streak,
            positions=[OpenPos(self.inst_by_id(p.instrument_id).symbol, p.qty, p.qty * self.mark(p)) for p in positions],
            pending_orders_symbol=pending, bid=t.bid if t else None, ask=t.ask if t else None,
            volume_24h=t.volume_24h_quote if t else None, stop=_d(sig.stop_suggestion), min_qty=inst.min_qty, min_notional=inst.min_notional or D(0), step=inst.step_size,
            last_range_atr=last_range_atr, strategy_name=s["name"], strategy_weight=weight,
            strategy_open_risk=sum((open_risk[p.id] for p in positions if p.strategy_id == s["id"]), D(0)),
            total_open_risk=sum(open_risk.values(), D(0)), risk_factor=factor, risk_factor_note=note,
            hours=inst.trading_hours, venue_note=self.venue_note(inst))
        rr = evaluate(ctx)
        dec = RiskDecision(user_id=self.user_id, signal_id=sig.id, kind="einstieg", result=rr.result, rule=rr.rule[:80],
                           limit_value=rr.limit[:60], actual_value=rr.actual[:60], position_size=rr.qty,
                           checks=[c.to_dict() for c in rr.checks], client_order_id=rr.client_order_id)
        self.db.add(dec)
        sig.status = "freigegeben" if rr.approved else "abgelehnt"
        if not rr.approved:
            log_event(self.user_id, "info", "risiko", f"Kauf {inst.symbol} abgelehnt: {rr.rule} (Grenze {rr.limit}, Ist {rr.actual})",
                      kind="abgelehnt", data={"signal_id": sig.id}, db=self.db)
            return dec
        trailing = D(str(s["params"]["trailing_atr"])) if s["params"].get("trailing") and s["params"].get("trailing_atr") else None
        self.om.open_position(rr, inst, ctx.stop, sig.take_profit, trailing, s["id"], s["name"], sig.id)
        return dec

    # ------------------------------------------------------------------ Ausstiege
    def exit_position(self, p: Position, reason: str, purpose: str, forced: bool = False, signal_id: int | None = None) -> bool:
        inst = self.inst_by_id(p.instrument_id)
        r = self.cfg["risk"]
        health = self.e.market.health(inst.symbol, None, r["max_tick_age_s"], r["max_data_age_candles"])
        pending = sum(1 for o in self.om.open_orders() if o.position_id == p.id and o.purpose != "stop")
        ctx = RiskContext(user_id=self.user_id, kind="ausstieg", symbol=inst.symbol, side="verkauf", state=self.rt.state,
                          now=utcnow(), risk=r, costs=self.cfg["costs"], feed_ok=health.ok, feed_reason=health.reason,
                          broker_ok=self.rt.broker_ok, reconcile_ok=True, reconcile_note="", tradable=True, blackouts=[],
                          equity=D(0), cash=D(0), day_start_equity=D(0), peak_equity=D(0), loss_streak=0, positions=[],
                          pending_orders_symbol=pending, exit_qty=p.qty, forced=forced)
        rr = evaluate(ctx)
        self.db.add(RiskDecision(user_id=self.user_id, signal_id=signal_id, kind="ausstieg", result=rr.result, rule=rr.rule[:80],
                                 limit_value=rr.limit[:60], actual_value=rr.actual[:60], position_size=rr.qty,
                                 checks=[c.to_dict() for c in rr.checks], client_order_id=rr.client_order_id))
        if not rr.approved:
            return False
        before = {p.id}
        ok = self.om.close_position(rr, p, inst, purpose, reason)
        self._after_closes(before)
        return ok

    def close_all(self, reason: str, forced: bool = True) -> int:
        """Schließt Handelspositionen. Sparplan-Bestand bleibt (langfristige Anlage, kein Stop)."""
        n = 0
        for p in self.trading_positions():
            if self.exit_position(p, reason, "notaus" if forced else "manuell", forced=forced):
                n += 1
        return n

    # ------------------------------------------------------------------ Snapshots/Berichte
    def _snapshot(self, now: datetime, equity: Decimal, cash: Decimal) -> None:
        rt = self.rt
        if rt.last_snapshot_at and now - rt.last_snapshot_at < SNAPSHOT_EVERY:
            return
        rt.last_snapshot_at = now
        peak = rt.peak_equity or equity
        dd = (peak - equity) / peak * 100 if peak else D(0)
        self.db.add(AccountSnapshot(user_id=self.user_id, account_kind=self.acct.kind, time=now, equity=equity, available=cash,
                                    peak=peak, drawdown_pct=dd.quantize(D("0.0001"))))

    def _reports(self, now: datetime) -> None:
        local = now.astimezone(BERLIN)
        rt = self.rt
        if local.hour < 20:
            return
        day = local.date().isoformat()
        if rt.last_report_day != day and self.cfg["notifications"].get("daily_report", True):
            rt.last_report_day = day
            from .reports import daily_report
            log_event(self.user_id, "info", "bericht", daily_report(self.db, self.user_id, self.acct, local), kind="tagesbericht", db=self.db)
        week = f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
        if local.weekday() == 6 and rt.last_week_report != week and self.cfg["notifications"].get("weekly_report", True):
            rt.last_week_report = week
            from .reports import weekly_report
            log_event(self.user_id, "info", "bericht", weekly_report(self.db, self.user_id, self.acct, local), kind="wochenbericht",
                      db=self.db)

    # ------------------------------------------------------------------ Befehle
    def command(self, action: str, by: str, **kw) -> str:
        rt = self.rt
        log_event(self.user_id, "info", "steuerung", f"Befehl „{action}“ von {by}", kind="befehl", db=self.db)
        try:
            if action == "start":
                rt.want_running = True
                if rt.state in ("BEREIT", "PAUSIERT"):
                    if rt.lock_kind == "verlustserie":
                        rt.loss_streak = 0
                    _set_state(self.db, rt, "AKTIV", f"Gestartet von {by}")
                elif rt.state == "INITIALISIERUNG":
                    pass
                else:
                    raise TransitionError(f"Start im Zustand {STATE_LABELS[rt.state]} nicht möglich – bitte zuerst freigeben")
            elif action == "pause":
                if rt.state == "AKTIV":
                    _set_state(self.db, rt, "PAUSIERT", f"Pausiert von {by}")
            elif action == "stop":
                rt.want_running = False
                if rt.state in ("AKTIV", "PAUSIERT"):
                    _set_state(self.db, rt, "BEREIT", f"Gestoppt von {by} – Positionen bleiben mit Stop geschützt")
            elif action == "wartung":
                rt.want_running = False
                if rt.state in ("AKTIV", "PAUSIERT", "BEREIT"):
                    _set_state(self.db, rt, "PAUSIERT", f"Wartungsmodus ({by})", "wartung")
            elif action == "notaus":
                rt.want_running = False
                _set_state(self.db, rt, "NOT_AUS", f"Not-Aus von {by}", "notaus", force=True)
                cancelled = 0
                if self.om:
                    for o in self.om.open_orders():
                        if o.purpose != "stop":
                            try:
                                self.om.apply(o, self.broker.cancel(o.client_order_id, o.broker_order_id))
                                cancelled += 1
                            except BrokerError:
                                pass
                closed = self.close_all("Not-Aus", forced=True) if self.cfg["risk"]["on_emergency"] == "schliessen" else 0
                log_event(self.user_id, "kritisch", "steuerung", f"NOT-AUS: {cancelled} Orders storniert, {closed} Positionen geschlossen",
                          kind="notaus", db=self.db)
            elif action == "freigeben":
                if rt.state not in ("GESPERRT", "NOT_AUS", "FEHLER"):
                    return "Keine Sperre aktiv"
                if rt.lock_kind == "drawdown":
                    equity, _ = self.equity()
                    rt.peak_equity = equity  # bewusste Freigabe: neuer Höchststand als Basis
                if rt.lock_kind == "verlustserie":
                    rt.loss_streak = 0
                if rt.lock_kind == "tagesverlust" and not kw.get("bestaetigt"):
                    raise TransitionError("Tagesverlustsperre gilt bis morgen – Freigabe nur mit ausdrücklicher Bestätigung")
                _set_state(self.db, rt, "SYNCHRONISIERUNG", f"Manuelle Freigabe von {by}")
                rt.last_reconcile_at = None
            elif action == "position_schliessen":
                p = self.db.get(Position, int(kw["position_id"]))
                if p is None or p.user_id != self.user_id or p.status != "offen":
                    raise ValueError("Position nicht gefunden")
                if not self.exit_position(p, f"Manuell ({by})", "manuell", forced=True):
                    raise ValueError("Schließen fehlgeschlagen – siehe Meldungen")
            elif action == "signal_bestaetigen":
                sig = self.db.get(SignalRow, int(kw["signal_id"]))
                if sig is None or sig.user_id != self.user_id or sig.status != "wartet_bestaetigung":
                    raise ValueError("Signal nicht (mehr) bestätigbar")
                tf = TIMEFRAMES[sig.timeframe]
                if utcnow() - (sig.candle_time + tf) > tf:
                    sig.status = "abgelaufen"
                    raise ValueError("Signal ist abgelaufen (älter als eine Kerze)")
                s = next((x for x in self.cfg["strategies"] if x["id"] == sig.strategy_id), None)
                if s is None:
                    raise ValueError("Strategie nicht mehr vorhanden")
                weights = controller.current_weights(self.db, self.user_id, self.cfg)
                d = self.execute_entry(sig, s, weights.get(s["id"], 0.0))
                return "Order freigegeben" if d.result != "abgelehnt" else f"Abgelehnt: {d.rule}"
            elif action == "signal_verwerfen":
                sig = self.db.get(SignalRow, int(kw["signal_id"]))
                if sig and sig.user_id == self.user_id and sig.status == "wartet_bestaetigung":
                    sig.status = "verworfen"
            elif action == "auswahl_neu":
                regimes = {m: self.e.regime_of(m, self.cfg["selection"]["regime_timeframe"]) for m in self.cfg["markets"]}
                controller.run(self.db, self.user_id, self.cfg, regimes, utcnow(), trigger=f"Manuell ({by})")
            elif action == "auswahl_bestaetigen":
                controller.apply_proposal(self.db, self.user_id)
                log_event(self.user_id, "info", "auswahl", f"Strategieauswahl bestätigt von {by}", kind="auswahl", db=self.db)
            else:
                raise ValueError("Unbekannter Befehl")
        except TransitionError as e:
            raise ValueError(str(e)) from e
        bus.publish(self.user_id)
        return "OK"


engine: Engine | None = None


def get_engine() -> Engine:
    global engine
    if engine is None:
        engine = Engine()
    return engine
