from flask import Flask, jsonify


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or "app.config.Config")

    from app.extensions import db, migrate
    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401  確保 models 被載入註冊

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    from app.auth import auth_bp
    app.register_blueprint(auth_bp)

    return app
