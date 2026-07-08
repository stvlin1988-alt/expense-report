from app.ocr.errors import OcrRetryableError, OcrFatalError
from app.ocr.retry import recognize_with_retry


class _FakeProvider:
    """依序丟出 side_effects：例外就 raise，dict 就 return。"""
    def __init__(self, side_effects):
        self._se = list(side_effects)
        self.calls = 0

    def recognize(self, image_bytes, content_type):
        self.calls += 1
        item = self._se.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_CFG = {"GEMINI_MAX_RETRIES": 3, "GEMINI_RETRY_BASE": 0.5}
_NO_SLEEP = lambda *_a, **_k: None
_FIELDS = {"summary": "x", "amount": 100}


def test_success_first_try():
    p = _FakeProvider([_FIELDS])
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "success" and r["fields"] == _FIELDS
    assert len(r["attempts"]) == 1 and r["attempts"][0]["outcome"] == "success"
    assert p.calls == 1


def test_retry_then_success():
    p = _FakeProvider([OcrRetryableError("rate_limit", 429), _FIELDS])
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "success"
    assert len(r["attempts"]) == 2
    assert r["attempts"][0]["outcome"] == "retryable" and r["attempts"][0]["error_type"] == "rate_limit"
    assert p.calls == 2


def test_exhausted_all_retryable():
    p = _FakeProvider([OcrRetryableError("overloaded", 503)] * 3)
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "exhausted" and r["fields"] is None
    assert len(r["attempts"]) == 3 and p.calls == 3


def test_fatal_no_retry():
    p = _FakeProvider([OcrFatalError("bad_request", 400), _FIELDS])
    r = recognize_with_retry(p, b"img", "image/jpeg", _CFG, sleep=_NO_SLEEP)
    assert r["final_outcome"] == "fatal" and r["fields"] is None
    assert len(r["attempts"]) == 1 and p.calls == 1  # 不重試


def test_sleep_called_between_retries():
    slept = []
    p = _FakeProvider([OcrRetryableError("server", 500), _FIELDS])
    recognize_with_retry(p, b"img", "image/jpeg", _CFG,
                         sleep=lambda s: slept.append(s), rand=lambda: 0.0)
    assert slept == [0.5]  # base * 2**0 + 0
