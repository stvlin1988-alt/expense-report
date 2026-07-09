import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Expense, Store, User, Device, Category
import app.storage.r2 as r2mod


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        cat = Category(name="食材", level=1, sort=1)
        db.session.add_all([u, dev, cat]); db.session.commit()
        return s.id, u.id, cat.id


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


def test_patch_amount_sets_modified_and_green(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True,
                 ocr_is_handwritten=False, ocr_confidence=0.9)
    c = _client(app, uid)
    body = c.patch(f"/expenses/{eid}", json={"amount": 250}).get_json()
    assert body["status"] == "ok"
    assert body["expense"]["amount"] == 250.0
    assert body["expense"]["is_modified_by_user"] is True
    # 人改過金額且金額 OK → 已確認 → 綠（不再是紅）
    assert body["expense"]["light"] == "green"


def test_patch_same_amount_not_modified(app):
    # 送出前前端會無條件帶 amount/category_id；值沒變就不該標記 modified（否則主管端全紅）
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True, category_id=cid,
                 ocr_is_handwritten=False, ocr_confidence=0.9)
    c = _client(app, uid)
    body = c.patch(f"/expenses/{eid}", json={"amount": 100, "category_id": cid}).get_json()
    assert body["expense"]["is_modified_by_user"] is False
    assert body["expense"]["light"] == "green"


def test_patch_same_amount_decimal_equiv_not_modified(app):
    # 1290 vs Decimal('1290.00') 視為相同、不標記 modified
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=1290, amount_parse_ok=True,
                 ocr_is_handwritten=False, ocr_confidence=0.9)
    c = _client(app, uid)
    body = c.patch(f"/expenses/{eid}", json={"amount": 1290}).get_json()
    assert body["expense"]["is_modified_by_user"] is False


def test_patch_only_summary_not_modified(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True,
                 ocr_is_handwritten=False, ocr_confidence=0.9)
    c = _client(app, uid)
    body = c.patch(f"/expenses/{eid}", json={"summary": "改摘要"}).get_json()
    assert body["expense"]["is_modified_by_user"] is False   # 只改摘要不算改金額/分類
    assert body["expense"]["light"] == "green"


def test_patch_rejects_non_draft(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid)
    with app.app_context():
        db.session.get(Expense, eid).status = "submitted"; db.session.commit()
    c = _client(app, uid)
    assert c.patch(f"/expenses/{eid}", json={"amount": 9}).status_code == 409


def test_patch_rejects_invalid_category_id(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    # 原本有分類，patch 成無效 id → 收斂為 None（這是真的變動）→ 標記 modified
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True, category_id=cid)
    c = _client(app, uid)
    resp = c.patch(f"/expenses/{eid}", json={"category_id": 99999})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["expense"]["category_id"] is None
    assert body["expense"]["is_modified_by_user"] is True
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.category_id is None
        assert e.is_modified_by_user is True


def test_submit_rejects_draft_without_valid_amount(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, amount=None, amount_parse_ok=False)
    c = _client(app, uid)
    resp = c.post(f"/expenses/{eid}/submit")
    assert resp.status_code == 400
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft"


def test_submit_transitions_and_sets_business_date(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    # 台灣 07:59 → 前一日
    from app.expenses.logic import TW_TZ
    created = datetime(2026, 7, 7, 7, 59, tzinfo=TW_TZ).astimezone(timezone.utc)
    eid = _draft(app, sid, uid, amount=100, amount_parse_ok=True)
    with app.app_context():
        db.session.get(Expense, eid).created_at = created; db.session.commit()
    c = _client(app, uid)
    assert c.post(f"/expenses/{eid}/submit").get_json()["status"] == "ok"
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "submitted"
        assert e.business_date.isoformat() == "2026-07-06"
        assert e.submitted_at is not None


def test_delete_removes_row_and_r2(app):
    r2mod._mock_singleton = None
    sid, uid, cid = _seed(app)
    eid = _draft(app, sid, uid, image_key="m.jpg", thumb_key="m_thumb.jpg")
    from app.storage.r2 import get_storage
    with app.app_context():
        get_storage().put("m.jpg", b"x", "image/jpeg")
        get_storage().put("m_thumb.jpg", b"x", "image/jpeg")
    c = _client(app, uid)
    assert c.delete(f"/expenses/{eid}").get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(Expense, eid) is None
        assert "m.jpg" not in r2mod._mock_singleton.objects
