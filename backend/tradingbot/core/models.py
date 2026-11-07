"""Datenmodell (Abschnitt 7). Alle Zeiten UTC, Geldbeträge als Decimal.

Orders-Statuswechsel, Fills und Risikoentscheidungen sind Append-only.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, Dec, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="benutzer")  # admin | benutzer
    status: Mapped[str] = mapped_column(String(20), default="aktiv")  # aktiv | eingeladen | gesperrt
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(10), default="de")
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    reset_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device: Mapped[str] = mapped_column(String(40))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True)  # z. B. BTC/EUR
    market: Mapped[str] = mapped_column(String(20))  # krypto | devisen
    base: Mapped[str] = mapped_column(String(12))
    quote: Mapped[str] = mapped_column(String(12))
    broker_symbol: Mapped[str] = mapped_column(String(20))  # Kraken-Pair, z. B. XBTEUR
    tick_size: Mapped[Decimal] = mapped_column(Dec)
    min_qty: Mapped[Decimal] = mapped_column(Dec)
    step_size: Mapped[Decimal] = mapped_column(Dec)
    trading_hours: Mapped[str] = mapped_column(String(40), default="24/7")
    tradable: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String(8))
    time: Mapped[datetime] = mapped_column(UTCDateTime)
    open: Mapped[Decimal] = mapped_column(Dec)
    high: Mapped[Decimal] = mapped_column(Dec)
    low: Mapped[Decimal] = mapped_column(Dec)
    close: Mapped[Decimal] = mapped_column(Dec)
    volume: Mapped[Decimal] = mapped_column(Dec)
    quality_flag: Mapped[str] = mapped_column(String(20), default="ok")
    __table_args__ = (UniqueConstraint("instrument_id", "timeframe", "time"),)


class BotRuntime(Base):
    """Persistenter Zustand des Bots je Benutzer (Zustandsautomat, Abschnitt 5.1)."""

    __tablename__ = "bot_runtime"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), default="INITIALISIERUNG")
    state_reason: Mapped[str] = mapped_column(String(300), default="")
    lock_kind: Mapped[str] = mapped_column(String(20), default="")  # abgleich | tagesverlust | drawdown | verlustserie | fehler
    last_snapshot_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    state_since: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    want_running: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_equity: Mapped[Decimal | None] = mapped_column(Dec)
    day: Mapped[str] = mapped_column(String(10), default="")
    day_start_equity: Mapped[Decimal | None] = mapped_column(Dec)
    loss_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_reconcile_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reconcile_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    last_reconcile_note: Mapped[str] = mapped_column(String(300), default="")
    broker_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_report_day: Mapped[str] = mapped_column(String(10), default="")
    last_week_report: Mapped[str] = mapped_column(String(10), default="")


class TradingAccount(Base):
    __tablename__ = "trading_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # paper | live
    broker: Mapped[str] = mapped_column(String(20))  # paper | kraken
    currency: Mapped[str] = mapped_column(String(6), default="EUR")
    start_capital: Mapped[Decimal] = mapped_column(Dec, default=Decimal("10000"))
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    api_secret_enc: Mapped[str | None] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(16), default="")
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    connection_note: Mapped[str] = mapped_column(String(300), default="")
    environment: Mapped[str] = mapped_column(String(10), default="live")  # Alpaca: paper | live
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "kind"),)


class PaperLedger(Base):
    """Kontoführung des Simulations-Brokers (unabhängig vom Order-Management, für den Abgleich)."""

    __tablename__ = "paper_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True)
    asset: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    __table_args__ = (UniqueConstraint("account_id", "asset"),)


class PaperOrder(Base):
    """Orderbuch des Simulations-Brokers (z. B. Stop-Loss-Orders)."""

    __tablename__ = "paper_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(12))  # market | stop
    qty: Mapped[Decimal] = mapped_column(Dec)
    stop_price: Mapped[Decimal | None] = mapped_column(Dec)
    status: Mapped[str] = mapped_column(String(16))  # open | filled | canceled | rejected
    filled_qty: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    avg_price: Mapped[Decimal | None] = mapped_column(Dec)
    fee: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    changed_by: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[dict] = mapped_column(JSON)


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    candle_time: Mapped[datetime] = mapped_column(UTCDateTime)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    strategy_id: Mapped[str] = mapped_column(String(40))
    strategy_name: Mapped[str] = mapped_column(String(80))
    strategy_version: Mapped[str] = mapped_column(String(20))
    timeframe: Mapped[str] = mapped_column(String(8))
    direction: Mapped[str] = mapped_column(String(10))  # kauf | verkauf
    strength: Mapped[Decimal] = mapped_column(Dec)
    price: Mapped[Decimal] = mapped_column(Dec)
    stop_suggestion: Mapped[Decimal | None] = mapped_column(Dec)
    take_profit: Mapped[Decimal | None] = mapped_column(Dec)
    reasoning: Mapped[dict] = mapped_column(JSON)
    config_version_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="neu")
    # neu | freigegeben | abgelehnt | wartet_bestaetigung | verworfen | nur_signal | abgelaufen
    __table_args__ = (Index("ix_signal_dedupe", "user_id", "strategy_id", "instrument_id", "candle_time", "direction"),)


class RiskDecision(Base):
    __tablename__ = "risk_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(12))  # einstieg | ausstieg
    result: Mapped[str] = mapped_column(String(16))  # freigegeben | verkleinert | abgelehnt
    rule: Mapped[str] = mapped_column(String(80), default="")
    limit_value: Mapped[str] = mapped_column(String(60), default="")
    actual_value: Mapped[str] = mapped_column(String(60), default="")
    position_size: Mapped[Decimal | None] = mapped_column(Dec)
    checks: Mapped[list] = mapped_column(JSON)
    client_order_id: Mapped[str | None] = mapped_column(String(64))


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id"))
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(8))  # kauf | verkauf
    type: Mapped[str] = mapped_column(String(12))  # market | stop
    purpose: Mapped[str] = mapped_column(String(16))  # einstieg | ausstieg | stop | notaus | manuell
    qty: Mapped[Decimal] = mapped_column(Dec)
    price: Mapped[Decimal | None] = mapped_column(Dec)
    stop_price: Mapped[Decimal | None] = mapped_column(Dec)
    status: Mapped[str] = mapped_column(String(16))
    filled_qty: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Dec)
    fees: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    risk_stamp: Mapped[str] = mapped_column(String(128), default="")
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"))
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OrderStatusEvent(Base):
    __tablename__ = "order_status_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(300), default="")


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    price: Mapped[Decimal] = mapped_column(Dec)
    qty: Mapped[Decimal] = mapped_column(Dec)
    fee: Mapped[Decimal] = mapped_column(Dec)
    broker_fill_id: Mapped[str] = mapped_column(String(64), default="")


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    strategy_id: Mapped[str] = mapped_column(String(40))
    strategy_name: Mapped[str] = mapped_column(String(80))
    side: Mapped[str] = mapped_column(String(8), default="long")
    qty: Mapped[Decimal] = mapped_column(Dec)
    avg_entry: Mapped[Decimal] = mapped_column(Dec)
    stop: Mapped[Decimal | None] = mapped_column(Dec)
    initial_stop: Mapped[Decimal | None] = mapped_column(Dec)
    take_profit: Mapped[Decimal | None] = mapped_column(Dec)
    trailing_atr_mult: Mapped[Decimal | None] = mapped_column(Dec)
    highest_price: Mapped[Decimal | None] = mapped_column(Dec)
    stop_client_order_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="offen")  # offen | geschlossen
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    exit_price: Mapped[Decimal | None] = mapped_column(Dec)
    exit_reason: Mapped[str] = mapped_column(String(60), default="")
    entry_value: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    fees: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    realized: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_kind: Mapped[str] = mapped_column(String(10))
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    equity: Mapped[Decimal] = mapped_column(Dec)
    available: Mapped[Decimal] = mapped_column(Dec)
    peak: Mapped[Decimal] = mapped_column(Dec)
    drawdown_pct: Mapped[Decimal] = mapped_column(Dec)
    __table_args__ = (Index("ix_snap_user_time", "user_id", "account_kind", "time"),)


class BotEvent(Base):
    __tablename__ = "bot_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    severity: Mapped[str] = mapped_column(String(12))  # info | warnung | fehler | kritisch
    module: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    keys: Mapped[dict] = mapped_column(JSON)
    device: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(12), default="laeuft")
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)


class RegimeLog(Base):
    """Erkanntes Marktregime im Zeitverlauf (FA-16)."""

    __tablename__ = "regime_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    candle_time: Mapped[datetime] = mapped_column(UTCDateTime)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    regime: Mapped[str] = mapped_column(String(24))
    values: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("instrument_id", "timeframe", "candle_time"),)


class ShadowTrade(Base):
    """Schattenbetrieb (FA-17): simulierte Trades jeder zugelassenen Strategie, nie an den Broker."""

    __tablename__ = "shadow_trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[str] = mapped_column(String(40), index=True)
    strategy_version: Mapped[str] = mapped_column(String(20))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String(8))
    regime: Mapped[str] = mapped_column(String(24), default="unklar")
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    entry: Mapped[Decimal] = mapped_column(Dec)
    stop: Mapped[Decimal] = mapped_column(Dec)
    initial_stop: Mapped[Decimal] = mapped_column(Dec)
    take_profit: Mapped[Decimal | None] = mapped_column(Dec)
    highest: Mapped[Decimal] = mapped_column(Dec)
    trailing_atr_mult: Mapped[Decimal | None] = mapped_column(Dec)
    status: Mapped[str] = mapped_column(String(12), default="offen")
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    exit_price: Mapped[Decimal | None] = mapped_column(Dec)
    exit_reason: Mapped[str] = mapped_column(String(60), default="")
    r_multiple: Mapped[Decimal | None] = mapped_column(Dec)  # Ergebnis in Vielfachen des Risikos, nach Kosten
    pnl_pct: Mapped[Decimal | None] = mapped_column(Dec)  # Ergebnis in % nach Kosten
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))


class StrategyPerformance(Base):
    """Scorecard je Strategie (Abschnitt 6.2), rollierend berechnet."""

    __tablename__ = "strategy_performance"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    strategy_id: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    window: Mapped[str] = mapped_column(String(12))  # 30t | 90t | gesamt
    mode: Mapped[str] = mapped_column(String(10))  # shadow | paper | live
    regime: Mapped[str] = mapped_column(String(24), default="alle")
    trades: Mapped[int] = mapped_column(Integer, default=0)
    expectancy_r: Mapped[Decimal | None] = mapped_column(Dec)
    expectancy_pct: Mapped[Decimal | None] = mapped_column(Dec)
    profit_factor: Mapped[Decimal | None] = mapped_column(Dec)
    win_rate: Mapped[Decimal | None] = mapped_column(Dec)
    drawdown_r: Mapped[Decimal | None] = mapped_column(Dec)
    stability: Mapped[Decimal | None] = mapped_column(Dec)
    backtest_deviation: Mapped[Decimal | None] = mapped_column(Dec)
    score: Mapped[Decimal | None] = mapped_column(Dec)


class StrategyAllocation(Base):
    """Entscheidungen der Strategieauswahl (Meta-Controller) mit Begründung."""

    __tablename__ = "strategy_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    strategy_id: Mapped[str] = mapped_column(String(40))
    weight: Mapped[Decimal] = mapped_column(Dec)
    status: Mapped[str] = mapped_column(String(16))  # aktiv | inaktiv | pausiert | vorschlag
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning: Mapped[dict] = mapped_column(JSON)
    batch: Mapped[str] = mapped_column(String(40), index=True)


class TermsAcceptance(Base):
    __tablename__ = "terms_acceptances"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(20))
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class IncomeEntry(Base):
    """Einzeln protokollierte Erträge (Abschnitt 15.3, Steuer-Export)."""

    __tablename__ = "income_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_kind: Mapped[str] = mapped_column(String(10))
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(40))  # strategie-id oder modul:…
    kind: Mapped[str] = mapped_column(String(20))  # kursgewinn | zins | staking | praemie | dividende
    asset: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Dec)  # in Kontowährung
    note: Mapped[str] = mapped_column(String(200), default="")


class ModuleRun(Base):
    __tablename__ = "module_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    module: Mapped[str] = mapped_column(String(30))
    period: Mapped[str] = mapped_column(String(12))  # z. B. 2026-W45 / 2026-11
    time: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    account_kind: Mapped[str] = mapped_column(String(10))
    result: Mapped[str] = mapped_column(String(20))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class AppSetting(Base):
    """Systemweite Einstellungen (Anbieterdaten, AGB-Version, Freigaben)."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
