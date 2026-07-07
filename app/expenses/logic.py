from datetime import datetime, timezone, timedelta, date

TW_TZ = timezone(timedelta(hours=8))
BUSINESS_DAY_START_HOUR = 8


def _aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_business_date(created_at_utc: datetime) -> date:
    """UTC → 台灣時間；台灣時間落在 00:00–08:00 記前一日曆日，否則當日。"""
    local = _aware_utc(created_at_utc).astimezone(TW_TZ)
    if local.hour < BUSINESS_DAY_START_HOUR:
        return (local - timedelta(days=1)).date()
    return local.date()


def traffic_light(is_handwritten, confidence, amount_parse_ok,
                  is_modified, green_threshold: float = 0.85) -> str:
    if is_handwritten or is_modified or amount_parse_ok is not True:
        return "red"
    if confidence is not None and confidence >= green_threshold:
        return "green"
    return "yellow"
