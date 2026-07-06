import hashlib
import os

from flask import (Blueprint, current_app, render_template, request, session,
                   send_from_directory)

from app.auth.gates import is_seed_mode
from app.devices.routes import is_device_authorized, UID_COOKIE_NAME
from app.models.user import User
from app.extensions import db

web_bp = Blueprint("web", __name__)


def _secret_hash():
    code = current_app.config["EXPENSE_TRIGGER_CODE"]
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@web_bp.get("/")
def index():
    identity = None
    uid = session.get("user_id")
    if uid:
        u = db.session.get(User, uid)
        if u and u.active:
            identity = {"id": u.id, "name": u.name, "role": u.role}

    seed = is_seed_mode()
    device_uid = (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None
    approved = is_device_authorized(device_uid)
    secret_hash = _secret_hash() if (seed or approved) else None

    return render_template(
        "index.html",
        seed_mode=seed,
        secret_hash=secret_hash,
        identity=identity,
    )


@web_bp.get("/sw.js")
def service_worker():
    return send_from_directory(
        os.path.join(current_app.root_path, "static"),
        "sw.js",
        mimetype="application/javascript",
    )
