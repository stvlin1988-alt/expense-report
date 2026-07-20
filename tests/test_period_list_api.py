import time
from datetime import date, datetime, timezone, timedelta

import pytest

from app.extensions import db
from app.models import Store, User, Device, AccountingPeriod

# 登入 / 裝置閘 helper 照 tests/test_period_settings_api.py 現成寫法。
DEVICE_UID = "dev-periods-list"


def _set_session(client, uid):
    client.set_cookie("device_uid", DEVICE_UID)
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_as(client, app, role):
    with app.app_context():
        uid = User.query.filter_by(role=role).first().id
    _set_session(client, uid)


@pytest.fixture
def base(app):
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()
        emp = User(name="員工A", role="employee", store_id=s1.id); emp.set_password("0000")
        mgr = User(name="主管A", role="manager", store_id=s1.id); mgr.set_password("0000")
        sa = User(name="業主", role="super_admin"); sa.set_password("0000")
        acct = User(name="會計", role="accountant"); acct.set_password("0000")
        dev = Device(client_uid=DEVICE_UID, store_id=s1.id, is_approved=True)
        db.session.add_all([emp, mgr, sa, acct, dev])
        db.session.commit()
        return {"store": s1.id}


def _make_period(label, start, end, status="open"):
    p = AccountingPeriod(
        label=label, start_date=start, end_date=end,
        lock_at=datetime.now(timezone.utc) + timedelta(days=1),
        status=status,
    )
    db.session.add(p)
    db.session.commit()
    return p


def _seed_three(app):
    with app.app_context():
        _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31), status="closed")
        _make_period("2026-02", date(2026, 2, 1), date(2026, 2, 28))
        _make_period("2026-03", date(2026, 3, 1), date(2026, 3, 31))


def test_accountant_lists_periods_newest_first(client, app, base):
    _seed_three(app)
    login_as(client, app, "accountant")
    r = client.get("/periods/")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    labels = [p["label"] for p in data["periods"]]
    assert labels == ["2026-03", "2026-02", "2026-01"]  # start_date desc
    # 每筆帶 id / label / status / 起訖日
    first = data["periods"][0]
    assert set(first) >= {"id", "label", "status", "start_date", "end_date"}
    assert first["start_date"] == "2026-03-01"
    # 已封月的那期 effective status 為 closed
    jan = [p for p in data["periods"] if p["label"] == "2026-01"][0]
    assert jan["status"] == "closed"


def test_super_admin_can_view(client, app, base):
    _seed_three(app)
    login_as(client, app, "super_admin")
    assert client.get("/periods/").status_code == 200


def test_manager_and_employee_forbidden(client, app, base):
    login_as(client, app, "manager")
    assert client.get("/periods/").status_code == 403
    login_as(client, app, "employee")
    assert client.get("/periods/").status_code == 403


def test_unauthenticated_401(client, app, base):
    client.set_cookie("device_uid", DEVICE_UID)
    assert client.get("/periods/").status_code == 401


def test_empty_when_no_periods(client, app, base):
    login_as(client, app, "accountant")
    r = client.get("/periods/")
    assert r.status_code == 200
    assert r.get_json()["periods"] == []
