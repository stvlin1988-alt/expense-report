import time
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        other_emp = User(name="emp2", role="employee", store_id=s.id); other_emp.set_password("1234")
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        sup = User(name="sup", role="super_admin", store_id=s.id); sup.set_password("1234")
        db.session.add_all([emp, other_emp, mgr, sup]); db.session.commit()
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add(dev); db.session.commit()
        now = datetime.now(timezone.utc)
        e = Expense(store_id=s.id, created_by=emp.id, status="draft",
                    created_at=now, amount=Decimal("100"))
        db.session.add(e); db.session.commit()
        db.session.add_all([
            AuditLog(expense_id=e.id, actor_user_id=emp.id, action="edit",
                     before_json={"amount": 100.0, "category_id": None},
                     after_json={"amount": 120.0, "category_id": None}, ts=now),
            AuditLog(expense_id=e.id, actor_user_id=mgr.id, action="check",
                     before_json=None, after_json={"status": "audited"}, ts=now),
        ])
        db.session.commit()
        return {"store": s.id, "emp": emp.id, "other": other_emp.id,
                "mgr": mgr.id, "sup": sup.id, "eid": e.id}


def _client(app, uid, uid_cookie="dev1"):
    c = app.test_client(); c.set_cookie("device_uid", uid_cookie)
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_owner_sees_logs(app):
    ids = _seed(app)
    c = _client(app, ids["emp"])
    r = c.get(f"/expenses/{ids['eid']}/logs")
    assert r.status_code == 200
    logs = r.get_json()["logs"]
    assert [l["action"] for l in logs] == ["edit", "check"]     # ts 升冪
    assert logs[0]["actor_name"] == "emp" and logs[1]["actor_name"] == "mgr"


def test_same_store_manager_sees_logs(app):
    ids = _seed(app)
    assert _client(app, ids["mgr"]).get(f"/expenses/{ids['eid']}/logs").status_code == 200


def test_super_admin_sees_logs(app):
    ids = _seed(app)
    assert _client(app, ids["sup"]).get(f"/expenses/{ids['eid']}/logs").status_code == 200


def test_other_employee_forbidden(app):
    ids = _seed(app)
    assert _client(app, ids["other"]).get(f"/expenses/{ids['eid']}/logs").status_code == 403


def test_cross_store_manager_forbidden(app):
    ids = _seed(app)
    with app.app_context():
        s2 = Store(name="B", code="B"); db.session.add(s2); db.session.commit()
        m2 = User(name="m2", role="manager", store_id=s2.id); m2.set_password("1234")
        db.session.add(m2); db.session.commit()
        d2 = Device(client_uid="dev2", store_id=s2.id, is_approved=True)
        db.session.add(d2); db.session.commit()
        m2_id = m2.id
    c = _client(app, m2_id, uid_cookie="dev2")
    assert c.get(f"/expenses/{ids['eid']}/logs").status_code == 403


def test_missing_404(app):
    ids = _seed(app)
    assert _client(app, ids["emp"]).get("/expenses/999999/logs").status_code == 404
