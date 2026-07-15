import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User, Device, Category, AccountingPeriod
import app.storage.r2 as r2mod


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        cat = Category(name="食材", level=1, sort=1)
        db.session.add_all([u, dev, cat]); db.session.commit()
        return s.id, u.id, cat.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def _draft(app, sid, uid, **kw):
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="draft",
                    created_at=datetime.now(timezone.utc), **kw)
        db.session.add(e); db.session.commit(); return e.id


def test_submit_assigns_period(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True, category_id=cid)
    c = _client(app, uid)
    assert c.post(f"/expenses/{eid}/submit").get_json()["status"] == "ok"
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.period_id is not None
        p = db.session.get(AccountingPeriod, e.period_id)
        assert p.start_date <= e.business_date <= p.end_date


def test_submit_reuses_existing_period(app):
    """同一期兩筆送出，不該各建一期（period_id 應相同、DB 只多一期）。"""
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    c = _client(app, uid)
    eid1 = _draft(app, sid, uid, amount=50, amount_parse_ok=True, category_id=cid)
    assert c.post(f"/expenses/{eid1}/submit").get_json()["status"] == "ok"
    eid2 = _draft(app, sid, uid, amount=60, amount_parse_ok=True, category_id=cid)
    assert c.post(f"/expenses/{eid2}/submit").get_json()["status"] == "ok"
    with app.app_context():
        e1 = db.session.get(Expense, eid1)
        e2 = db.session.get(Expense, eid2)
        assert e1.period_id == e2.period_id
        assert AccountingPeriod.query.count() == 1
