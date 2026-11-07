"""Tages- und Wochenbericht (FA-11) als kurzer deutscher Text."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core.models import AccountSnapshot, Position, RiskDecision, TradingAccount


def _eur(x: Decimal) -> str:
    return f"{x:+,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _summary(db: Session, user_id: int, acct: TradingAccount, since: datetime, label: str) -> str:
    closed = list(db.scalars(select(Position).where(Position.user_id == user_id, Position.account_id == acct.id,
                                                    Position.status == "geschlossen", Position.closed_at >= since)))
    pnl = sum((p.realized for p in closed), Decimal(0))
    wins = sum(1 for p in closed if p.realized > 0)
    open_n = len(list(db.scalars(select(Position.id).where(Position.user_id == user_id, Position.account_id == acct.id,
                                                           Position.status == "offen"))))
    rejected = len(list(db.scalars(select(RiskDecision.id).where(RiskDecision.user_id == user_id, RiskDecision.result == "abgelehnt",
                                                                 RiskDecision.time >= since))))
    snap = db.scalars(select(AccountSnapshot).where(AccountSnapshot.user_id == user_id, AccountSnapshot.account_kind == acct.kind)
                      .order_by(AccountSnapshot.id.desc()).limit(1)).first()
    eq = f", Kontowert {snap.equity:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if snap else ""
    mode = "PAPER" if acct.kind == "paper" else "LIVE"
    return (f"{label} ({mode}): {len(closed)} Trades geschlossen ({wins} Gewinner), Ergebnis {_eur(pnl)}, "
            f"{open_n} Positionen offen, {rejected} Signale vom Risikomodul abgelehnt{eq}.")


def daily_report(db: Session, user_id: int, acct: TradingAccount, local: datetime) -> str:
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return _summary(db, user_id, acct, start, f"Tagesbericht {local:%d.%m.%Y}")


def weekly_report(db: Session, user_id: int, acct: TradingAccount, local: datetime) -> str:
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return _summary(db, user_id, acct, start, f"Wochenbericht KW {local.isocalendar().week}")
