import base64

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.user import User
from app.auth.decorators import current_user
from app.face.engine import encode_face_async

face_bp = Blueprint("face", __name__, url_prefix="/face")


def _can_enroll(actor, target):
    if actor is None:
        return False
    if actor.id == target.id:
        return True
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return target.store_id == actor.store_id
    return False


@face_bp.post("/enroll")
def enroll():
    data = request.get_json(silent=True) or {}
    face_image = data.get("face_image")
    target_id = data.get("user_id")

    actor = current_user()
    if target_id is None:
        target = actor
    else:
        target = db.session.get(User, target_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404

    if actor is None:
        return jsonify(status="error", message="unauthenticated"), 401
    if not _can_enroll(actor, target):
        return jsonify(status="error", message="forbidden"), 403

    if not face_image:
        return jsonify(status="face_not_found")
    try:
        img_bytes = base64.b64decode(str(face_image).split(",")[-1])
    except Exception:
        img_bytes = b""
    encoding = encode_face_async(img_bytes)
    if encoding is None:
        return jsonify(status="face_not_found")

    import numpy as np
    target.face_encoding = np.asarray(encoding, dtype=np.float64).tobytes()
    db.session.commit()
    return jsonify(status="ok")
