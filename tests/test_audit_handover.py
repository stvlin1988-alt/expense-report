import time
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, emp, dev]); db.session.commit()
        now = datetime.now(timezone.utc)

        def mk(status, amt):
            return Expense(store_id=s.id, created_by=emp.id, status=status,
                           created_at=now, amount=Decimal(str(amt)))
        a1 = mk("audited", 100); a2 = mk("audited", 50); sub = mk("submitted", 999)
        db.session.add_all([a1, a2, sub]); db.session.commit()
        return mgr.id, s.id, a1.id, a2.id, sub.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_handover_stamps_audited_open_only(app):
    mgr_id, sid, a1, a2, sub = _seed(app)
    c = _client(app, mgr_id)
    r = c.post("/audit/handover", json={"type": "shift"}).get_json()
    assert r["status"] == "ok" and r["count"] == 2 and r["type"] == "shift"
    with app.app_context():
        h = Handover.query.one()
        assert db.session.get(Expense, a1).handover_id == h.id
        assert db.session.get(Expense, a2).handover_id == h.id
        assert db.session.get(Expense, sub).handover_id is None  # submitted 不歸班


def test_empty_handover_400(app):
    mgr_id, sid, a1, a2, sub = _seed(app)
    c = _client(app, mgr_id)
    c.post("/audit/handover", json={"type": "shift"})       # 先歸掉 a1/a2
    assert c.post("/audit/handover", json={"type": "shift"}).status_code == 400


def test_undo_reopens_last(app):
    mgr_id, sid, a1, a2, sub = _seed(app)
    c = _client(app, mgr_id)
    c.post("/audit/handover", json={"type": "shift"})
    r = c.post("/audit/handover/undo", json={}).get_json()
    assert r["status"] == "ok" and r["reopened"] == 2
    with app.app_context():
        assert Handover.query.count() == 0
        assert db.session.get(Expense, a1).handover_id is None
