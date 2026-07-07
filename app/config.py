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

    # 儲存（R2 / mock）
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "mock")
    R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET = os.environ.get("R2_BUCKET", "")
    R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "")
    R2_URL_EXPIRE_SECONDS = int(os.environ.get("R2_URL_EXPIRE_SECONDS", "300"))


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
