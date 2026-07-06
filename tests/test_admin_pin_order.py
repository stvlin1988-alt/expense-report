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
        mgr = User(name="店長A", role="manager", store_id=a.id); mgr.set_password("pw")
        emp_b = User(name="員工B", role="employee", store_id=b.id); emp_b.set_password("pw")
        mgr_dev = Device(client_uid="devMgr", store_id=a.id, is_approved=True)
        pend_b = Device(client_uid="pendB", store_id=b.id, device_name="B新機")
        db.session.add_all([mgr, emp_b, mgr_dev, pend_b]); db.session.commit()
        return {"a": a.id, "b": b.id, "mgr": mgr.id, "emp_b": emp_b.id,
                "pend_b": pend_b.id}


def test_reset_password_authz_before_pin_format(app):
    # manager 對他店員工重設密碼 + 密碼格式錯 → 應回 403（越權），不因格式先回 400
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/users/{ids['emp_b']}/password", json={"password": "abc"})
    assert r.status_code == 403


def test_approve_new_user_authz_before_pin_format(app):
    # manager 核准他店待核准裝置 + 建 new_user（格式錯）→ 應回 403（越權他店裝置），非 400
    ids = _base(app)
    c = _login_as(app, ids["mgr"])
    r = c.post(f"/admin/devices/{ids['pend_b']}/approve",
               json={"new_user": {"name": "新人", "password": "abc", "role": "employee"}})
    assert r.status_code == 403
