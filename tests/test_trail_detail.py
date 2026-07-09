import time
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Category
from app.audit.log import snapshot, log_edit_if_changed


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="u", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        c1 = Category(name="餐飲", level=1, sort=1)
        c2 = Category(name="交通", level=1, sort=2)
        db.session.add_all([c1, c2]); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc),
                    amount=Decimal("100"), category_id=c1.id)
        db.session.add(e); db.session.commit()
        return s.id, u.id, e.id, c1.id, c2.id


def test_last_modified_fields_amount_only(app):
    _, uid, eid, _, _ = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        e.amount = Decimal("250")
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        assert db.session.get(Expense, eid).last_modified_fields == "amount"


def test_last_modified_fields_category_only(app):
    _, uid, eid, _, c2 = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        e.category_id = c2
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        assert db.session.get(Expense, eid).last_modified_fields == "category"


def test_last_modified_fields_both(app):
    _, uid, eid, _, c2 = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        e.amount = Decimal("250"); e.category_id = c2
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        assert db.session.get(Expense, eid).last_modified_fields == "amount,category"


def test_last_modified_fields_accumulates_across_edits(app):
    # 分類、金額分兩次 PATCH（實務上 UI 就是分開送）→ 聯集標到兩欄
    _, uid, eid, _, c2 = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        b1 = snapshot(e)
        e.category_id = c2
        assert log_edit_if_changed(e, uid, b1) is True
        db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_fields == "category"
        b2 = snapshot(e)
        e.amount = Decimal("999")
        assert log_edit_if_changed(e, uid, b2) is True
        db.session.commit()
        # 第二次只改金額，但仍保留先前的分類 → 兩欄都標
        assert db.session.get(Expense, eid).last_modified_fields == "amount,category"


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_logs_endpoint_returns_changes(app):
    store_id, uid, eid, c1, c2 = _mk(app)
    with app.app_context():
        db.session.add(Device(client_uid="dev1", store_id=store_id, is_approved=True))
        # 一筆 edit：金額 100→250、分類 餐飲(c1)→交通(c2)
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        e.amount = Decimal("250"); e.category_id = c2
        log_edit_if_changed(e, uid, before)
        db.session.commit()
    r = _client(app, uid).get(f"/expenses/{eid}/logs")
    assert r.status_code == 200
    log = r.get_json()["logs"][0]
    assert log["action"] == "edit"
    changes = {c["field"]: (c["from"], c["to"]) for c in log["changes"]}
    assert changes["金額"] == (100.0, 250.0)
    assert changes["分類"] == ("餐飲", "交通")
