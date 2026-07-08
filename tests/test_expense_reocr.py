import time
from datetime import datetime, timezone
from app.extensions import db
from app.models import Store, User, Device, Expense
from app.storage.r2 import get_storage
import app.expenses.tasks as tasks


def _seed(app, ocr_failed=True, image_key="k1"):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([u, dev]); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc), ocr_failed=ocr_failed,
                    image_key=image_key)
        db.session.add(e); db.session.commit()
        return u.id, e.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_reocr_resets_and_schedules(app, monkeypatch):
    uid, eid = _seed(app)
    with app.app_context():
        get_storage().put("k1", b"img", "image/jpeg")
    called = []
    monkeypatch.setattr("app.expenses.routes.schedule_ocr", lambda *a, **k: called.append(a))
    r = _client(app, uid).post(f"/expenses/{eid}/reocr")
    assert r.status_code == 202
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr" and e.ocr_failed is False and e.ocr_attempts == 0
    assert len(called) == 1


def test_reocr_non_failed_409(app):
    uid, eid = _seed(app, ocr_failed=False)
    assert _client(app, uid).post(f"/expenses/{eid}/reocr").status_code == 409


def test_reocr_missing_image_400(app):
    uid, eid = _seed(app, image_key="gone")
    assert _client(app, uid).post(f"/expenses/{eid}/reocr").status_code == 400
