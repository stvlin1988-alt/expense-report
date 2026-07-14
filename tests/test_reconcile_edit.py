import time
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog, Category

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
        cat1 = Category(name="文具", level=1)
        cat2 = Category(name="清潔用品", level=1)
        db.session.add_all([emp, acct, dev, cat1, cat2])
        db.session.commit()

        now = datetime.now(timezone.utc)
        audited = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                           created_at=now, business_date=date(2026, 7, 7),
                           amount=Decimal("200"), amount_parse_ok=True, submitted_at=now,
                           category_id=cat1.id)
        submitted = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                             created_at=now, business_date=date(2026, 7, 7),
                             amount=Decimal("50"), amount_parse_ok=True, submitted_at=now,
                             category_id=cat1.id)
        reconciled = Expense(store_id=s1.id, created_by=emp.id, status="reconciled",
                              created_at=now, business_date=date(2026, 7, 7),
                              amount=Decimal("120"), amount_parse_ok=True, submitted_at=now,
                              reconciled_by=acct.id, reconciled_at=now, category_id=cat1.id)
        rejected = Expense(store_id=s1.id, created_by=emp.id, status="rejected",
                            created_at=now, business_date=date(2026, 7, 7),
                            amount=Decimal("80"), amount_parse_ok=True, submitted_at=now,
                            reject_reason="金額不符", category_id=cat1.id)
        db.session.add_all([audited, submitted, reconciled, rejected])
        db.session.commit()
        result = {
            "audited_id": audited.id,
            "submitted_id": submitted.id,
            "reconciled_id": reconciled.id,
            "rejected_id": rejected.id,
            "cat1_id": cat1.id,
            "cat2_id": cat2.id,
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


@pytest.fixture
def rejected_id(seeded):
    return seeded["rejected_id"]


@pytest.fixture
def cat_id(seeded):
    return seeded["cat2_id"]


def test_accountant_edits_amount_and_category(client, app, audited_id, cat_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": -250, "category_id": cat_id})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert float(e.amount) == -250.0
        assert e.category_id == cat_id


def test_edit_writes_log(client, app, audited_id):
    login_accountant(client, app)
    client.patch(f"/reconcile/{audited_id}", json={"amount": 999})
    with app.app_context():
        actions = [l.action for l in AuditLog.query.filter_by(expense_id=audited_id).all()]
        assert "edit" in actions


def test_edit_does_not_change_light(client, app, audited_id):
    login_accountant(client, app)
    before = client.get("/reconcile/pending").get_json()
    light_before = [i for g in before["groups"] for i in g["items"] if i["id"] == audited_id][0]["light"]
    client.patch(f"/reconcile/{audited_id}", json={"amount": 777})
    after = client.get("/reconcile/pending").get_json()
    light_after = [i for g in after["groups"] for i in g["items"] if i["id"] == audited_id][0]["light"]
    assert light_after == light_before


def test_edit_zero_rejected(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": 0})
    assert r.status_code == 400
    assert r.get_json()["message"] == "amount_zero"


def test_edit_negative_amount_ok(client, app, audited_id):
    """負數金額全端合法（會計沖銷可能是負的）。"""
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": -1})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert float(e.amount) == -1.0


def test_edit_reconciled_allowed(client, app, reconciled_id):
    """已核銷的單也允許就地改（會計事後發現要調整）。"""
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{reconciled_id}", json={"amount": 150})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, reconciled_id)
        assert float(e.amount) == 150.0


def test_edit_submitted_not_editable(client, app, submitted_id):
    """submitted 還沒經過主管稽核，不在會計可視/可編輯狀態內。"""
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{submitted_id}", json={"amount": 100})
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_editable"


def test_edit_rejected_not_editable(client, app, rejected_id):
    """rejected 要先由主管改回 audited 才能再進會計流程，會計不能直接改。"""
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{rejected_id}", json={"amount": 100})
    assert r.status_code == 409
    assert r.get_json()["message"] == "not_editable"


def test_edit_nonexistent_404(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch("/reconcile/999999", json={"amount": 100})
    assert r.status_code == 404


def test_edit_does_not_set_modified_by_user_or_manager_flags(client, app, audited_id):
    """會計改動只留 audit_log 軌跡，不能牽動 is_modified_by_user/is_modified_by_manager
    —— 那兩個旗標分別驅動員工/主管端的燈號語意，不該被會計端動作誤觸發。"""
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        before_user_flag = e.is_modified_by_user
        before_manager_flag = getattr(e, "is_modified_by_manager", None)
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": 321, "category_id": None})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.is_modified_by_user == before_user_flag
        assert getattr(e, "is_modified_by_manager", None) == before_manager_flag


# ---------- I1 回歸：_valid_category_id 沒做型別防護 → dict/list/非數字字串會 500 ----------

def test_edit_category_id_dict_not_500(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"category_id": {"a": 1}})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Expense, audited_id).category_id is None


def test_edit_category_id_list_not_500(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"category_id": [1]})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Expense, audited_id).category_id is None


