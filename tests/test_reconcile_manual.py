import time
from datetime import datetime, timezone
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, Category, AccountingPeriod

# 登入/建單 helper 照 tests/test_reconcile_edit.py / test_reconcile_approve.py 現成寫法


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

        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        cat1 = Category(name="文具", level=1)
        db.session.add_all([acct, dev, cat1])
        db.session.commit()
        return {"store_id": s1.id, "cat1_id": cat1.id}


@pytest.fixture
def store_id(seeded):
    return seeded["store_id"]


@pytest.fixture
def cat_id(seeded):
    return seeded["cat1_id"]


def test_manual_creates_reconciled(client, app, store_id, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "補水電", "amount": 1200, "category_id": cat_id,
    })
    assert r.status_code == 200
    eid = r.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "reconciled"
        assert e.is_no_receipt is True
        assert e.reconciled_by is not None
        assert e.note is None
        assert e.day_seq is not None
        assert e.period_id is not None
        p = db.session.get(AccountingPeriod, e.period_id)
        assert p.start_date <= e.business_date <= p.end_date


def test_manual_allows_negative(client, app, store_id, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "退款", "amount": -500, "category_id": cat_id,
    })
    assert r.status_code == 200


def test_manual_requires_valid_store(client, app, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": 99999, "business_date": "2026-07-01",
        "summary": "x", "amount": 100, "category_id": cat_id,
    })
    assert r.status_code == 400


def test_manual_shows_in_list_as_reconciled(client, app, store_id, cat_id):
    login_accountant(client, app)
    client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "補水電", "amount": 1200, "category_id": cat_id,
    })
    body = client.get("/reconcile/pending?status=reconciled").get_json()
    items = [i for g in body["groups"] for i in g["items"]]
    assert any(i["summary"] == "補水電" for i in items)


def test_manual_non_integer_store_id_400_not_500(client, app, cat_id):
    """store_id 非數字（如 "abc"）：db.session.get(Store, "abc") 在 Postgres 上
    會炸 DataError → 500。要求走 _coerce_id，非數字一律當「store 不存在」回 400。"""
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": "abc", "business_date": "2026-07-01",
        "summary": "x", "amount": 100, "category_id": cat_id,
    })
    assert r.status_code == 400


def test_manual_non_string_summary_400_not_500(client, app, store_id, cat_id):
    """summary 非字串（如 int）：(data.get("summary") or "").strip() 會
    AttributeError → 500。要求非字串非 null 一律回 400。"""
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": 5, "amount": 100, "category_id": cat_id,
    })
    assert r.status_code == 400


def test_manual_missing_amount_400(client, app, store_id, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "x", "category_id": cat_id,
    })
    assert r.status_code == 400


def test_manual_zero_amount_400(client, app, store_id, cat_id):
    login_accountant(client, app)
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "x", "amount": 0, "category_id": cat_id,
    })
    assert r.status_code == 400


def test_manual_unauthenticated_401(client, app, store_id, cat_id):
    r = client.post("/reconcile/manual", json={
        "store_id": store_id, "business_date": "2026-07-01",
        "summary": "x", "amount": 100, "category_id": cat_id,
    })
    assert r.status_code == 401
