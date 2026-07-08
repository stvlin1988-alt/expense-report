import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="emp", role="employee", store_id=s.id); u.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        e = Expense(store_id=s.id, created_by=None, status="draft",
                    created_at=datetime.now(timezone.utc))
        db.session.add_all([u, dev]); db.session.commit()
        e.created_by = u.id; db.session.add(e); db.session.commit()
        return u.id, e.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_employee_patch_amount_writes_edit_log(app):
    uid, eid = _seed(app)
    c = _client(app, uid)
    r = c.patch(f"/expenses/{eid}", json={"amount": "300"})
    assert r.status_code == 200
    with app.app_context():
        logs = AuditLog.query.filter_by(expense_id=eid, action="edit").all()
        assert len(logs) == 1
        assert logs[0].actor_user_id == uid
        assert logs[0].after_json["amount"] == 300.0


def test_employee_patch_summary_only_no_log(app):
    uid, eid = _seed(app)
    c = _client(app, uid)
    c.patch(f"/expenses/{eid}", json={"summary": "改摘要"})
    with app.app_context():
        assert AuditLog.query.filter_by(expense_id=eid).count() == 0
