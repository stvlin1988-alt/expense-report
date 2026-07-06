import numpy as np
import pytest
from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.models.device import Device


def _enc(fill):
    return np.full(128, float(fill), dtype=np.float64)


@pytest.fixture
def seeded(app):
    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A")
        db.session.add(store); db.session.commit()
        emp = User(name="小明", role="employee", store_id=store.id)
        emp.set_password("1234"); emp.face_encoding = _enc(0.0).tobytes()
        dev = Device(client_uid="devA", store_id=store.id, is_approved=True)
        db.session.add_all([emp, dev]); db.session.commit()
        return {"store_id": store.id}


def _client_with_device(app, uid="devA"):
    c = app.test_client()
    c.set_cookie("device_uid", uid)
    return c


def test_verify_ok(monkeypatch, app, seeded):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "ok"


def test_verify_ok_returns_store_id(monkeypatch, app, seeded):
    # 前端 manager 建帳號需靠 verify 回傳的 store_id；缺它會誤送 null 導致後端 403
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["store_id"] == seeded["store_id"]


def test_verify_ok_super_admin_store_id_null(monkeypatch, app, seeded):
    # super_admin 無所屬店 -> verify 回傳 store_id 應為 null
    with app.app_context():
        sa = User(name="業主", role="super_admin", store_id=None)
        sa.set_password("1234"); sa.face_encoding = _enc(0.0).tobytes()
        db.session.add(sa); db.session.commit()
        # 讓小明無臉，避免同店同臉造成 ambiguous；改以獨立無店裝置比中業主
        emp = User.query.filter_by(name="小明").one()
        emp.face_encoding = None
        dev = Device(client_uid="devSA", store_id=None, is_approved=True)
        db.session.add(dev); db.session.commit()
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app, uid="devSA")
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["store_id"] is None


def test_verify_wrong_password(app, seeded):
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "bad", "face_image": "data:x"})
    assert r.get_json()["status"] == "wrong_password"


def test_verify_face_mismatch(monkeypatch, app, seeded):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(9.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "face_mismatch"


def test_verify_need_face_enroll(app, seeded):
    with app.app_context():
        u = User.query.filter_by(name="小明").one()
        u.face_encoding = None
        db.session.commit()
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "need_face_enroll"


def test_verify_face_not_found(monkeypatch, app, seeded):
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: None)
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "face_not_found"


def test_verify_candidate_scoped_to_store(monkeypatch, app, seeded):
    # 另一店員工同密碼同臉，不應被 A 店裝置比中
    with app.app_context():
        other = Store(name="B店", code="B"); db.session.add(other); db.session.commit()
        u = User(name="B小華", role="employee", store_id=other.id)
        u.set_password("1234"); u.face_encoding = _enc(0.0).tobytes()
        db.session.add(u); db.session.commit()
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    # 仍應登入 A 店小明（B 店員工不在候選內），驗證未撞臉整批拒
    assert r.get_json()["status"] == "ok"


def test_verify_ambiguous(monkeypatch, app, seeded):
    # 同店兩位員工同密碼、同臉部 encoding，且與送出的 encoding 距離幾乎相同
    # -> best_match_among 前兩名距離差 < ambiguous_margin -> 整批拒為 ambiguous
    with app.app_context():
        store_id = seeded["store_id"]
        twin = User(name="小明二號", role="employee", store_id=store_id)
        twin.set_password("1234")
        twin.face_encoding = _enc(0.0).tobytes()
        db.session.add(twin)
        db.session.commit()
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "ambiguous"


def test_verify_store_disabled(monkeypatch, app, seeded):
    # 密碼+臉都比中，但比中者所屬的店已停用 -> store_disabled
    with app.app_context():
        store = Store.query.filter_by(id=seeded["store_id"]).one()
        store.active = False
        db.session.commit()
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    c = _client_with_device(app)
    r = c.post("/auth/verify", json={"password": "1234", "face_image": "data:x"})
    assert r.get_json()["status"] == "store_disabled"


def test_e2e_new_device_approval_assigns_store_and_enables_employee_login(monkeypatch, app):
    """End-to-end：新裝置註冊(無 store_id) -> 店長核准建員工 -> device/employee 皆繼承店長 store_id
    -> 新裝置(已核准)以新員工身分成功登入。驗證 approve_device 一定會設 store_id 的修復。"""
    import re
    import time

    with app.app_context():
        db.create_all()
        store = Store(name="A店", code="A")
        db.session.add(store); db.session.commit()

        sa = User(name="業主", role="super_admin")
        sa.set_password("pw")
        sa.face_encoding = _enc(1.0).tobytes()
        mgr = User(name="店長A", role="manager", store_id=store.id)
        mgr.set_password("pw")
        db.session.add_all([sa, mgr]); db.session.commit()

        # 一台已核准裝置（super_admin 的），用來脫離 seed mode
        sa_dev = Device(client_uid="devSA", is_approved=True)
        mgr_dev = Device(client_uid="devMgr", store_id=store.id, is_approved=True)
        db.session.add_all([sa_dev, mgr_dev]); db.session.commit()

        mgr_id, store_id = mgr.id, store.id

    # 1) 新裝置註冊，不帶 store_id
    reg_client = app.test_client()
    r = reg_client.post("/api/v1/register-device", json={"device_name": "新手機"})
    assert r.status_code == 200
    set_cookie = r.headers.get("Set-Cookie", "")
    m = re.search(r"device_uid=([^;]+)", set_cookie)
    assert m
    new_uid = m.group(1)

    with app.app_context():
        new_device = Device.query.filter_by(client_uid=new_uid).one()
        new_device_id = new_device.id
        assert new_device.store_id is None
        assert new_device.is_approved is False

    # 2) 店長以自己已核准的裝置登入身分，核准新裝置並建立新員工帳號
    mgr_client = app.test_client()
    mgr_client.set_cookie("device_uid", "devMgr")
    with mgr_client.session_transaction() as s:
        s["user_id"] = mgr_id
        s["_last_request_at"] = int(time.time())

    r2 = mgr_client.post(
        f"/admin/devices/{new_device_id}/approve",
        json={"new_user": {"name": "E2E員工", "password": "1357", "role": "employee"}},
    )
    assert r2.get_json()["status"] == "ok"

    # 3) 斷言：新裝置 store_id、新員工 store_id 都必須等於店長的 store_id（Critical 修復點）
    with app.app_context():
        d = db.session.get(Device, new_device_id)
        assert d.is_approved is True
        assert d.store_id == store_id
        emp = db.session.get(User, d.bound_user_id)
        assert emp is not None
        assert emp.store_id == store_id
        # 模擬員工已完成臉部註冊（超出本測試範圍，直接寫入 encoding）
        emp.face_encoding = _enc(0.0).tobytes()
        db.session.commit()

    # 4) 新裝置（現已核准）以新員工身分登入
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: _enc(0.0))
    emp_client = app.test_client()
    emp_client.set_cookie("device_uid", new_uid)
    r3 = emp_client.post("/auth/verify", json={"password": "1357", "face_image": "data:x"})
    assert r3.get_json()["status"] == "ok"


def test_verify_malformed_face_image_no_500(monkeypatch, app, seeded):
    # base64 解碼失敗時應乾淨降級（收斂後的 except (binascii.Error, ValueError)），不可 500
    monkeypatch.setattr("app.auth.routes.encode_face_async", lambda *_a, **_k: None)
    c = _client_with_device(app)
    r = c.post(
        "/auth/verify",
        json={"password": "1234", "face_image": "!!!not-base64!!!"},
    )
    assert r.status_code == 200
    assert "status" in r.get_json()
