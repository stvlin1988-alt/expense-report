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

    from app.extensions import db, migrate
    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401  確保 models 被載入註冊

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    from app.auth import auth_bp
    app.register_blueprint(auth_bp)

    from app.devices import device_bp
    app.register_blueprint(device_bp)

    return app
