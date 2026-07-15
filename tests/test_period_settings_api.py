import time
from datetime import date, datetime, timezone, timedelta

import pytest

from app.extensions import db
from app.models import Store, User, Device, AccountingPeriod
from app.periods.service import get_or_create_period

# 登入 helper 照 tests/test_reconcile_close_period.py / tests/test_admin_lists.py 現成寫法。
# 裝置閘（app/auth/gates.py _device_gate）只認 client_uid 是否已核准，
# 跟哪個 user 登入無關，所以整份測試共用一台已核准裝置即可。

DEVICE_UID = "dev-periods"


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
    """建店 + 四種角色 user + 一台已核准裝置。"""
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        mgr = User(name="主管A", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        sa = User(name="業主", role="super_admin")
        sa.set_password("0000")
        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid=DEVICE_UID, store_id=s1.id, is_approved=True)
        db.session.add_all([emp, mgr, sa, acct, dev])
        db.session.commit()
        return {"store": s1.id, "emp": emp.id, "mgr": mgr.id, "sa": sa.id, "acct": acct.id}


# ---------------------------------------------------------------------------
# GET/PATCH /periods/settings
# ---------------------------------------------------------------------------

def test_accountant_can_get_and_patch_settings(client, app, base):
    login_as(client, app, "accountant")
    r = client.get("/periods/settings")
    assert r.status_code == 200
    assert r.get_json()["period_close_day"] == 1  # 預設值（settings.py DEFAULTS）

    r = client.patch("/periods/settings", json={"period_close_day": 5})
    assert r.status_code == 200

    r = client.get("/periods/settings")
    assert r.get_json()["period_close_day"] == 5


def test_super_admin_can_view_but_not_edit(client, app, base):
    # 經理(super_admin)：可觀看設定，但不能改
    login_as(client, app, "super_admin")
    r = client.get("/periods/settings")
    assert r.status_code == 200
    r = client.patch("/periods/settings", json={"period_close_day": 5})
    assert r.status_code == 403


def test_patch_settings_validates_range(client, app, base):
    login_as(client, app, "accountant")
    r = client.patch("/periods/settings", json={"period_close_day": 31})
    assert r.status_code == 400
    assert r.get_json()["message"] == "bad_close_day"

    r = client.patch("/periods/settings", json={"period_close_day": 0})
    assert r.status_code == 400
    assert r.get_json()["message"] == "bad_close_day"


def test_patch_settings_validates_offset_range(client, app, base):
    login_as(client, app, "accountant")
    r = client.patch("/periods/settings", json={"period_lock_offset_hours": 169})
    assert r.status_code == 400
    assert r.get_json()["message"] == "bad_offset"

    r = client.patch("/periods/settings", json={"period_lock_offset_hours": -1})
    assert r.status_code == 400
    assert r.get_json()["message"] == "bad_offset"


def test_settings_forbidden_for_manager_and_employee(client, app, base):
    # 主管(manager)與員工完全看不到
    login_as(client, app, "manager")
    assert client.get("/periods/settings").status_code == 403

    login_as(client, app, "employee")
    assert client.get("/periods/settings").status_code == 403


def test_settings_unauthenticated_401(client, app, base):
    client.set_cookie("device_uid", DEVICE_UID)
    r = client.get("/periods/settings")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /periods/<pid>/end-date
# ---------------------------------------------------------------------------

def _make_period(label, start, end, status="open"):
    offset_days = 1  # lock_at 值本身不是本組測試重點，給個合理值即可
    p = AccountingPeriod(
        label=label, start_date=start, end_date=end,
        lock_at=datetime.now(timezone.utc) + timedelta(days=offset_days),
        status=status,
    )
    db.session.add(p)
    db.session.commit()
    return p


def test_edit_end_date_shifts_existing_next_period(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        feb = _make_period("2026-02", date(2026, 2, 1), date(2026, 2, 28))
        jan_id, feb_id = jan.id, feb.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2026-01-24"})
    assert r.status_code == 200

    with app.app_context():
        jan_after = db.session.get(AccountingPeriod, jan_id)
        feb_after = db.session.get(AccountingPeriod, feb_id)
        assert jan_after.end_date == date(2026, 1, 24)
        assert feb_after.start_date == date(2026, 1, 25)
        assert feb_after.end_date == date(2026, 2, 28)  # 沒被亂動


def test_edit_end_date_creates_next_period_when_absent(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        jan_id = jan.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2026-01-24"})
    assert r.status_code == 200

    with app.app_context():
        jan_after = db.session.get(AccountingPeriod, jan_id)
        assert jan_after.end_date == date(2026, 1, 24)

        nxt = get_or_create_period(date(2026, 1, 25))
        assert nxt.label == "2026-02"
        assert nxt.start_date == date(2026, 1, 25)
        assert nxt.end_date == date(2026, 2, 28)
        assert nxt.id != jan_id  # 確實是新建的一期，不是原期被誤更新


def test_edit_end_date_404_when_missing(client, app, base):
    login_as(client, app, "accountant")
    r = client.patch("/periods/999999/end-date", json={"end_date": "2026-01-24"})
    assert r.status_code == 404


def test_edit_end_date_409_when_period_closed(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31), status="closed")
        jan_id = jan.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2026-01-24"})
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"


def test_edit_end_date_400_bad_date(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        jan_id = jan.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "not-a-date"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "bad_date"


def test_edit_end_date_400_end_before_start(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        jan_id = jan.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2025-12-31"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "end_before_start"


def test_edit_end_date_409_when_next_period_closed(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        feb = _make_period("2026-02", date(2026, 2, 1), date(2026, 2, 28), status="closed")
        jan_id, feb_id = jan.id, feb.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2026-01-24"})
    assert r.status_code == 409
    assert r.get_json()["message"] == "next_period_closed"

    with app.app_context():
        # rollback 保證：jan/feb 都沒被半套更新
        jan_after = db.session.get(AccountingPeriod, jan_id)
        feb_after = db.session.get(AccountingPeriod, feb_id)
        assert jan_after.end_date == date(2026, 1, 31)
        assert feb_after.start_date == date(2026, 2, 1)


def test_edit_end_date_400_would_invert_next(client, app, base):
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        # feb 只有 2/1 一天：把 jan.end_date 往後拉到 2/1 之後會讓 feb 反轉（start>end）
        feb = _make_period("2026-02", date(2026, 2, 1), date(2026, 2, 1))
        jan_id, feb_id = jan.id, feb.id

    login_as(client, app, "accountant")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2026-02-05"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "would_invert_next"

    with app.app_context():
        jan_after = db.session.get(AccountingPeriod, jan_id)
        feb_after = db.session.get(AccountingPeriod, feb_id)
        assert jan_after.end_date == date(2026, 1, 31)
        assert feb_after.start_date == date(2026, 2, 1)


def test_edit_end_date_forbidden_for_super_admin(client, app, base):
    # 經理唯讀：連改期都不能碰
    with app.app_context():
        jan = _make_period("2026-01", date(2026, 1, 1), date(2026, 1, 31))
        jan_id = jan.id

    login_as(client, app, "super_admin")
    r = client.patch(f"/periods/{jan_id}/end-date", json={"end_date": "2026-01-24"})
    assert r.status_code == 403
