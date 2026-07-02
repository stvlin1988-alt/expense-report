import numpy as np
from app.extensions import db
from app.models.device import Device
from app.models.user import User


def test_create_device_defaults(app):
    with app.app_context():
        db.create_all()
        d = Device(client_uid="uid-123", fingerprint="fp-abc", device_name="門市iPad")
        db.session.add(d)
        db.session.commit()
        assert d.id is not None
        assert d.is_approved is False
        assert d.is_revoked is False
        assert d.created_at is not None
        assert d.last_seen_at is not None


def test_client_uid_unique(app):
    with app.app_context():
        db.create_all()
        db.session.add(Device(client_uid="dup"))
        db.session.commit()
        db.session.add(Device(client_uid="dup"))
        import pytest, sqlalchemy
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_user_face_encoding_roundtrip(app):
    with app.app_context():
        db.create_all()
        enc = np.arange(128, dtype=np.float64)
        u = User(name="小明", role="employee")
        u.face_encoding = enc.tobytes()
        db.session.add(u)
        db.session.commit()
        back = np.frombuffer(u.face_encoding, dtype=np.float64)
        assert back.shape == (128,)
        assert np.allclose(back, enc)
