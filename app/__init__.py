from flask import Flask, jsonify


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or "app.config.Config")

    if not app.testing and app.config.get("APP_ENV") == "production" \
            and app.config.get("SECRET_KEY") in (None, "", "dev-insecure-key"):
        raise RuntimeError(
            "SECRET_KEY must be set to a secure value when APP_ENV=production; "
            "refusing to start with the insecure default."
        )

    from app.extensions import db, migrate, limiter
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    from app import models  # noqa: F401  確保 models 被載入註冊

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    from app.auth import auth_bp
    app.register_blueprint(auth_bp)

    from app.devices import device_bp
    app.register_blueprint(device_bp)

    from app.auth.gates import register_gates
    register_gates(app)

    from app.face.routes import face_bp
    app.register_blueprint(face_bp)

    from app.admin import admin_bp
    app.register_blueprint(admin_bp)

    from app.web import web_bp
    app.register_blueprint(web_bp)

    from app.fx import fx_bp
    app.register_blueprint(fx_bp)

    from app.expenses import expense_bp
    app.register_blueprint(expense_bp)

    from app.audit import audit_bp
    app.register_blueprint(audit_bp)

    # 開發專用一鍵登入捷徑：僅在旗標開啟且非 production 時註冊（prod 連路由都沒有）
    if app.config.get("E2E_LOGIN_BYPASS") and app.config.get("APP_ENV") != "production":
        from app.dev import dev_bp
        app.register_blueprint(dev_bp)

    return app
