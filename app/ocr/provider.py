from flask import current_app


def coerce_amount(value):
    """→ (float|None, ok)。接受 int/float/字串（可含千分位逗號、貨幣符號）。"""
    if value is None:
        return None, False
    if isinstance(value, (int, float)):
        return float(value), True
    s = str(value).strip().replace(",", "").replace("NT$", "").replace("$", "")
    try:
        return float(s), True
    except ValueError:
        return None, False


class OCRProvider:
    def recognize(self, image_bytes, content_type):  # pragma: no cover - 介面
        raise NotImplementedError


class MockProvider(OCRProvider):
    def __init__(self, result=None):
        self._result = result

    def recognize(self, image_bytes, content_type):
        if self._result is not None:
            return dict(self._result)
        return {
            "summary": "測試單據", "category_id": None, "amount": 100,
            "confidence": 0.9, "is_handwritten": False, "raw": {"mock": True},
        }


def get_provider():
    if current_app.config.get("OCR_PROVIDER") == "gemini":
        from app.ocr.gemini import GeminiProvider   # Task 6
        return GeminiProvider(current_app.config)
    return MockProvider()
