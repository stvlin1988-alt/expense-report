import time
import pytest
from datetime import datetime, timezone, date, timedelta
from app.extensions import db
from app.models import Store, User, Device, Expense
from app.expenses.logic import compute_business_date


def _setup_store_and_user(app):
    """Base setup: create stores, users, and device for a test."""
    with app.app_context():
        db.create_all()
        s1 = Store(name="Store1", code="S1")
        s2 = Store(name="Store2", code="S2")
        db.session.add_all([s1, s2])
        db.session.commit()

        mgr1 = User(name="mgr1", role="manager", store_id=s1.id)
        mgr1.set_password("1234")
        mgr2 = User(name="mgr2", role="manager", store_id=s2.id)
        mgr2.set_password("1234")
        emp = User(name="emp", role="employee", store_id=s1.id)
        emp.set_password("1234")

        dev = Device(client_uid="dev1", store_id=s1.id, is_approved=True)
        db.session.add_all([mgr1, mgr2, emp, dev])
        db.session.commit()

        return {
            'mgr1_id': mgr1.id,
            'mgr2_id': mgr2.id,
            'emp_id': emp.id,
            's1_id': s1.id,
            's2_id': s2.id,
        }


def _client(app, uid):
    """Create a test client with session login."""
    c = app.test_client()
    c.set_cookie("device_uid", "dev1")
    with c.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_last_request_at"] = int(time.time())
    return c


@pytest.fixture
def submitted_today_id(app):
    """Fixture: only today's submitted expense."""
    setup = _setup_store_and_user(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        today_bd = compute_business_date(now)
        from decimal import Decimal
        e = Expense(
            store_id=setup['s1_id'],
            created_by=setup['emp_id'],
            status="submitted",
            created_at=now,
            business_date=today_bd,
            amount=Decimal("100"),
            submitted_at=now
        )
        db.session.add(e)
        db.session.commit()
        return e.id


@pytest.fixture
def submitted_yesterday_id(app):
    """Fixture: only yesterday's submitted expense."""
    setup = _setup_store_and_user(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        today_bd = compute_business_date(now)
        yesterday_bd = today_bd - timedelta(days=1)
        from decimal import Decimal
        e = Expense(
            store_id=setup['s1_id'],
            created_by=setup['emp_id'],
            status="submitted",
            created_at=now,
            business_date=yesterday_bd,
            amount=Decimal("50"),
            submitted_at=now
        )
        db.session.add(e)
        db.session.commit()
        return e.id


@pytest.fixture
def audited_yesterday_id(app):
    """Fixture: only yesterday's audited expense."""
    setup = _setup_store_and_user(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        today_bd = compute_business_date(now)
        yesterday_bd = today_bd - timedelta(days=1)
        mgr1_id = setup['mgr1_id']
        from decimal import Decimal
        e = Expense(
            store_id=setup['s1_id'],
            created_by=setup['emp_id'],
            status="audited",
            created_at=now,
            business_date=yesterday_bd,
            amount=Decimal("75"),
            submitted_at=now,
            audited_at=now,
            audited_by=mgr1_id
        )
        db.session.add(e)
        db.session.commit()
        return e.id


def test_today_submitted_not_overdue(app, submitted_today_id):
    """Expenses submitted today should not be considered overdue."""
    with app.app_context():
        mgr = User.query.filter_by(name="mgr1").first()
    c = _client(app, mgr.id)
    body = c.get("/audit/overdue").get_json()
    assert body["status"] == "ok"
    assert body["count"] == 0
    assert body["oldest_business_date"] is None


def test_yesterday_submitted_is_overdue(app, submitted_yesterday_id):
    """Expenses submitted yesterday should be considered overdue."""
    with app.app_context():
        mgr = User.query.filter_by(name="mgr1").first()
    c = _client(app, mgr.id)
    body = c.get("/audit/overdue").get_json()
    assert body["status"] == "ok"
    assert body["count"] == 1
    assert body["oldest_business_date"] is not None


def test_audited_not_overdue(app, audited_yesterday_id):
    """Expenses that are already audited should not be counted as overdue."""
    with app.app_context():
        mgr = User.query.filter_by(name="mgr1").first()
    c = _client(app, mgr.id)
    body = c.get("/audit/overdue").get_json()
    assert body["status"] == "ok"
    assert body["count"] == 0


@pytest.fixture
def overdue_with_other_store(app):
    """Fixture: create overdue expense in store1 and store2 for per-store isolation test."""
    setup = _setup_store_and_user(app)
    with app.app_context():
        now = datetime.now(timezone.utc)
        today_bd = compute_business_date(now)
        yesterday_bd = today_bd - timedelta(days=1)
        from decimal import Decimal

        # Store1: yesterday submitted
        e1 = Expense(
            store_id=setup['s1_id'],
            created_by=setup['emp_id'],
            status="submitted",
            created_at=now,
            business_date=yesterday_bd,
            amount=Decimal("100"),
            submitted_at=now
        )
        # Store2: yesterday submitted
        e2 = Expense(
            store_id=setup['s2_id'],
            created_by=setup['emp_id'],
            status="submitted",
            created_at=now,
            business_date=yesterday_bd,
            amount=Decimal("200"),
            submitted_at=now
        )
        db.session.add_all([e1, e2])
        db.session.commit()
        return setup


def test_overdue_per_store_isolation(app, overdue_with_other_store):
    """Manager from store2 should not see overdue expenses from store1."""
    setup = overdue_with_other_store
    with app.app_context():
        mgr1 = User.query.filter_by(name="mgr1").first()
        mgr2 = User.query.filter_by(name="mgr2").first()

    # mgr1 from store1 should see 1 overdue (store1's expense)
    c1 = _client(app, mgr1.id)
    body1 = c1.get("/audit/overdue").get_json()
    assert body1["status"] == "ok"
    assert body1["count"] == 1

    # mgr2 from store2 should see 1 overdue (store2's expense, not store1's)
    c2 = _client(app, mgr2.id)
    body2 = c2.get("/audit/overdue").get_json()
    assert body2["status"] == "ok"
    assert body2["count"] == 1
