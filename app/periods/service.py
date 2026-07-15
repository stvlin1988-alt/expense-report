from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from app.expenses.logic import TW_TZ


def _clamped(year, month, day):
    """該月第 day 天；月份不足（如 2/31）clamp 到月底。"""
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _add_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _sub_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _period_start(d, close_day):
    """d 所屬期間起始（<= d 的最近換期日）。"""
    this_month = _clamped(d.year, d.month, close_day)
    if d >= this_month:
        return this_month
    y, m = _sub_month(d.year, d.month)
    return _clamped(y, m, close_day)


def canonical_bounds(d, close_day):
    start = _period_start(d, close_day)
    ny, nm = _add_month(start.year, start.month)
    next_start = _clamped(ny, nm, close_day)
    return start, next_start - timedelta(days=1)


def lock_at_for(next_start, offset_hours):
    local_midnight = datetime(next_start.year, next_start.month, next_start.day,
                              tzinfo=TW_TZ)
    return (local_midnight + timedelta(hours=offset_hours)).astimezone(timezone.utc)


def label_for(start):
    return f"{start.year:04d}-{start.month:02d}"
