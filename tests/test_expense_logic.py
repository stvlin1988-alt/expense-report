from datetime import datetime, timezone, date
from app.expenses.logic import compute_business_date, traffic_light, audit_light, iso_utc, TW_TZ


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


def test_traffic_light_green_printed_high_conf():
    # 印刷單、高信心、金額 OK、沒人動過 → 綠
    assert traffic_light(False, 0.9, True, False) == "green"


def test_traffic_light_green_modified_confirmed():
    # 人改過金額且金額 OK → 已被確認 → 綠（不再是紅）
    assert traffic_light(False, 0.99, True, True) == "green"


def test_traffic_light_green_modified_even_if_handwritten():
    # 手寫但被人確認/修正 → 綠（人比機器可信）
    assert traffic_light(True, None, True, True) == "green"


def test_traffic_light_yellow_handwritten_unconfirmed():
    # 手寫但沒人確認 → 黃（請看一眼），不再直接紅
    assert traffic_light(True, 0.99, True, False) == "yellow"


def test_traffic_light_red_parse_fail():
    # 金額沒解析成功 → 紅（真正卡住的才紅）
    assert traffic_light(False, 0.99, False, False) == "red"


def test_traffic_light_red_parse_fail_even_if_modified():
    # 金額壞掉即使有人動過也是紅（金額不可信最優先）
    assert traffic_light(False, 0.99, False, True) == "red"


def test_traffic_light_yellow_low_conf():
    assert traffic_light(False, 0.5, True, False) == "yellow"


def test_traffic_light_none_signals_red():
    # 尚未辨識（全 None）當保守：紅（parse 未知）
    assert traffic_light(None, None, None, False) == "red"


# --- 主管稽核端燈號 audit_light（語意與員工端不同）---
# 參數：(amount_parse_ok, is_modified_by_user, is_no_receipt, is_handwritten, confidence)

def test_audit_light_red_employee_modified():
    # 員工改過金額/分類 → 紅（請主管 double check 為何改）
    assert audit_light(True, True, False, False, 0.99) == "red"


def test_audit_light_red_parse_fail():
    # 金額壞 → 紅（最優先）
    assert audit_light(False, False, False, False, 0.99) == "red"


def test_audit_light_yellow_no_receipt():
    # 無單據單（沒 OCR 可比對）→ 黃，即使 is_modified_by_user=True 也不轉紅
    assert audit_light(True, True, True, False, None) == "yellow"


def test_audit_light_yellow_handwritten_untouched():
    # 手寫但員工沒改 → 黃（提醒看一眼）
    assert audit_light(True, False, False, True, 0.99) == "yellow"


def test_audit_light_yellow_low_conf_untouched():
    assert audit_light(True, False, False, False, 0.5) == "yellow"


def test_audit_light_green_ocr_untouched_high_conf():
    # OCR 印刷單、員工沒動、高信心 → 綠（機器讀的、員工也認同）
    assert audit_light(True, False, False, False, 0.9) == "green"


# --- iso_utc：序列化時間一定帶時區（避免前端 new Date 誤判本地時間）---

def test_iso_utc_naive_treated_as_utc():
    # SQLite 讀回的 naive datetime → 補 +00:00
    naive = datetime(2026, 7, 7, 9, 26, 3)
    assert iso_utc(naive) == "2026-07-07T09:26:03+00:00"


def test_iso_utc_aware_preserved():
    aware = datetime(2026, 7, 7, 9, 26, 3, tzinfo=timezone.utc)
    assert iso_utc(aware).endswith("+00:00")


def test_iso_utc_none():
    assert iso_utc(None) is None
