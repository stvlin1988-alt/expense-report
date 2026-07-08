import base64
import http.client
import json
import socket
import urllib.error
import urllib.request

from app.models import Category
from app.ocr.provider import OCRProvider
from app.ocr.prompt import build_prompt, build_response_schema
from app.ocr.errors import classify_exception

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
        self.model = cfg.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self.key = cfg.get("GEMINI_API_KEY", "")
        self.timeout = cfg.get("GEMINI_TIMEOUT", 30)
        # -1=動態思考、0=關閉。lite 底模需明確開思考才讀得穩手寫金額
        self.thinking_budget = cfg.get("GEMINI_THINKING_BUDGET", -1)

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
                "thinkingConfig": {"thinkingBudget": self.thinking_budget},
            },
        }
        try:
            resp = self._call_api(payload)
        except (urllib.error.URLError, socket.timeout, TimeoutError,
                OSError, http.client.IncompleteRead, json.JSONDecodeError) as e:
            raise classify_exception(e) from e
        try:
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("non-dict response")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as e:
            raise classify_exception(e) from e
        return {
            "summary": obj.get("summary"),
            "category_id": obj.get("category_id"),
            "amount": obj.get("amount"),
            "confidence": obj.get("confidence"),
            "is_handwritten": obj.get("is_handwritten"),
            "raw": obj,
        }
