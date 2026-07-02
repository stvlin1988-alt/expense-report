import base64
import time

from flask import Blueprint, current_app, request, session, jsonify
from sqlalchemy import or_

from app.extensions import limiter
from app.models.user import User
from app.models.device import Device
from app.devices.routes import UID_COOKIE_NAME
from app.face.engine import best_match_among, encode_face_async

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login(user):
    session["user_id"] = user.id
    session.permanent = True
    session["_last_request_at"] = int(time.time())


def _candidate_users():
    """該裝置所屬店的在職 user + 全域角色（accountant/super_admin）。"""
    uid = (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None
    device = Device.query.filter_by(client_uid=uid).first() if uid else None
    store_id = device.store_id if device else None
    q = User.query.filter_by(active=True)
    conds = [User.role.in_(("accountant", "super_admin"))]
    if store_id is not None:
        conds.append(User.store_id == store_id)
    return q.filter(or_(*conds)).all()


@auth_bp.post("/verify")
@limiter.limit(
    "20 per minute",
    exempt_when=lambda: current_app.config.get("TESTING"),
)
def verify():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    face_image = data.get("face_image")

    pin_users = [u for u in _candidate_users() if u.check_password(password)]
    if not pin_users:
        return jsonify(status="wrong_password")

    face_enrolled = [u for u in pin_users if u.face_encoding is not None]
    if not face_enrolled:
        return jsonify(status="need_face_enroll")
    if not face_image:
        return jsonify(status="face_mismatch")

    try:
        img_bytes = base64.b64decode(str(face_image).split(",")[-1])
    except Exception:
        img_bytes = b""
    submitted = encode_face_async(img_bytes)
    if submitted is None:
        return jsonify(status="face_not_found")

    matched, info = best_match_among(face_enrolled, submitted)
    if matched is None:
        return jsonify(status="ambiguous" if info.get("ambiguous") else "face_mismatch")

    if matched.store_id and matched.store and not matched.store.active:
        return jsonify(status="store_disabled")

    login(matched)
    return jsonify(status="ok", id=matched.id, name=matched.name, role=matched.role)


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify(status="ok")
