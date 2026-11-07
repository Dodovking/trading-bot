"""Order-Management (Abschnitt 6): einziger Weg zum Broker.

Nimmt nur Orders mit gültigem Freigabestempel des Risikomoduls an, vergibt Client-Order-IDs,
führt den Lebenszyklus (Append-only Statushistorie) und überwacht Teilausführungen.
Jede Einstiegsposition erhält sofort eine Stop-Loss-Order beim Broker.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..brokers.base import BrokerError, BrokerOrderStatus, OrderRequest
from ..core.db import utcnow
from ..core.events import log_event
from ..core.models import Fill, IncomeEntry, Instrument, Order, OrderStatusEvent, Position
from ..data.quality import round_tick
from ..risk.rules import RiskResult, verify_stamp

D = Decimal
OPEN_STATES = ("erstellt", "freigegeben", "gesendet", "bestaetigt", "teilausgefuehrt")
FINAL_STATES = ("ausgefuehrt", "abgelehnt", "storniert", "fehlgeschlagen")
BROKER_TO_ORDER = {"offen": "bestaetigt", "teilausgefuehrt": "teilausgefuehrt", "ausgefuehrt": "ausgefuehrt",
                   "storniert": "storniert", "abgelehnt": "abgelehnt"}
STATUS_LABELS = {"erstellt": "Erstellt", "freigegeben": "Freigegeben", "gesendet": "Gesendet", "bestaetigt": "Bestätigt",
                 "teilausgefuehrt": "Teilweise ausgeführt", "ausgefuehrt": "Ausgeführt", "abgelehnt": "Abgelehnt",
                 "storniert": "Storniert", "fehlgeschlagen": "Fehlgeschlagen"}


class StampError(PermissionError):
    pass


def _fmt(x: Decimal | None) -> str:
    return "–" if x is None else format(x.normalize(), "f")


class OrderManager:
    def __init__(self, db: Session, user_id: int, account_id: int, broker, mode: str):
        self.db = db
        self.user_id = user_id
        self.account_id = account_id
        self.broker = broker
        self.mode = mode  # paper | live

    # ------------------------------------------------------------ Hilfen
    def _status(self, o: Order, status: str, note: str = "") -> None:
        if o.status == status and not note:
            return
        o.status = status
        o.updated_at = utcnow()
        if note:
            o.note = note[:300]
        self.db.add(OrderStatusEvent(order_id=o.id, time=utcnow(), status=status, note=note[:300]))
        self.db.flush()

    def _new_order(self, inst: Instrument, side: str, type_: str, purpose: str, qty: Decimal, stop: Decimal | None,
                   stamp: str, coid: str, signal_id: int | None = None, position_id: int | None = None) -> Order:
        o = Order(user_id=self.user_id, account_id=self.account_id, client_order_id=coid, instrument_id=inst.id,
                  side=side, type=type_, purpose=purpose, qty=qty, stop_price=stop, status="erstellt",
                  risk_stamp=stamp, signal_id=signal_id, position_id=position_id)
        self.db.add(o)
        self.db.flush()
        self.db.add(OrderStatusEvent(order_id=o.id, time=utcnow(), status="erstellt", note=""))
        return o

    def _send(self, o: Order, inst: Instrument) -> BrokerOrderStatus | None:
        req = OrderRequest(o.client_order_id, inst.symbol, inst.broker_symbol, o.side, o.type, o.qty,
                           o.stop_price if o.type == "stop" else None)
        self._status(o, "gesendet")
        try:
            st = self.broker.submit(req)
        except BrokerError as e:
            # Status unklar: nicht blind wiederholen, sondern über die Client-Order-ID nachfragen
            log_event(self.user_id, "warnung", "order", f"Order {inst.symbol} – Verbindung unklar, frage Status ab: {e}",
                      kind="order_unklar", db=self.db)
            try:
                st = self.broker.query(o.client_order_id)
            except BrokerError:
                o.note = "Status unklar – wird beim Abgleich geprüft"
                return None
            if st.status == "unbekannt":
                self._status(o, "fehlgeschlagen", f"Nicht beim Broker angekommen: {e}")
                return None
        except Exception as e:  # BrokerRejected und Unerwartetes
            self._status(o, "abgelehnt", str(e))
            log_event(self.user_id, "warnung", "order", f"Broker lehnte Order {inst.symbol} ab: {e}", kind="order_abgelehnt", db=self.db)
            return None
        self.apply(o, st)
        return st

    def apply(self, o: Order, st: BrokerOrderStatus) -> list[Fill]:
        """Broker-Status übernehmen, neue Teilausführungen als Fills speichern."""
        if st.broker_order_id and not o.broker_order_id:
            o.broker_order_id = st.broker_order_id
        new_fills = []
        known = {f.broker_fill_id for f in self.db.scalars(select(Fill).where(Fill.order_id == o.id))}
        for bf in st.fills:
            if bf.fill_id in known:
                continue
            f = Fill(order_id=o.id, time=utcnow(), price=bf.price, qty=bf.qty, fee=bf.fee, broker_fill_id=bf.fill_id)
            self.db.add(f)
            new_fills.append(f)
        if st.filled_qty and st.avg_price is not None:
            o.filled_qty, o.avg_fill_price, o.fees = st.filled_qty, st.avg_price, st.fee
        new = BROKER_TO_ORDER.get(st.status)
        if new and new != o.status:
            self._status(o, new, st.note)
        self.db.flush()
        return new_fills

    # ------------------------------------------------------------ Einstieg
    def open_position(self, rr: RiskResult, inst: Instrument, stop: Decimal, take_profit: Decimal | None,
                      trailing: Decimal | None, strategy_id: str, strategy_name: str, signal_id: int | None) -> Position | None:
        if not rr.approved or not rr.client_order_id or not verify_stamp(
                self.user_id, rr.client_order_id, inst.symbol, "kauf", rr.qty, stop, rr.stamp):
            log_event(self.user_id, "kritisch", "order", "Order ohne gültigen Freigabestempel abgewiesen", kind="stempel_ungueltig", db=self.db)
            raise StampError("Kein gültiger Freigabestempel")
        o = self._new_order(inst, "kauf", "market", "einstieg", rr.qty, stop, rr.stamp, rr.client_order_id, signal_id)
        self._status(o, "freigegeben", "Risikoprüfung bestanden")
        st = self._send(o, inst)
        if st is None or o.filled_qty <= 0:
            return None
        return self._create_position(o, inst, stop, take_profit, trailing, strategy_id, strategy_name, signal_id)

    def _create_position(self, o: Order, inst: Instrument, stop: Decimal, take_profit, trailing, strategy_id, strategy_name,
                         signal_id) -> Position:
        stop = round_tick(stop, inst.tick_size)
        pos = Position(user_id=self.user_id, account_id=self.account_id, instrument_id=inst.id, strategy_id=strategy_id,
                       strategy_name=strategy_name, qty=o.filled_qty, avg_entry=o.avg_fill_price, stop=stop, initial_stop=stop,
                       take_profit=take_profit, trailing_atr_mult=trailing, highest_price=o.avg_fill_price, status="offen",
                       entry_value=o.filled_qty * o.avg_fill_price, fees=o.fees, signal_id=signal_id)
        self.db.add(pos)
        self.db.flush()
        o.position_id = pos.id
        log_event(self.user_id, "info", "order",
                  f"Kauf {inst.symbol}: {_fmt(o.filled_qty)} zu {_fmt(o.avg_fill_price)} € ({strategy_name}), Stop {_fmt(stop)} €",
                  kind="trade_eroeffnet", data={"position_id": pos.id, "symbol": inst.symbol}, db=self.db)
        self.place_stop(pos, inst)
        return pos

    def place_stop(self, pos: Position, inst: Instrument) -> bool:
        coid = str(uuid.uuid4())
        o = self._new_order(inst, "verkauf", "stop", "stop", pos.qty, pos.stop, "schutz:" + str(pos.id), coid, position_id=pos.id)
        self._status(o, "freigegeben", "Schutz-Stop zur Position")
        st = self._send(o, inst)
        if st is None or o.status not in ("bestaetigt", "ausgefuehrt"):
            log_event(self.user_id, "kritisch", "order", f"Position {inst.symbol} ohne Stop-Loss beim Broker!", kind="ohne_stop",
                      data={"position_id": pos.id}, db=self.db)
            pos.stop_client_order_id = None
            return False
        pos.stop_client_order_id = coid
        if o.status == "ausgefuehrt":
            self.close_from_fill(pos, o, inst, "Stop-Loss")
        return True

    # ------------------------------------------------------------ Stop nachziehen
    def move_stop(self, pos: Position, inst: Instrument, new_stop: Decimal, reason: str) -> bool:
        new_stop = round_tick(new_stop, inst.tick_size)
        if pos.stop is not None and new_stop <= pos.stop:
            return False  # Stops werden nur in Gewinnrichtung nachgezogen
        so = self._order(pos.stop_client_order_id)
        if so is None or so.status not in ("bestaetigt", "gesendet"):
            return False
        try:
            st = self.broker.modify_stop(so.client_order_id, new_stop) if self.mode == "paper" else \
                self.broker.modify_stop(so.client_order_id, new_stop, so.broker_order_id)
        except Exception as e:
            log_event(self.user_id, "warnung", "order", f"Stop {inst.symbol} konnte nicht nachgezogen werden: {e}", db=self.db)
            return False
        if st.status in ("offen", "teilausgefuehrt"):
            old = pos.stop
            pos.stop = new_stop
            so.stop_price = new_stop
            self.db.add(OrderStatusEvent(order_id=so.id, time=utcnow(), status=so.status, note=f"Stop {_fmt(old)} → {_fmt(new_stop)} ({reason})"))
            log_event(self.user_id, "info", "order", f"Stop {inst.symbol} nachgezogen: {_fmt(old)} → {_fmt(new_stop)} € ({reason})",
                      kind="stop_nachgezogen", db=self.db)
            return True
        return False

    # ------------------------------------------------------------ Ausstieg
    def close_position(self, rr: RiskResult, pos: Position, inst: Instrument, purpose: str, reason: str) -> bool:
        if not rr.approved or not verify_stamp(self.user_id, rr.client_order_id, inst.symbol, "verkauf", rr.qty, None, rr.stamp):
            raise StampError("Kein gültiger Freigabestempel")
        so = self._order(pos.stop_client_order_id)
        if so is not None and so.status in OPEN_STATES:
            try:
                st = self.broker.cancel(so.client_order_id, so.broker_order_id)
                self.apply(so, st)
            except BrokerError as e:
                log_event(self.user_id, "warnung", "order", f"Stop {inst.symbol} konnte nicht storniert werden: {e}", db=self.db)
                return False
            if so.status == "ausgefuehrt":  # Stop kam zuvor
                self.close_from_fill(pos, so, inst, "Stop-Loss")
                return True
        o = self._new_order(inst, "verkauf", "market", purpose, rr.qty, None, rr.stamp, rr.client_order_id, position_id=pos.id)
        self._status(o, "freigegeben", reason)
        self._send(o, inst)
        if o.status == "ausgefuehrt":
            self.close_from_fill(pos, o, inst, reason)
            return True
        # Verkauf nicht durchgeführt: Schutz wiederherstellen
        if o.status in ("abgelehnt", "fehlgeschlagen"):
            self.place_stop(pos, inst)
        return False

    def close_from_fill(self, pos: Position, o: Order, inst: Instrument, reason: str) -> None:
        if pos.status != "offen":
            return
        proceeds = o.filled_qty * o.avg_fill_price
        pos.fees = pos.fees + o.fees
        pos.realized = proceeds - pos.entry_value - pos.fees
        pos.exit_price = o.avg_fill_price
        pos.exit_reason = reason[:60]
        pos.closed_at = utcnow()
        pos.status = "geschlossen"
        self.db.add(IncomeEntry(user_id=self.user_id, account_kind=self.mode, source=pos.strategy_id, kind="kursgewinn",
                                asset=inst.base, amount=pos.realized, note=f"{pos.strategy_name}: {reason}"[:200]))
        self.db.flush()
        pct = pos.realized / pos.entry_value * 100 if pos.entry_value else D(0)
        sign = "+" if pos.realized >= 0 else ""
        log_event(self.user_id, "info", "order",
                  f"Verkauf {inst.symbol} ({reason}): {sign}{pos.realized.quantize(D('0.01'))} € ({sign}{pct.quantize(D('0.01'))} %)",
                  kind="trade_geschlossen", data={"position_id": pos.id, "symbol": inst.symbol, "pnl": str(pos.realized)}, db=self.db)

    # ------------------------------------------------------------ Ertragsmodule (Bestand ohne Stop)
    def buy_holding(self, rr: RiskResult, inst: Instrument, module: str, module_name: str) -> Position | None:
        if not rr.approved or not verify_stamp(self.user_id, rr.client_order_id, inst.symbol, "kauf", rr.qty, None, rr.stamp):
            log_event(self.user_id, "kritisch", "order", "Order ohne gültigen Freigabestempel abgewiesen", kind="stempel_ungueltig", db=self.db)
            raise StampError("Kein gültiger Freigabestempel")
        o = self._new_order(inst, "kauf", "market", "modul", rr.qty, None, rr.stamp, rr.client_order_id)
        self._status(o, "freigegeben", f"Ertragsmodul {module_name}")
        self._send(o, inst)
        if o.filled_qty <= 0:
            return None
        pos = self.holding(inst, module)
        value = o.filled_qty * o.avg_fill_price
        if pos is None:
            pos = Position(user_id=self.user_id, account_id=self.account_id, instrument_id=inst.id, strategy_id=module,
                           strategy_name=module_name, side="bestand", qty=D(0), avg_entry=o.avg_fill_price, status="offen",
                           entry_value=D(0), fees=D(0), highest_price=o.avg_fill_price)
            self.db.add(pos)
        pos.entry_value += value
        pos.qty += o.filled_qty
        pos.fees += o.fees
        pos.avg_entry = pos.entry_value / pos.qty
        self.db.flush()
        o.position_id = pos.id
        log_event(self.user_id, "info", "modul", f"{module_name}: Kauf {inst.symbol} {_fmt(o.filled_qty)} zu {_fmt(o.avg_fill_price)} €",
                  kind="modul_kauf", data={"position_id": pos.id, "symbol": inst.symbol}, db=self.db)
        return pos

    def sell_holding(self, rr: RiskResult, pos: Position, inst: Instrument, reason: str) -> bool:
        if not rr.approved or not verify_stamp(self.user_id, rr.client_order_id, inst.symbol, "verkauf", rr.qty, None, rr.stamp):
            raise StampError("Kein gültiger Freigabestempel")
        qty = min(rr.qty, pos.qty)
        o = self._new_order(inst, "verkauf", "market", "modul", qty, None, rr.stamp, rr.client_order_id, position_id=pos.id)
        self._status(o, "freigegeben", reason)
        self._send(o, inst)
        if o.filled_qty <= 0:
            return False
        frac = o.filled_qty / pos.qty
        cost = pos.entry_value * frac
        gain = o.filled_qty * o.avg_fill_price - cost - o.fees
        pos.entry_value -= cost
        pos.qty -= o.filled_qty
        pos.realized += gain
        pos.fees += o.fees
        if pos.qty <= inst.min_qty / 10:
            pos.status, pos.closed_at, pos.exit_price, pos.exit_reason = "geschlossen", utcnow(), o.avg_fill_price, reason[:60]
        self.db.add(IncomeEntry(user_id=self.user_id, account_kind=self.mode, source=pos.strategy_id, kind="kursgewinn",
                                asset=inst.base, amount=gain, note=f"{reason}: Verkauf {_fmt(o.filled_qty)} {inst.base}"))
        log_event(self.user_id, "info", "modul", f"{pos.strategy_name}: Verkauf {inst.symbol} {_fmt(o.filled_qty)} ({reason}), "
                  f"Ergebnis {gain.quantize(D('0.01'))} €", kind="modul_verkauf", db=self.db)
        self.db.flush()
        return True

    def holding(self, inst: Instrument, module: str) -> Position | None:
        return self.db.scalars(select(Position).where(Position.user_id == self.user_id, Position.account_id == self.account_id,
                                                      Position.instrument_id == inst.id, Position.strategy_id == module,
                                                      Position.side == "bestand", Position.status == "offen")).first()

    # ------------------------------------------------------------ Abfragen
    def _order(self, coid: str | None) -> Order | None:
        if not coid:
            return None
        return self.db.scalars(select(Order).where(Order.client_order_id == coid)).first()

    def open_orders(self) -> list[Order]:
        return list(self.db.scalars(select(Order).where(Order.user_id == self.user_id, Order.account_id == self.account_id,
                                                        Order.status.in_(OPEN_STATES))))

    def refresh_open(self) -> list[tuple[Order, Position | None]]:
        """Offene Orders beim Broker abfragen. Ausgelöste Stops schließen die Position."""
        closed = []
        for o in self.open_orders():
            if o.status == "erstellt":
                self._status(o, "fehlgeschlagen", "Nie gesendet (Neustart)")
                continue
            try:
                st = self.broker.query(o.client_order_id, o.broker_order_id)
            except BrokerError:
                continue
            if st.status == "unbekannt":
                if o.status in ("gesendet", "freigegeben") and (utcnow() - o.updated_at).total_seconds() > 120:
                    self._status(o, "fehlgeschlagen", "Beim Broker nicht vorhanden")
                continue
            self.apply(o, st)
            if o.purpose == "einstieg" and o.filled_qty > 0:
                self._sync_entry(o)
                continue
            if o.status == "ausgefuehrt" and o.position_id:
                pos = self.db.get(Position, o.position_id)
                inst = self.db.get(Instrument, o.instrument_id)
                if pos and pos.status == "offen" and o.side == "verkauf":
                    self.close_from_fill(pos, o, inst, "Stop-Loss" if o.purpose == "stop" else o.note or "Ausstieg")
                    closed.append((o, pos))
        return closed

    def _sync_entry(self, o: Order) -> None:
        """Nachträglich (teil-)ausgeführter Einstieg: Position anlegen bzw. Menge und Stop anpassen."""
        inst = self.db.get(Instrument, o.instrument_id)
        pos = self.db.get(Position, o.position_id) if o.position_id else None
        if pos is None:
            from ..core.models import SignalRow
            sig = self.db.get(SignalRow, o.signal_id) if o.signal_id else None
            self._create_position(o, inst, o.stop_price, sig.take_profit if sig else None, None,
                                  sig.strategy_id if sig else "manuell", sig.strategy_name if sig else "Manuell", o.signal_id)
            return
        if pos.status == "offen" and o.filled_qty > pos.qty:
            pos.qty, pos.avg_entry, pos.fees = o.filled_qty, o.avg_fill_price, o.fees
            pos.entry_value = o.filled_qty * o.avg_fill_price
            so = self._order(pos.stop_client_order_id)
            if so is not None and so.status in OPEN_STATES:
                try:
                    self.apply(so, self.broker.cancel(so.client_order_id, so.broker_order_id))
                except BrokerError:
                    return
            self.place_stop(pos, inst)

    def cancel_all(self, reason: str) -> int:
        n = 0
        for o in self.open_orders():
            try:
                st = self.broker.cancel(o.client_order_id, o.broker_order_id)
                self.apply(o, st)
                n += 1
            except BrokerError as e:
                log_event(self.user_id, "fehler", "order", f"Stornierung fehlgeschlagen: {e}", db=self.db)
        log_event(self.user_id, "warnung", "order", f"{n} offene Orders storniert ({reason})", kind="storniert", db=self.db)
        return n
