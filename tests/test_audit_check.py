import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog, Category


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


def test_check_submitted_to_audited(app):
    mgr_id, sub_id, _ = _seed(app)
    c = _client(app, mgr_id)
    r = c.post(f"/audit/{sub_id}/check")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.status == "audited" and e.audited_by == mgr_id
        assert e.audited_at is not None and e.handover_id is None
        from app.models import AuditLog
        assert AuditLog.query.filter_by(expense_id=sub_id, action="check").count() == 1


def test_check_non_submitted_409(app):
    mgr_id, _, aud_id = _seed(app)
    c = _client(app, mgr_id)
    assert c.post(f"/audit/{aud_id}/check").status_code == 409


# ---------- Addendum 10.1：重送標記 resubmitted_at ----------

def test_check_first_time_from_submitted_leaves_resubmitted_at_null(app):
    mgr_id, sub_id, _ = _seed(app)
    c = _client(app, mgr_id)
    r = c.post(f"/audit/{sub_id}/check")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.resubmitted_at is None


def test_check_rejected_resubmit_sets_resubmitted_at(app):
    mgr_id, sub_id, _ = _seed(app)
    c = _client(app, mgr_id)
    # 先打勾一次成為 audited，模擬會計退回，回到 rejected 且 audited_at 已存在
    assert c.post(f"/audit/{sub_id}/check").status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.audited_at is not None
        e.status = "rejected"
        e.reject_reason = "金額有誤"
        db.session.commit()
    # 主管改完重送（第二次 check）
    r = c.post(f"/audit/{sub_id}/check")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, sub_id)
        assert e.status == "audited"
        assert e.reject_reason is None
        assert e.resubmitted_at is not None


def test_check_cross_store_forbidden(app):
    mgr_id, _, _ = _seed(app)
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
    r = c.post(f"/audit/{other_sub_id}/check")
    assert r.status_code == 403
    with app.app_context():
        e = db.session.get(Expense, other_sub_id)
        assert e.status == "submitted" and e.audited_by is None
        assert AuditLog.query.filter_by(expense_id=other_sub_id, action="check").count() == 0


# ---------- M2 回歸：manual 單（audited_at 一律 NULL）被會計退回後，
# 不可透過 /audit/<id>/check 補蓋 audited_at —— 那會讓一筆可能回溯數月的補帳單
# 變成可被下一次交班掃描收編，污染該班現金小計。----------

def test_check_rejected_manual_row_409_and_stays_unswept(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        acct = User(name="acct", role="accountant"); acct.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        cat = Category(name="雜項", level=1)
        db.session.add_all([mgr, acct, dev, cat]); db.session.commit()
        store_id, mgr_id, acct_id = s.id, mgr.id, acct.id

    acct_c = app.test_client()
    with acct_c.session_transaction() as sess:
        sess["user_id"] = acct_id; sess["_last_request_at"] = int(time.time())

    # business_date 用「今天」而非寫死的過去日期：這個測試要驗證的是 check() 對
    # rejected manual 單的 409 閘門，跟 business_date 落在哪個期間無關；寫死日期
    # 會隨真實時鐘走到該期 lock_at 之後被封月讀成 closed，manual() 建單先被period_closed
    # 擋下、測試失真（C1 修好 effective_status 改用時間判斷後才會踩到這個坑）。
    manual = acct_c.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": date.today().isoformat(),
        "summary": "回溯補帳", "amount": 500,
    })
    assert manual.status_code == 200
    manual_id = manual.get_json()["id"]

    reject = acct_c.post(f"/reconcile/{manual_id}/reject", json={"reason": "key 錯"})
    assert reject.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, manual_id)
        assert e.status == "rejected" and e.audited_at is None

    mgr_c = _client(app, mgr_id)
    r = mgr_c.post(f"/audit/{manual_id}/check")
    assert r.status_code == 409

    with app.app_context():
        e = db.session.get(Expense, manual_id)
        assert e.status == "rejected"
        assert e.audited_at is None
        assert e.handover_id is None

    # 之後的交班：不該把這筆 manual/退回單掃進去（沒有其他可結的單 → 400）
    handover = mgr_c.post("/audit/handover", json={"type": "shift"})
    assert handover.status_code == 400
    with app.app_context():
        assert db.session.get(Expense, manual_id).handover_id is None
