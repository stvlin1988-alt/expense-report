import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover, Category


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); s2 = Store(name="B", code="B")
        db.session.add_all([s, s2]); db.session.commit()
        mgr = User(name="小王", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="員工", role="employee", store_id=s.id); emp.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        cat = Category(name="食材", level=2, sort=1)
        db.session.add_all([mgr, emp, dev, cat]); db.session.commit()
        now = datetime.now(timezone.utc)
        h = Handover(store_id=s.id, closed_at=now, closed_by=mgr.id, type="shift")
        hb = Handover(store_id=s2.id, closed_at=now, closed_by=mgr.id, type="shift")
        db.session.add_all([h, hb]); db.session.commit()
        # 已歸班（屬 h）
        e1 = Expense(store_id=s.id, created_by=emp.id, status="audited", created_at=now,
                     business_date=date(2026, 7, 8), amount=Decimal("100"), category_id=cat.id,
                     audited_by=mgr.id, audited_at=now, is_modified_by_manager=True, handover_id=h.id)
        # 當前未歸班（audited, handover_id null）
        e2 = Expense(store_id=s.id, created_by=emp.id, status="audited", created_at=now,
                     amount=Decimal("50"), audited_by=mgr.id, audited_at=now, handover_id=None)
        db.session.add_all([e1, e2]); db.session.commit()
        return mgr.id, s.id, h.id, hb.id, e1.id, e2.id


def _client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def test_handover_items(app):
    mgr_id, sid, hid, _, e1, _ = _seed(app)
    body = _client(app, mgr_id).get(f"/audit/handover/{hid}/items").get_json()
    assert body["status"] == "ok" and len(body["items"]) == 1
    it = body["items"][0]
    assert it["id"] == e1 and it["audited_by_name"] == "小王"
    assert it["is_modified_by_manager"] is True and it["category_name"] == "食材"
    assert "image_url" in it and it["audited_at"] is not None


def test_handover_items_cross_store_forbidden(app):
    mgr_id, sid, _, hb, _, _ = _seed(app)
    assert _client(app, mgr_id).get(f"/audit/handover/{hb}/items").status_code == 403


def test_handover_items_not_found_404(app):
    mgr_id, sid, _, _, _, _ = _seed(app)
    assert _client(app, mgr_id).get("/audit/handover/9999/items").status_code == 404


def test_open_items_only_audited_unassigned(app):
    mgr_id, sid, _, _, _, e2 = _seed(app)
    body = _client(app, mgr_id).get("/audit/open-items").get_json()
    assert body["status"] == "ok"
    assert [it["id"] for it in body["items"]] == [e2]   # 只回當前未歸班那筆
