import random
import time

from app.ocr.errors import OcrRetryableError, OcrFatalError


def recognize_with_retry(provider, image_bytes, content_type, cfg,
                         sleep=time.sleep, rand=random.random, clock=time.monotonic):
    """對 provider.recognize 做有限次重試。retryable 才退避重試，fatal 立即停。
    退避 = base * 2**(attempt-1) + rand()*base（sleep 可注入，測試傳 no-op）。"""
    max_retries = cfg.get("GEMINI_MAX_RETRIES", 3)
    base = cfg.get("GEMINI_RETRY_BASE", 0.5)
    attempts = []
    for attempt in range(1, max_retries + 1):
        start = clock()

        def _dur():
            return int((clock() - start) * 1000)

        try:
            fields = provider.recognize(image_bytes, content_type)
        except OcrFatalError as ex:
            attempts.append({"attempt": attempt, "outcome": "fatal",
                             "error_type": ex.error_type, "http_status": ex.http_status,
                             "duration_ms": _dur()})
            return {"fields": None, "final_outcome": "fatal", "attempts": attempts}
        except OcrRetryableError as ex:
            attempts.append({"attempt": attempt, "outcome": "retryable",
                             "error_type": ex.error_type, "http_status": ex.http_status,
                             "duration_ms": _dur()})
            if attempt < max_retries:
                sleep(base * (2 ** (attempt - 1)) + rand() * base)
            continue
        attempts.append({"attempt": attempt, "outcome": "success",
                         "error_type": None, "http_status": None, "duration_ms": _dur()})
        return {"fields": fields, "final_outcome": "success", "attempts": attempts}
    return {"fields": None, "final_outcome": "exhausted", "attempts": attempts}
