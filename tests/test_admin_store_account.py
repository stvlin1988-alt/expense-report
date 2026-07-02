from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _login_as(app, user_id):
    c = app.test_client()
    c.set_cookie("device_uid", "devA")
    with c.session_transaction() as s:
        s["user_id"] = user_id
        import time; s["_last_request_at"] = int(time.time())
    return c


def _base(app):
    with app.app_context():
        db.create_all()
        a = Store(name="A店", code="A"); db.session.add(a); db.session.commit()
        sa = User(name="業主", role="super_admin"); sa.set_password("pw")
        mgr = User(name="店長", role="manager", store_id=a.id); mgr.set_password("pw")
        dev = Device(client_uid="devA", store_id=a.id, is_approved=True)
        db.session.add_all([sa, mgr, dev]); db.session.commit()
        return {"a": a.id, "sa": sa.id, "mgr": mgr.id}


def test_super_admin_creates_store(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"])
    r = c.post("/admin/stores", json={"name": "B店", "code": "B"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert Store.query.filter_by(code="B").one().name == "B店"


def test_manager_cannot_create_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post("/admin/stores", json={"name": "B店", "code": "B"})
    assert r.status_code == 403


def test_manager_creates_own_store_employee(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post("/admin/users", json={"name": "小明", "password": "1234",
                                     "role": "employee", "store_id": ids["a"]})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert User.query.filter_by(name="小明").one().check_password("1234")


def test_manager_cannot_create_other_store_user(app):
    ids = _base(app)
    with app.app_context():
        b = Store(name="B店", code="B"); db.session.add(b); db.session.commit()
        b_id = b.id
    c = _login_as(app, ids["mgr"])
    r = c.post("/admin/users", json={"name": "外店", "password": "1234",
                                     "role": "employee", "store_id": b_id})
    assert r.status_code == 403


def test_manager_resets_own_store_user_password(app):
    ids = _base(app)
    with app.app_context():
        emp = User(name="小明", role="employee", store_id=ids["a"]); emp.set_password("old")
        db.session.add(emp); db.session.commit()
        emp_id = emp.id
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/users/{emp_id}/password", json={"password": "new"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, emp_id).check_password("new")


def test_self_change_password_requires_old(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    bad = c.post("/admin/me/password", json={"old_password": "wrong", "new_password": "x"})
    assert bad.status_code == 400
    ok = c.post("/admin/me/password", json={"old_password": "pw", "new_password": "new"})
    assert ok.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["mgr"]).check_password("new")
