import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog

# 登入/建單 helper 照 tests/test_audit_edit.py 現成寫法


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
        db.session.add(sub); db.session.commit()
        return mgr.id, sub.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_manager_can_edit_note(app):
    mgr_id, sub_id = _seed(app)
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"note": "主管補充"})
    assert r.status_code == 200
    r2 = c.get("/audit/pending")
    item = r2.get_json()["groups"][0]["items"][0]
    assert item["note"] == "主管補充"


def test_note_edit_writes_audit_log(app):
    mgr_id, sub_id = _seed(app)
    c = _client(app, mgr_id)
    c.patch(f"/audit/{sub_id}", json={"note": "主管補充"})
    r = c.get(f"/expenses/{sub_id}/logs")
    actions = [x["action"] for x in r.get_json()["logs"]]
    assert "edit" in actions


def test_note_too_long_400(app):
    mgr_id, sub_id = _seed(app)
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"note": "x" * 201})
    assert r.status_code == 400
    assert r.get_json()["message"] == "note_too_long"


def test_note_whitespace_only_stores_null(app):
    mgr_id, sub_id = _seed(app)
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"note": "   "})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.note is None


def test_note_only_edit_does_not_flag_manager_modified(app):
    """備註改動不算「主管改過金額/分類」——不該讓 is_modified_by_manager 被誤設為 True，
    不然主管稽核清單上的「主管改」標籤/燈號會被備註改動誤觸發。"""
    mgr_id, sub_id = _seed(app)
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"note": "只改備註"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.is_modified_by_manager is False
        assert e.last_modified_fields is None
    r2 = c.get("/audit/pending")
    item = r2.get_json()["groups"][0]["items"][0]
    assert item["is_modified_by_manager"] is False
