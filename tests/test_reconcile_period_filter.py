import time
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense
from app.periods.service import get_or_create_period

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
def two_period_audited(app):
    """建當期（含 2026-07-10）audited 單 + 上一期（含 2026-06-15）audited 單。"""
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

        cur_bd = date(2026, 7, 10)
        prev_bd = date(2026, 6, 15)
        cur_period = get_or_create_period(cur_bd)
        prev_period = get_or_create_period(prev_bd)
        db.session.commit()

        now = datetime.now(timezone.utc)
        cur = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                      created_at=now, business_date=cur_bd,
                      amount=Decimal("100"), amount_parse_ok=True, submitted_at=now,
                      period_id=cur_period.id)
        # 上一期單用 reconciled（已核銷）：因為 pending() 讀取時會觸發 maybe_autoclose，
        # 上一期早已過鎖定時刻，若用 audited/rejected 一碰就會被自動挪到下一期，
        # 讓「查上一期 period_id 應看到它」這個斷言失真——reconciled 不會被挪期，
        # 才是「已核銷、留在原期」的真實情境。
        old = Expense(store_id=s1.id, created_by=emp.id, status="reconciled",
                      created_at=now, business_date=prev_bd,
                      amount=Decimal("50"), amount_parse_ok=True, submitted_at=now,
                      reconciled_by=acct.id, reconciled_at=now,
                      period_id=prev_period.id)
        db.session.add_all([cur, old])
        db.session.commit()
        result = {
            "cur_id": cur.id,
            "old_id": old.id,
            "cur_period_id": cur_period.id,
            "prev_period_id": prev_period.id,
            "cur_period_label": cur_period.label,
            "prev_period_label": prev_period.label,
            "cur_period_end": cur_period.end_date.isoformat(),
        }
    return result


def test_pending_defaults_to_current_period(client, app, two_period_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    assert r.status_code == 200
    data = r.get_json()

    assert data["period"] is not None
    assert data["period"]["id"] == two_period_audited["cur_period_id"]
    assert data["period"]["label"] == two_period_audited["cur_period_label"]
    assert data["period"]["status"] in ("open", "closing", "closed")
    # 月結管理最上面「下次月結」用的本期截止日
    assert data["period"]["end_date"] == two_period_audited["cur_period_end"]

    items = [i for g in data["groups"] for i in g["items"]]
    ids = {i["id"] for i in items}
    assert two_period_audited["cur_id"] in ids
    assert two_period_audited["old_id"] not in ids
    for i in items:
        assert i["period_id"] == two_period_audited["cur_period_id"]
        assert i["period_label"] == two_period_audited["cur_period_label"]


def test_pending_filter_by_period_id(client, app, two_period_audited):
    login_accountant(client, app)
    r = client.get(f"/reconcile/pending?period_id={two_period_audited['prev_period_id']}")
    assert r.status_code == 200
    data = r.get_json()

    assert data["period"] is not None
    assert data["period"]["id"] == two_period_audited["prev_period_id"]
    assert data["period"]["label"] == two_period_audited["prev_period_label"]

    items = [i for g in data["groups"] for i in g["items"]]
    ids = {i["id"] for i in items}
    assert two_period_audited["old_id"] in ids
    assert two_period_audited["cur_id"] not in ids
    for i in items:
        assert i["period_id"] == two_period_audited["prev_period_id"]
        assert i["period_label"] == two_period_audited["prev_period_label"]
