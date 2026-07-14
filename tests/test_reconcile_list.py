import time
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense

# 登入/建單 helper 照 tests/test_audit_*.py 現成寫法


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_accountant(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="accountant").first().id
    _set_session(client, uid)


def login_manager(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="manager").first().id
    _set_session(client, uid)


@pytest.fixture
def two_store_audited(app):
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        s2 = Store(name="B店", code="B")
        db.session.add_all([s1, s2])
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        mgr = User(name="主管A", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        db.session.add_all([emp, mgr, acct, dev])
        db.session.commit()

        now = datetime.now(timezone.utc)
        e1 = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                     created_at=now, business_date=date(2026, 7, 7),
                     amount=Decimal("200"), amount_parse_ok=True, submitted_at=now)
        e2 = Expense(store_id=s2.id, created_by=emp.id, status="audited",
                     created_at=now, business_date=date(2026, 7, 7),
                     amount=Decimal("-100"), amount_parse_ok=True, submitted_at=now)
        e3 = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                     created_at=now, business_date=date(2026, 7, 7),
                     amount=Decimal("50"), amount_parse_ok=True, submitted_at=now)
        db.session.add_all([e1, e2, e3])
        db.session.commit()
        result = {
            "store_ids": [s1.id, s2.id],
            "submitted_id": e3.id,
            "expected_pending_sum": 200.0 + (-100.0),
        }
    return result


def test_accountant_sees_audited_across_stores(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    assert r.status_code == 200
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert {i["store_id"] for i in items} == set(two_store_audited["store_ids"])


def test_submitted_not_visible_to_accountant(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert two_store_audited["submitted_id"] not in [i["id"] for i in items]


def test_note_never_leaks_to_accountant(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert items
    for i in items:
        assert "note" not in i
        assert "last_modified_by" not in i
        assert "last_modified_at" not in i
        assert "last_modified_fields" not in i
        assert "is_modified_by_manager" not in i


def test_manager_forbidden(client, app, two_store_audited):
    login_manager(client, app)
    r = client.get("/reconcile/pending")
    assert r.status_code == 403


def test_totals_signed(client, app, two_store_audited):
    # fixture 內含一張 -100 的單，合計要帶號加總（不能取絕對值）
    login_accountant(client, app)
    t = client.get("/reconcile/pending").get_json()["total"]
    assert t["pending"] == two_store_audited["expected_pending_sum"]


def test_bad_store_id_returns_200_not_500(client, app, two_store_audited):
    # 非數字 query param 不可讓 int() 炸掉變 500；應忽略該篩選條件
    login_accountant(client, app)
    r = client.get("/reconcile/pending?store_id=abc")
    assert r.status_code == 200


def test_bad_category_id_returns_200_not_500(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending?category_id=xyz")
    assert r.status_code == 200


def test_store_id_filter_narrows_result(client, app, two_store_audited):
    login_accountant(client, app)
    sid = two_store_audited["store_ids"][0]
    r = client.get(f"/reconcile/pending?store_id={sid}")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert items and all(i["store_id"] == sid for i in items)


def test_unauthenticated_401(client, app, two_store_audited):
    r = client.get("/reconcile/pending")
    assert r.status_code == 401


# ---------- Addendum 10.1：resubmitted_at 白名單 ----------

def test_resubmitted_at_null_when_never_rejected(client, app, two_store_audited):
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    assert items
    for i in items:
        assert "resubmitted_at" in i
        assert i["resubmitted_at"] is None


def test_resubmitted_at_iso_utc_when_set(client, app, two_store_audited):
    with app.app_context():
        e = Expense.query.filter_by(store_id=two_store_audited["store_ids"][0], status="audited").first()
        e.resubmitted_at = datetime(2026, 7, 10, 3, 0, 0, tzinfo=timezone.utc)
        db.session.commit()
        eid = e.id
    login_accountant(client, app)
    r = client.get("/reconcile/pending")
    items = [i for g in r.get_json()["groups"] for i in g["items"]]
    item = next(i for i in items if i["id"] == eid)
    assert item["resubmitted_at"] == "2026-07-10T03:00:00+00:00"
