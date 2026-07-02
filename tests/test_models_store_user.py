from app.extensions import db
from app.models.store import Store
from app.models.user import User, ROLES


def test_create_store_and_user(app):
    with app.app_context():
        db.create_all()
        store = Store(name="測試店", code="S001")
        db.session.add(store)
        db.session.commit()

        user = User(store_id=store.id, name="小明", role="employee")
        db.session.add(user)
        db.session.commit()

        assert user.id is not None
        assert user.store.name == "測試店"
        assert "super_admin" in ROLES


def test_accountant_and_admin_have_no_store(app):
    with app.app_context():
        db.create_all()
        acc = User(store_id=None, name="會計", role="accountant")
        db.session.add(acc)
        db.session.commit()
        assert acc.store_id is None
