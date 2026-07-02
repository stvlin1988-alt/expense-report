from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _login_as(app, user_id, uid="devMgr"):
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
        # 管理者自己的已核准裝置（供登入用）
        mgr_dev = Device(client_uid="devMgr", store_id=a.id, is_approved=True)
        sa_dev = Device(client_uid="devSA", is_approved=True)
        # 待核准裝置
        pend_a = Device(client_uid="pendA", store_id=a.id, device_name="A新機")
        pend_b = Device(client_uid="pendB", store_id=b.id, device_name="B新機")
        db.session.add_all([sa, mgr, mgr_dev, sa_dev, pend_a, pend_b]); db.session.commit()
        return {"a": a.id, "b": b.id, "sa": sa.id, "mgr": mgr.id,
                "pend_a": pend_a.id, "pend_b": pend_b.id}


def test_manager_lists_only_own_store_devices(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.get("/admin/devices")
    uids = {d["client_uid"] for d in r.get_json()["devices"]}
    assert "pendA" in uids and "devMgr" in uids
    assert "pendB" not in uids and "devSA" not in uids


def test_super_admin_store_filter(app):
    ids = _base(app)
    c = _login_as(app, ids["sa"], uid="devSA")
    all_r = c.get("/admin/devices")
    assert {d["client_uid"] for d in all_r.get_json()["devices"]} >= {"pendA", "pendB"}
    filtered = c.get(f"/admin/devices?store_id={ids['b']}")
    uids = {d["client_uid"] for d in filtered.get_json()["devices"]}
    assert "pendB" in uids and "pendA" not in uids


def test_manager_cannot_approve_other_store_device(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_b']}/approve", json={})
    assert r.status_code == 403


def test_approve_with_new_account_binds_user(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"new_user": {"name": "小明", "password": "1234", "role": "employee"}})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        d = db.session.get(Device, ids["pend_a"])
        assert d.is_approved is True and d.bound_user_id is not None
        assert db.session.get(User, d.bound_user_id).name == "小明"


def test_approve_rebind_existing_revokes_old(app):
    ids = _base(app)
    with app.app_context():
        emp = User(name="小明", role="employee", store_id=ids["a"]); emp.set_password("1234")
        db.session.add(emp); db.session.commit()
        old = Device(client_uid="oldPhone", store_id=ids["a"],
                     is_approved=True, bound_user_id=emp.id)
        db.session.add(old); db.session.commit()
        emp_id, old_id = emp.id, old.id
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"bound_user_id": emp_id})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(Device, old_id).is_revoked is True   # 舊機撤銷
        assert db.session.get(Device, ids["pend_a"]).is_approved is True


def test_revoke_device(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/revoke", json={})
    assert r.get_json()["status"] == "ok"
    with app.app_context():
        assert db.session.get(Device, ids["pend_a"]).is_revoked is True


def test_manager_cannot_create_superadmin_via_approve(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"new_user": {"name": "壞人", "password": "1234", "role": "super_admin"}})
    assert r.status_code == 403
    with app.app_context():
        assert User.query.filter_by(name="壞人").first() is None
        assert db.session.get(Device, ids["pend_a"]).is_approved is False


def test_manager_cannot_rebind_to_other_store_user(app):
    ids = _base(app)
    with app.app_context():
        other_emp = User(name="B店員工", role="employee", store_id=ids["b"])
        other_emp.set_password("1234")
        db.session.add(other_emp); db.session.commit()
        other_dev = Device(client_uid="bPhone", store_id=ids["b"],
                            is_approved=True, bound_user_id=other_emp.id)
        db.session.add(other_dev); db.session.commit()
        other_emp_id, other_dev_id = other_emp.id, other_dev.id
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"bound_user_id": other_emp_id})
    assert r.status_code == 403
    with app.app_context():
        assert db.session.get(Device, other_dev_id).is_revoked is False
        pend = db.session.get(Device, ids["pend_a"])
        assert pend.is_approved is False
        assert pend.bound_user_id is None


def test_manager_cannot_rebind_to_superadmin(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"bound_user_id": ids["sa"]})
    assert r.status_code == 403
    with app.app_context():
        pend = db.session.get(Device, ids["pend_a"])
        assert pend.is_approved is False
        assert pend.bound_user_id is None


def test_approve_new_user_requires_name_password(app):
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_a']}/approve",
               json={"new_user": {"name": "小明", "role": "employee"}})
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(Device, ids["pend_a"]).is_approved is False
