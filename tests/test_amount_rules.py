"""金額規則：負數合法（無單據建帳/會計沖銷可能是負的），0 一律不合法。
涵蓋 parse_amount 單元測試 + 三個寫入端（員工 PATCH / 無單據建帳 / 主管 edit）的 API 層測試。"""
import time
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Expense, Store, User, Device
from app.expenses.amount import parse_amount


# ---------- 單元測試：parse_amount ----------

def test_positive():
    assert parse_amount(120) == (Decimal("120"), None)


def test_negative_allowed():
    assert parse_amount(-50) == (Decimal("-50"), None)


def test_negative_string_allowed():
    assert parse_amount("-50.25") == (Decimal("-50.25"), None)


def test_zero_rejected():
    assert parse_amount(0) == (None, "amount_zero")
    assert parse_amount("0.00") == (None, "amount_zero")


def test_garbage_rejected():
    assert parse_amount("abc") == (None, "amount_invalid")


def test_none_is_passthrough():
    assert parse_amount(None) == (None, None)


# ---------- API 層測試：共用 seed/login helper（照抄各自既有測試檔的模式）----------

def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        mgr = User(name="主管A", role="manager", store_id=s.id); mgr.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, mgr, dev]); db.session.commit()
        return s.id, u.id, mgr.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def _draft(app, sid, uid, **kw):
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="draft",
                    created_at=datetime.now(timezone.utc), **kw)
        db.session.add(e); db.session.commit(); return e.id


# ---- 無單據建帳 /expenses/no-receipt ----

def test_no_receipt_rejects_zero(app):
    sid, uid, mgr_id = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"amount": 0, "summary": "x"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "amount_zero"


def test_no_receipt_accepts_negative(app):
    sid, uid, mgr_id = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"amount": -300, "summary": "退款"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, r.get_json()["id"])
        assert e.amount == Decimal("-300")


# ---- 員工 PATCH /expenses/<id> ----

def test_patch_rejects_zero_amount(app):
    sid, uid, mgr_id = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True)
    c = _client(app, uid)
    r = c.patch(f"/expenses/{eid}", json={"amount": 0})
    assert r.status_code == 400
    assert r.get_json()["message"] == "amount_zero"
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.amount == Decimal("100")  # 沒被改掉


def test_patch_accepts_negative_amount(app):
    sid, uid, mgr_id = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True)
    c = _client(app, uid)
    r = c.patch(f"/expenses/{eid}", json={"amount": -50})
    assert r.status_code == 200
    body = r.get_json()
    assert body["expense"]["amount"] == -50.0
    assert body["expense"]["is_modified_by_user"] is True


# ---- 主管 edit PATCH /audit/<id> ----

def test_manager_edit_rejects_zero_amount(app):
    sid, uid, mgr_id = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="submitted",
                    created_at=datetime.now(timezone.utc),
                    amount=Decimal("100"), amount_parse_ok=True)
        db.session.add(e); db.session.commit(); eid = e.id
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{eid}", json={"amount": 0})
    assert r.status_code == 400
    assert r.get_json()["message"] == "amount_zero"
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.amount == Decimal("100")  # 沒被改掉


def test_manager_edit_accepts_negative_amount(app):
    sid, uid, mgr_id = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="submitted",
                    created_at=datetime.now(timezone.utc),
                    amount=Decimal("100"), amount_parse_ok=True)
        db.session.add(e); db.session.commit(); eid = e.id
    c = _client(app, mgr_id)
    r = c.patch(f"/audit/{eid}", json={"amount": "-40"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.amount == Decimal("-40")
        assert e.is_modified_by_manager is True
