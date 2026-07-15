from datetime import date, datetime, timezone
from app.extensions import db
from app.models import AccountingPeriod, Expense, Store, User


def test_create_period_and_link_expense(app):
    with app.app_context():
        db.create_all()
        p = AccountingPeriod(
            label="2026-01", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            lock_at=datetime(2026, 2, 2, 4, 0, tzinfo=timezone.utc), status="open")
        db.session.add(p)
        db.session.commit()
        assert p.id is not None
        assert p.status == "open"
        assert p.closed_by is None

        s = Store(name="A店", code="A")
        db.session.add(s)
        db.session.commit()
        u = User(name="員工", role="employee", store_id=s.id)
        db.session.add(u)
        db.session.commit()

        e = Expense(
            store_id=s.id, created_by=u.id, status="draft",
            created_at=datetime.now(timezone.utc), period_id=p.id,
        )
        db.session.add(e)
        db.session.commit()
        got = db.session.get(Expense, e.id)
        assert got.period_id == p.id


def test_period_status_defaults_to_open(app):
    with app.app_context():
        db.create_all()
        p = AccountingPeriod(
            label="2026-02", start_date=date(2026, 2, 1), end_date=date(2026, 2, 28),
            lock_at=datetime(2026, 3, 2, 4, 0, tzinfo=timezone.utc))
        db.session.add(p)
        db.session.commit()
        assert p.status == "open"
