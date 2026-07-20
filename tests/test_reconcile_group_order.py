import time
from datetime import datetime, timezone, date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Store, User, Device, Expense
from app.periods.service import get_or_create_period

# 登入/裝置閘 helper 照 tests/test_reconcile_list.py 現成寫法


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
def three_days(app):
    """同一期間內三個不同營業日各一張待核銷單。"""
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()
        emp = User(name="員工A", role="employee", store_id=s1.id); emp.set_password("0000")
        acct = User(name="會計", role="accountant"); acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        db.session.add_all([emp, acct, dev])
        db.session.commit()

        days = [date(2026, 7, 7), date(2026, 7, 20), date(2026, 7, 13)]  # 故意亂序建立
        period = get_or_create_period(days[0])
        db.session.commit()
        now = datetime.now(timezone.utc)
        for bd in days:
            db.session.add(Expense(
                store_id=s1.id, created_by=emp.id, status="audited",
                created_at=now, business_date=bd, period_id=period.id,
                amount=Decimal("100"), amount_parse_ok=True, submitted_at=now))
        db.session.commit()
    return None


def test_groups_are_newest_business_day_first(client, app, three_days):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    assert r.status_code == 200
    dates = [g["business_date"] for g in r.get_json()["groups"]]
    assert dates == ["2026-07-20", "2026-07-13", "2026-07-07"]  # 新到舊，最新在最上面
