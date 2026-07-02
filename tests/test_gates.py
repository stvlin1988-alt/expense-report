import time
from app.extensions import db
from app.models.user import User
from app.models.device import Device
from app.auth.gates import is_seed_mode, IDLE_MAX_SECONDS


def _mk_super_admin_with_face():
    u = User(name="業主", role="super_admin")
    u.set_password("pw")
    u.face_encoding = b"\x00" * 1024
    return u


def test_seed_mode_true_when_no_super_admin(app):
    with app.app_context():
        db.create_all()
        assert is_seed_mode() is True


def test_seed_mode_true_when_no_approved_device(app):
    with app.app_context():
        db.create_all()
        db.session.add(_mk_super_admin_with_face())
        db.session.commit()
        assert is_seed_mode() is True  # 無已核准裝置


def test_seed_mode_false_when_admin_face_and_approved_device(app):
    with app.app_context():
        db.create_all()
        db.session.add(_mk_super_admin_with_face())
        db.session.add(Device(client_uid="d1", is_approved=True))
        db.session.commit()
        assert is_seed_mode() is False


def test_seed_mode_true_when_admin_has_no_face(app):
    with app.app_context():
        db.create_all()
        u = User(name="業主", role="super_admin"); u.set_password("pw")
        db.session.add(u)
        db.session.add(Device(client_uid="d1", is_approved=True))
        db.session.commit()
        assert is_seed_mode() is True


def test_idle_max_is_30_minutes():
    assert IDLE_MAX_SECONDS == 1800


def test_revoking_last_approved_device_reenters_seed_mode(app):
    """撤銷所有已核准裝置後應可重新回到 seed mode（可復原的鎖死）。"""
    with app.app_context():
        db.create_all()
        db.session.add(_mk_super_admin_with_face())
        dev = Device(client_uid="d1", is_approved=True, is_revoked=False)
        db.session.add(dev)
        db.session.commit()
        assert is_seed_mode() is False

        dev.is_revoked = True
        db.session.commit()
        assert is_seed_mode() is True
