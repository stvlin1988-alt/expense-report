import time
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog

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


def login_employee(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="employee").first().id
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

        now = datetime.now(timezone.utc)
        audited = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                           created_at=now, business_date=date(2026, 7, 7),
                           amount=Decimal("200"), amount_parse_ok=True, submitted_at=now)
        submitted = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                             created_at=now, business_date=date(2026, 7, 7),
                             amount=Decimal("50"), amount_parse_ok=True, submitted_at=now)
        reconciled = Expense(store_id=s1.id, created_by=emp.id, status="reconciled",
                              created_at=now, business_date=date(2026, 7, 7),
                              amount=Decimal("120"), amount_parse_ok=True, submitted_at=now,
                              reconciled_by=acct.id, reconciled_at=now)
        db.session.add_all([audited, submitted, reconciled])
        db.session.commit()
        result = {
            "audited_id": audited.id,
            "submitted_id": submitted.id,
            "reconciled_id": reconciled.id,
        }
    return result


@pytest.fixture
def audited_id(seeded):
    return seeded["audited_id"]


@pytest.fixture
def submitted_id(seeded):
    return seeded["submitted_id"]


@pytest.fixture
def reconciled_id(seeded):
    return seeded["reconciled_id"]


def test_reject_audited(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "金額與照片不符"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.status == "rejected"
        assert e.reject_reason == "金額與照片不符"


def test_reject_reconciled(client, app, reconciled_id):
    """已核銷的單要改帳 → 會計退回，主管改完重送。退回即撤銷核銷。"""
    login_accountant(client, app)
    r = client.post(f"/reconcile/{reconciled_id}/reject", json={"reason": "科目錯了"})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, reconciled_id)
        assert e.status == "rejected"
        assert e.reject_reason == "科目錯了"
        assert e.reconciled_by is None
        assert e.reconciled_at is None


def test_reason_required(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "   "})
    assert r.status_code == 400
    assert r.get_json()["message"] == "reason_required"


def test_reason_missing_key_required(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={})
    assert r.status_code == 400
    assert r.get_json()["message"] == "reason_required"


def test_reason_too_long(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "x" * 201})
    assert r.status_code == 400
    assert r.get_json()["message"] == "reason_too_long"
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.status == "audited"


def test_reason_exactly_200_ok(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "x" * 200})
    assert r.status_code == 200


def test_reason_non_string_int_400(client, app, audited_id):
    """brief 原碼 ((...).get("reason") or "").strip() 對非字串（如 int）會炸
    AttributeError → 500；這裡要求非字串一律回 400 reason_required，不可 500。"""
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": 5})
    assert r.status_code == 400
    assert r.get_json()["message"] == "reason_required"


def test_reason_non_string_list_400(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": ["x"]})
    assert r.status_code == 400
    assert r.get_json()["message"] == "reason_required"


def test_cannot_reject_submitted(client, app, submitted_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{submitted_id}/reject", json={"reason": "x"})
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_rejectable"
    with app.app_context():
        e = db.session.get(Expense, submitted_id)
        assert e.status == "submitted"


def test_reject_nonexistent_404(client, app, audited_id):
    login_accountant(client, app)
    r = client.post("/reconcile/999999/reject", json={"reason": "x"})
    assert r.status_code == 404


def test_reject_writes_log(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/reject", json={"reason": "金額不符"})
    with app.app_context():
        logs = AuditLog.query.filter_by(expense_id=audited_id).all()
        actions = [l.action for l in logs]
        assert "reject" in actions
        reject_log = next(l for l in logs if l.action == "reject")
        assert reject_log.before_json == {"status": "audited"}
        assert reject_log.after_json == {"status": "rejected", "reason": "金額不符"}


def test_reject_writes_log_reconciled_branch(client, app, reconciled_id):
    """退回已核銷單：record_reject 必須在 status 被覆寫成 rejected 之前呼叫，
    否則 before_json 會誤記成 rejected 而非原本的 reconciled，稽核軌跡就失真。"""
    login_accountant(client, app)
    client.post(f"/reconcile/{reconciled_id}/reject", json={"reason": "科目錯了"})
    with app.app_context():
        logs = AuditLog.query.filter_by(expense_id=reconciled_id).all()
        reject_log = next(l for l in logs if l.action == "reject")
        assert reject_log.before_json == {"status": "reconciled"}
        assert reject_log.after_json == {"status": "rejected", "reason": "科目錯了"}


def test_unauthenticated_401(client, app, audited_id):
    r = client.post(f"/reconcile/{audited_id}/reject", json={"reason": "x"})
    assert r.status_code == 401


def test_rejected_expense_still_in_submitted_queryset_but_leaks_nothing(client, app, audited_id):
    """（本條原名 test_rejected_expense_excluded_from_submitted_queryset，釘的是
    「rejected 的單整批被排除在員工複查區外」。那個行為是舊 query 只挑
    status in (submitted, audited) 的副作用，而不是設計意圖：submitted() 的 docstring
    明說複查區是「本人這一班已送出、主管尚未交/結班的單」，清空時機只有 handover。
    會計核銷/退回並不代表主管結班了，卻會讓該列從員工畫面憑空消失 → 改成
    ("submitted",) + CHECKED_STATUSES 後，rejected 列會留下來，故本條斷言反轉。

    原 docstring 自己就寫明：這條對白名單「沒有任何回歸保護力」，因為根本沒有 rejected
    列可以序列化。現在真的有 rejected 列會被序列化了，於是這裡補上白名單斷言——
    保護力比原本更強，不是變弱。）"""
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/reject", json={"reason": "金額不符"})
    login_employee(client, app)
    r = client.get("/expenses/submitted")     # 員工複查端點
    body = r.get_json()
    rows = {row["id"]: row for row in body["expenses"]}
    assert audited_id in rows, "主管還沒結班，會計退回不該讓該筆從員工複查區消失"
    row = rows[audited_id]
    for leaked in ("status", "reject_reason", "is_rejected", "last_modified_by",
                   "last_modified_at", "last_modified_fields", "is_modified_by_manager"):
        assert leaked not in row, f"{leaked} 不應出現在員工複查回傳（rejected 列也一樣）"
