"""C1 回歸：audited 在本 branch 變成過渡狀態（會計會把它推進 reconciled/rejected），
主管端所有彙整查詢卻還在用 status=="audited" 當「主管已打勾」的判斷式，
導致會計一動手，這些彙整就悄悄漏掉那些單。
「主管已打勾／已認列」這件事現在對應的集合是 CHECKED_STATUSES = (audited, reconciled, rejected)。"""
import time
from datetime import datetime, timezone, date
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Device, Expense, Handover, Category


def _seed(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        mgr = User(name="mgr", role="manager", store_id=s.id); mgr.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s.id); emp.set_password("1234")
        acct = User(name="acct", role="accountant"); acct.set_password("1234")
        dev = Device(client_uid="dev1", store_id=s.id, is_approved=True)
        cat = Category(name="雜項", level=1)
        db.session.add_all([mgr, emp, acct, dev, cat]); db.session.commit()
        return mgr.id, emp.id, acct.id, s.id, cat.id


def _mgr_client(app, uid):
    c = app.test_client(); c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def _acct_client(app, uid):
    # 會計是跨店角色，不吃 device 綁定；沿用 test_reconcile_* 的既有寫法（不帶 device_uid cookie 也可）
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = uid; sess["_last_request_at"] = int(time.time())
    return c


def _audited(store_id, emp_id, mgr_id, amt, bd, handover_id=None):
    now = datetime.now(timezone.utc)
    return Expense(store_id=store_id, created_by=emp_id, status="audited",
                   created_at=now, submitted_at=now, business_date=bd,
                   amount=Decimal(str(amt)), amount_parse_ok=True,
                   audited_by=mgr_id, audited_at=now, handover_id=handover_id)


def test_closed_day_total_unchanged_after_accountant_reconciles(app):
    """已結班(closed) 的營業日：會計把裡面一筆單核銷後，/audit/by-date 的當日總額不應改變。
    修正前：by-date 的 query 只認 status in (submitted, audited)，reconciled 一出現就從
    總額消失 —— 一個已經結束的營業日，總額卻會因為會計動作事後改變（甚至歸零）。"""
    mgr_id, emp_id, acct_id, sid, cat_id = _seed(app)
    bd = date(2026, 7, 8)
    with app.app_context():
        h = Handover(store_id=sid, closed_at=datetime(2026, 7, 8, 12, tzinfo=timezone.utc),
                     closed_by=mgr_id, type="day")
        db.session.add(h); db.session.flush()
        e = _audited(sid, emp_id, mgr_id, 100, bd, handover_id=h.id)
        db.session.add(e); db.session.commit()
        eid = e.id

    mgr = _mgr_client(app, mgr_id)
    before = mgr.get(f"/audit/by-date?date={bd.isoformat()}").get_json()
    assert before["total"] == 100.0
    assert before["count"] == 1

    acct = _acct_client(app, acct_id)
    assert acct.post(f"/reconcile/{eid}/approve").status_code == 200
    with app.app_context():
        assert db.session.get(Expense, eid).status == "reconciled"

    after = mgr.get(f"/audit/by-date?date={bd.isoformat()}").get_json()
    assert after["total"] == 100.0, "已結班營業日的總額不該因會計核銷而改變/歸零"
    assert after["count"] == 1


