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


def test_mock_provider_default(app):
    with app.app_context():
        p = get_provider()
        assert isinstance(p, MockProvider)
        r = p.recognize(b"img", "image/jpeg")
        assert set(r) >= {"summary", "category_id", "amount", "confidence", "is_handwritten", "raw"}
