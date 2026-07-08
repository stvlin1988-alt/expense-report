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
    # 開發專用：跳過密碼/人臉的一鍵登入捷徑。production 一律無效，且需明設此旗標才註冊路由。
    E2E_LOGIN_BYPASS = os.environ.get("E2E_LOGIN_BYPASS", "").lower() in ("1", "true", "yes")
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

    # OCR
    OCR_PROVIDER = os.environ.get("OCR_PROVIDER", "mock")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "30"))
    # lite 底模預設不思考；-1=動態思考(手寫/難單金額才讀得穩)，0=關閉
    GEMINI_THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", "-1"))
    GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))
    GEMINI_RETRY_BASE = float(os.environ.get("GEMINI_RETRY_BASE", "0.5"))
    OCR_MAX_ROUNDS = int(os.environ.get("OCR_MAX_ROUNDS", "3"))
    # 暫存區/燈號
    OCR_STALE_SECONDS = int(os.environ.get("OCR_STALE_SECONDS", "120"))
    GREEN_THRESHOLD = float(os.environ.get("GREEN_THRESHOLD", "0.85"))
    EXPENSE_OCR_SYNC = os.environ.get("EXPENSE_OCR_SYNC", "false").lower() == "true"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    EXPENSE_OCR_SYNC = True
    OCR_PROVIDER = "mock"