def test_edit_category_id_non_numeric_string_clears(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"category_id": "abc"})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Expense, audited_id).category_id is None


def test_edit_category_id_bool_clears(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"category_id": True})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Expense, audited_id).category_id is None


def test_edit_category_id_none_clears(client, app, audited_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"category_id": None})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Expense, audited_id).category_id is None


def test_edit_category_id_valid_id_still_works(client, app, audited_id, cat_id):
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"category_id": cat_id})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Expense, audited_id).category_id == cat_id


def test_unauthenticated_401(client, app, audited_id):
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": 100})
    assert r.status_code == 401


def _light_of(payload, eid):
    return [i for g in payload["groups"] for i in g["items"] if i["id"] == eid][0]["light"]


@pytest.fixture
def bad_amount_id(seeded, app):
    """已 audited 但 amount_parse_ok=False（例如主管把金額清空後仍放行）
    —— 燈號應為 red，這是會計端要能事後修正回綠燈的個案。"""
    with app.app_context():
        s1 = Store.query.first()
        emp = User.query.filter_by(role="employee").first()
        now = datetime.now(timezone.utc)
        e = Expense(store_id=s1.id, created_by=emp.id, status="audited",
                    created_at=now, business_date=date(2026, 7, 7),
                    amount=None, amount_parse_ok=False, submitted_at=now,
                    category_id=seeded["cat1_id"])
        db.session.add(e)
        db.session.commit()
        return e.id


def test_edit_fixes_bad_amount_parse_ok_and_clears_red_light(client, app, bad_amount_id):
    """會計把 amount_parse_ok=False 的爛單補上合法金額後，
    amount_parse_ok 要跟著轉 True、燈號不再是 red —— 這是這行程式碼存在的理由。"""
    login_accountant(client, app)
    before = client.get("/reconcile/pending").get_json()
    assert _light_of(before, bad_amount_id) == "red"

    r = client.patch(f"/reconcile/{bad_amount_id}", json={"amount": 500})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, bad_amount_id)
        assert e.amount_parse_ok is True

    after = client.get("/reconcile/pending").get_json()
    assert _light_of(after, bad_amount_id) != "red"


def test_edit_null_amount_sets_parse_ok_false_and_red_light(client, app, audited_id):
    """會計把金額清空（amount: null）時，amount_parse_ok 要跟著變 False、
    燈號轉 red —— 不能留下 amount=None 但 amount_parse_ok=True 的失真狀態。"""
    login_accountant(client, app)
    r = client.patch(f"/reconcile/{audited_id}", json={"amount": None})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, audited_id)
        assert e.amount is None
        assert e.amount_parse_ok is False

    after = client.get("/reconcile/pending").get_json()
    assert _light_of(after, audited_id) == "red"
