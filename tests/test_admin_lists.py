from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _login_as(app, user_id, uid="devA"):
    c = app.test_client()
    c.set_cookie("device_uid", uid)
    with c.session_transaction() as s:
        s["user_id"] = user_id
        import time; s["_last_request_at"] = int(time.time())
    return c


def _base(app):
    with app.app_context():
        db.create_all()
        a = Store(name="A店", code="A"); b = Store(name="B店", code="B")
        db.session.add_all([a, b]); db.session.commit()
        sa = User(name="業主", role="super_admin"); sa.set_password("pw")
        mgr = User(name="店長A", role="manager", store_id=a.id); mgr.set_password("pw")
        emp = User(name="員工A", role="employee", store_id=a.id); emp.set_password("pw")
        emp_b = User(name="員工B", role="employee", store_id=b.id); emp_b.set_password("pw")
        sa_dev = Device(client_uid="devSA", store_id=a.id, is_approved=True)
        mgr_dev = Device(client_uid="devMgr", store_id=a.id, is_approved=True)
        db.session.add_all([sa, mgr, emp, emp_b, sa_dev, mgr_dev]); db.session.commit()
        return {"a": a.id, "b": b.id, "sa": sa.id, "mgr": mgr.id,
                "emp": emp.id, "emp_b": emp_b.id}


def test_super_admin_lists_all_stores(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get("/admin/stores")
    body = r.get_json()
    assert body["status"] == "ok"
    codes = {s["code"] for s in body["stores"]}
    assert codes == {"A", "B"}


def test_manager_lists_only_own_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.get("/admin/stores")
    codes = {s["code"] for s in r.get_json()["stores"]}
    assert codes == {"A"}


def test_super_admin_lists_all_users(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get("/admin/users")
    body = r.get_json()
    assert body["status"] == "ok"
    names = {u["name"] for u in body["users"]}
    assert {"業主", "店長A", "員工A", "員工B"} <= names


def test_super_admin_users_store_filter(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get(f"/admin/users?store_id={ids['b']}")
    names = {u["name"] for u in r.get_json()["users"]}
    assert names == {"員工B"}


def test_manager_lists_only_own_store_users(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.get("/admin/users")
    names = {u["name"] for u in r.get_json()["users"]}
    assert names == {"店長A", "員工A"}
    assert "員工B" not in names and "業主" not in names


def test_users_payload_has_face_flag_not_encoding(app):
    ids = _base(app)
    with app.app_context():
        u = db.session.get(User, ids["emp"])
        u.face_encoding = b"\x00" * 16  # 假 encoding
        db.session.commit()
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.get(f"/admin/users?store_id={ids['a']}")
    row = next(u for u in r.get_json()["users"] if u["name"] == "員工A")
    assert row["has_face"] is True
    assert "face_encoding" not in row and "encoding" not in row
    other = next(u for u in r.get_json()["users"] if u["name"] == "店長A")
    assert other["has_face"] is False
