import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.extensions import db
from app.models import Expense, Store, User, Device, Handover, Category
import app.storage.r2 as r2mod


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A"); db.session.add(s); db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id); u.set_password("0000")
        u2 = User(name="員工B", role="employee", store_id=s.id); u2.set_password("0000")
        dev = Device(client_uid="devEmp", store_id=s.id, is_approved=True)
        db.session.add_all([u, u2, dev]); db.session.commit()
        return s.id, u.id, u2.id


def _client(app, user_id):
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")
    with c.session_transaction() as sess:
        sess["user_id"] = user_id; sess["_last_request_at"] = int(time.time())
    return c


def _mk(sid, uid, status, amt, submitted_at, handover_id=None, day_seq=1,
        category_id=None, image_key=None):
    return Expense(store_id=sid, created_by=uid, status=status,
                   created_at=datetime.now(timezone.utc), submitted_at=submitted_at,
                   amount=Decimal(str(amt)), handover_id=handover_id, day_seq=day_seq,
                   category_id=category_id, image_key=image_key)


def test_lists_own_submitted_and_audited(app):
    r2mod._mock_singleton = None
    sid, uid, uid2 = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, now, day_seq=1),
            _mk(sid, uid, "audited", 200, now, day_seq=2),
            _mk(sid, uid, "draft", 300, None, day_seq=None),        # 不列
            _mk(sid, uid, "pending_ocr", 0, None, day_seq=None),    # 不列
            _mk(sid, uid2, "submitted", 999, now, day_seq=3),       # 他人不列
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert body["status"] == "ok"
    assert sorted(e["amount"] for e in body["expenses"]) == [100.0, 200.0]


def test_excludes_handed_over(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=now - timedelta(hours=1),
                     closed_by=uid, type="shift")
        db.session.add(h); db.session.commit()
        db.session.add(_mk(sid, uid, "audited", 100, now, handover_id=h.id, day_seq=1))
        db.session.commit()
    c = _client(app, uid)
    assert c.get("/expenses/submitted").get_json()["expenses"] == []


def test_time_boundary_clears_before_last_handover(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        base = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=uid, type="shift")
        db.session.add(h); db.session.commit()
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, base - timedelta(minutes=5), day_seq=1),  # 交班前→清
            _mk(sid, uid, "submitted", 200, base + timedelta(minutes=5), day_seq=2),  # 交班後→留
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert [e["amount"] for e in body["expenses"]] == [200.0]


