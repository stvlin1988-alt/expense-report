import json
from app.extensions import db
from app.models import Category
from app.ocr.gemini import GeminiProvider


def _seed_categories(app):
    with app.app_context():
        db.create_all()
        parent = Category(name="廚房支出", level=1, sort=1)
        db.session.add(parent); db.session.commit()
        child = Category(name="食材", level=2, parent_id=parent.id, sort=1)
        db.session.add(child); db.session.commit()
        return child.id


def _fake_api_response(obj):
    # 模擬 Gemini generateContent 回傳結構
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


def test_gemini_maps_response_to_ocrresult(app, monkeypatch):
    cid = _seed_categories(app)
    with app.app_context():
        p = GeminiProvider(app.config)
        monkeypatch.setattr(p, "_call_api", lambda payload: _fake_api_response({
            "summary": "牛肉角等2項", "category_id": cid, "amount": "1,290",
            "confidence": 0.92, "is_handwritten": False,
        }))
        r = p.recognize(b"imgbytes", "image/jpeg")
        assert r["summary"] == "牛肉角等2項"
        assert r["category_id"] == cid
        assert r["amount"] in (1290, 1290.0, "1,290")  # 原值傳回，coerce 在 tasks 做
        assert r["confidence"] == 0.92
        assert r["is_handwritten"] is False
        assert r["raw"] is not None


def test_gemini_bad_json_returns_empty_result(app, monkeypatch):
    _seed_categories(app)
    with app.app_context():
        p = GeminiProvider(app.config)
        monkeypatch.setattr(p, "_call_api", lambda payload: {"candidates": [{"content": {"parts": [{"text": "非JSON"}]}}]})
        r = p.recognize(b"img", "image/jpeg")
        assert r["summary"] is None and r["amount"] is None
        assert r["confidence"] is None
