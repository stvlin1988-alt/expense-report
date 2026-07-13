import time
from datetime import datetime, timezone
import pytest
from app.extensions import db
from app.models import Expense, Store, User, Device

# 登入/建單 helper 照 tests/test_expense_edit_submit.py（現有 expenses 測試檔）的既有寫法


@pytest.fixture
def client(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        uid = u.id
    c = app.test_client()
    c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())
    return c


@pytest.fixture
def draft_expense_id(app, client):
    with app.app_context():
        u = User.query.filter_by(name="員工A").first()
        # amount 先給合法值，讓 submit（測 note 送出後鎖）不會卡在「金額必填」
        e = Expense(store_id=u.store_id, created_by=u.id, status="draft",
                    amount=100, amount_parse_ok=True,
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return e.id


def test_employee_can_set_note_on_draft(client, app, draft_expense_id):
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "老闆請客"})
    assert r.status_code == 200
    r2 = client.get(f"/expenses/{draft_expense_id}")
    assert r2.get_json()["expense"]["note"] == "老闆請客"


def test_note_locked_after_submit(client, app, draft_expense_id):
    client.patch(f"/expenses/{draft_expense_id}", json={"note": "原始說法"})
    client.post(f"/expenses/{draft_expense_id}/submit")
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "改口"})
    assert r.status_code == 409
    assert r.get_json()["message"] == "not editable"
    r2 = client.get(f"/expenses/{draft_expense_id}")
    assert r2.get_json()["expense"]["note"] == "原始說法"


def test_note_max_200(client, app, draft_expense_id):
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "x" * 201})
    assert r.status_code == 400


def test_note_exactly_200_chars_accepted(client, app, draft_expense_id):
    # 邊界值：剛好 200 字要能存，只擋 201+
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "x" * 200})
    assert r.status_code == 200
    r2 = client.get(f"/expenses/{draft_expense_id}")
    assert r2.get_json()["expense"]["note"] == "x" * 200


def test_note_whitespace_only_stores_null(client, app, draft_expense_id):
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": "   "})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, draft_expense_id)
        assert e.note is None


def test_note_empty_stores_null(client, app, draft_expense_id):
    r = client.patch(f"/expenses/{draft_expense_id}", json={"note": ""})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, draft_expense_id)
        assert e.note is None


def test_no_receipt_note_too_long(client, app):
    # no-receipt 建單同樣要擋 >200 字，不然會直接打到 String(200) 欄位在 Postgres 炸 500
    r = client.post("/expenses/no-receipt", json={"summary": "x", "amount": 1, "note": "x" * 201})
    assert r.status_code == 400
    assert r.get_json()["message"] == "note_too_long"


def test_no_receipt_note_whitespace_only_and_empty_store_null(client, app):
    r1 = client.post("/expenses/no-receipt", json={"summary": "x", "amount": 1, "note": "   "})
    assert r1.status_code == 200
    r2 = client.post("/expenses/no-receipt", json={"summary": "x", "amount": 1, "note": ""})
    assert r2.status_code == 200
    with app.app_context():
        e1 = db.session.get(Expense, r1.get_json()["id"])
        e2 = db.session.get(Expense, r2.get_json()["id"])
        assert e1.note is None
        assert e2.note is None
