import http.client
import json
import socket
import urllib.error

_RETRYABLE_STATUS = {429: "rate_limit", 500: "server", 502: "server",
                     503: "overloaded", 504: "server"}


class OcrError(Exception):
    def __init__(self, error_type, http_status=None):
        super().__init__(f"{error_type} (http={http_status})")
        self.error_type = error_type
        self.http_status = http_status


class OcrRetryableError(OcrError):
    pass


class OcrFatalError(OcrError):
    pass


def classify_exception(exc):
    """把一次 Gemini 嘗試的例外分類成 retryable / fatal。"""
    # HTTPError 是 URLError 子類，必須先判
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code in _RETRYABLE_STATUS:
            return OcrRetryableError(_RETRYABLE_STATUS[code], code)
        if code == 400:
            return OcrFatalError("bad_request", code)
        return OcrFatalError("other", code)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return OcrRetryableError("timeout", None)
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return OcrRetryableError("timeout", None)
        return OcrRetryableError("server", None)
    if isinstance(exc, json.JSONDecodeError):
        return OcrFatalError("parse", None)
    if isinstance(exc, ValueError):
        return OcrFatalError("schema", None)
    if isinstance(exc, (http.client.IncompleteRead, ConnectionError, OSError)):
        return OcrRetryableError("connection", None)
    return OcrFatalError("other", None)
