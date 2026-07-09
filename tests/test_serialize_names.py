from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models import Store, User, Expense
from app.expenses.serialize import serialize_expense
from app.storage.r2 import get_storage


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A"); db.session.add(s); db.session.commit()
        u = User(name="小明", role="employee", store_id=s.id); u.set_password("1234")
        m = User(name="主管", role="manager", store_id=s.id); m.set_password("1234")
        db.session.add_all([u, m]); db.session.commit()
        e = Expense(store_id=s.id, created_by=u.id, status="draft",
                    created_at=datetime.now(timezone.utc), amount=Decimal("100"),
                    last_modified_by=m.id, last_modified_at=datetime.now(timezone.utc))
        db.session.add(e); db.session.commit()
        return u.id, m.id, e.id


def test_serialize_with_name_map(app):
    uid, mid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        names = {uid: "小明", mid: "主管"}
        d = serialize_expense(e, get_storage(), name_by_id=names)
        assert d["created_by_name"] == "小明"
        assert d["last_modified_by_name"] == "主管"
        assert d["last_modified_at"] is not None


def test_serialize_without_name_map_is_none(app):
    uid, mid, eid = _mk(app)
    with app.app_context():
        e = db.session.get(Expense, eid)
        d = serialize_expense(e, get_storage())
        assert d["created_by_name"] is None
        assert d["last_modified_by_name"] is None
