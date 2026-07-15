from datetime import date, timezone
from app.periods.service import canonical_bounds, lock_at_for, label_for


def test_close_day_1_january():
    start, end = canonical_bounds(date(2026, 1, 15), 1)
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_close_day_1_boundary_is_new_period():
    # 1 號當天算「新期起始」，不屬於上一期
    start, end = canonical_bounds(date(2026, 2, 1), 1)
    assert start == date(2026, 2, 1)


def test_close_day_5_labels_by_start_month():
    start, end = canonical_bounds(date(2026, 1, 20), 5)
    assert start == date(2026, 1, 5)
    assert end == date(2026, 2, 4)
    assert label_for(start) == "2026-01"


def test_close_day_clamps_short_month():
    # close_day=31，2 月沒有 31 → clamp 到月底；期間首尾仍相接
    start, end = canonical_bounds(date(2026, 2, 10), 31)
    assert start == date(2026, 1, 31)
    assert end == date(2026, 2, 27)   # 下一個換期日 2/28（clamp）前一天


def test_lock_at_default_offset_is_next_day_noon_tw():
    # 2/1 00:00 台灣 + 36h = 2/2 12:00 台灣 = 2/2 04:00 UTC
    la = lock_at_for(date(2026, 2, 1), 36)
    assert la.astimezone(timezone.utc).isoformat() == "2026-02-02T04:00:00+00:00"
