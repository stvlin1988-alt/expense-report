import time
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog

# 登入/建單 helper 照 tests/test_reconcile_list.py 現成寫法


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_accountant(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="accountant").first().id
    _set_session(client, uid)


@pytest.fixture
def seeded(app):
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

        now = datetime.now(timezone.utc)
        audited = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                           created_at=now, business_date=date(2026, 7, 7),
                           amount=Decimal("200"), amount_parse_ok=True, submitted_at=now)
        submitted = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                             created_at=now, business_date=date(2026, 7, 7),
                             amount=Decimal("50"), amount_parse_ok=True, submitted_at=now)
        db.session.add_all([audited, submitted])
        db.session.commit()
        result = {"audited_id": audited.id, "submitted_id": submitted.id}
    return result


@pytest.fixture
def audited_id(seeded):
    return seeded["audited_id"]


@pytest.fixture
def submitted_id(seeded):
    return seeded["submitted_id"]


def test_approve_audited(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.status == "reconciled"
        assert e.reconciled_by is not None
        assert e.reconciled_at is not None


def test_approve_twice_is_conflict(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/approve")
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_reconcilable"


def test_cannot_approve_submitted(client, app, submitted_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{submitted_id}/approve")
    assert r.status_code == 409


def test_approve_nonexistent_404(client, app, audited_id):
    login_accountant(client, app)
    r = client.post("/reconcile/999999/approve")
    assert r.status_code == 404


def test_approve_writes_log(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/approve")
    with app.app_context():
        actions = [l.action for l in AuditLog.query.filter_by(expense_id=audited_id).all()]
        assert "reconcile" in actions


def test_batch_approve_partial(client, app, audited_id, submitted_id):
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": [audited_id, submitted_id]})
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == [submitted_id]


def test_batch_approve_non_int_id_skipped_not_500(client, app, audited_id):
    # brief 原碼把 ids 元素直接丟進 db.session.get(Expense, eid)；
    # 非整數（如 "abc"）在 Postgres 上會炸 DataError → 500。
    # 這裡要求：不可 500，非整數的元素進 skipped，不能悄悄從回應消失。
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": ["abc", audited_id]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == ["abc"]


def test_batch_approve_null_id_skipped_not_500(client, app, audited_id):
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": [None, audited_id]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == [None]


def test_unauthenticated_401(client, app, audited_id):
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 401
