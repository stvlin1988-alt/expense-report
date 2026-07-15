import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog, AccountingPeriod
from app.periods.service import get_or_create_period

# 登入/建單 helper 照 tests/test_reconcile_approve.py 現成寫法


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

        # 建當期期間（jan），單掛在這期
        jan = get_or_create_period(date(2026, 1, 15))
        db.session.commit()

        now = datetime.now(timezone.utc)
        audited = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                           created_at=now, business_date=date(2026, 1, 15),
                           amount=Decimal("200"), amount_parse_ok=True, submitted_at=now,
                           period_id=jan.id)
        no_period = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                             created_at=now, business_date=date(2026, 1, 15),
                             amount=Decimal("90"), amount_parse_ok=True, submitted_at=now,
                             period_id=None)
        db.session.add_all([audited, no_period])
        db.session.commit()
        result = {
            "audited_id": audited.id,
            "no_period_id": no_period.id,
            "jan_id": jan.id,
            "jan_end": jan.end_date,
        }
    return result


@pytest.fixture
def audited_id(seeded):
    return seeded["audited_id"]


def test_move_next_changes_period(client, app, seeded):
    login_accountant(client, app)
    eid = seeded["audited_id"]
    jan_id = seeded["jan_id"]

    with app.app_context():
        feb = get_or_create_period(seeded["jan_end"] + timedelta(days=1))
        db.session.commit()
        feb_id = feb.id
        feb_label = feb.label

    r = client.post(f"/reconcile/{eid}/move-next")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["period_id"] == feb_id
    assert body["period_label"] == feb_label

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.period_id == feb_id
        assert e.period_id != jan_id

        logs = AuditLog.query.filter_by(expense_id=eid, action="move_period").all()
        assert len(logs) == 1
        assert logs[0].before_json == {"period_id": jan_id}
        assert logs[0].after_json == {"period_id": feb_id}
        assert logs[0].actor_user_id is not None


def test_move_next_rejected_when_next_closed(client, app, seeded):
    login_accountant(client, app)
    eid = seeded["audited_id"]
    jan_id = seeded["jan_id"]

    with app.app_context():
        feb = get_or_create_period(seeded["jan_end"] + timedelta(days=1))
        feb.status = "closed"
        db.session.commit()

    r = client.post(f"/reconcile/{eid}/move-next")
    assert r.status_code == 409
    assert r.get_json()["message"] == "next_period_closed"

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.period_id == jan_id  # 沒被改動
        logs = AuditLog.query.filter_by(expense_id=eid, action="move_period").all()
        assert logs == []


def test_move_next_no_period_409(client, app, seeded):
    login_accountant(client, app)
    eid = seeded["no_period_id"]

    r = client.post(f"/reconcile/{eid}/move-next")
    assert r.status_code == 409
    assert r.get_json()["message"] == "no_period"


def test_move_next_current_period_closed_409(client, app, seeded):
    login_accountant(client, app)
    eid = seeded["audited_id"]
    jan_id = seeded["jan_id"]

    with app.app_context():
        jan = db.session.get(AccountingPeriod, jan_id)
        jan.status = "closed"
        db.session.commit()

    r = client.post(f"/reconcile/{eid}/move-next")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.period_id == jan_id


def test_move_next_nonexistent_404(client, app, seeded):
    login_accountant(client, app)
    r = client.post("/reconcile/999999/move-next")
    assert r.status_code == 404


def test_move_next_unauthenticated_401(client, app, seeded):
    eid = seeded["audited_id"]
    r = client.post(f"/reconcile/{eid}/move-next")
    assert r.status_code == 401
