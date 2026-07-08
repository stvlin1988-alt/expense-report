import time
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Store, User, Device, Handover


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, dev]); db.session.commit()
        base = datetime(2026, 7, 6, 10, tzinfo=timezone.utc)
        d1 = Handover(store_id=s.id, closed_at=base, closed_by=mgr.id, type="day")
        sh = Handover(store_id=s.id, closed_at=base + timedelta(hours=5), closed_by=mgr.id, type="shift")
        d2 = Handover(store_id=s.id, closed_at=base + timedelta(days=1), closed_by=mgr.id, type="day")
        db.session.add_all([d1, sh, d2]); db.session.commit()
        return mgr.id, d1.id, d2.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_days_only_day_type_desc(app):
    mgr_id, d1, d2 = _seed(app)
    body = _client(app, mgr_id).get("/audit/days").get_json()
    assert body["status"] == "ok"
    ids = [d["handover_id"] for d in body["days"]]
    assert ids == [d2, d1]          # 只含 type=day，closed_at desc；不含 shift
