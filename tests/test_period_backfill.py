import time
from datetime import date, datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Expense, Store, User
from app.periods.service import backfill_periods


def _seed_store_user(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A")
        db.session.add(s)
        db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id)
        u.set_password("0000")
        db.session.add(u)
        db.session.commit()
        return s.id, u.id


def test_backfill_assigns_and_idempotent(app):
    sid, uid = _seed_store_user(app)
    with app.app_context():
        e = Expense(store_id=sid, created_by=uid,
                    created_at=datetime.now(timezone.utc),
                    business_date=date(2026, 1, 10), status="audited",
                    amount=Decimal("100"), amount_parse_ok=True, period_id=None)
        db.session.add(e)
        db.session.commit()

        n = backfill_periods()
        db.session.commit()
        assert n == 1
        db.session.refresh(e)
        assert e.period_id is not None

        assert backfill_periods() == 0   # 冪等


def _set_session(client, uid):
    client.set_cookie("device_uid", "dev1")
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())


def test_backfill_makes_expense_visible_in_period_filtered_query(client, app):
    """I1 回歸：backfill_periods()（遷移實際包的邏輯）跑完後，既有的 period_id=NULL 舊單
    要能被期間篩選過的查詢（/reconcile/pending?period_id=）看到——不然光補上 period_id
    欄位沒意義，會計端月結核銷清單裡還是看不到它。"""
    with app.app_context():
        db.create_all()
        s = Store(name="A店", code="A")
        db.session.add(s)
        db.session.commit()
        u = User(name="員工A", role="employee", store_id=s.id)
        u.set_password("0000")
        acct = User(name="會計", role="accountant")
        acct.set_password("0000")
        db.session.add_all([u, acct])
        db.session.commit()

        # status="reconciled"（非 audited/rejected）：/reconcile/pending 讀取時會順帶
        # maybe_autoclose() 該期間（2026-01 早就過了 lock_at），audited/rejected 單會被
        # 挪去下一期，讓「查回填後這期應看得到它」的斷言失真；reconciled 不會被挪期
        # （同 tests/test_reconcile_period_filter.py 的 two_period_audited fixture 註解）。
        e = Expense(store_id=s.id, created_by=u.id,
                    created_at=datetime.now(timezone.utc),
                    business_date=date(2026, 1, 10), status="reconciled",
                    reconciled_by=acct.id, reconciled_at=datetime.now(timezone.utc),
                    amount=Decimal("100"), amount_parse_ok=True, period_id=None)
        db.session.add(e)
        db.session.commit()
        eid = e.id
        acct_id = acct.id

        n = backfill_periods()
        db.session.commit()
        assert n == 1
        db.session.refresh(e)
        period_id = e.period_id
        assert period_id is not None

    _set_session(client, acct_id)
    r = client.get(f"/reconcile/pending?period_id={period_id}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["period"]["id"] == period_id
    items = [i for g in data["groups"] for i in g["items"]]
    ids = {i["id"] for i in items}
    assert eid in ids
