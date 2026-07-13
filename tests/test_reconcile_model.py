from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A")
        db.session.add(s); db.session.commit()
        u = User(name="員工", role="employee", store_id=s.id)
        db.session.add(u); db.session.commit()
        return s.id, u.id


def test_expense_has_reconcile_fields(app):
    sid, uid = _seed(app)
    with app.app_context():
        e = Expense(
            store_id=sid, created_by=uid, status="reconciled",
            created_at=datetime.now(timezone.utc),
            reconciled_by=uid, reconciled_at=datetime.now(timezone.utc),
            reject_reason=None, note="老闆交代的",
        )
        db.session.add(e); db.session.commit()
        got = db.session.get(Expense, e.id)
        assert got.status == "reconciled"
        assert got.reconciled_by == uid
        assert got.note == "老闆交代的"


def test_statuses_include_reconciled_and_rejected():
    assert "reconciled" in Expense.STATUSES
    assert "rejected" in Expense.STATUSES
