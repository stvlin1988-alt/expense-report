import time
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Store, User, Device, Expense, AccountingPeriod
from app.periods.service import get_or_create_period


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
def closed_and_open_periods(app):
    """closed 期含 1 筆 submitted（未處理，主管沒打勾）+ 1 筆 audited（已打勾，不算未處理）；
    open 期另含 1 筆 submitted（還在進行中，不算「上期」未處理）。"""
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A")
        db.session.add(s)
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s.id)
        emp.set_password("0000")
        acct = User(name="會計", role="accountant")
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([emp, acct, dev])
        db.session.commit()

        closed_bd = date(2026, 6, 20)
        closed_period = get_or_create_period(closed_bd)
        db.session.commit()
        closed_period.status = "closed"
        db.session.commit()

        open_bd = date(2026, 7, 7)
        open_period = get_or_create_period(open_bd)
        db.session.commit()
        assert open_period.status == "open"

        now = datetime.now(timezone.utc)
        stuck = Expense(store_id=s.id, created_by=emp.id, status="submitted",
                         created_at=now, submitted_at=now, business_date=closed_bd,
                         day_seq=1, period_id=closed_period.id,
                         summary="未處理單", amount=Decimal("120"), amount_parse_ok=True,
                         image_key="k-stuck")
        audited_in_closed = Expense(store_id=s.id, created_by=emp.id, status="audited",
                                     created_at=now, submitted_at=now, business_date=closed_bd,
                                     day_seq=2, period_id=closed_period.id,
                                     summary="已打勾單", amount=Decimal("80"), amount_parse_ok=True)
        submitted_in_open = Expense(store_id=s.id, created_by=emp.id, status="submitted",
                                     created_at=now, submitted_at=now, business_date=open_bd,
                                     day_seq=1, period_id=open_period.id,
                                     summary="本期未打勾", amount=Decimal("50"), amount_parse_ok=True)
        db.session.add_all([stuck, audited_in_closed, submitted_in_open])
        db.session.commit()
        result = {
            "store_id": s.id,
            "store_name": s.code,   # 顯示一律用店代號（code），不露店名
            "stuck_id": stuck.id,
            "audited_in_closed_id": audited_in_closed.id,
            "submitted_in_open_id": submitted_in_open.id,
            "closed_bd": closed_bd,
        }
    return result


def test_unprocessed_lists_only_submitted_in_closed_periods(client, app, closed_and_open_periods):
    login_accountant(client, app)
    r = client.get("/reconcile/unprocessed")
    assert r.status_code == 200
    body = r.get_json()
    items = body["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == closed_and_open_periods["stuck_id"]
    # 已打勾的那筆、以及 open 期那筆都不該出現
    ids = [i["id"] for i in items]
    assert closed_and_open_periods["audited_in_closed_id"] not in ids
    assert closed_and_open_periods["submitted_in_open_id"] not in ids


def test_unprocessed_item_fields_and_no_note(client, app, closed_and_open_periods):
    login_accountant(client, app)
    r = client.get("/reconcile/unprocessed")
    item = r.get_json()["items"][0]
    assert item["business_date"] == closed_and_open_periods["closed_bd"].isoformat()
    assert item["store_id"] == closed_and_open_periods["store_id"]
    assert item["store_name"] == closed_and_open_periods["store_name"]
    assert item["summary"] == "未處理單"
    assert item["amount"] == 120.0
    assert item["image_url"] == "/mock-storage/k-stuck"
    # 白名單守門：會計端絕不可看到 note
    assert "note" not in item


def test_unprocessed_empty_when_no_closed_periods(client, app):
    with app.app_context():
        db.create_all()
        acct = User(name="會計", role="accountant")
        acct.set_password("0000")
        db.session.add(acct)
        db.session.commit()
        # 建一個 open 期，確認不是「沒有期間」而是「沒有 closed 期間」
        get_or_create_period(date(2026, 7, 7))
        db.session.commit()
    login_accountant(client, app)
    r = client.get("/reconcile/unprocessed")
    assert r.status_code == 200
    assert r.get_json()["items"] == []


def test_unprocessed_unauthenticated_401(client, app, closed_and_open_periods):
    r = client.get("/reconcile/unprocessed")
    assert r.status_code == 401
