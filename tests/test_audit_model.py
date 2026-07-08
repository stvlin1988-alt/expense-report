from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Category, Expense, Handover, AuditLog


def test_models_and_expense_fields(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="mgr", role="manager", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        now = datetime.now(timezone.utc)
        e = Expense(store_id=s.id, created_by=u.id, status="submitted", created_at=now)
        db.session.add(e); db.session.commit()

        # 稽核欄位可寫
        e.audited_by = u.id; e.audited_at = now; e.is_modified_by_manager = True
        h = Handover(store_id=s.id, closed_at=now, closed_by=u.id, type="shift")
        db.session.add(h); db.session.commit()
        e.handover_id = h.id; db.session.commit()

        log = AuditLog(expense_id=e.id, actor_user_id=u.id, action="edit",
                       before_json={"amount": None, "category_id": None},
                       after_json={"amount": 100.0, "category_id": None}, ts=now)
        db.session.add(log); db.session.commit()

        assert "audited" in Expense.STATUSES
        assert Handover.query.count() == 1
        assert AuditLog.query.filter_by(action="edit").count() == 1
        assert db.session.get(Expense, e.id).handover_id == h.id
