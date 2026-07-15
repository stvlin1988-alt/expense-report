import time
from datetime import datetime, timezone, date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Store, User, Device, Expense, Category
from app.periods.service import get_or_create_period


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def _login(client, app, role):
    with app.app_context():
        uid = User.query.filter_by(role=role).first().id
    _set_session(client, uid)


@pytest.fixture
def two_store_two_major(app):
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        s2 = Store(name="B店", code="B")
        db.session.add_all([s1, s2])
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        acct = User(name="會計", role="accountant")
        acct.set_password("0000")
        sup = User(name="經理", role="super_admin")
        sup.set_password("0000")
        mgr = User(name="主管A", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        db.session.add_all([emp, acct, sup, mgr, dev])
        db.session.commit()

        water = Category(name="水電瓦斯", level=1, sort=1)
        db.session.add(water)
        db.session.commit()
        water_bill = Category(name="水費", level=2, parent_id=water.id, sort=1)
        food = Category(name="餐飲", level=1, sort=2)
        db.session.add_all([water_bill, food])
        db.session.commit()

        bd = date(2026, 7, 7)
        period = get_or_create_period(bd)
        db.session.commit()

        now = datetime.now(timezone.utc)
        e1 = Expense(store_id=s1.id, created_by=emp.id, status="reconciled",
                     created_at=now, business_date=bd, period_id=period.id,
                     category_id=water_bill.id, amount=Decimal("300"),
                     amount_parse_ok=True, submitted_at=now)
        e2 = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                     created_at=now, business_date=bd, period_id=period.id,
                     category_id=water.id, amount=Decimal("-50"),
                     amount_parse_ok=True, submitted_at=now)
        e3 = Expense(store_id=s2.id, created_by=emp.id, status="reconciled",
                     created_at=now, business_date=bd, period_id=period.id,
                     category_id=food.id, amount=Decimal("120"),
                     amount_parse_ok=True, submitted_at=now)
        e4 = Expense(store_id=s2.id, created_by=emp.id, status="rejected",
                     created_at=now, business_date=bd, period_id=period.id,
                     category_id=food.id, amount=Decimal("-20"),
                     amount_parse_ok=True, submitted_at=now)
        # submitted 不應進報表
        e5 = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                     created_at=now, business_date=bd, period_id=period.id,
                     category_id=food.id, amount=Decimal("999"),
                     amount_parse_ok=True, submitted_at=now)
        db.session.add_all([e1, e2, e3, e4, e5])
        db.session.commit()
        result = {"period_id": period.id, "store_ids": [s1.id, s2.id]}
    return result


def test_accountant_sees_correct_cross_table(client, app, two_store_two_major):
    _login(client, app, "accountant")
    r = client.get(f"/reports/monthly?period_id={two_store_two_major['period_id']}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert "note" not in body

    rows_by_major = {row["major_name"]: row for row in body["rows"]}
    assert set(rows_by_major.keys()) == {"水電瓦斯", "餐飲"}

    water = rows_by_major["水電瓦斯"]
    assert water["total"] == {"reconciled": 300.0, "pending": -50.0}

    food = rows_by_major["餐飲"]
    assert food["total"] == {"reconciled": 120.0, "pending": -20.0}
    # submitted 單 (999) 不應計入
    assert food["total"]["reconciled"] == 120.0

    s1, s2 = two_store_two_major["store_ids"]
    assert body["store_totals"][str(s1)] == {"reconciled": 300.0, "pending": -50.0}
    assert body["store_totals"][str(s2)] == {"reconciled": 120.0, "pending": -20.0}
    assert body["grand_total"] == {"reconciled": 420.0, "pending": -70.0}
    assert body["period"]["id"] == two_store_two_major["period_id"]


def test_non_viewable_store_excluded_from_report(client, app, two_store_two_major):
    # 把 s2 設為不可檢視 → 報表欄位與其單據(食物 120/-20)都不出現
    from app.models import Store
    with app.app_context():
        db.session.get(Store, two_store_two_major["store_ids"][1]).viewable = False
        db.session.commit()
    _login(client, app, "accountant")
    body = client.get(f"/reports/monthly?period_id={two_store_two_major['period_id']}").get_json()
    store_ids = {s["id"] for s in body["stores"]}
    assert two_store_two_major["store_ids"][1] not in store_ids   # s2 欄位不見了
    rows_by_major = {row["major_name"]: row for row in body["rows"]}
    assert "餐飲" not in rows_by_major   # s2 的餐飲單被排除，該大類無資料


def test_super_admin_can_view(client, app, two_store_two_major):
    _login(client, app, "super_admin")
    r = client.get(f"/reports/monthly?period_id={two_store_two_major['period_id']}")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_manager_forbidden(client, app, two_store_two_major):
    _login(client, app, "manager")
    r = client.get(f"/reports/monthly?period_id={two_store_two_major['period_id']}")
    assert r.status_code == 403


def test_employee_forbidden(client, app, two_store_two_major):
    _login(client, app, "employee")
    r = client.get(f"/reports/monthly?period_id={two_store_two_major['period_id']}")
    assert r.status_code == 403
