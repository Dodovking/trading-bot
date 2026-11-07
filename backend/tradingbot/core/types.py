"""Gemeinsame Datentypen."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

TIMEFRAMES: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}

TIMEFRAME_LABELS = {"15m": "15 Minuten", "1h": "1 Stunde", "4h": "4 Stunden", "1d": "1 Tag"}


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    ok: bool = True
    flag: str = "ok"


@dataclass
class PositionView:
    entry: float
    stop: float | None
    highest: float
    opened_at: datetime


@dataclass
class Decision:
    direction: str  # kauf | verkauf | halten
    strength: float = 0.0
    stop: float | None = None
    take_profit: float | None = None
    trailing_atr_mult: float | None = None
    reasoning: dict = field(default_factory=dict)
