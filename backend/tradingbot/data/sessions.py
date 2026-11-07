"""Handelszeiten der US-Börsen (NYSE/Nasdaq) für Aktien und ETFs."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
OPEN, CLOSE, EARLY_CLOSE = time(9, 30), time(16, 0), time(13, 0)

HOLIDAYS = {date.fromisoformat(d) for d in (
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
    "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
)}
EARLY = {date.fromisoformat(d) for d in ("2025-07-03", "2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24", "2027-11-26")}

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def session(d: date) -> tuple[datetime, datetime] | None:
    """Regulärer Handel des Tages (UTC) oder None an Wochenenden/Feiertagen."""
    if d.weekday() >= 5 or d in HOLIDAYS:
        return None
    end = EARLY_CLOSE if d in EARLY else CLOSE
    return (datetime.combine(d, OPEN, ET).astimezone(timezone.utc), datetime.combine(d, end, ET).astimezone(timezone.utc))


def is_open(now: datetime) -> bool:
    s = session(now.astimezone(ET).date())
    return s is not None and s[0] <= now < s[1]


def tradable(now: datetime, grace: timedelta = timedelta(minutes=20)) -> bool:
    """Handelbar: während der Sitzung und kurz nach Schluss (Signale der Schlusskerze, Order zum Schlusskurs
    bzw. beim Broker zur nächsten Eröffnung)."""
    s = session(now.astimezone(ET).date())
    return s is not None and s[0] <= now < s[1] + grace


def next_open(now: datetime) -> datetime:
    d = now.astimezone(ET).date()
    for i in range(15):
        s = session(d + timedelta(days=i))
        if s and s[0] > now:
            return s[0]
    return now


def open_label(now: datetime) -> str:
    """Z. B. „öffnet Mo 15:30“ (deutsche Zeit)."""
    t = next_open(now).astimezone(BERLIN)
    today = now.astimezone(BERLIN).date()
    day = "heute" if t.date() == today else "morgen" if t.date() == today + timedelta(days=1) else WEEKDAYS[t.weekday()]
    return f"öffnet {day} {t:%H:%M} Uhr"


def session_seconds(a: datetime, b: datetime) -> float:
    """Handelszeit (Sekunden) zwischen a und b – für das Datenalter von Aktienkursen."""
    if b <= a:
        return 0.0
    total = 0.0
    d = a.astimezone(ET).date()
    last = b.astimezone(ET).date()
    while d <= last:
        s = session(d)
        if s:
            lo, hi = max(a, s[0]), min(b, s[1])
            if hi > lo:
                total += (hi - lo).total_seconds()
        d += timedelta(days=1)
    return total