def test_day_handover_also_clears(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        base = datetime.now(timezone.utc)
        h = Handover(store_id=sid, closed_at=base, closed_by=uid, type="day")
        db.session.add(h); db.session.commit()
        db.session.add(_mk(sid, uid, "submitted", 100, base - timedelta(minutes=5), day_seq=1))
        db.session.commit()
    c = _client(app, uid)
    assert c.get("/expenses/submitted").get_json()["expenses"] == []


def test_includes_category_name_and_image_url(app):
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        cat = Category(name="餐費", level=1, sort=1, active=True)
        db.session.add(cat); db.session.commit()
        db.session.add(_mk(sid, uid, "submitted", 100, datetime.now(timezone.utc),
                           day_seq=1, category_id=cat.id, image_key="m1.jpg"))
        db.session.commit()
    c = _client(app, uid)
    row = c.get("/expenses/submitted").get_json()["expenses"][0]
    assert row["category_name"] == "餐費"
    assert "m1.jpg" in row["image_url"]


def test_no_status_leak(app):
    """員工複查區不揭露稽核狀態：回傳每筆都不能有 status 欄位。"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add_all([
            _mk(sid, uid, "submitted", 100, now, day_seq=1),
            _mk(sid, uid, "audited", 200, now, day_seq=2),
        ]); db.session.commit()
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert len(body["expenses"]) == 2
    for row in body["expenses"]:
        assert "status" not in row


def test_note_present_but_no_audit_metadata_leak(app):
    """員工複查區可看到自己填的備註（唯讀），但仍不能揭露稽核/改動狀態
    （note 是門市內部欄位，加進白名單不能連帶鬆綁其他欄位）。"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        e = _mk(sid, uid, "audited", 100, datetime.now(timezone.utc), day_seq=1)
        e.note = "備註內容"
        # reject_reason 正常只在 status=rejected 時有值，這裡強塞是為了確認
        # 序列化器本身不會洩漏這個欄位，不代表真實資料組合
        e.reject_reason = "單據不清楚"
        e.last_modified_by = uid
        e.last_modified_at = datetime.now(timezone.utc)
        e.last_modified_fields = "amount"
        e.is_modified_by_manager = True
        db.session.add(e); db.session.commit()
    c = _client(app, uid)
    row = c.get("/expenses/submitted").get_json()["expenses"][0]
    assert row["note"] == "備註內容"
    for leaked in ("status", "reject_reason", "last_modified_by", "last_modified_at",
                   "last_modified_fields", "is_modified_by_manager"):
        assert leaked not in row, f"{leaked} 不應出現在員工複查回傳"


def test_payload_whitelist_hides_audit_metadata(app):
    """員工複查區不揭露主管稽核/改動狀態：即使主管已改過金額/分類，回傳也不能帶
    last_modified_at/last_modified_fields/light/ocr_failed 等 metadata，只能有唯讀白名單欄位。"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        cat = Category(name="餐費", level=1, sort=1, active=True)
        db.session.add(cat); db.session.commit()
        e = _mk(sid, uid, "audited", 150, datetime.now(timezone.utc),
                day_seq=1, category_id=cat.id, image_key="m1.jpg")
        e.last_modified_at = datetime.now(timezone.utc)
        e.last_modified_fields = "amount,category"
        db.session.add(e); db.session.commit()
    c = _client(app, uid)
    row = c.get("/expenses/submitted").get_json()["expenses"][0]
    for leaked in ("last_modified_at", "last_modified_fields", "light",
                   "ocr_failed", "ocr_last_error", "is_modified_by_user",
                   "created_by_name", "created_at", "status", "category_id"):
        assert leaked not in row, f"{leaked} 不應出現在員工複查回傳"
    for wanted in ("id", "doc_no", "amount", "category_name", "image_url", "summary"):
        assert wanted in row, f"{wanted} 應出現在員工複查回傳"


def test_still_listed_after_accountant_reconciles_before_handover(app):
    """會計核銷（audited → reconciled）不該讓該筆從員工複查區提早消失：
    複查區的界定是「主管尚未交/結班」，清空時機只有 handover，不是會計動作。
    status 篩選只寫 [submitted, audited] 時，會計一按核銷該列就憑空不見。"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        acct = User(name="會計", role="accountant"); acct.set_password("0000")
        db.session.add(acct); db.session.commit()
        acct_id = acct.id
        e = _mk(sid, uid, "audited", 100, datetime.now(timezone.utc), day_seq=1)
        db.session.add(e); db.session.commit()
        eid = e.id

    ac = app.test_client()
    with ac.session_transaction() as sess:
        sess["user_id"] = acct_id; sess["_last_request_at"] = int(time.time())
    assert ac.post(f"/reconcile/{eid}/approve").status_code == 200
    with app.app_context():
        assert db.session.get(Expense, eid).status == "reconciled"

    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert [e["id"] for e in body["expenses"]] == [eid], (
        "主管還沒結班，會計核銷不該讓該筆從員工複查區消失"
    )


def test_still_listed_after_accountant_rejects_before_handover(app):
    """會計退回（audited → rejected）同理：主管未結班前，該筆仍留在員工複查區。
    （複查區是唯讀的，仍不得洩漏 status / reject_reason —— 見 whitelist 守門測）"""
    r2mod._mock_singleton = None
    sid, uid, _ = _seed(app)
    with app.app_context():
        e = _mk(sid, uid, "rejected", 100, datetime.now(timezone.utc), day_seq=1)
        e.reject_reason = "金額不符"
        db.session.add(e); db.session.commit()
        eid = e.id
    c = _client(app, uid)
    body = c.get("/expenses/submitted").get_json()
    assert [x["id"] for x in body["expenses"]] == [eid]
    assert "reject_reason" not in body["expenses"][0]
    assert "status" not in body["expenses"][0]


def test_unauth_401(app):
    r2mod._mock_singleton = None
    _seed(app)
    c = app.test_client(); c.set_cookie("device_uid", "devEmp")  # 裝置過閘但無 session
    assert c.get("/expenses/submitted").status_code == 401
