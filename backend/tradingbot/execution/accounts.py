"""Handelskonten je Benutzer und Broker-Erzeugung (Paper oder Kraken)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..brokers.kraken import KrakenBroker
from ..brokers.paper import PaperBroker
from ..core.crypto import decrypt
from ..core.models import BotRuntime, PaperLedger, TradingAccount

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


def make_broker(db: Session, acct: TradingAccount, cfg: dict, ticker_fn):
    if acct.kind == "paper":
        return PaperBroker(db, acct.id, ticker_fn, Decimal(str(cfg["costs"]["fee_pct"])), Decimal(str(cfg["costs"]["slippage_pct"])))
    key, secret = decrypt(acct.api_key_enc), decrypt(acct.api_secret_enc)
    if not key or not secret:
        raise ValueError("Für das Echtgeld-Konto ist kein API-Schlüssel hinterlegt")
    return KrakenBroker(key, secret)
