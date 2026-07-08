from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        db.session.add(u); db.session.commit()
        return s.id, u.id


def test_expense_defaults(app):
    sid, uid = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="pending_ocr",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        got = db.session.get(Expense, e.id)
        assert got.status == "pending_ocr"
        assert got.currency == "TWD"
        assert got.is_modified_by_user is False
        assert got.amount is None and got.summary is None
        assert got.business_date is None


def test_expense_status_constants():
    assert Expense.STATUSES == ("pending_ocr", "draft", "submitted", "audited")
