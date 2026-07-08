from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Store, User, Expense
from app.storage.r2 import get_storage
import app.expenses.tasks as tasks


def _stale_expense(app, attempts, image_key="k1"):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="e", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        old = datetime.now(timezone.utc) - timedelta(seconds=9999)
        e = Expense(store_id=s.id, created_by=u.id, status="pending_ocr",
                    created_at=old, ocr_attempts=attempts, image_key=image_key)
        db.session.add(e); db.session.commit()
        return u.id, e.id


def test_below_limit_reschedules(app, monkeypatch):
    app.config["OCR_MAX_ROUNDS"] = 3
    uid, eid = _stale_expense(app, attempts=1)
    with app.app_context():
        get_storage().put("k1", b"img", "image/jpeg")
    called = []
    monkeypatch.setattr(tasks, "schedule_ocr", lambda *a, **k: called.append(a))
    with app.app_context():
        tasks.reconcile_stale(uid)
        e = db.session.get(Expense, eid)
        assert e.status == "pending_ocr"    # 重排、不收斂
    assert len(called) == 1


def test_at_limit_converges_failed(app, monkeypatch):
    app.config["OCR_MAX_ROUNDS"] = 3
    uid, eid = _stale_expense(app, attempts=3)
    monkeypatch.setattr(tasks, "schedule_ocr", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該重排")))
    with app.app_context():
        tasks.reconcile_stale(uid)
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True


def test_missing_image_converges_failed(app, monkeypatch):
    app.config["OCR_MAX_ROUNDS"] = 3
    uid, eid = _stale_expense(app, attempts=0, image_key="gone")  # R2 沒這 key
    monkeypatch.setattr(tasks, "schedule_ocr", lambda *a, **k: called.append(a))
    called = []
    with app.app_context():
        tasks.reconcile_stale(uid)
        e = db.session.get(Expense, eid)
        assert e.status == "draft" and e.ocr_failed is True
    assert called == []
