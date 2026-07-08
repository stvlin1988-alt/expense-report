import time
from datetime import datetime, timezone, date
from app.extensions import db
from app.models import Store, User, Device, Expense


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); s2 = Store(name="B", code="B")
        db.session.add_all([s, s2]); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, emp, dev]); db.session.commit()
        now = datetime.now(timezone.utc)
        from decimal import Decimal
        e1 = Expense(store_id=s.id, created_by=emp.id, status="submitted", created_at=now,
                     business_date=date(2026, 7, 7), amount=Decimal("100"), submitted_at=now)
        e2 = Expense(store_id=s.id, created_by=emp.id, status="submitted", created_at=now,
                     business_date=date(2026, 7, 7), amount=Decimal("50"), submitted_at=now)
        other = Expense(store_id=s2.id, created_by=emp.id, status="submitted", created_at=now,
                        business_date=date(2026, 7, 7), amount=Decimal("999"), submitted_at=now)
        db.session.add_all([e1, e2, other]); db.session.commit()
        return mgr.id, s.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_pending_groups_by_business_date_with_subtotal(app):
    mgr_id, sid = _seed(app)
    c = _client(app, mgr_id)
    body = c.get("/audit/pending").get_json()
    assert body["status"] == "ok"
    assert len(body["groups"]) == 1
    g = body["groups"][0]
    assert g["business_date"] == "2026-07-07"
    assert g["subtotal"] == 150.0            # 只含本店（100+50），不含他店 999
    assert len(g["items"]) == 2


def test_pending_requires_manager(app):
    _seed(app)
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    assert c.get("/audit/pending").status_code == 401
