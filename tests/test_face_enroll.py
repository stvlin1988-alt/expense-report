import numpy as np
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _enc(fill):
    return np.full(128, float(fill), dtype=np.float64)


def _login_as(app, user_id):
    c = app.test_client()
    c.set_cookie("device_uid", "devA")
    with c.session_transaction() as s:
        s["user_id"] = user_id
        import time; s["_last_request_at"] = int(time.time())
    return c


def test_admin_enrolls_user_face(monkeypatch, app):
    monkeypatch.setattr("app.face.routes.encode_face_async", lambda *_a, **_k: _enc(1.0))
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        admin = User(name="店長", role="manager", store_id=store.id); admin.set_password("pw")
        emp = User(name="小明", role="employee", store_id=store.id); emp.set_password("pw")
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([admin, emp, dev]); db.session.commit()
        admin_id, emp_id = admin.id, emp.id
    c = _login_as(app, admin_id)
    r = c.post("/face/enroll", json={"user_id": emp_id, "face_image": "data:x"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert User.query.get(emp_id).face_encoding is not None


def test_enroll_no_face_detected(monkeypatch, app):
    monkeypatch.setattr("app.face.routes.encode_face_async", lambda *_a, **_k: None)
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        admin = User(name="店長", role="manager", store_id=store.id); admin.set_password("pw")
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([admin, dev]); db.session.commit()
        admin_id = admin.id
    c = _login_as(app, admin_id)
    r = c.post("/face/enroll", json={"user_id": admin_id, "face_image": "data:x"})
    assert r.get_json()["status"] == "face_not_found"


def test_unauthenticated_cannot_enroll_even_in_seed_mode(app):
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        emp = User(name="小明", role="employee", store_id=store.id); emp.set_password("pw")
        db.session.add(emp); db.session.commit()
        emp_id = emp.id

    c = app.test_client()
    c.set_cookie("device_uid", "devA")  # 沒有已核准裝置 -> 仍是 seed mode，但無 session actor
    r = c.post("/face/enroll", json={"user_id": emp_id, "face_image": "data:x"})
    assert r.status_code == 401
    with app.app_context():
        assert User.query.get(emp_id).face_encoding is None


def test_unauthenticated_no_user_id_returns_401(app):
    with app.app_context():
        db.create_all()

    c = app.test_client()
    c.set_cookie("device_uid", "devA")  # seed mode, no session actor, no user_id
    r = c.post("/face/enroll", json={"face_image": "data:x"})
    assert r.status_code == 401


def test_employee_cannot_enroll_others(monkeypatch, app):
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A"); db.session.add(store); db.session.commit()
        emp = User(name="小明", role="employee", store_id=store.id); emp.set_password("pw")
        other = User(name="小華", role="employee", store_id=store.id); other.set_password("pw")
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([emp, other, dev]); db.session.commit()
        emp_id, other_id = emp.id, other.id
    c = _login_as(app, emp_id)
    r = c.post("/face/enroll", json={"user_id": other_id, "face_image": "data:x"})
    assert r.status_code == 403
