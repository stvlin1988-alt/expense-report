import time
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog, AccountingPeriod


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


def test_manager_edit_blocked_when_period_closed(app):
    """I2 回歸：audit.edit（主管改 submitted/rejected 單的金額/分類/備註）先前沒有封月閘，
    會計核銷用的是同一套 is_period_closed 閘門（見 check()），edit 卻漏了——主管可以在封月後
    繼續改一筆凍結在已封月期間裡的 submitted 單，違反 §5.4/§7 永久唯讀。"""
    mgr_id, sub_id, _ = _seed(app)
    with app.app_context():
        closed_period = AccountingPeriod(
            label="closed", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            lock_at=datetime(2026, 2, 2, 4, 0, tzinfo=timezone.utc), status="closed")
        db.session.add(closed_period)
        db.session.commit()
        e = db.session.get(Expense, sub_id)
        e.period_id = closed_period.id
        db.session.commit()
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"amount": "999"})
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert float(e.amount) == 100.0            # 沒被改
        assert e.is_modified_by_manager is False
        assert AuditLog.query.filter_by(expense_id=sub_id, action="edit").count() == 0


def test_manager_edit_open_period_still_works(app):
    """控制組：同樣的 edit 端點，期間還沒鎖時仍要能正常改（確保 I2 的閘沒有誤擋）。"""
    mgr_id, sub_id, _ = _seed(app)
    with app.app_context():
        open_period = AccountingPeriod(
            label="open", start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
            lock_at=datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc), status="open")
        db.session.add(open_period)
        db.session.commit()
        e = db.session.get(Expense, sub_id)
        e.period_id = open_period.id
        db.session.commit()
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{sub_id}", json={"amount": "120"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert float(e.amount) == 120.0 and e.is_modified_by_manager is True


def test_manager_edit_cross_store_forbidden(app):
    mgr_id, sub_id, _ = _seed(app)
    with app.app_context():
        other = Store(name="B", code="B"); db.session.add(other); db.session.commit()
        other_emp = User(name="emp2", role="employee", store_id=other.id)
        other_emp.set_password("1234")
        db.session.add(other_emp); db.session.commit()
        other_sub = Expense(store_id=other.id, created_by=other_emp.id, status="submitted",
                            created_at=datetime.now(timezone.utc),
                            business_date=date(2026, 7, 7), amount=Decimal("50"))
        db.session.add(other_sub); db.session.commit()
        other_sub_id = other_sub.id
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{other_sub_id}", json={"amount": "1"})
    assert r.status_code == 403
    with app.app_context():
        e = db.session.get(Expense, other_sub_id)
        assert float(e.amount) == 50.0 and e.is_modified_by_manager is False
