import time
from app.extensions import db
from app.models import Expense, Store, User, Device


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        return s.id, u.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_no_receipt_creates_submitted(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    resp = c.post("/expenses/no-receipt",
                  json={"summary": "計程車", "amount": 250, "reason": "臨時叫車無收據"})
    assert resp.status_code == 200
    eid = resp.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "submitted"
        assert e.image_key is None
        assert e.no_receipt_reason == "臨時叫車無收據"
        assert e.business_date is not None
        assert float(e.amount) == 250.0


def test_no_receipt_requires_reason(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"summary": "x", "amount": 1})
    assert r.status_code == 400


def test_no_receipt_requires_amount(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"summary": "x", "reason": "y"})
    assert r.status_code == 400
