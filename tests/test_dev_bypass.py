"""鎖住 dev 登入捷徑的安全不變式：
只有『E2E_LOGIN_BYPASS 為真 且 非 production』才會註冊 /dev 路由。"""
from app import create_app
from app.config import TestConfig


class _BypassDev(TestConfig):
    E2E_LOGIN_BYPASS = True
    APP_ENV = "development"


class _BypassProd(TestConfig):
    E2E_LOGIN_BYPASS = True
    APP_ENV = "production"
    SECRET_KEY = "a-secure-secret-for-test"


class _NoBypass(TestConfig):
    E2E_LOGIN_BYPASS = False
    APP_ENV = "development"


def _has_dev_routes(app):
    return any(r.rule.startswith("/dev/") for r in app.url_map.iter_rules())


def _init_db(app):
    with app.app_context():
        from app.extensions import db
        db.create_all()


def test_bypass_off_by_default_not_registered():
    app = create_app(_NoBypass)
    _init_db(app)  # gate 的 is_seed_mode 會查 DB
    assert not _has_dev_routes(app)
    assert app.test_client().get("/dev/login-test").status_code == 404


def test_bypass_not_registered_in_production():
    # 即使旗標開，production 也絕不註冊（__init__ 的第二道鎖）
    app = create_app(_BypassProd)
    _init_db(app)
    assert not _has_dev_routes(app)
    assert app.test_client().get("/dev/login-test").status_code == 404


def test_bypass_works_in_dev_when_flagged():
    app = create_app(_BypassDev)
    _init_db(app)
    assert _has_dev_routes(app)
    c = app.test_client()
    resp = c.get("/dev/login-test")
    assert resp.status_code == 302  # 登入後導回 /
    assert c.get("/dev/sample-receipt").status_code == 200
