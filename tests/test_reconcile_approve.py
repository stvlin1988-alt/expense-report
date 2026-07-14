import time
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog
from app.reconcile.routes import _coerce_id, MAX_BATCH_IDS

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
        rejected = Expense(store_id=s1.id, created_by=emp.id, status="rejected",
                            created_at=now, business_date=date(2026, 7, 7),
                            amount=Decimal("80"), amount_parse_ok=True, submitted_at=now)
        db.session.add_all([audited, submitted, rejected])
        db.session.commit()
        result = {
            "audited_id": audited.id,
            "submitted_id": submitted.id,
            "rejected_id": rejected.id,
        }
    return result


@pytest.fixture
def audited_id(seeded):
    return seeded["audited_id"]


@pytest.fixture
def submitted_id(seeded):
    return seeded["submitted_id"]


@pytest.fixture
def rejected_id(seeded):
    return seeded["rejected_id"]


def test_approve_audited(client, app, audited_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.status == "reconciled"
        assert e.reconciled_by is not None
        assert e.reconciled_at is not None


def test_approve_twice_is_conflict(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/approve")
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_reconcilable"


def test_cannot_approve_submitted(client, app, submitted_id):
    login_accountant(client, app)
    r = client.post(f"/reconcile/{submitted_id}/approve")
    assert r.status_code == 409


def test_cannot_approve_rejected(client, app, rejected_id):
    # 狀態機最高風險規則：rejected（會計退回）不能直接被會計核銷，
    # 必須先由主管改回 audited。少了這條，退回單可以被繞過直接核掉。
    login_accountant(client, app)
    r = client.post(f"/reconcile/{rejected_id}/approve")
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_reconcilable"
    with app.app_context():
        e = db.session.get(Expense, rejected_id)
        assert e.status == "rejected"


def test_approve_nonexistent_404(client, app, audited_id):
    login_accountant(client, app)
    r = client.post("/reconcile/999999/approve")
    assert r.status_code == 404


def test_approve_writes_log(client, app, audited_id):
    login_accountant(client, app)
    client.post(f"/reconcile/{audited_id}/approve")
    with app.app_context():
        actions = [l.action for l in AuditLog.query.filter_by(expense_id=audited_id).all()]
        assert "reconcile" in actions


def test_batch_approve_partial(client, app, audited_id, submitted_id):
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": [audited_id, submitted_id]})
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == [submitted_id]


def test_batch_approve_rejected_skipped(client, app, audited_id, rejected_id):
    # 批次版本的同一條規則：rejected 混在 ids 裡要落在 skipped，狀態不變。
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": [audited_id, rejected_id]})
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == [rejected_id]
    with app.app_context():
        e = db.session.get(Expense, rejected_id)
        assert e.status == "rejected"


def test_batch_approve_non_int_id_skipped_not_500(client, app, audited_id):
    # brief 原碼把 ids 元素直接丟進 db.session.get(Expense, eid)；
    # 非整數（如 "abc"）在 Postgres 上會炸 DataError → 500。
    # 這裡要求：不可 500，非整數的元素進 skipped，不能悄悄從回應消失。
    # 注意：這條在 SQLite（測試 DB）上就算把 _coerce_id 拿掉、退回原碼的
    # db.session.get(Expense, "abc") 也會通過——SQLite 對非法型別的 PK 只是
    # 靜靜回傳 None，不會像 Postgres 一樣炸 DataError → 500。這條測試只驗證
    # 「HTTP 層 200 + skipped 語意」的合約，真正守住 _coerce_id 這道防線的是
    # 下面 test_coerce_id_* 那組對 _coerce_id 本身的單元測試。
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": ["abc", audited_id]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == ["abc"]


def test_batch_approve_null_id_skipped_not_500(client, app, audited_id):
    # 同上：這條在 SQLite 上一樣對「拿掉 _coerce_id」沒有偵測力，理由同前一條的註解。
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": [None, audited_id]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["approved"] == [audited_id]
    assert body["skipped"] == [None]


def test_batch_approve_too_many_ids_400(client, app, audited_id):
    login_accountant(client, app)
    r = client.post("/reconcile/approve-batch", json={"ids": list(range(MAX_BATCH_IDS + 1))})
    assert r.status_code == 400
    assert r.get_json()["message"] == "too_many_ids"


def test_batch_approve_at_cap_still_ok(client, app, audited_id):
    # 剛好等於上限不該被擋。
    login_accountant(client, app)
    ids = [audited_id] + [-i for i in range(1, MAX_BATCH_IDS)]  # 湊到剛好 MAX_BATCH_IDS 筆
    assert len(ids) == MAX_BATCH_IDS
    r = client.post("/reconcile/approve-batch", json={"ids": ids})
    assert r.status_code == 200
    assert r.get_json()["approved"] == [audited_id]


def test_unauthenticated_401(client, app, audited_id):
    r = client.post(f"/reconcile/{audited_id}/approve")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# _coerce_id 單元測試：這才是真正守住「非法 PK 不能丟進 db.session.get」這道
# 防線的測試。上面兩條 HTTP 層測試在 SQLite 上就算把 _coerce_id 整個拿掉、
# 退回 db.session.get(Expense, eid) 原碼也會通過（見上方註解），所以拆掉/弱化
# _coerce_id 的守門邏輯，靠的是這裡的測試變紅來抓，不是靠 HTTP 層。
# ---------------------------------------------------------------------------

def test_coerce_id_int_passthrough():
    assert _coerce_id(5) == 5


def test_coerce_id_numeric_string():
    assert _coerce_id("5") == 5


def test_coerce_id_non_numeric_string_is_none():
    assert _coerce_id("abc") is None


def test_coerce_id_none_is_none():
    assert _coerce_id(None) is None


def test_coerce_id_bool_is_none():
    # bool 是 int 子類別，int(True)==1 會誤配到 id=1，必須明確擋掉。
    assert _coerce_id(True) is None
    assert _coerce_id(False) is None


def test_coerce_id_list_is_none():
    assert _coerce_id([1]) is None


def test_coerce_id_dict_is_none():
    assert _coerce_id({"id": 1}) is None
