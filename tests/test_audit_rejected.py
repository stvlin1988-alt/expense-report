import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense
import pytest


@pytest.fixture
def rejected_expense_id(app):
    """Create a rejected expense in app context.
    這是「正常員工單」的退回情境：audited（主管打勾，蓋 audited_at）→ 會計退回（rejected）。
    audited_at 必須確實有值，才能跟「會計 manual 單被退回」（audited_at 永遠 NULL）區分
    ——M2：/audit/<id>/check 現在用 audited_at is not None 判斷 rejected 單能不能再被打勾。"""
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A")
        db.session.add(s)
        db.session.commit()
        emp = User(name="emp", role="employee", store_id=s.id)
        emp.set_password("1234")
        first_mgr = User(name="mgr0", role="manager", store_id=s.id)
        first_mgr.set_password("1234")
        db.session.add_all([emp, first_mgr])
        db.session.commit()
        now = datetime.now(timezone.utc)
        e = Expense(
            store_id=s.id,
            created_by=emp.id,
            status="rejected",
            reject_reason="金額與照片不符",
            created_at=now,
            business_date=date(2026, 7, 7),
            amount=Decimal("100"),
            submitted_at=now,
            audited_by=first_mgr.id,
            audited_at=now,
        )
        db.session.add(e)
        db.session.commit()
        eid = e.id
    return eid


def _seed_manager(app, rejected_id):
    """Setup manager and device after rejected expense created"""
    with app.app_context():
        s = db.session.query(Store).first()
        mgr = User(name="mgr", role="manager", store_id=s.id)
        mgr.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, dev])
        db.session.commit()
        return mgr.id


def _client(app, uid):
    c = app.test_client()
    c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())
    return c


def test_rejected_shows_in_pending(app, rejected_expense_id):
    mgr_id = _seed_manager(app, rejected_expense_id)
    c = _client(app, mgr_id)
    r = c.get("/audit/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    hit = [i for i in items if i["id"] == rejected_expense_id]
    assert hit and hit[0]["is_rejected"] is True
    assert hit[0]["reject_reason"] == "金額與照片不符"


def test_manager_recheck_clears_reject(app, rejected_expense_id):
    mgr_id = _seed_manager(app, rejected_expense_id)
    c = _client(app, mgr_id)
    r = c.post(f"/audit/{rejected_expense_id}/check")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, rejected_expense_id)
        assert e.status == "audited"
        assert e.reject_reason is None
