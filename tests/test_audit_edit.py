import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, emp, dev]); db.session.commit()
        now = datetime.now(timezone.utc)
        sub = Expense(store_id=s.id, created_by=emp.id, status="submitted", created_at=now,
                      business_date=date(2026, 7, 7), amount=Decimal("100"), submitted_at=now)
        aud = Expense(store_id=s.id, created_by=emp.id, status="audited", created_at=now,
                      amount=Decimal("80"))
        db.session.add_all([sub, aud]); db.session.commit()
        return mgr.id, sub.id, aud.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_manager_edit_submitted(app):
    mgr_id, sub_id, _ = _seed(app)
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"amount": "120"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert float(e.amount) == 120.0 and e.is_modified_by_manager is True
        assert AuditLog.query.filter_by(expense_id=sub_id, action="edit").count() == 1


def test_manager_edit_audited_locked_409(app):
    mgr_id, _, aud_id = _seed(app)
    c = _client(app, mgr_id)
    assert c.patch(f"/audit/{aud_id}", json={"amount": "1"}).status_code == 409
