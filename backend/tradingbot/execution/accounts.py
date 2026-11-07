"""Handelskonten je Benutzer und Broker-Erzeugung (Paper oder Echtgeld über eine/mehrere Verbindungen)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..brokers.kraken import KrakenBroker
from ..brokers.paper import PaperBroker
from ..core.crypto import decrypt
from ..core.models import BotRuntime, BrokerLink, Instrument, Order, PaperLedger, TradingAccount

PAPER_START = Decimal("10000")


def ensure_user_setup(db: Session, user_id: int) -> None:
    if db.get(BotRuntime, user_id) is None:
        db.add(BotRuntime(user_id=user_id))
    acct = db.scalars(select(TradingAccount).where(TradingAccount.user_id == user_id, TradingAccount.kind == "paper")).first()
    if acct is None:
        acct = TradingAccount(user_id=user_id, kind="paper", broker="paper", currency="EUR", start_capital=PAPER_START,
                              connected=True, connection_note="Simulation")
        db.add(acct)
        db.flush()
        db.add(PaperLedger(account_id=acct.id, asset="EUR", amount=PAPER_START))
    db.flush()


def get_account(db: Session, user_id: int, kind: str) -> TradingAccount | None:
    return db.scalars(select(TradingAccount).where(TradingAccount.user_id == user_id, TradingAccount.kind == kind)).first()


def get_links(db: Session, user_id: int) -> list[BrokerLink]:
    return list(db.scalars(select(BrokerLink).where(BrokerLink.user_id == user_id).order_by(BrokerLink.id)))


def get_link(db: Session, user_id: int, broker: str) -> BrokerLink | None:
    return db.scalars(select(BrokerLink).where(BrokerLink.user_id == user_id, BrokerLink.broker == broker)).first()


def trading_links(db: Session, user_id: int) -> list[BrokerLink]:
    """Verbindungen, über die das Echtgeld-Konto handelt (verbunden, Umgebung live)."""
    return [lk for lk in get_links(db, user_id) if lk.connected and lk.environment == "live" and lk.api_key_enc]


def ensure_live_account(db: Session, user_id: int) -> TradingAccount:
    acct = get_account(db, user_id, "live")
    if acct is None:
        acct = TradingAccount(user_id=user_id, kind="live", broker="multi", currency="EUR", start_capital=Decimal(0),
                              connected=False, connection_note="")
        db.add(acct)
        db.flush()
    return acct


def migrate_broker_links(db: Session) -> None:
    """Früher lag genau ein Schlüssel direkt am Echtgeld-Konto – als Verbindung übernehmen."""
    for acct in db.scalars(select(TradingAccount).where(TradingAccount.kind == "live", TradingAccount.api_key_enc.is_not(None))):
        if acct.broker not in ("multi", "paper") and get_link(db, acct.user_id, acct.broker) is None:
            db.add(BrokerLink(user_id=acct.user_id, broker=acct.broker, environment=acct.environment or "live",
                              api_key_enc=acct.api_key_enc, api_secret_enc=acct.api_secret_enc, api_key_hint=acct.api_key_hint,
                              connected=acct.connected, connection_note=acct.connection_note))
        acct.api_key_enc = acct.api_secret_enc = None
        acct.broker = "multi"
    db.flush()


def link_broker(link: BrokerLink, ticker_fn):
    key, secret = decrypt(link.api_key_enc), decrypt(link.api_secret_enc)
    if not key or not secret:
        raise ValueError(f"Für {link.broker} ist kein API-Schlüssel hinterlegt")
    if link.broker == "alpaca":
        from ..brokers.alpaca import AlpacaBroker
        return AlpacaBroker(key, secret, link.environment or "live", _usd_per_eur(ticker_fn))
    if link.broker == "kraken":
        return KrakenBroker(key, secret)
    raise ValueError(f"Anbieter {link.broker} ist noch nicht angebunden")


def make_broker(db: Session, acct: TradingAccount, cfg: dict, ticker_fn):
    if acct.kind == "paper":
        return PaperBroker(db, acct.id, ticker_fn, Decimal(str(cfg["costs"]["fee_pct"])), Decimal(str(cfg["costs"]["slippage_pct"])))
    from ..brokers.catalog import BY_ID
    from ..brokers.router import RouterBroker
    venues: dict[str, tuple[str, object]] = {}
    for lk in trading_links(db, acct.user_id):
        p = BY_ID.get(lk.broker)
        if p is None:
            continue
        for mk in p["markets"]:
            venue = "aktie" if mk == "aktien" else "krypto"
            if venue not in venues:
                venues[venue] = (p["name"], link_broker(lk, ticker_fn))
    if not venues:
        raise ValueError("Kein Echtgeld-Anbieter verbunden (Einstellungen → Konto & Börse)")

    def market_of_order(coid: str) -> str | None:
        o = db.scalars(select(Order).where(Order.client_order_id == coid)).first()
        inst = db.get(Instrument, o.instrument_id) if o else None
        return inst.market if inst else None

    return RouterBroker(venues, market_of_order)


def _usd_per_eur(ticker_fn):
    def rate() -> Decimal:
        t = ticker_fn("EUR/USD")
        if t is not None and t.mid > 0:
            return t.mid
        from ..engine import get_engine
        fx = getattr(get_engine().market.source, "fx", None)
        if fx is None:
            raise ValueError("Kein EUR/USD-Kurs verfügbar")
        return fx.usd_per_eur()
    return rate
