from app.ocr.provider import get_provider, MockProvider, coerce_amount


def test_coerce_amount_plain_int():
    assert coerce_amount(1290) == (1290.0, True)


def test_coerce_amount_comma_string():
    assert coerce_amount("5,230") == (5230.0, True)


def test_coerce_amount_float_string():
    assert coerce_amount("45000.0") == (45000.0, True)


def test_coerce_amount_garbage():
    assert coerce_amount("約？") == (None, False)


def test_coerce_amount_none():
    assert coerce_amount(None) == (None, False)


# ---- C2 同一失效模式的 OCR 路徑：Gemini 幻覺金額不得存進 DB ----
# 裸 float() 會吃下 Infinity / NaN / 1e400，值一旦進 DB，/expenses/pending 就會吐出
# 裸的 Infinity/NaN token → 瀏覽器嚴格 JSON.parse 直接丟例外 → 員工暫存區整頁死掉，
# 而那正是唯一能修那筆的畫面。垃圾金額必須變成「沒讀到金額」(None, False)。

def test_coerce_amount_infinity_string_rejected():
    assert coerce_amount("Infinity") == (None, False)


def test_coerce_amount_nan_string_rejected():
    assert coerce_amount("NaN") == (None, False)


def test_coerce_amount_huge_exponent_string_rejected():
    assert coerce_amount("1e400") == (None, False)


def test_coerce_amount_inf_float_rejected():
    # json.loads('{"amount": 1e999}') → float('inf')（合法 JSON，Gemini 真的可能吐）
    import json
    v = json.loads('{"amount": 1e999}')["amount"]
    assert v == float("inf")
    assert coerce_amount(v) == (None, False)


def test_coerce_amount_nan_float_rejected():
    assert coerce_amount(float("nan")) == (None, False)


def test_coerce_amount_over_numeric_limit_rejected():
    assert coerce_amount("10000000000") == (None, False)


def test_mock_provider_default(app):
    with app.app_context():
        p = get_provider()
        assert isinstance(p, MockProvider)
        r = p.recognize(b"img", "image/jpeg")
        assert set(r) >= {"summary", "category_id", "amount", "confidence", "is_handwritten", "raw"}
