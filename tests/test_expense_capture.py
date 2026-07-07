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


def _client(app, uid_cookie="devEmp", user_id=None):
    c = app.test_client(); c.set_cookie("device_uid", uid_cookie)
    if user_id:
        with c.session_transaction() as sess:
            sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def test_capture_creates_draft_via_sync_ocr(app):
    r2mod._mock_singleton = None
    sid, uid = _seed(app)
    c = _client(app, user_id=uid)
    resp = c.post("/expenses", json={"image": _b64_jpeg()})
    assert resp.status_code == 202
    eid = resp.get_json()["id"]
    with app.app_context():
        e = db.session.get(Expense, eid)
        # TestConfig EXPENSE_OCR_SYNC=True + MockProvider → 已轉 draft
        assert e.status == "draft"
        assert e.summary == "測試單據"        # MockProvider 預設
        assert e.amount is not None
        assert e.image_key and e.thumb_key
        assert e.image_key in r2mod._mock_singleton.objects


def test_capture_requires_login(app):
    _seed(app)
    c = _client(app)  # 無 session user
    resp = c.post("/expenses", json={"image": _b64_jpeg()})
    assert resp.status_code == 401


def test_capture_no_image_400(app):
    sid, uid = _seed(app)
    c = _client(app, user_id=uid)
    assert c.post("/expenses", json={}).status_code == 400
