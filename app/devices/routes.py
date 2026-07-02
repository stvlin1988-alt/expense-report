import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.device import Device

device_bp = Blueprint("device", __name__, url_prefix="/api/v1")

UID_COOKIE_NAME = "device_uid"
UID_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 10  # 10 年
PENDING_DEVICE_TTL_MINUTES = 30


def _get_cookie_uid():
    return (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None


def _set_uid_cookie(resp, uid):
    resp.set_cookie(
        UID_COOKIE_NAME, uid,
        max_age=UID_COOKIE_MAX_AGE,
        httponly=True, secure=True, samesite="Lax",
    )


def _cleanup_pending_devices():
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=PENDING_DEVICE_TTL_MINUTES)
    stale = Device.query.filter(
        Device.is_approved.is_(False), Device.created_at < cutoff
    ).all()
    for d in stale:
        db.session.delete(d)
    if stale:
        db.session.commit()
    return len(stale)


def is_device_authorized(client_uid):
    """僅用 client_uid 判斷；fingerprint 永不參與。"""
    if not client_uid:
        return False
    d = Device.query.filter_by(client_uid=client_uid).first()
    if not d or not d.is_approved or d.is_revoked:
        return False
    if d.bound_user_id and d.bound_user and not d.bound_user.active:
        return False
    return True


@device_bp.post("/register-device")
def register_device():
    try:
        _cleanup_pending_devices()
    except Exception:
        db.session.rollback()

    data = request.get_json(silent=True) or {}
    fp = (data.get("fingerprint") or "").strip() or None
    body_uid = (data.get("client_uid") or "").strip() or None
    device_name = data.get("device_name") or "Unknown"

    uid = _get_cookie_uid() or body_uid
    device = Device.query.filter_by(client_uid=uid).first() if uid else None

    if device is None:
        uid = uid or uuid.uuid4().hex
        device = Device(client_uid=uid, fingerprint=fp, device_name=device_name)
        db.session.add(device)
    else:
        device.last_seen_at = datetime.now(timezone.utc)
        if fp:
            device.fingerprint = fp
    db.session.commit()

    resp = jsonify(status="ok",
                   approved=device.is_approved,
                   revoked=device.is_revoked)
    _set_uid_cookie(resp, uid)
    return resp
