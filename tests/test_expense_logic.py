from datetime import datetime, timezone, date
from app.expenses.logic import compute_business_date, traffic_light, TW_TZ


def _utc(y, m, d, hh, mm):
    # 給台灣時間，轉回 UTC 存
    from datetime import timedelta
    return datetime(y, m, d, hh, mm, tzinfo=TW_TZ).astimezone(timezone.utc)


def test_business_date_before_8am_counts_prev_day():
    # 台灣 2026-07-07 07:59 → 前一日 07-06
    assert compute_business_date(_utc(2026, 7, 7, 7, 59)) == date(2026, 7, 6)


def test_business_date_at_8am_counts_same_day():
    assert compute_business_date(_utc(2026, 7, 7, 8, 0)) == date(2026, 7, 7)


def test_business_date_after_8am_counts_same_day():
    assert compute_business_date(_utc(2026, 7, 7, 8, 1)) == date(2026, 7, 7)


def test_business_date_naive_treated_as_utc():
    # 無 tzinfo 的 UTC（SQLite 取回）→ 當 UTC。台灣 00:30 = 前一日 UTC 16:30
    naive = datetime(2026, 7, 6, 16, 30)  # UTC，台灣為 07-07 00:30
    assert compute_business_date(naive) == date(2026, 7, 6)


def test_traffic_light_green():
    assert traffic_light(False, 0.9, True, False) == "green"


def test_traffic_light_red_handwritten():
    assert traffic_light(True, 0.99, True, False) == "red"


def test_traffic_light_red_modified():
    assert traffic_light(False, 0.99, True, True) == "red"


def test_traffic_light_red_parse_fail():
    assert traffic_light(False, 0.99, False, False) == "red"


def test_traffic_light_yellow_low_conf():
    assert traffic_light(False, 0.5, True, False) == "yellow"


def test_traffic_light_none_signals_yellow_or_red():
    # 尚未辨識（全 None）當保守：紅（parse 未知）
    assert traffic_light(None, None, None, False) == "red"
