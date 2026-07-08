import json
import socket
import urllib.error
from app.ocr.errors import OcrRetryableError, OcrFatalError, classify_exception


def _http(code):
    return urllib.error.HTTPError("u", code, "msg", {}, None)


def test_http_429_retryable_rate_limit():
    e = classify_exception(_http(429))
    assert isinstance(e, OcrRetryableError)
    assert e.error_type == "rate_limit" and e.http_status == 429


def test_http_503_retryable_overloaded():
    e = classify_exception(_http(503))
    assert isinstance(e, OcrRetryableError) and e.error_type == "overloaded"


def test_http_500_retryable_server():
    assert isinstance(classify_exception(_http(500)), OcrRetryableError)


def test_http_400_fatal_bad_request():
    e = classify_exception(_http(400))
    assert isinstance(e, OcrFatalError) and e.error_type == "bad_request"


def test_urlerror_retryable():
    assert isinstance(classify_exception(urllib.error.URLError("boom")), OcrRetryableError)


def test_timeout_retryable():
    e = classify_exception(socket.timeout())
    assert isinstance(e, OcrRetryableError) and e.error_type == "timeout"


def test_jsondecode_fatal_parse():
    e = classify_exception(json.JSONDecodeError("x", "y", 0))
    assert isinstance(e, OcrFatalError) and e.error_type == "parse"


def test_valueerror_fatal_schema():
    e = classify_exception(ValueError("non-dict"))
    assert isinstance(e, OcrFatalError) and e.error_type == "schema"
