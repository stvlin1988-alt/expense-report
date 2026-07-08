from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Expense, OcrLog


def test_ocr_log_and_expense_fields(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()

        # 新欄位預設
        assert db.session.get(Expense, e.id).ocr_attempts == 0
        assert db.session.get(Expense, e.id).ocr_failed is False

        e.ocr_attempts = 2; e.ocr_failed = True; e.ocr_last_error = "overloaded"
        log = OcrLog(expense_id=e.id, store_id=s.id, attempt=1, outcome="retryable",
                     error_type="overloaded", http_status=503, duration_ms=120,
                     ts=datetime.now(timezone.utc))
        db.session.add(log); db.session.commit()

        assert OcrLog.query.filter_by(expense_id=e.id, outcome="retryable").count() == 1
        assert db.session.get(Expense, e.id).ocr_last_error == "overloaded"
