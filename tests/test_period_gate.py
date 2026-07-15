import time
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import Store, User, Device, Expense, Category, AccountingPeriod
from app.periods.service import is_period_closed

# 登入/建單 helper 照 tests/test_reconcile_approve.py / tests/test_audit_check.py 現成寫法


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def login_as(client, app, role):
    with app.app_context():
        uid = User.query.filter_by(role=role).first().id
    _set_session(client, uid)


# ---------------------------------------------------------------------------
# 單元測試：is_period_closed
# ---------------------------------------------------------------------------

def test_is_period_closed_true_for_closed_period(app):
    with app.app_context():
        db.create_all()
        p = AccountingPeriod(label="2026-01", start_date=date(2026, 1, 1),
                              end_date=date(2026, 1, 31),
                              lock_at=datetime(2026, 2, 2, 4, 0, tzinfo=timezone.utc),
                              status="closed")
        db.session.add(p)
        db.session.commit()
        now = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        assert is_period_closed(p.id, now) is True


def test_is_period_closed_false_for_none():
    now = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    assert is_period_closed(None, now) is False


def test_is_period_closed_false_for_open_period(app):
    with app.app_context():
        db.create_all()
        p = AccountingPeriod(label="2026-07", start_date=date(2026, 7, 1),
                              end_date=date(2026, 7, 31),
                              lock_at=datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc),
                              status="open")
        db.session.add(p)
        db.session.commit()
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        assert is_period_closed(p.id, now) is False


def test_is_period_closed_false_for_nonexistent_period_id(app):
    with app.app_context():
        db.create_all()
        now = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        assert is_period_closed(999999, now) is False


# ---------------------------------------------------------------------------
# 整合測試：封月後各寫入端點要擋
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(app):
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        mgr = User(name="主管", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        acct = User(name="會計", role="accountant")  # 跨店角色，不吃 store_id
        acct.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        cat1 = Category(name="文具", level=1)
        db.session.add_all([emp, mgr, acct, dev, cat1])
        db.session.commit()

        closed_period = AccountingPeriod(
            label="2026-06", start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
            lock_at=datetime(2026, 7, 2, 4, 0, tzinfo=timezone.utc), status="closed")
        open_period = AccountingPeriod(
            label="2026-07", start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
            lock_at=datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc), status="open")
        db.session.add_all([closed_period, open_period])
        db.session.commit()

        now = datetime.now(timezone.utc)
        closed_bd = date(2026, 6, 15)
        open_bd = date(2026, 7, 15)

        audited_closed = Expense(
            store_id=s1.id, created_by=emp.id, status="audited",
            created_at=now, business_date=closed_bd,
            amount=Decimal("200"), amount_parse_ok=True, submitted_at=now,
            category_id=cat1.id, period_id=closed_period.id)
        audited_open = Expense(
            store_id=s1.id, created_by=emp.id, status="audited",
            created_at=now, business_date=open_bd,
            amount=Decimal("150"), amount_parse_ok=True, submitted_at=now,
            category_id=cat1.id, period_id=open_period.id)
        reconciled_closed = Expense(
            store_id=s1.id, created_by=emp.id, status="reconciled",
            created_at=now, business_date=closed_bd,
            amount=Decimal("120"), amount_parse_ok=True, submitted_at=now,
            reconciled_by=acct.id, reconciled_at=now,
            category_id=cat1.id, period_id=closed_period.id)
        submitted_closed = Expense(
            store_id=s1.id, created_by=emp.id, status="submitted",
            created_at=now, business_date=closed_bd,
            amount=Decimal("80"), amount_parse_ok=True, submitted_at=now,
            category_id=cat1.id, period_id=closed_period.id)
        draft_closed = Expense(
            store_id=s1.id, created_by=emp.id, status="draft",
            created_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
            amount=Decimal("60"), amount_parse_ok=True,
            category_id=cat1.id)
        db.session.add_all([audited_closed, audited_open, reconciled_closed,
                             submitted_closed, draft_closed])
        db.session.commit()
        result = {
            "store_id": s1.id,
            "cat1_id": cat1.id,
            "closed_period_id": closed_period.id,
            "open_period_id": open_period.id,
            "audited_closed_id": audited_closed.id,
            "audited_open_id": audited_open.id,
            "reconciled_closed_id": reconciled_closed.id,
            "submitted_closed_id": submitted_closed.id,
            "draft_closed_id": draft_closed.id,
        }
    return result


def test_reconcile_approve_blocked_when_closed(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.post(f"/reconcile/{seeded['audited_closed_id']}/approve")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, seeded["audited_closed_id"])
        assert e.status == "audited"          # 沒被核銷


def test_reconcile_approve_open_period_still_works(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.post(f"/reconcile/{seeded['audited_open_id']}/approve")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Expense, seeded["audited_open_id"])
        assert e.status == "reconciled"


