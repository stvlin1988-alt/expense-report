import re
import json
import hashlib

import numpy as np

from app.extensions import db
from app.models.user import User
from app.models.device import Device


def _cfg(data):
    m = re.search(rb'id="app-config"[^>]*>(.*?)</script>', data, re.S)
    return json.loads(m.group(1))


def test_index_renders(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/")
    assert r.status_code == 200
    assert b"app-config" in r.data


def test_index_seed_mode_true_when_empty(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/")
    assert _cfg(r.data)["seedMode"] is True


def test_index_secret_hash_matches_config(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/")
    assert _cfg(r.data)["secretHash"] == hashlib.sha256(b"078*2").hexdigest()


def _make_non_seed():
    sa = User(name="業主", role="super_admin")
    sa.set_password("pw")
    sa.face_encoding = np.zeros(128, dtype=np.float64).tobytes()
    db.session.add(sa)
    db.session.add(Device(client_uid="devOK", is_approved=True))
    db.session.commit()
    return sa.id


def test_index_exempt_even_when_device_unapproved(app):
    with app.app_context():
        db.create_all()
        _make_non_seed()
    c = app.test_client()
    c.set_cookie("device_uid", "bad")
    assert c.get("/").status_code == 200  # '/' 豁免 device gate


def test_secret_hash_null_for_unapproved_device(app):
    with app.app_context():
        db.create_all()
        _make_non_seed()
    c = app.test_client()
    c.set_cookie("device_uid", "bad")
    assert _cfg(c.get("/").data)["secretHash"] is None


def test_secret_hash_present_for_approved_device(app):
    with app.app_context():
        db.create_all()
        _make_non_seed()
    c = app.test_client()
    c.set_cookie("device_uid", "devOK")
    assert _cfg(c.get("/").data)["secretHash"] == hashlib.sha256(b"078*2").hexdigest()


def test_index_injects_identity_when_logged_in(app):
    with app.app_context():
        db.create_all()
        u = User(name="王小明", role="employee")
        u.set_password("p")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
    cfg = _cfg(c.get("/").data)
    assert cfg["identity"]["name"] == "王小明"
    assert cfg["identity"]["role"] == "employee"


def test_index_no_identity_when_anonymous(app):
    with app.app_context():
        db.create_all()
    assert _cfg(app.test_client().get("/").data)["identity"] is None


def test_sw_served_at_root(app):
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["Content-Type"]
