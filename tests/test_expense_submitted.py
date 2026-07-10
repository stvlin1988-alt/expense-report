import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Expense, Store, User, Device, Handover, Category
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


def _mk(sid, uid, status, amt, submitted_at, handover_id=None, day_seq=1,
        category_id=None, image_key=None):
    return Expense(store_id=sid, created_by=uid, status=status,
                   created_at=datetime.now(timezone.utc), submitted_at=submitted_at,
                   amount=Decimal(str(amt)), handover_id=handover_id, day_seq=day_seq,
                   category_id=category_id, image_key=image_key)


def test_lists_own_submitted_and_audited(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, now, day_seq=1),
            _mk(sid, uid, "audited", 200, now, day_seq=2),
            _mk(sid, uid, "draft", 300, None, day_seq=None),        # 不列
            _mk(sid, uid, "pending_ocr", 0, None, day_seq=None),    # 不列
            _mk(sid, uid2, "submitted", 999, now, day_seq=3),       # 他人不列
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert body["status"] == "ok"
    assert sorted(e["amount"] for e in body["expenses"]) == [100.0, 200.0]


def test_excludes_handed_over(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=now - timedelta(hours=1),
                     closed_by=uid, type="shift")
        db.session.add(h); db.session.commit()
        db.session.add(_mk(sid, uid, "audited", 100, now, handover_id=h.id, day_seq=1))
        db.session.commit()
    c = _client(app, uid)
    assert c.get("/expenses/submitted").get_json()["expenses"] == []


def test_time_boundary_clears_before_last_handover(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        base = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=uid, type="shift")
        db.session.add(h); db.session.commit()
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, base - timedelta(minutes=5), day_seq=1),  # 交班前→清
            _mk(sid, uid, "submitted", 200, base + timedelta(minutes=5), day_seq=2),  # 交班後→留
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert [e["amount"] for e in body["expenses"]] == [200.0]


def test_day_handover_also_clears(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        base = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=uid, type="day")
        db.session.add(h); db.session.commit()
        db.session.add(_mk(sid, uid, "submitted", 100, base - timedelta(minutes=5), day_seq=1))
        db.session.commit()
    c = _client(app, uid)
    assert c.get("/expenses/submitted").get_json()["expenses"] == []


def test_includes_category_name_and_image_url(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        cat = Category(name="餐費", level=1, sort=1, active=True)
        db.session.add(cat); db.session.commit()
        db.session.add(_mk(sid, uid, "submitted", 100, datetime.now(timezone.utc),
                           day_seq=1, category_id=cat.id, image_key="m1.jpg"))
        db.session.commit()
    c = _client(app, uid)
    row = c.get("/expenses/submitted").get_json()["expenses"][0]
    assert row["category_name"] == "餐費"
    assert "m1.jpg" in row["image_url"]


def test_no_status_leak(app):
    """員工複查區不揭露稽核狀態：回傳每筆都不能有 status 欄位。"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, now, day_seq=1),
            _mk(sid, uid, "audited", 200, now, day_seq=2),
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert len(body["expenses"]) == 2
    for row in body["expenses"]:
        assert "status" not in row


def test_payload_whitelist_hides_audit_metadata(app):
    """員工複查區不揭露主管稽核/改動狀態：即使主管已改過金額/分類，回傳也不能帶
    last_modified_at/last_modified_fields/light/ocr_failed 等 metadata，只能有唯讀白名單欄位。"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        cat = Category(name="餐費", level=1, sort=1, active=True)
        db.session.add(cat); db.session.commit()
        e = _mk(sid, uid, "audited", 150, datetime.now(timezone.utc),
                day_seq=1, category_id=cat.id, image_key="m1.jpg")
        e.last_modified_at = datetime.now(timezone.utc)
        e.last_modified_fields = "amount,category"
        db.session.add(e); db.session.commit()
    c = _client(app, uid)
    row = c.get("/expenses/submitted").get_json()["expenses"][0]
    for leaked in ("last_modified_at", "last_modified_fields", "light",
                   "ocr_failed", "ocr_last_error", "is_modified_by_user",
                   "created_by_name", "created_at", "status", "category_id"):
        assert leaked not in row, f"{leaked} 不應出現在員工複查回傳"
    for wanted in ("id", "doc_no", "amount", "category_name", "image_url", "summary"):
        assert wanted in row, f"{wanted} 應出現在員工複查回傳"


def test_unauth_401(app):
    r2mod._mock_singleton = None
    _seed(app)
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")  # 裝置過閘但無 session
    assert c.get("/expenses/submitted").status_code == 401
