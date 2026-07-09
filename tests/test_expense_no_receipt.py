import io, base64, time
from PIL import Image
from app.extensions import db
from app.models import Expense, Store, User, Device
import app.storage.r2 as r2mod


def _b64_jpeg(w=1200, h=900):
    buf = io.BytesIO(); Image.new("RGB", (w, h), (200, 180, 160)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        return s.id, u.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_no_receipt_creates_draft(app):
    # 無單據單改成進暫存區 draft，讓員工確認正確再送出（不再直接 submitted）
    sid, uid = _seed(app)
    c = _client(app, uid)
    resp = c.post("/expenses/no-receipt",
                  json={"summary": "計程車", "amount": 250, "reason": "臨時叫車無收據"})
    assert resp.status_code == 200
    eid = resp.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "draft"
        assert e.is_no_receipt is True
        assert e.image_key is None           # 沒拍照 → 無圖
        assert e.no_receipt_reason == "臨時叫車無收據"
        assert e.business_date is None       # 送出時才算
        assert e.submitted_at is None
        assert float(e.amount) == 250.0


def test_no_receipt_with_optional_photo_stores_image_no_ocr(app):
    # 無單據可選附一張佐證照 → 壓縮存 R2、不跑 OCR
    r2mod._mock_singleton = None
    sid, uid = _seed(app)
    c = _client(app, uid)
    resp = c.post("/expenses/no-receipt",
                  json={"summary": "停車", "amount": 60, "image": _b64_jpeg()})
    assert resp.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, resp.get_json()["id"])
        assert e.is_no_receipt is True
        assert e.image_key is not None       # 有存圖
        assert e.status == "draft"           # 仍是 draft、沒進 pending_ocr
        assert e.ocr_attempts == 0           # 沒跑 OCR


def test_no_receipt_draft_shows_in_pending_and_can_submit(app):
    # 建立後員工在暫存區看得到；確認後送出才變 submitted 並設 business_date
    sid, uid = _seed(app)
    c = _client(app, uid)
    eid = c.post("/expenses/no-receipt",
                 json={"summary": "計程車", "amount": 250, "reason": "臨時"}).get_json()["id"]
    listed = c.get("/expenses/pending").get_json()["expenses"]
    assert any(x["id"] == eid for x in listed)
    r = c.post(f"/expenses/{eid}/submit")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "submitted"
        assert e.business_date is not None
        assert e.submitted_at is not None


def test_no_receipt_reason_optional(app):
    # 原因（備註）非必填：不帶也能建
    sid, uid = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"summary": "x", "amount": 1})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, r.get_json()["id"])
        assert e.no_receipt_reason is None


def test_no_receipt_requires_amount(app):
    sid, uid = _seed(app)
    c = _client(app, uid)
    r = c.post("/expenses/no-receipt", json={"summary": "x", "reason": "y"})
    assert r.status_code == 400