def test_reconcile_approve_batch_closed_goes_to_skipped(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.post("/reconcile/approve-batch", json={
        "ids": [seeded["audited_closed_id"], seeded["audited_open_id"]]})
    body = r.get_json()
    assert body["approved"] == [seeded["audited_open_id"]]
    assert body["skipped"] == [seeded["audited_closed_id"]]
    with app.app_context():
        e = db.session.get(Expense, seeded["audited_closed_id"])
        assert e.status == "audited"


def test_reconcile_edit_blocked_when_closed(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.patch(f"/reconcile/{seeded['audited_closed_id']}", json={"amount": 999})
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, seeded["audited_closed_id"])
        assert float(e.amount) == 200.0        # 沒被改


def test_reconcile_edit_reconciled_blocked_when_closed(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.patch(f"/reconcile/{seeded['reconciled_closed_id']}", json={"amount": 1})
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"


def test_reconcile_reject_blocked_when_closed(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.post(f"/reconcile/{seeded['audited_closed_id']}/reject", json={"reason": "x"})
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, seeded["audited_closed_id"])
        assert e.status == "audited"


def test_reconcile_manual_blocked_when_business_date_in_closed_period(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.post("/reconcile/manual", json={
        "store_id": seeded["store_id"], "business_date": "2026-06-15",
        "summary": "補水電", "amount": 100, "category_id": seeded["cat1_id"],
    })
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        # 沒有任何新的 manual 單被留下來
        count = Expense.query.filter_by(store_id=seeded["store_id"], is_no_receipt=True).count()
        assert count == 0


def test_reconcile_manual_open_period_still_works(client, app, seeded):
    login_as(client, app, "accountant")
    r = client.post("/reconcile/manual", json={
        "store_id": seeded["store_id"], "business_date": "2026-07-15",
        "summary": "補水電", "amount": 100, "category_id": seeded["cat1_id"],
    })
    assert r.status_code == 200


def test_audit_check_blocked_when_closed(client, app, seeded):
    login_as(client, app, "manager")
    r = client.post(f"/audit/{seeded['submitted_closed_id']}/check")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, seeded["submitted_closed_id"])
        assert e.status == "submitted"
        assert e.audited_by is None


def test_expenses_submit_blocked_when_target_period_closed(client, app, seeded):
    login_as(client, app, "employee")
    r = client.post(f"/expenses/{seeded['draft_closed_id']}/submit")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, seeded["draft_closed_id"])
        assert e.status == "draft"
        assert e.period_id is None


# ---------------------------------------------------------------------------
# C1 回歸：effective_status 要用時間（lock_at）判斷，不能只看 period.status 這個
# 持久欄位。DB 欄位翻轉只在 maybe_autoclose 被「碰觸」時才發生（查看該期的
# pending/reports），一個剛過鎖定時刻、還沒被任何人碰過的「上一期」在修好之前會一直讀成
# closing，寫入閘形同虛設。這裡刻意讓 period.status 維持 "open"、只讓 lock_at 落在過去。
# ---------------------------------------------------------------------------

@pytest.fixture
def stale_open_period(app):
    """lock_at 已過去，但 period.status 這個持久欄位還沒被 maybe_autoclose 翻成 closed
    （模擬「沒人剛好去碰那個期間」的情境）。用相對「今天」的日期建期，避免寫死年份的
    期間隨真實時鐘推移而意外落入/跳出鎖定窗。"""
    with app.app_context():
        db.create_all()
        s1 = Store(name="A店", code="A")
        db.session.add(s1)
        db.session.commit()

        emp = User(name="員工A", role="employee", store_id=s1.id)
        emp.set_password("0000")
        mgr = User(name="主管", role="manager", store_id=s1.id)
        mgr.set_password("0000")
        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        cat1 = Category(name="文具", level=1)
        db.session.add_all([emp, mgr, dev, cat1])
        db.session.commit()

        end_date = date.today() - timedelta(days=40)
        start_date = end_date - timedelta(days=29)
        lock_at = datetime.now(timezone.utc) - timedelta(days=1)   # 已過鎖定時刻
        p = AccountingPeriod(label="stale", start_date=start_date, end_date=end_date,
                              lock_at=lock_at, status="open")      # 持久欄位還沒被翻
        db.session.add(p)
        db.session.commit()

        now = datetime.now(timezone.utc)
        submitted = Expense(store_id=s1.id, created_by=emp.id, status="submitted",
                             created_at=now, business_date=end_date, period_id=p.id,
                             amount=Decimal("70"), amount_parse_ok=True, submitted_at=now)
        # created_at 落在 end_date 當天台灣時間 18:00（08:00 分界後）→ compute_business_date
        # 會算出 business_date == end_date，落在這個尚未真正 flip 的過期期間裡。
        draft = Expense(store_id=s1.id, created_by=emp.id, status="draft",
                         created_at=datetime(end_date.year, end_date.month, end_date.day,
                                              10, 0, tzinfo=timezone.utc),
                         amount=Decimal("60"), amount_parse_ok=True, category_id=cat1.id)
        db.session.add_all([submitted, draft])
        db.session.commit()
        result = {
            "period_id": p.id,
            "submitted_id": submitted.id,
            "draft_id": draft.id,
        }
    return result


def test_is_period_closed_true_when_lock_at_passed_but_status_still_open(app, stale_open_period):
    with app.app_context():
        p = db.session.get(AccountingPeriod, stale_open_period["period_id"])
        assert p.status == "open"           # 持久欄位確實還沒被翻
        assert is_period_closed(p.id, datetime.now(timezone.utc)) is True


def test_audit_check_blocked_when_lock_at_passed_but_status_open(client, app, stale_open_period):
    login_as(client, app, "manager")
    r = client.post(f"/audit/{stale_open_period['submitted_id']}/check")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, stale_open_period["submitted_id"])
        assert e.status == "submitted"
        assert e.audited_by is None


def test_expenses_submit_blocked_when_lock_at_passed_but_status_open(client, app, stale_open_period):
    login_as(client, app, "employee")
    r = client.post(f"/expenses/{stale_open_period['draft_id']}/submit")
    assert r.status_code == 409
    assert r.get_json()["message"] == "period_closed"
    with app.app_context():
        e = db.session.get(Expense, stale_open_period["draft_id"])
        assert e.status == "draft"
        assert e.period_id is None
