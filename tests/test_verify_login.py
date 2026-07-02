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
