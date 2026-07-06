import base64
import binascii
import time
import uuid

import numpy as np
from flask import Blueprint, current_app, request, session, jsonify

from app.extensions import db, limiter
from app.models.user import User, is_valid_pin
from app.models.device import Device
from app.devices.routes import UID_COOKIE_NAME, _set_uid_cookie, _clean_str
from app.face.engine import best_match_among, encode_face_async

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login(user):
    session["user_id"] = user.id
    session.permanent = True
    session["_last_request_at"] = int(time.time())


def _super_admin_with_face_count():
    return User.query.filter(
        User.role == "super_admin", User.face_encoding.isnot(None)
    ).count()


@auth_bp.post("/bootstrap")
@limiter.limit(
    "5 per minute",
    exempt_when=lambda: current_app.config.get("TESTING"),
)
def bootstrap():
    """Seed-only 首次啟用：建立第一位 super_admin + 核准當前裝置。"""
    if _super_admin_with_face_count() > 0:
        return jsonify(status="already_initialized"), 403

    data = request.get_json(silent=True) or {}
    name = _clean_str(data.get("name"), 100)
    password = data.get("password")
    password = password if isinstance(password, str) else ""
    face_image = data.get("face_image")

    if not name or not password:
        return jsonify(status="error", message="name/password required"), 400
    if not is_valid_pin(password):
        return jsonify(status="error", message="pin must be 4 digits"), 400
    if not face_image:
        return jsonify(status="face_not_found")

    try:
        img_bytes = base64.b64decode(str(face_image).split(",")[-1])
    except (binascii.Error, ValueError):
        img_bytes = b""
    encoding = encode_face_async(img_bytes)
    if encoding is None:
        return jsonify(status="face_not_found")

    owner = User(name=name, role="super_admin", store_id=None)
    owner.set_password(password)
    owner.face_encoding = np.asarray(encoding, dtype=np.float64).tobytes()
    db.session.add(owner)
    db.session.flush()

    # 競態收斂：flush 後重查，若已有其他 super_admin 搶先建立（race），回滾放棄。
    if _super_admin_with_face_count() > 1:
        db.session.rollback()
        return jsonify(status="already_initialized"), 403

    uid = (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None
    device = Device.query.filter_by(client_uid=uid).first() if uid else None
    if device is None:
        uid = uid or uuid.uuid4().hex
        device = Device(client_uid=uid)
        db.session.add(device)
    device.is_approved = True
    device.is_revoked = False
    device.bound_user_id = owner.id
    db.session.commit()

    login(owner)
    resp = jsonify(status="ok", id=owner.id)
    _set_uid_cookie(resp, uid)
    return resp


def _candidate_users():
    """公務機模式：裝置一經核准（由 device gate 保證），任一在職帳號皆為登入候選，
    不再受裝置所屬店別限制。登入以密碼先過濾、再用人臉在密碼吻合者中找最接近的帳號；
    帳號之間以密碼區分（同密碼且同臉才會判為撞臉 ambiguous）。"""
    return User.query.filter_by(active=True).all()


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
    except (binascii.Error, ValueError):
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
    return jsonify(
        status="ok",
        id=matched.id,
        name=matched.name,
        role=matched.role,
        store_id=matched.store_id,
    )


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify(status="ok")
