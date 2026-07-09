from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Expense, AuditLog
from app.audit.log import snapshot, log_edit_if_changed, record_check


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="u", role="employee", store_id=s.id); u.set_password("1234")
        db.session.add(u); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc), amount=Decimal("100"))
        db.session.add(e); db.session.commit()
        return u.id, e.id


def test_stamp_on_change(app):
    uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        e.amount = Decimal("250")
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_by == uid
        assert e.last_modified_at is not None
        row = AuditLog.query.filter_by(action="edit").one()
        assert e.last_modified_at == row.ts   # 同一時戳


def test_no_stamp_when_unchanged(app):
    uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        assert log_edit_if_changed(e, uid, before) is False
        db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_by is None and e.last_modified_at is None


def test_check_does_not_stamp(app):
    uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        record_check(e, uid); db.session.commit()
        e = db.session.get(Expense, eid)
        assert e.last_modified_by is None and e.last_modified_at is None
