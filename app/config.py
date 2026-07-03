import os
from datetime import timedelta


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///dev.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=35)

    # 隱蔽登入暗號（可經 env 改；預設 078*2）
    EXPENSE_TRIGGER_CODE = os.environ.get("EXPENSE_TRIGGER_CODE", "078*2")
    # 匯率
    FX_API_URL = os.environ.get("FX_API_URL", "https://open.er-api.com/v6/latest/USD")
    FX_TTL_SECONDS = int(os.environ.get("FX_TTL_SECONDS", str(6 * 3600)))
    FX_FETCH_TIMEOUT = int(os.environ.get("FX_FETCH_TIMEOUT", "8"))


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
