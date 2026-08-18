"""Date helpers. 'Today' is local to the team, not UTC — a 06:00 IST entry is
still the previous day in UTC, which is how the Django app mis-dated mornings."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.config import settings

TZ = ZoneInfo(settings.TIMEZONE)


def today() -> date:
    return datetime.now(TZ).date()


def day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """The [start, end) of a team-local calendar day, in UTC and tz-naive —
    what a `timestamp without time zone` column storing UTC instants (e.g.
    `EntryItemStatusEvent.changed_at`) needs to be compared against. Comparing
    such a column directly to a bare `date` silently treats it as UTC
    midnight, which is 5:30 off from midnight IST — the exact mis-dating this
    module's `today()` already exists to avoid."""
    start = datetime(d.year, d.month, d.day, tzinfo=TZ).astimezone(UTC).replace(tzinfo=None)
    end = datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(days=1)
    return start, end.astimezone(UTC).replace(tzinfo=None)


def week_bounds(d: date | None = None) -> tuple[date, date]:
    d = d or today()
    start = d - timedelta(days=(d.weekday() - settings.WEEK_START) % 7)
    return start, start + timedelta(days=6)


def month_bounds(d: date | None = None) -> tuple[date, date]:
    d = d or today()
    start = d.replace(day=1)
    return start, (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def resolve_range(period: str | None, frm: date | None, to: date | None) -> tuple[date, date]:
    """Explicit from/to wins; otherwise a named period; otherwise the last week.

    No named range ever ends in the future. `week_bounds` returns the calendar
    week Monday-to-Sunday, and since this is the default period, opening the app
    on a Monday asked for 10-16 Aug — six days that hadn't happened yet and one
    on which nobody had filed yet. Every screen showed every person on zero
    tickets, which read as missing data rather than an empty window.

    "week" is therefore a rolling seven days ending today, and the calendar
    periods are clamped. A trailing window also survives Monday morning, when a
    calendar week is one working hour old.
    """
    if frm and to:
        return frm, to
    t = today()
    match period:
        case "today":
            return t, t
        case "yesterday":
            return t - timedelta(days=1), t - timedelta(days=1)
        case "month":
            return month_bounds(t)[0], t
        case "quarter":
            return date(t.year, 3 * ((t.month - 1) // 3) + 1, 1), t
        case _:
            return t - timedelta(days=6), t
