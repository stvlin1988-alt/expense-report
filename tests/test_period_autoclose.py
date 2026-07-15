from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Expense, AccountingPeriod, Store, User
from app.periods.service import get_or_create_period, maybe_autoclose


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


def _mk_expense(store_id, created_by, bd, status, period_id, amount=100):
    e = Expense(store_id=store_id, created_by=created_by, created_at=datetime.now(timezone.utc),
                business_date=bd, status=status, amount=Decimal(str(amount)), amount_parse_ok=True,
                period_id=period_id)
    db.session.add(e)
    db.session.flush()
    return e


def test_autoclose_moves_checked_leaves_submitted(app):
    sid, uid = _seed_store_user(app)
    with app.app_context():
        jan = get_or_create_period(date(2026, 1, 15))
        db.session.commit()
        audited = _mk_expense(sid, uid, date(2026, 1, 20), "audited", jan.id)
        rejected = _mk_expense(sid, uid, date(2026, 1, 22), "rejected", jan.id)
        submitted = _mk_expense(sid, uid, date(2026, 1, 21), "submitted", jan.id)
        db.session.commit()

        now = jan.lock_at + timedelta(hours=1)
        closed = maybe_autoclose(jan, now)
        db.session.commit()

        assert closed is True
        assert jan.status == "closed"
        db.session.refresh(audited)
        db.session.refresh(rejected)
        db.session.refresh(submitted)
        assert audited.period_id != jan.id            # 挪到下一期
        assert rejected.period_id != jan.id            # 挪到下一期
        assert audited.period_id == rejected.period_id
        assert submitted.period_id == jan.id           # 留原期
        nxt = db.session.get(AccountingPeriod, audited.period_id)
        assert nxt.start_date == date(2026, 2, 1)
        assert nxt.status == "open"


def test_autoclose_idempotent_and_time_gated(app):
    with app.app_context():
        db.create_all()
        jan = get_or_create_period(date(2026, 1, 15))
        db.session.commit()
        before = jan.lock_at - timedelta(hours=1)
        assert maybe_autoclose(jan, before) is False   # 還沒到鎖定時刻
        assert jan.status == "open"
        after = jan.lock_at + timedelta(hours=1)
        assert maybe_autoclose(jan, after) is True
        db.session.commit()
        assert jan.status == "closed"
        assert maybe_autoclose(jan, after) is False     # 已封，不重複
