import time
from datetime import datetime, timezone
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, Category

# 端到端整合測試：員工送出 → 主管打勾 → 會計退回 → 主管改完重送 → 會計核銷。
# 登入/建單 helper 照 tests/test_reconcile_approve.py / test_reconcile_list.py 現成寫法。


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_employee(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="employee").first().id
    _set_session(client, uid)


def login_manager(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="manager").first().id
    _set_session(client, uid)


def login_accountant(client, app):
    with app.app_context():
        uid = User.query.filter_by(role="accountant").first().id
    _set_session(client, uid)


def employee_submit(client, app, store_id, amount, note=None):
    """員工建單（金額直接灌，跳過拍照/OCR）→（可選）填備註 → 送出。回傳 expense id。"""
    login_employee(client, app)
    with app.app_context():
        emp = User.query.filter_by(role="employee", store_id=store_id).first()
        e = Expense(store_id=store_id, created_by=emp.id, status="draft",
                    amount=amount, amount_parse_ok=True,
                    created_at=datetime.now(timezone.utc))
        db.session.add(e)
        db.session.commit()
        eid = e.id
    if note is not None:
        r = client.patch(f"/expenses/{eid}", json={"note": note})
        assert r.status_code == 200
    r = client.post(f"/expenses/{eid}/submit")
    assert r.status_code == 200
    return eid


@pytest.fixture
def seeded(app):
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        mgr = User(name="主管A", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        cat = Category(name="文具", level=1)
        db.session.add_all([emp, mgr, acct, dev, cat])
        db.session.commit()
        return {"store_id": s1.id, "cat_id": cat.id}


@pytest.fixture
def store_id(seeded):
    return seeded["store_id"]


@pytest.fixture
def cat_id(seeded):
    return seeded["cat_id"]


def test_full_cycle(client, app, store_id, cat_id):
    """員工送出 → 主管打勾 → 會計退回 → 主管改完重送 → 會計核銷。"""
    eid = employee_submit(client, app, store_id, amount=500, note="老闆交代")

    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200

    login_accountant(client, app)
    assert client.post(f"/reconcile/{eid}/reject", json={"reason": "金額不符"}).status_code == 200

    login_manager(client, app)
    pending = client.get("/audit/pending").get_json()
    row = [i for g in pending["groups"] for i in g["items"] if i["id"] == eid][0]
    assert row["is_rejected"] is True
    assert row["note"] == "老闆交代"
    client.patch(f"/audit/{eid}", json={"amount": 450})
    assert client.post(f"/audit/{eid}/check").status_code == 200

    login_accountant(client, app)
    body = client.get("/reconcile/pending").get_json()
    row = [i for g in body["groups"] for i in g["items"] if i["id"] == eid][0]
    assert row["status"] == "audited"
    assert "note" not in row                 # 會計永遠看不到備註
    assert client.post(f"/reconcile/{eid}/approve").status_code == 200

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "reconciled"
        # brief 原句 `e.reject_reason is None or e.status == "reconciled"` 是恆真式
        # （此時 status 必為 reconciled），改成真正要驗的斷言：主管 re-check 時
        # check() 會清空 reject_reason，核銷這步它應已是 None。
        assert e.reject_reason is None


def test_note_never_leaks_across_full_cycle(client, app, store_id, cat_id):
    """會計端在流程走過的每一個可見狀態（audited/rejected/reconciled 再回 audited/
    reconciled）打 /reconcile/pending，回傳的那一筆都不能帶 note key。"""
    eid = employee_submit(client, app, store_id, amount=300, note="機密備註")

    def _accountant_row_has_no_note(status_filter=None):
        login_accountant(client, app)
        url = "/reconcile/pending" if status_filter is None else f"/reconcile/pending?status={status_filter}"
        body = client.get(url).get_json()
        items = [i for g in body["groups"] for i in g["items"] if i["id"] == eid]
        assert items, f"expense {eid} 應該出現在 /reconcile/pending（status={status_filter}）"
        assert "note" not in items[0]
        return items[0]

    # 1) audited
    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200
    _accountant_row_has_no_note("audited")

    # 2) rejected（會計退回）
    login_accountant(client, app)
    assert client.post(f"/reconcile/{eid}/reject", json={"reason": "科目錯了"}).status_code == 200
    _accountant_row_has_no_note("rejected")

    # 3) 主管改完重送 → audited
    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200
    _accountant_row_has_no_note("audited")

    # 4) reconciled
    login_accountant(client, app)
    assert client.post(f"/reconcile/{eid}/approve").status_code == 200
    _accountant_row_has_no_note("reconciled")


def test_manager_cannot_touch_reconciled(client, app, store_id, cat_id):
    """核銷後主管不能再直接改動或再打勾已核銷的單——要改帳只能靠會計退回
    （/reconcile/<id>/reject 把它打回 rejected，主管才能重新編輯/打勾）。"""
    eid = employee_submit(client, app, store_id, amount=200)

    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200

    login_accountant(client, app)
    assert client.post(f"/reconcile/{eid}/approve").status_code == 200

    with app.app_context():
        assert db.session.get(Expense, eid).status == "reconciled"

    login_manager(client, app)
    r_patch = client.patch(f"/audit/{eid}", json={"amount": 999})
    assert r_patch.status_code == 409, (
        f"預期已核銷單 PATCH /audit/<id> 回 409，實際 {r_patch.status_code} "
        f"{r_patch.get_json()} —— 這是規格要求的狀態機防線被繞過，屬真 bug。"
    )
    r_check = client.post(f"/audit/{eid}/check")
    assert r_check.status_code == 409, (
        f"預期已核銷單 POST /audit/<id>/check 回 409，實際 {r_check.status_code} "
        f"{r_check.get_json()} —— 主管不該能繞過會計直接把已核銷單再打勾一次。"
    )

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "reconciled"
        assert float(e.amount) == 200.0   # 兩次動作都被擋，金額沒被改動


def test_resubmitted_expense_clears_reject_reason_for_accountant(client, app, store_id, cat_id):
    """退回後又重送的單，會計端看到的 reject_reason 已被清空
    （主管 check() 重送時要清掉舊的退回原因，不能讓會計看到過期的退回理由）。"""
    eid = employee_submit(client, app, store_id, amount=100)

    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200

    login_accountant(client, app)
    assert client.post(f"/reconcile/{eid}/reject", json={"reason": "單據不清楚"}).status_code == 200
    body = client.get("/reconcile/pending?status=rejected").get_json()
    row = [i for g in body["groups"] for i in g["items"] if i["id"] == eid][0]
    assert row["reject_reason"] == "單據不清楚"

    login_manager(client, app)
    assert client.post(f"/audit/{eid}/check").status_code == 200   # 主管重送，不改金額也行

    login_accountant(client, app)
    body2 = client.get("/reconcile/pending?status=audited").get_json()
    row2 = [i for g in body2["groups"] for i in g["items"] if i["id"] == eid][0]
    assert row2["reject_reason"] is None

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.reject_reason is None
