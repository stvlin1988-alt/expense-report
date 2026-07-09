import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover
from app.expenses.logic import compute_business_date


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


def _exp(store_id, mgr_id, amt, bd, status="audited"):
    return Expense(store_id=store_id, created_by=mgr_id, status=status,
                   created_at=datetime.now(timezone.utc), amount=Decimal(str(amt)),
                   amount_parse_ok=True, business_date=bd,
                   submitted_at=datetime.now(timezone.utc))


def test_summary_dates_lists_distinct_business_dates_desc_incl_today(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        db.session.add_all([
            _exp(sid, mgr_id, 100, date(2026, 7, 7)),
            _exp(sid, mgr_id, 50, date(2026, 7, 8)),
            _exp(sid, mgr_id, 30, date(2026, 7, 8)),
        ])
        db.session.commit()
    body = _client(app, mgr_id).get("/audit/summary-dates").get_json()
    assert body["status"] == "ok"
    today = compute_business_date(datetime.now(timezone.utc)).isoformat()
    # 含今日、去重、由新到舊
    assert body["dates"][0] == today or today in body["dates"]
    assert "2026-07-08" in body["dates"]
    assert "2026-07-07" in body["dates"]
    # 7/8 只出現一次（去重）
    assert body["dates"].count("2026-07-08") == 1
    # 由新到舊
    idx8 = body["dates"].index("2026-07-08")
    idx7 = body["dates"].index("2026-07-07")
    assert idx8 < idx7


def test_by_date_total_and_open_group(app):
    mgr_id, sid = _seed(app)
    with app.app_context():
        db.session.add_all([
            _exp(sid, mgr_id, 100, date(2026, 7, 8)),
            _exp(sid, mgr_id, 50, date(2026, 7, 8), status="submitted"),
            _exp(sid, mgr_id, 999, date(2026, 7, 7)),   # 別天，不算
        ])
        db.session.commit()
    body = _client(app, mgr_id).get("/audit/by-date?date=2026-07-08").get_json()
    assert body["status"] == "ok"
    assert body["date"] == "2026-07-08"
    assert body["count"] == 2
    assert body["total"] == 150.0
    # 都沒歸班 → 一個「當前未歸班」組
    assert len(body["shifts"]) == 1
    assert body["shifts"][0]["handover_id"] is None
    assert body["shifts"][0]["type"] == "open"
    assert body["shifts"][0]["count"] == 2
    assert "light" in body["shifts"][0]["items"][0]  # 帶主管端燈號


def test_by_date_groups_by_shift(app):
    # 同一天分兩班（兩個 handover）+ 一張未歸班 → 3 組，各自小計、seq 遞增
    mgr_id, sid = _seed(app)
    with app.app_context():
        base = datetime(2026, 7, 8, 2, tzinfo=timezone.utc)
        h1 = Handover(store_id=sid, closed_at=base, closed_by=mgr_id, type="shift")
        h2 = Handover(store_id=sid, closed_at=base.replace(hour=8), closed_by=mgr_id, type="day")
        db.session.add_all([h1, h2]); db.session.flush()
        e1 = _exp(sid, mgr_id, 100, date(2026, 7, 8)); e1.handover_id = h1.id
        e2 = _exp(sid, mgr_id, 200, date(2026, 7, 8)); e2.handover_id = h2.id
        e3 = _exp(sid, mgr_id, 30, date(2026, 7, 8))   # 未歸班
        db.session.add_all([e1, e2, e3]); db.session.commit()
    body = _client(app, mgr_id).get("/audit/by-date?date=2026-07-08").get_json()
    shifts = body["shifts"]
    assert len(shifts) == 3
    # 依 closed_at 排序：第1班(h1,shift,100)、第2班(h2,day,200)、當前未歸班(30)
    assert shifts[0]["seq"] == 1 and shifts[0]["type"] == "shift" and shifts[0]["subtotal"] == 100.0
    assert shifts[1]["seq"] == 2 and shifts[1]["type"] == "day" and shifts[1]["subtotal"] == 200.0
    assert shifts[2]["handover_id"] is None and shifts[2]["subtotal"] == 30.0
    assert body["total"] == 330.0


def test_by_date_bad_date_400(app):
    mgr_id, sid = _seed(app)
    r = _client(app, mgr_id).get("/audit/by-date?date=notadate")
    assert r.status_code == 400


def test_by_date_scoped_to_store(app):
    # 別家店的單不會出現
    mgr_id, sid = _seed(app)
    with app.app_context():
        other = Store(name="B", code="B"); db.session.add(other); db.session.commit()
        db.session.add(_exp(other.id, mgr_id, 777, date(2026, 7, 8)))
        db.session.add(_exp(sid, mgr_id, 100, date(2026, 7, 8)))
        db.session.commit()
    body = _client(app, mgr_id).get("/audit/by-date?date=2026-07-08").get_json()
    assert body["total"] == 100.0
    assert body["count"] == 1
