import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add_all([mgr, dev]); db.session.commit()
        return mgr.id, s.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def _audited(store_id, mgr_id, amt, handover_id=None):
    return Expense(store_id=store_id, created_by=mgr_id, status="audited",
                   created_at=datetime.now(timezone.utc), amount=Decimal(str(amt)),
                   audited_by=mgr_id, audited_at=datetime.now(timezone.utc),
                   handover_id=handover_id)


def test_summary_current_day(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        # 一個已交班區間(100+50) + 當前未歸班(30)
        base = datetime(2026, 7, 7, 10, tzinfo=timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=mgr_id, type="shift")
        db.session.add(h); db.session.flush()
        db.session.add_all([_audited(sid, mgr_id, 100, h.id), _audited(sid, mgr_id, 50, h.id),
                            _audited(sid, mgr_id, 30, None)])
        db.session.commit()
    c = _client(app, mgr_id)
    body = c.get("/audit/summary").get_json()
    assert body["status"] == "ok"
    assert len(body["intervals"]) == 1
    assert body["intervals"][0]["subtotal"] == 150.0 and body["intervals"][0]["seq"] == 1
    assert body["open"]["subtotal"] == 30.0
    assert body["day_total"] == 180.0


def test_summary_excludes_before_day_close(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        t0 = datetime(2026, 7, 6, 10, tzinfo=timezone.utc)
        # 昨天結班(type=day) 含 200
        d = Handover(store_id=sid, closed_at=t0, closed_by=mgr_id, type="day")
        db.session.add(d); db.session.flush()
        db.session.add(_audited(sid, mgr_id, 200, d.id))
        # 今天當前未歸班 40
        db.session.add(_audited(sid, mgr_id, 40, None))
        db.session.commit()
    c = _client(app, mgr_id)
    body = c.get("/audit/summary").get_json()
    assert body["intervals"] == []            # 昨天已結班，不算今天
    assert body["open"]["subtotal"] == 40.0
    assert body["day_total"] == 40.0


def test_summary_past_day_before_id(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        t_prev = datetime(2026, 7, 5, 10, tzinfo=timezone.utc)
        t_day = datetime(2026, 7, 6, 10, tzinfo=timezone.utc)
        # 更早一天的結班(下界)，含 999，不應被算進本次查詢
        prev_day = Handover(store_id=sid, closed_at=t_prev, closed_by=mgr_id, type="day")
        db.session.add(prev_day); db.session.flush()
        db.session.add(_audited(sid, mgr_id, 999, prev_day.id))
        # 目標當天：一個 shift 交班(100+50) 後接著 day 結班(20)
        h = Handover(store_id=sid, closed_at=t_day - timedelta(hours=2),
                     closed_by=mgr_id, type="shift")
        db.session.add(h); db.session.flush()
        db.session.add_all([_audited(sid, mgr_id, 100, h.id), _audited(sid, mgr_id, 50, h.id)])
        d = Handover(store_id=sid, closed_at=t_day, closed_by=mgr_id, type="day")
        db.session.add(d); db.session.flush()
        db.session.add(_audited(sid, mgr_id, 20, d.id))
        # 今天當前未歸班，查過去日時不應出現
        db.session.add(_audited(sid, mgr_id, 40, None))
        db.session.commit()
        target_id = d.id
    c = _client(app, mgr_id)
    body = c.get(f"/audit/summary?before={target_id}").get_json()
    assert body["status"] == "ok"
    assert len(body["intervals"]) == 2
    assert body["intervals"][0]["subtotal"] == 150.0
    assert body["intervals"][1]["subtotal"] == 20.0
    assert body["open"] in ({"subtotal": 0.0, "count": 0}, {"subtotal": 0, "count": 0})
    assert body["day_total"] == 170.0          # 不含未歸班 40，不含前一天 999


def test_summary_before_not_found(app):
    mgr_id, sid = _seed(app)
    c = _client(app, mgr_id)
    resp = c.get("/audit/summary?before=999999")
    assert resp.status_code == 404


def test_summary_before_cross_store_forbidden(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        other = Store(name="B", code="B"); db.session.add(other); db.session.commit()
        other_mgr = User(name="mgr2", role="manager", store_id=other.id)
        other_mgr.set_password("1234")
        db.session.add(other_mgr); db.session.commit()
        d = Handover(store_id=other.id, closed_at=datetime.now(timezone.utc),
                     closed_by=other_mgr.id, type="day")
        db.session.add(d); db.session.commit()
        other_day_id = d.id
    c = _client(app, mgr_id)
    resp = c.get(f"/audit/summary?before={other_day_id}")
    assert resp.status_code == 403


def test_summary_before_shift_type_bad_request(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        h = Handover(store_id=sid, closed_at=datetime.now(timezone.utc),
                     closed_by=mgr_id, type="shift")
        db.session.add(h); db.session.commit()
        shift_id = h.id
    c = _client(app, mgr_id)
    resp = c.get(f"/audit/summary?before={shift_id}")
    assert resp.status_code == 400
