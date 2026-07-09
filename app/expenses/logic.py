from datetime import datetime, timezone, timedelta, date

TW_TZ = timezone(timedelta(hours=8))
BUSINESS_DAY_START_HOUR = 8


def _aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso_utc(dt):
    """datetime → ISO 字串且一定帶時區標記。
    DB 存 UTC，但 SQLite 讀回是 naive（tzinfo=None），naive 的 isoformat 不帶 offset，
    前端 new Date() 會誤判成瀏覽器本地時間 → 差 8 小時。統一補上 UTC 標記。"""
    if dt is None:
        return None
    return _aware_utc(dt).isoformat()


def compute_business_date(created_at_utc: datetime) -> date:
    """UTC → 台灣時間；台灣時間落在 00:00–08:00 記前一日曆日，否則當日。"""
    local = _aware_utc(created_at_utc).astimezone(TW_TZ)
    if local.hour < BUSINESS_DAY_START_HOUR:
        return (local - timedelta(days=1)).date()
    return local.date()


def traffic_light(is_handwritten, confidence, amount_parse_ok,
                  is_modified, green_threshold: float = 0.85) -> str:
    """燈號＝金額可信度 / 要不要人工把關。
    紅：金額沒解析成功（含 OCR 失敗）— 唯一真正卡住、必須處理的情況。
    綠：已被人確認/修正（is_modified）或 印刷單且 OCR 高信心。
    黃：手寫但沒人確認、或 OCR 信心不足 — 請看一眼。
    """
    if amount_parse_ok is not True:
        return "red"
    if is_modified:
        return "green"
    if is_handwritten:
        return "yellow"
    if confidence is not None and confidence >= green_threshold:
        return "green"
    return "yellow"


def audit_light(amount_parse_ok, is_modified_by_user, is_no_receipt,
                is_handwritten, confidence, green_threshold: float = 0.85) -> str:
    """主管稽核端燈號（語意與員工端不同）。
    紅：金額壞 或 員工改過 OCR 的金額/分類 — 請主管 double check 為何偏離機器讀值。
    黃：無單據單（無 OCR 可比對）、手寫沒人改、或 OCR 信心不足 — 請看一眼。
    綠：OCR 印刷單、員工沒動過、且 OCR 高信心 — 機器讀的、員工也認同。
    """
    if amount_parse_ok is not True:
        return "red"
    if is_no_receipt:
        return "yellow"
    if is_modified_by_user:
        return "red"
    if is_handwritten:
        return "yellow"
    if confidence is not None and confidence >= green_threshold:
        return "green"
    return "yellow"
