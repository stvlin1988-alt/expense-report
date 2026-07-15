import time
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, AccountingPeriod

# 登入 helper 照 tests/test_reconcile_approve.py / tests/test_period_gate.py 現成寫法


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_as(client, app, role):
    with app.app_context():
        uid = User.query.filter_by(role=role).first().id
    _set_session(client, uid)


@pytest.fixture
def grace_period(app):
    """已結束但未鎖（寬限期 closing）的期：end_date 在過去、lock_at 在未來。
    端點用 datetime.now()，故用相對「今天」的日期建期，不能用固定 2026 年日期。
    含 2 筆 submitted + 1 筆 audited。"""
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        db.session.add_all([emp, acct, dev])
        db.session.commit()

        today = date.today()
        end_date = today - timedelta(days=1)          # 已結束
        start_date = end_date - timedelta(days=29)
        lock_at = datetime.now(timezone.utc) + timedelta(days=2)   # 還沒到自動封月

        p = AccountingPeriod(label="grace", start_date=start_date, end_date=end_date,
                              lock_at=lock_at, status="open")
        db.session.add(p)
        db.session.commit()

        now = datetime.now(timezone.utc)
        sub1 = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                        created_at=now, business_date=end_date, period_id=p.id,
                        amount=Decimal("50"), amount_parse_ok=True, submitted_at=now)
        sub2 = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                        created_at=now, business_date=end_date, period_id=p.id,
                        amount=Decimal("60"), amount_parse_ok=True, submitted_at=now)
        audited = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                           created_at=now, business_date=end_date, period_id=p.id,
                           amount=Decimal("200"), amount_parse_ok=True, submitted_at=now)
        db.session.add_all([sub1, sub2, audited])
        db.session.commit()
        result = {
            "period_id": p.id,
            "sub1_id": sub1.id,
            "sub2_id": sub2.id,
            "audited_id": audited.id,
        }
    return result


def test_close_preview_counts_unaudited(client, app, grace_period):
    login_as(client, app, "accountant")
    r = client.get(f"/reconcile/period/{grace_period['period_id']}/close-preview")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["unaudited_count"] == 2
    assert body["label"] == "grace"


def test_close_preview_nonexistent_404(client, app, grace_period):
    login_as(client, app, "accountant")
    r = client.get("/reconcile/period/999999/close-preview")
    assert r.status_code == 404


def test_manual_close_moves_audited_leaves_submitted(client, app, grace_period):
    login_as(client, app, "accountant")
    r = client.post(f"/reconcile/period/{grace_period['period_id']}/close")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        p = db.session.get(AccountingPeriod, grace_period["period_id"])
        assert p.status == "closed"
        assert p.closed_by is not None

        sub1 = db.session.get(Expense, grace_period["sub1_id"])
        sub2 = db.session.get(Expense, grace_period["sub2_id"])
        audited = db.session.get(Expense, grace_period["audited_id"])
        assert sub1.period_id == p.id             # submitted 留原期
        assert sub2.period_id == p.id
        assert audited.period_id != p.id           # audited 挪到下一期

        acct = User.query.filter_by(role="accountant").first()
        assert p.closed_by == acct.id


def test_cannot_close_open_period(client, app, grace_period):
    # 進行中（open）的當期 → 409 period_not_ended（提早鎖要先調 end_date）
    login_as(client, app, "accountant")
    with app.app_context():
        from app.periods.service import get_or_create_period
        from app.expenses.logic import compute_business_date
        p = get_or_create_period(compute_business_date(datetime.now(timezone.utc)))
        db.session.commit()
        pid = p.id
    r = client.post(f"/reconcile/period/{pid}/close")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_not_ended"
    with app.app_context():
        p = db.session.get(AccountingPeriod, pid)
        assert p.status == "open"


def test_manual_close_already_closed(client, app, grace_period):
    login_as(client, app, "accountant")
    with app.app_context():
        p = db.session.get(AccountingPeriod, grace_period["period_id"])
        p.status = "closed"
        db.session.commit()
    r = client.post(f"/reconcile/period/{grace_period['period_id']}/close")
    assert r.status_code == 409
    assert r.get_json()["message"] == "already_closed"


def test_close_nonexistent_404(client, app, grace_period):
    login_as(client, app, "accountant")
    r = client.post("/reconcile/period/999999/close")
    assert r.status_code == 404


def test_close_requires_accountant_role(client, app, grace_period):
    login_as(client, app, "employee")
    r = client.post(f"/reconcile/period/{grace_period['period_id']}/close")
    assert r.status_code == 403
