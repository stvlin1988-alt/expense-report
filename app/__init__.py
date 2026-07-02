from flask import Flask, jsonify


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or "app.config.Config")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app
