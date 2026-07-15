"""店別停用 → 該店裝置一律未授權（擋在最外層計算機）；綁定經理的裝置不擋。"""
from app.extensions import db
from app.models import Store, User, Device
from app.devices.routes import is_device_authorized


def _mk(app):
    with app.app_context():
        db.create_all()
        s = Store(name="A", code="A")
        db.session.add(s); db.session.commit()
        emp = User(name="員工", role="employee", store_id=s.id, active=True)
        sup = User(name="經理", role="super_admin", store_id=None, active=True)
        db.session.add_all([emp, sup]); db.session.commit()
        # 共用店機（綁員工）、經理機（綁 super_admin，但 store_id 設成該店以測豁免）
        shared = Device(client_uid="shared", store_id=s.id, bound_user_id=emp.id,
                        is_approved=True, is_revoked=False)
        mgr_dev = Device(client_uid="mgrdev", store_id=s.id, bound_user_id=sup.id,
                         is_approved=True, is_revoked=False)
        db.session.add_all([shared, mgr_dev]); db.session.commit()
        return s.id


def test_active_store_device_authorized(app):
    _mk(app)
    with app.app_context():
        assert is_device_authorized("shared") is True


def test_disabled_store_blocks_shared_device(app):
    sid = _mk(app)
    with app.app_context():
        db.session.get(Store, sid).active = False
        db.session.commit()
        # 該店共用裝置被擋（回卡在計算機最外層）
        assert is_device_authorized("shared") is False


def test_disabled_store_still_allows_super_admin_device(app):
    sid = _mk(app)
    with app.app_context():
        db.session.get(Store, sid).active = False
        db.session.commit()
        # 綁經理的裝置不擋，讓經理仍能進後台重新啟用
        assert is_device_authorized("mgrdev") is True
