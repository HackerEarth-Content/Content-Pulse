"""Date helpers. 'Today' is local to the team, not UTC — a 06:00 IST entry is
still the previous day in UTC, which is how the Django app mis-dated mornings."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.config import settings

TZ = ZoneInfo(settings.TIMEZONE)


def today() -> date:
    return datetime.now(TZ).date()


def week_bounds(d: date | None = None) -> tuple[date, date]:
    d = d or today()
    start = d - timedelta(days=(d.weekday() - settings.WEEK_START) % 7)
    return start, start + timedelta(days=6)


def month_bounds(d: date | None = None) -> tuple[date, date]:
    d = d or today()
    start = d.replace(day=1)
    return start, (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def resolve_range(period: str | None, frm: date | None, to: date | None) -> tuple[date, date]:
    """Explicit from/to wins; otherwise a named period; otherwise this week."""
    if frm and to:
        return frm, to
    t = today()
    match period:
        case "today":
            return t, t
        case "yesterday":
            return t - timedelta(days=1), t - timedelta(days=1)
        case "month":
            return month_bounds(t)
        case "quarter":
            start = date(t.year, 3 * ((t.month - 1) // 3) + 1, 1)
            return start, t
        case _:
            return week_bounds(t)
