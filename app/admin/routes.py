from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.user import User, ROLES
from app.models.store import Store
from app.models.device import Device
from app.auth.decorators import current_user, role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _manages(actor, target):
    if actor is None:
        return False
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return (
            target.role == "employee"
            and target.store_id is not None
            and target.store_id == actor.store_id
        )
    return False


@admin_bp.post("/stores")
@role_required("super_admin")
def create_store():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    code = (data.get("code") or "").strip()
    if not name or not code:
        return jsonify(status="error", message="name/code required"), 400
    if Store.query.filter_by(code=code).first() or Store.query.filter_by(name=name).first():
        return jsonify(status="error", message="store exists"), 409
    store = Store(name=name, code=code)
    db.session.add(store); db.session.commit()
    return jsonify(status="ok", id=store.id)


@admin_bp.post("/users")
@role_required("manager", "super_admin")
def create_user():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    password = str(data.get("password") or "")
    role = data.get("role") or "employee"
    store_id = data.get("store_id")
    if not name or not password or role not in ROLES:
        return jsonify(status="error", message="invalid input"), 400

    actor = current_user()
    # normalize store_id to int when present
    if store_id is not None:
        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            return jsonify(status="error", message="invalid store_id"), 400
    if actor.role == "manager":
        if role != "employee" or store_id != actor.store_id:
            return jsonify(status="error", message="forbidden"), 403

    user = User(name=name, role=role, store_id=store_id)
    user.set_password(password)
    db.session.add(user); db.session.commit()
    return jsonify(status="ok", id=user.id)


@admin_bp.post("/users/<int:user_id>/password")
@role_required("manager", "super_admin")
def reset_password(user_id):
    data = request.get_json(silent=True) or {}
    new_password = str(data.get("password") or "")
    if not new_password:
        return jsonify(status="error", message="password required"), 400
    target = db.session.get(User, user_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404
    if not _manages(current_user(), target):
        return jsonify(status="error", message="forbidden"), 403
    target.set_password(new_password); db.session.commit()
    return jsonify(status="ok")


@admin_bp.post("/me/password")
def change_own_password():
    actor = current_user()
    if actor is None:
        return jsonify(status="error", message="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    if not actor.check_password(str(data.get("old_password") or "")):
        return jsonify(status="error", message="wrong old password"), 400
    new_password = str(data.get("new_password") or "")
    if not new_password:
        return jsonify(status="error", message="new password required"), 400
    actor.set_password(new_password); db.session.commit()
    return jsonify(status="ok")


def _visible_device_query(actor, store_id_filter=None):
    q = Device.query
    if actor.role == "manager":
        return q.filter(Device.store_id == actor.store_id)
    # super_admin
    if store_id_filter is not None:
        return q.filter(Device.store_id == store_id_filter)
    return q


def _manages_device(actor, device):
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return device.store_id == actor.store_id
    return False


@admin_bp.get("/devices")
@role_required("manager", "super_admin")
def list_devices():
    actor = current_user()
    store_id_filter = request.args.get("store_id", type=int)
    devices = _visible_device_query(actor, store_id_filter).order_by(
        Device.created_at.desc()
    ).all()
    return jsonify(status="ok", devices=[
        {"id": d.id, "client_uid": d.client_uid, "device_name": d.device_name,
         "store_id": d.store_id, "bound_user_id": d.bound_user_id,
         "is_approved": d.is_approved, "is_revoked": d.is_revoked}
        for d in devices
    ])


@admin_bp.post("/devices/<int:device_id>/approve")
@role_required("manager", "super_admin")
def approve_device(device_id):
    actor = current_user()
    device = db.session.get(Device, device_id)
    if device is None:
        return jsonify(status="error", message="device not found"), 404
    if not _manages_device(actor, device):
        return jsonify(status="error", message="forbidden"), 403

    data = request.get_json(silent=True) or {}
    bound_user_id = data.get("bound_user_id")
    new_user = data.get("new_user")

    if new_user:
        name = (new_user.get("name") or "").strip()
        password = str(new_user.get("password") or "")
        role = new_user.get("role") or "employee"
        if not name or not password:
            return jsonify(status="error", message="name/password required"), 400
        if role not in ROLES:
            return jsonify(status="error", message="invalid role"), 400
        if actor.role == "manager" and role != "employee":
            return jsonify(status="error", message="forbidden"), 403
        u = User(name=name, role=role, store_id=device.store_id)
        u.set_password(password)
        db.session.add(u); db.session.flush()
        bound_user_id = u.id

    elif bound_user_id is not None:
        target = db.session.get(User, bound_user_id)
        if target is None:
            return jsonify(status="error", message="user not found"), 404
        if not _manages(actor, target):
            return jsonify(status="error", message="forbidden"), 403

    if bound_user_id is not None:
        # 換機：撤該 user 其他已核准裝置（撤舊發新）
        for old in Device.query.filter(
            Device.bound_user_id == bound_user_id,
            Device.id != device.id,
            Device.is_approved.is_(True),
        ).all():
            old.is_revoked = True
        device.bound_user_id = bound_user_id

    device.is_approved = True
    device.is_revoked = False
    db.session.commit()
    return jsonify(status="ok", bound_user_id=device.bound_user_id)


@admin_bp.post("/devices/<int:device_id>/revoke")
@role_required("manager", "super_admin")
def revoke_device(device_id):
    actor = current_user()
    device = db.session.get(Device, device_id)
    if device is None:
        return jsonify(status="error", message="device not found"), 404
    if not _manages_device(actor, device):
        return jsonify(status="error", message="forbidden"), 403
    device.is_revoked = True
    db.session.commit()
    return jsonify(status="ok")
