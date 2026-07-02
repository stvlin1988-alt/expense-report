import pytest

from app import create_app
from app.config import Config, TestConfig


class ProdInsecureConfig:
    """production env, but SECRET_KEY left at the insecure default."""

    APP_ENV = "production"
    SECRET_KEY = "dev-insecure-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class ProdSecureConfig:
    """production env with a real secret configured."""

    APP_ENV = "production"
    SECRET_KEY = "a-real-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def test_create_app_raises_when_production_with_insecure_default_secret_key():
    with pytest.raises(RuntimeError):
        create_app(ProdInsecureConfig)


def test_create_app_does_not_raise_when_production_with_real_secret_key():
    app = create_app(ProdSecureConfig)
    assert app is not None


def test_create_app_does_not_raise_for_default_dev_config():
    # Local dev: APP_ENV unset/development, insecure default key, not testing.
    app = create_app(Config)
    assert app is not None


def test_create_app_does_not_raise_for_test_config():
    # TESTING=True must always skip the guard regardless of APP_ENV/SECRET_KEY.
    app = create_app(TestConfig)
    assert app is not None
