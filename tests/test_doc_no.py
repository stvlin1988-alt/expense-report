import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense
from app.expenses.logic import format_doc_no
from app.expenses.serialize import serialize_expense
from app.storage.r2 import get_storage


def test_format_doc_no():
    assert format_doc_no(date(2026, 7, 9), 3) == "0709-03"
    assert format_doc_no(date(2026, 12, 25), 12) == "1225-12"
    assert format_doc_no(None, 3) is None
    assert format_doc_no(date(2026, 7, 9), None) is None


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        db.session.add(emp); db.session.commit()
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add(dev); db.session.commit()
        return s.id, emp.id


def _draft(app, store_id, emp_id, created_at):
    with app.app_context():
        e = Expense(store_id=store_id, created_by=emp_id, status="draft",
                    created_at=created_at, amount=Decimal("100"), amount_parse_ok=True)
        db.session.add(e); db.session.commit()
        return e.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_submit_assigns_incrementing_day_seq(app):
    store_id, emp_id = _seed(app)
    # 同一營業日（台灣 10:00 → business_date 當日）
    at = datetime(2026, 7, 9, 2, 0, tzinfo=timezone.utc)  # 台灣 10:00
    e1 = _draft(app, store_id, emp_id, at)
    e2 = _draft(app, store_id, emp_id, at)
    c = _client(app, emp_id)
    assert c.post(f"/expenses/{e1}/submit").status_code == 200
    assert c.post(f"/expenses/{e2}/submit").status_code == 200
    with app.app_context():
        assert db.session.get(Expense, e1).day_seq == 1
        assert db.session.get(Expense, e2).day_seq == 2
        # doc_no 對應
        d = serialize_expense(db.session.get(Expense, e2), get_storage())
        assert d["doc_no"] == "0709-02"


def test_day_seq_independent_per_store(app):
    store_id, emp_id = _seed(app)
    with app.app_context():
        s2 = Store(name="B", code="B"); db.session.add(s2); db.session.commit()
        emp2 = User(name="emp2", role="employee", store_id=s2.id); emp2.set_password("1234")
        db.session.add(emp2); db.session.commit()
        dev2 = Device(client_uid="dev2", store_id=s2.id, is_approved=True)
        db.session.add(dev2); db.session.commit()
        s2_id, emp2_id = s2.id, emp2.id
    at = datetime(2026, 7, 9, 2, 0, tzinfo=timezone.utc)
    e1 = _draft(app, store_id, emp_id, at)
    eb = _draft(app, s2_id, emp2_id, at)
    _client(app, emp_id).post(f"/expenses/{e1}/submit")
    cb = app.test_client(); cb.set_cookie("device_uid", "dev2")
    with cb.session_transaction() as sess:
        sess["user_id"] = emp2_id; sess["_last_request_at"] = int(time.time())
    cb.post(f"/expenses/{eb}/submit")
    with app.app_context():
        # B 店同日也從 1 開始（不受 A 店影響）
        assert db.session.get(Expense, e1).day_seq == 1
        assert db.session.get(Expense, eb).day_seq == 1
