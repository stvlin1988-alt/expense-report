from app.extensions import db
from app.models.user import User
from app.seeds.seed_admin import seed_admin


def test_password_hash_roundtrip(app):
    with app.app_context():
        db.create_all()
        u = User(name="owner", role="super_admin")
        u.set_password("secret123")
        assert u.password_hash != "secret123"
        assert u.check_password("secret123") is True
        assert u.check_password("wrong") is False


def test_seed_admin_idempotent(app):
    with app.app_context():
        db.create_all()
        a = seed_admin("業主", "owner-pw")
        seed_admin("業主", "owner-pw")
        assert a.role == "super_admin"
        assert a.is_admin is True
        assert User.query.filter_by(role="super_admin").count() == 1


def test_login_and_session(app, client):
    with app.app_context():
        db.create_all()
        seed_admin("業主", "owner-pw")

    resp = client.post("/auth/login", json={"name": "業主", "password": "owner-pw"})
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "super_admin"

    bad = client.post("/auth/login", json={"name": "業主", "password": "x"})
    assert bad.status_code == 401
