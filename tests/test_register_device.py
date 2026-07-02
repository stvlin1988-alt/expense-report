from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.device import Device
from app.devices.routes import is_device_authorized, _cleanup_pending_devices


def test_register_new_device_creates_pending_and_sets_cookie(app, client):
    with app.app_context():
        db.create_all()
    resp = client.post("/api/v1/register-device",
                       json={"fingerprint": "fp1", "device_name": "iPad"})
    assert resp.status_code == 200
    assert "device_uid" in resp.headers.get("Set-Cookie", "")
    with app.app_context():
        d = Device.query.one()
        assert d.is_approved is False
        assert d.fingerprint == "fp1"
        assert d.client_uid


def test_register_existing_uid_is_seen_not_duplicated(app, client):
    with app.app_context():
        db.create_all()
        db.session.add(Device(client_uid="known", fingerprint="fp"))
        db.session.commit()
    resp = client.post("/api/v1/register-device",
                       json={"client_uid": "known", "fingerprint": "fp"})
    assert resp.status_code == 200
    with app.app_context():
        assert Device.query.count() == 1


def test_is_device_authorized_uid_only(app):
    with app.app_context():
        db.create_all()
        db.session.add(Device(client_uid="ok", fingerprint="shared",
                              is_approved=True, is_revoked=False))
        db.session.add(Device(client_uid="revoked", fingerprint="shared",
                              is_approved=True, is_revoked=True))
        db.session.commit()
        assert is_device_authorized("ok") is True
        assert is_device_authorized("revoked") is False
        assert is_device_authorized("nonexistent") is False
        assert is_device_authorized(None) is False
        # fingerprint 永不作認證：就算 fingerprint 相同，未核准仍不通過
        db.session.add(Device(client_uid="pending", fingerprint="shared"))
        db.session.commit()
        assert is_device_authorized("pending") is False


def test_cleanup_removes_stale_pending(app):
    with app.app_context():
        db.create_all()
        old = Device(client_uid="old", is_approved=False)
        old.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        fresh = Device(client_uid="fresh", is_approved=False)
        approved_old = Device(client_uid="appr", is_approved=True)
        approved_old.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db.session.add_all([old, fresh, approved_old])
        db.session.commit()
        removed = _cleanup_pending_devices()
        assert removed == 1
        assert {d.client_uid for d in Device.query.all()} == {"fresh", "appr"}


def test_register_non_string_client_uid_does_not_500(app, client):
    with app.app_context():
        db.create_all()
    r = client.post("/api/v1/register-device", json={"client_uid": 123, "fingerprint": ["x"]})
    assert r.status_code == 200  # coerced, not crashed


def test_register_overlong_values_truncated(app, client):
    with app.app_context():
        db.create_all()
    long_uid = "u" * 200
    r = client.post("/api/v1/register-device",
                    json={"client_uid": long_uid, "device_name": "d" * 200})
    assert r.status_code == 200
    with app.app_context():
        d = Device.query.one()
        assert len(d.client_uid) <= 64
        assert len(d.device_name) <= 100
