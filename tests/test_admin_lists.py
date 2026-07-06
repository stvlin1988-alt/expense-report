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


def test_manager_lists_all_stores(app):
    # 主管改「本店帳號」的店別需要目標店清單 → GET /admin/stores 回全部店
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.get("/admin/stores")
    codes = {s["code"] for s in r.get_json()["stores"]}
    assert codes == {"A", "B"}


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


def test_super_admin_deactivates_and_reactivates_user(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/active", json={"active": False})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).active is False
    r2 = c.post(f"/admin/users/{ids['emp']}/active", json={"active": True})
    assert r2.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).active is True


def test_active_non_bool_rejected(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/active", json={"active": "yes"})
    assert r.status_code == 400


def test_active_target_not_found(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post("/admin/users/99999/active", json={"active": False})
    assert r.status_code == 404


def test_manager_cannot_deactivate_other_store_or_non_employee(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    # 他店員工 → 403
    r1 = c.post(f"/admin/users/{ids['emp_b']}/active", json={"active": False})
    assert r1.status_code == 403
    # super_admin（非 employee）→ 403
    r2 = c.post(f"/admin/users/{ids['sa']}/active", json={"active": False})
    assert r2.status_code == 403


def test_cannot_deactivate_self(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['mgr']}/active", json={"active": False})
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(User, ids["mgr"]).active is True


def test_cannot_deactivate_last_super_admin(app):
    # 唯一 super_admin 停用自己 → 400（自我守門先擋，且為最後 super_admin）
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['sa']}/active", json={"active": False})
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(User, ids["sa"]).active is True


def test_super_admin_can_deactivate_other_super_admin(app):
    # 有兩位 super_admin 時可停用另一位（非最後一位）
    ids = _base(app)
    with app.app_context():
        sa2 = User(name="業主2", role="super_admin", active=True); sa2.set_password("pw")
        db.session.add(sa2); db.session.commit()
        sa2_id = sa2.id
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{sa2_id}/active", json={"active": False})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, sa2_id).active is False


# ---- 修改帳號店別/角色（經理改店別+角色；主管改本店員工店別）----

def test_super_admin_changes_any_user_store(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/store", json={"store_id": ids["b"]})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).store_id == ids["b"]


def test_manager_changes_own_store_employee_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['emp']}/store", json={"store_id": ids["b"]})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).store_id == ids["b"]


def test_manager_cannot_change_other_store_employee_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['emp_b']}/store", json={"store_id": ids["a"]})
    assert r.status_code == 403


def test_manager_cannot_change_non_employee_store(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['sa']}/store", json={"store_id": ids["a"]})
    assert r.status_code == 403


def test_set_store_invalid_store_id(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/store", json={"store_id": 99999})
    assert r.status_code == 400


def test_super_admin_changes_role(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/role", json={"role": "manager"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["emp"]).role == "manager"


def test_manager_cannot_change_role(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['emp']}/role", json={"role": "manager"})
    assert r.status_code == 403


def test_cannot_change_own_role(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['sa']}/role", json={"role": "employee"})
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(User, ids["sa"]).role == "super_admin"


def test_set_role_invalid(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{ids['emp']}/role", json={"role": "boss"})
    assert r.status_code == 400


def test_super_admin_can_demote_other_super_admin(app):
    ids = _base(app)
    with app.app_context():
        sa2 = User(name="業主2", role="super_admin"); sa2.set_password("pw")
        db.session.add(sa2); db.session.commit()
        sa2_id = sa2.id
    c = _login_as(app, ids["sa"], uid="devSA")
    r = c.post(f"/admin/users/{sa2_id}/role", json={"role": "employee"})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, sa2_id).role == "employee"


def test_manager_changes_own_store(app):
    # 主管可改自己的店別
    ids = _base(app)
    c = _login_as(app, ids["mgr"], uid="devMgr")
    r = c.post(f"/admin/users/{ids['mgr']}/store", json={"store_id": ids["b"]})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(User, ids["mgr"]).store_id == ids["b"]
