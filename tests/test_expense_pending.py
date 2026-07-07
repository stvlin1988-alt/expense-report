import time
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Expense, Store, User, Device
import app.storage.r2 as r2mod


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        u2 = User(name="員工B", role="employee", store_id=s.id); u2.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, u2, dev]); db.session.commit()
        return s.id, u.id, u2.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_pending_lists_own_draft_and_pending(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            Expense(store_id=sid, created_by=uid, status="draft", created_at=now, thumb_key="t1.jpg"),
            Expense(store_id=sid, created_by=uid, status="pending_ocr", created_at=now),
            Expense(store_id=sid, created_by=uid, status="submitted", created_at=now),   # 不列
            Expense(store_id=sid, created_by=uid2, status="draft", created_at=now),      # 他人不列
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/pending").get_json()
    assert body["status"] == "ok"
    statuses = sorted(e["status"] for e in body["expenses"])
    assert statuses == ["draft", "pending_ocr"]
    row = next(e for e in body["expenses"] if e["status"] == "draft")
    assert row["thumb_url"] and "t1.jpg" in row["thumb_url"]
    assert "light" in row


def test_pending_reconciles_stale_pending_ocr(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        old = datetime.now(timezone.utc) - timedelta(seconds=999)
        db.session.add(Expense(store_id=sid, created_by=uid, status="pending_ocr", created_at=old))
        db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/pending").get_json()
    row = body["expenses"][0]
    assert row["status"] == "draft"        # 逾時被收斂
    assert row["light"] == "red"           # amount_parse_ok=False → 紅


def test_get_detail_own_returns_image_url(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid, status="draft",
                    created_at=datetime.now(timezone.utc), image_key="m1.jpg")
        db.session.add(e); db.session.commit(); eid = e.id
    c = _client(app, uid)
    body = c.get(f"/expenses/{eid}").get_json()
    assert body["status"] == "ok"
    assert "m1.jpg" in body["expense"]["image_url"]


def test_get_detail_other_user_403(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid2, status="draft",
                    created_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit(); eid = e.id
    c = _client(app, uid)
    assert c.get(f"/expenses/{eid}").status_code == 403
