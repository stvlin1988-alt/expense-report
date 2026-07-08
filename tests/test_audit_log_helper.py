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
        return s.id, u.id, e.id


def test_log_edit_only_when_changed(app):
    _, uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        before = snapshot(e)
        # 無變動 → 不寫
        assert log_edit_if_changed(e, uid, before) is False
        # 改金額 → 寫一筆 edit，before/after 正確
        from decimal import Decimal
        e.amount = Decimal("250")
        assert log_edit_if_changed(e, uid, before) is True
        db.session.commit()
        rows = AuditLog.query.filter_by(action="edit").all()
        assert len(rows) == 1
        assert rows[0].before_json == {"amount": 100.0, "category_id": None}
        assert rows[0].after_json == {"amount": 250.0, "category_id": None}


def test_record_check(app):
    _, uid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        record_check(e, uid); db.session.commit()
        row = AuditLog.query.filter_by(action="check").one()
        assert row.before_json is None
        assert row.after_json == {"status": "audited"}