def test_handover_items_count_matches_interval_subtotal(app):
    """/audit/handover/<hid>/items 沒有 status 篩選，永遠列出該區間全部單據；
    /audit/summary 的區間小計不能漏算已被會計動過(reconciled/rejected)的單，
    否則畫面會出現「有明細、小計卻是 0」的自相矛盾。"""
    mgr_id, emp_id, acct_id, sid, cat_id = _seed(app)
    bd = date(2026, 7, 8)
    with app.app_context():
        e1 = _audited(sid, emp_id, mgr_id, 100, bd)
        e2 = _audited(sid, emp_id, mgr_id, 50, bd)
        db.session.add_all([e1, e2]); db.session.commit()
        e1_id, e2_id = e1.id, e2.id

    mgr = _mgr_client(app, mgr_id)
    r = mgr.post("/audit/handover", json={"type": "shift"}).get_json()
    assert r["status"] == "ok" and r["count"] == 2
    hid = r["handover_id"]

    acct = _acct_client(app, acct_id)
    assert acct.post(f"/reconcile/{e1_id}/approve").status_code == 200
    assert acct.post(f"/reconcile/{e2_id}/reject", json={"reason": "測試"}).status_code == 200

    items_body = mgr.get(f"/audit/handover/{hid}/items").get_json()
    assert len(items_body["items"]) == 2, "handover_items 不篩 status，應仍列出兩筆"

    summary_body = mgr.get("/audit/summary").get_json()
    interval = [i for i in summary_body["intervals"] if i["handover_id"] == hid][0]
    assert interval["count"] == 2
    assert interval["subtotal"] == 150.0, (
        "有兩筆明細卻小計不等於 150 —— 明細筆數與小計自相矛盾"
    )


def test_expense_reconciled_before_handover_close_still_gets_swept(app):
    """會計在主管結班之前就核銷的單：交班時仍要被掃到、拿到 handover_id
    （之前的 bug：一旦不是 audited，handover 掃描永遠不會再碰它，永久漏編班別）。"""
    mgr_id, emp_id, acct_id, sid, cat_id = _seed(app)
    bd = date(2026, 7, 8)
    with app.app_context():
        e = _audited(sid, emp_id, mgr_id, 100, bd)
        db.session.add(e); db.session.commit()
        eid = e.id

    acct = _acct_client(app, acct_id)
    assert acct.post(f"/reconcile/{eid}/approve").status_code == 200
    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.status == "reconciled"
        assert e.handover_id is None   # 核銷當下主管還沒結班

    mgr = _mgr_client(app, mgr_id)
    r = mgr.post("/audit/handover", json={"type": "shift"}).get_json()
    assert r["status"] == "ok" and r["count"] == 1

    with app.app_context():
        e = db.session.get(Expense, eid)
        assert e.handover_id == r["handover_id"], (
            "會計提早核銷的單，主管結班時應該被掃到並拿到 handover_id"
        )


def test_manual_entry_counted_in_by_date_but_never_swept_by_handover(app):
    """會計自建 manual 單：是門市真實支出，該計入該店該日 by-date 總額；
    但它沒經過主管打勾/交接班，handover_id 應該永遠維持 NULL —— 不能被之後任何一次
    handover 交班掃描誤收編（那樣會讓一筆跟這班無關的錢混進某個班別的小計）。"""
    mgr_id, emp_id, acct_id, sid, cat_id = _seed(app)
    bd = date(2026, 7, 8)

    acct = _acct_client(app, acct_id)
    r = acct.post("/reconcile/manual", json={
        "store_id": sid, "business_date": bd.isoformat(),
        "summary": "上期漏帳", "amount": 500, "category_id": cat_id,
    })
    assert r.status_code == 200
    manual_id = r.get_json()["id"]
    with app.app_context():
        m = db.session.get(Expense, manual_id)
        assert m.status == "reconciled"
        assert m.handover_id is None

    mgr = _mgr_client(app, mgr_id)
    body = mgr.get(f"/audit/by-date?date={bd.isoformat()}").get_json()
    assert body["total"] == 500.0
    assert body["count"] == 1

    # 同一家店另有一筆真的被主管打勾的單，主管結班時應該正常被掃到；
    # manual 單即使跟它同店同天，也不該被一起掃進這個班別。
    with app.app_context():
        real = _audited(sid, emp_id, mgr_id, 80, bd)
        db.session.add(real); db.session.commit()
        real_id = real.id

    r2 = mgr.post("/audit/handover", json={"type": "shift"}).get_json()
    assert r2["status"] == "ok" and r2["count"] == 1, "只有那筆真的 audited 的單該被掃到"

    with app.app_context():
        assert db.session.get(Expense, real_id).handover_id == r2["handover_id"]
        assert db.session.get(Expense, manual_id).handover_id is None, (
            "manual 單不該被交接班掃描誤收編，handover_id 應維持 NULL"
        )
