from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Expense, OcrLog
import app.expenses.tasks as tasks


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return e.id


def _patch(monkeypatch, result):
    monkeypatch.setattr(tasks, "recognize_with_retry",
                        lambda *a, **k: result)


def test_success_sets_draft_and_logs(app, monkeypatch):
    eid = _mk(app)
    _patch(monkeypatch, {"fields": {"summary": "全家", "amount": 1290, "category_id": None,
                                    "confidence": 0.9, "is_handwritten": False, "raw": {}},
                         "final_outcome": "success",
                         "attempts": [{"attempt": 1, "outcome": "success", "error_type": None,
                                       "http_status": None, "duration_ms": 50}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is False and float(e.amount) == 1290.0
        assert e.ocr_attempts == 1
        assert OcrLog.query.filter_by(expense_id=eid, outcome="success").count() == 1


def test_fatal_sets_draft_failed(app, monkeypatch):
    eid = _mk(app)
    _patch(monkeypatch, {"fields": None, "final_outcome": "fatal",
                         "attempts": [{"attempt": 1, "outcome": "fatal", "error_type": "schema",
                                       "http_status": None, "duration_ms": 30}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True and e.ocr_last_error == "schema"


def test_exhausted_below_limit_stays_pending(app, monkeypatch):
    eid = _mk(app)
    app.config["OCR_MAX_ROUNDS"] = 3
    _patch(monkeypatch, {"fields": None, "final_outcome": "exhausted",
                         "attempts": [{"attempt": 1, "outcome": "retryable", "error_type": "overloaded",
                                       "http_status": 503, "duration_ms": 40}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr" and e.ocr_failed is False  # 留給背景重排
        assert e.ocr_attempts == 1 and e.ocr_last_error == "overloaded"


def test_exhausted_at_limit_marks_failed(app, monkeypatch):
    eid = _mk(app)
    app.config["OCR_MAX_ROUNDS"] = 1   # 第一輪就達上限
    _patch(monkeypatch, {"fields": None, "final_outcome": "exhausted",
                         "attempts": [{"attempt": 1, "outcome": "retryable", "error_type": "rate_limit",
                                       "http_status": 429, "duration_ms": 40}]})
    tasks._run_ocr(app, eid, b"img", "image/jpeg")
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True
