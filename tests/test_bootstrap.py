import numpy as np
from app.extensions import db
from app.models.user import User
from app.models.device import Device
from app.auth.gates import is_seed_mode


def _enc(fill):
    return np.full(128, float(fill), dtype=np.float64)


def test_bootstrap_creates_owner_enrolls_face_approves_device(monkeypatch, app):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(1.0))
    with app.app_context():
        db.create_all()

    c = app.test_client()
    c.set_cookie("device_uid", "devBoot")

    r = c.post(
        "/auth/bootstrap",
        json={"name": "業主", "password": "pw", "face_image": "data:x"},
    )
    assert r.get_json()["status"] == "ok"

    with app.app_context():
        admins = User.query.filter_by(role="super_admin").all()
        assert len(admins) == 1
        assert admins[0].face_encoding is not None

        dev = Device.query.filter_by(client_uid="devBoot").one()
        assert dev.is_approved is True
        assert dev.bound_user_id == admins[0].id

        assert is_seed_mode() is False


def test_bootstrap_refused_once_owner_has_face(monkeypatch, app):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(1.0))
    with app.app_context():
        db.create_all()
        owner = User(name="業主", role="super_admin", store_id=None)
        owner.set_password("pw")
        owner.face_encoding = _enc(1.0).tobytes()
        db.session.add(owner)
        db.session.commit()

    c = app.test_client()
    c.set_cookie("device_uid", "devBoot2")

    r = c.post(
        "/auth/bootstrap",
        json={"name": "冒充者", "password": "pw2", "face_image": "data:x"},
    )
    assert r.status_code == 403
    assert r.get_json()["status"] == "already_initialized"

    with app.app_context():
        assert User.query.filter_by(role="super_admin").count() == 1


def test_bootstrap_rejects_non_string_name(monkeypatch, app):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(1.0))
    with app.app_context():
        db.create_all()

    c = app.test_client()
    c.set_cookie("device_uid", "devBoot4")

    r = c.post(
        "/auth/bootstrap",
        json={"name": 123, "password": "pw", "face_image": "data:x"},
    )
    assert r.status_code == 400

    with app.app_context():
        assert User.query.filter_by(role="super_admin").count() == 0


def test_bootstrap_truncates_long_name(monkeypatch, app):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(1.0))
    with app.app_context():
        db.create_all()

    c = app.test_client()
    c.set_cookie("device_uid", "devBoot5")

    r = c.post(
        "/auth/bootstrap",
        json={"name": "業" * 200, "password": "pw", "face_image": "data:x"},
    )
    assert r.get_json()["status"] == "ok"

    with app.app_context():
        owner = User.query.filter_by(role="super_admin").one()
        assert len(owner.name) <= 100


def test_bootstrap_face_not_found(monkeypatch, app):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: None)
    with app.app_context():
        db.create_all()

    c = app.test_client()
    c.set_cookie("device_uid", "devBoot3")

    r = c.post(
        "/auth/bootstrap",
        json={"name": "業主", "password": "pw", "face_image": "data:x"},
    )
    assert r.get_json()["status"] == "face_not_found"

    with app.app_context():
        assert User.query.filter_by(role="super_admin").count() == 0
