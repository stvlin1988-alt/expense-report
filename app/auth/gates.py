import time

from flask import request, session, jsonify

from app.models.user import User
from app.models.device import Device
from app.devices.routes import is_device_authorized, UID_COOKIE_NAME

IDLE_MAX_SECONDS = 30 * 60

_EXEMPT_PREFIXES = ("/static/", "/api/v1/")
_EXEMPT_PATHS = ("/health", "/sw.js", "/auth/logout")


def is_seed_mode():
    """任一成立即 seed mode：無 super_admin / 無已核准裝置 / 所有 super_admin 無臉。"""
    admins = User.query.filter_by(role="super_admin").all()
    if not admins:
        return True
    if Device.query.filter_by(is_approved=True).count() == 0:
        return True
    if all(a.face_encoding is None for a in admins):
        return True
    return False


def _is_exempt(path):
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


def register_gates(app):
    @app.before_request
    def _device_gate():
        path = request.path or ""
        if _is_exempt(path):
            return None
        if is_seed_mode():
            return None  # 首次啟用：放行以完成 bootstrap
        uid = (request.cookies.get(UID_COOKIE_NAME) or "").strip() or None
        if not is_device_authorized(uid):
            return jsonify(status="device_not_approved"), 403
        return None

    @app.before_request
    def _idle_gate():
        path = request.path or ""
        if _is_exempt(path):
            return None
        if not session.get("user_id"):
            return None
        now = int(time.time())
        last = session.get("_last_request_at")
        if last is not None and now - last > IDLE_MAX_SECONDS:
            session.clear()
            return jsonify(status="session_expired"), 401
        session["_last_request_at"] = now  # 滑動續命
        return None
