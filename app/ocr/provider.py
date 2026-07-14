from flask import current_app

from app.expenses.amount import parse_amount


def coerce_amount(value):
    """→ (Decimal|None, ok)。接受 int/float/字串（可含千分位逗號、貨幣符號）。
    清掉貨幣格式後一律交給 parse_amount 把關：裸 float() 會吃下 Infinity / NaN / 1e400
    （`json.loads('{"amount": 1e999}')` → inf 是合法 JSON，Gemini 幻覺金額真的會走到這裡），
    值一旦進 DB，/expenses/pending 就會吐出裸的 Infinity/NaN token，瀏覽器嚴格 JSON.parse
    直接丟例外 → 員工暫存區整頁死掉，而那正是唯一能修那筆的畫面。
    垃圾金額（含 0、超出 Numeric(12,2) 範圍）一律回「沒讀到金額」→ 該筆亮紅/黃燈由員工手 key。"""
    if value is None:
        return None, False
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("NT$", "").replace("$", "")
    elif not isinstance(value, (int, float)):
        return None, False
    val, err = parse_amount(value)
    if err or val is None:
        return None, False
    return val, True


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
