"""
CooperCorp PRJ-002 — Market Hours Utility
Checks if NYSE is currently open, handles weekends and US holidays.
"""
from datetime import date, datetime, timedelta
import pytz

ET = pytz.timezone("America/New_York")

US_MARKET_HOLIDAYS_2025 = [
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25"
]

US_MARKET_HOLIDAYS_2026 = [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"
]

ALL_HOLIDAYS = set(US_MARKET_HOLIDAYS_2025 + US_MARKET_HOLIDAYS_2026)


def is_market_holiday(d: date = None) -> bool:
    if d is None:
        d = datetime.now(ET).date()
    return d.isoformat() in ALL_HOLIDAYS


def is_market_open() -> bool:
    """Returns True if NYSE is currently open (9:30–16:00 ET, Mon–Fri, non-holiday)."""
    now_et = datetime.now(ET)
    # Weekend check
    if now_et.weekday() >= 5:
        return False
    # Holiday check
    if is_market_holiday(now_et.date()):
        return False
    # Hours check: 9:30 AM – 4:00 PM ET
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et < market_close


def next_market_open() -> datetime:
    """Returns the next market open datetime in ET."""
    now_et = datetime.now(ET)
    candidate = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

    # If we're past today's open, start from tomorrow
    if now_et >= candidate:
        candidate += timedelta(days=1)

    # Advance past weekends and holidays
    while candidate.weekday() >= 5 or is_market_holiday(candidate.date()):
        candidate += timedelta(days=1)

    return candidate
