import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, AuditLog

_TW = timezone(timedelta(hours=8))


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        db.session.add_all([emp, mgr]); db.session.commit()
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        db.session.add(dev); db.session.commit()
        e = Expense(store_id=s.id, created_by=emp.id, status="draft",
                    created_at=datetime.now(timezone.utc), amount=Decimal("100"), summary="午餐")
        db.session.add(e); db.session.commit()
        # 台灣 2026-07-09 之內的兩筆（一 emp edit、一 mgr check）
        t1 = datetime(2026, 7, 9, 10, 0, tzinfo=_TW).astimezone(timezone.utc)  # 09 TW
        t2 = datetime(2026, 7, 9, 23, 30, tzinfo=_TW).astimezone(timezone.utc) # 09 TW（UTC 已跨到 07-09 15:30）
        # 台灣 2026-07-10 的一筆（不應出現在 07-09 查詢）
        t3 = datetime(2026, 7, 10, 0, 30, tzinfo=_TW).astimezone(timezone.utc)
        db.session.add_all([
            AuditLog(expense_id=e.id, actor_user_id=emp.id, action="edit",
                     before_json={}, after_json={}, ts=t1),
            AuditLog(expense_id=e.id, actor_user_id=mgr.id, action="check",
                     before_json=None, after_json={}, ts=t2),
            AuditLog(expense_id=e.id, actor_user_id=emp.id, action="edit",
                     before_json={}, after_json={}, ts=t3),
        ])
        db.session.commit()
        return {"store": s.id, "emp": emp.id, "mgr": mgr.id}


def _client(app, uid, device="dev1"):
    c = app.test_client(); c.set_cookie("device_uid", device)
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_manager_logs_by_date(app):
    ids = _seed(app)
    c = _client(app, ids["mgr"])
    r = c.get("/audit/logs?date=2026-07-09")
    assert r.status_code == 200
    body = r.get_json()
    # 07-09 兩筆、依 ts 降冪（check 在前）
    assert [i["action"] for i in body["items"]] == ["check", "edit"]
    assert body["items"][0]["summary"] == "午餐"
    assert {a["name"] for a in body["actors"]} == {"emp", "mgr"}


def test_date_excludes_other_day(app):
    ids = _seed(app)
    r = _client(app, ids["mgr"]).get("/audit/logs?date=2026-07-10")
    assert [i["action"] for i in r.get_json()["items"]] == ["edit"]   # 只剩 t3 那筆


def test_actor_filter(app):
    ids = _seed(app)
    r = _client(app, ids["mgr"]).get(f"/audit/logs?date=2026-07-09&actor_id={ids['emp']}")
    items = r.get_json()["items"]
    assert len(items) == 1 and items[0]["action"] == "edit"


def test_bad_date_400(app):
    ids = _seed(app)
    assert _client(app, ids["mgr"]).get("/audit/logs?date=nope").status_code == 400


def test_super_admin_needs_store_id(app):
    ids = _seed(app)
    with app.app_context():
        sup = User(name="sup", role="super_admin", store_id=ids["store"]); sup.set_password("1234")
        db.session.add(sup); db.session.commit(); sup_id = sup.id
    c = _client(app, sup_id)
    assert c.get("/audit/logs?date=2026-07-09").status_code == 400
    assert c.get(f"/audit/logs?date=2026-07-09&store_id={ids['store']}").status_code == 200


def test_cross_store_isolation(app):
    ids = _seed(app)
    with app.app_context():
        s2 = Store(name="B", code="B"); db.session.add(s2); db.session.commit()
        m2 = User(name="m2", role="manager", store_id=s2.id); m2.set_password("1234")
        db.session.add(m2); db.session.commit()
        dev2 = Device(client_uid="dev2", store_id=s2.id, is_approved=True)
        db.session.add(dev2); db.session.commit()
        m2_id = m2.id
    c = _client(app, m2_id, device="dev2")
    r = c.get("/audit/logs?date=2026-07-09")
    assert r.status_code == 200
    assert r.get_json()["items"] == []
