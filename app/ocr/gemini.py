import base64
import json
import logging
import urllib.request

from app.models import Category
from app.ocr.provider import OCRProvider
from app.ocr.prompt import build_prompt, build_response_schema

logger = logging.getLogger(__name__)
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def _load_categories():
    rows = (Category.query
            .filter_by(active=True)
            .order_by(Category.sort).all())
    by_id = {r.id: r for r in rows}
    out = []
    for r in rows:
        if r.level == 2:
            parent = by_id.get(r.parent_id)
            out.append({"id": r.id, "科目": parent.name if parent else "", "項目": r.name})
    return out


class GeminiProvider(OCRProvider):
    def __init__(self, cfg):
        self.model = cfg.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.key = cfg.get("GEMINI_API_KEY", "")
        self.timeout = cfg.get("GEMINI_TIMEOUT", 30)

    def _call_api(self, payload):
        url = _ENDPOINT.format(model=self.model, key=self.key)
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def recognize(self, image_bytes, content_type):
        categories = _load_categories()
        payload = {
            "contents": [{"parts": [
                {"text": build_prompt(categories)},
                {"inline_data": {"mime_type": content_type,
                                 "data": base64.b64encode(image_bytes).decode("ascii")}},
            ]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": build_response_schema(),
            },
        }
        empty = {"summary": None, "category_id": None, "amount": None,
                 "confidence": None, "is_handwritten": None, "raw": None}
        try:
            resp = self._call_api(payload)
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("non-dict response")
        except Exception as e:
            logger.warning("Gemini recognize failed: %s", e)
            return empty
        return {
            "summary": obj.get("summary"),
            "category_id": obj.get("category_id"),
            "amount": obj.get("amount"),
            "confidence": obj.get("confidence"),
            "is_handwritten": obj.get("is_handwritten"),
            "raw": obj,
        }
