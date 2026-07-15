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
