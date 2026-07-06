from flask import Blueprint, request, jsonify
from sqlalchemy import and_, or_

from app.extensions import db
from app.models.user import User, ROLES, is_valid_pin
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
    code = (data.get("code") or "").strip()
    # 店別以英文代碼為唯一識別；未給 name 時 name 預設等於 code。
    name = (data.get("name") or "").strip() or code
    if not code:
        return jsonify(status="error", message="code required"), 400
    if Store.query.filter_by(code=code).first() or Store.query.filter_by(name=name).first():
        return jsonify(status="error", message="store exists"), 409
    store = Store(name=name, code=code)
    db.session.add(store); db.session.commit()
    return jsonify(status="ok", id=store.id)


@admin_bp.get("/stores")
@role_required("manager", "super_admin")
def list_stores():
    # 經理與主管皆回全部店：主管改「本店帳號」的店別時需要目標店清單（店代碼非敏感資料）。
    stores = Store.query.order_by(Store.id).all()
    return jsonify(status="ok", stores=[
        {"id": s.id, "name": s.name, "code": s.code} for s in stores
    ])


@admin_bp.delete("/stores/<int:store_id>")
@role_required("super_admin")
def delete_store(store_id):
    store = db.session.get(Store, store_id)
    if store is None:
        return jsonify(status="error", message="store not found"), 404
    # 有帳號或裝置綁定的店不可刪（避免孤兒資料/破壞在用中的店）
    if User.query.filter_by(store_id=store_id).count() > 0:
        return jsonify(status="error", message="store has users"), 409
    if Device.query.filter_by(store_id=store_id).count() > 0:
        return jsonify(status="error", message="store has devices"), 409
    db.session.delete(store); db.session.commit()
    return jsonify(status="ok")


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
    if not is_valid_pin(password):
        return jsonify(status="error", message="pin must be 4 digits"), 400

    actor = current_user()
    # normalize store_id to int when present
    if store_id is not None:
        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            return jsonify(status="error", message="invalid store_id"), 400
        if db.session.get(Store, store_id) is None:
            return jsonify(status="error", message="store not found"), 400
    if actor.role == "manager":
        if role != "employee" or store_id != actor.store_id:
            return jsonify(status="error", message="forbidden"), 403

    user = User(name=name, role=role, store_id=store_id)
    user.set_password(password)
    db.session.add(user); db.session.commit()
    return jsonify(status="ok", id=user.id)


@admin_bp.get("/users")
@role_required("manager", "super_admin")
def list_users():
    actor = current_user()
    q = User.query
    if actor.role == "super_admin":
        store_id_filter = request.args.get("store_id", type=int)
        if store_id_filter is not None:
            q = q.filter(User.store_id == store_id_filter)
    else:  # manager：僅本店
        q = q.filter(User.store_id == actor.store_id)
    users = q.order_by(User.id).all()
    return jsonify(status="ok", users=[
        {"id": u.id, "name": u.name, "role": u.role, "store_id": u.store_id,
         "active": u.active, "has_face": u.face_encoding is not None}
        for u in users
    ])


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
    if not is_valid_pin(new_password):
        return jsonify(status="error", message="pin must be 4 digits"), 400
    target.set_password(new_password); db.session.commit()
    return jsonify(status="ok")


@admin_bp.post("/users/<int:user_id>/active")
@role_required("manager", "super_admin")
def set_user_active(user_id):
    data = request.get_json(silent=True) or {}
    active = data.get("active")
    if not isinstance(active, bool):
        return jsonify(status="error", message="active must be bool"), 400
    target = db.session.get(User, user_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404
    actor = current_user()
    if active is False and target.id == actor.id:
        return jsonify(status="error", message="cannot deactivate self"), 400
    if not _manages(actor, target):
        return jsonify(status="error", message="forbidden"), 403
    if active is False and target.role == "super_admin":
        # Defence-in-depth (spec §5.3 禁止停用最後一位在職 super_admin)。
        # 目前結構上被上方自我守門完全遮蔽而不可達：能走到這裡且 target != actor 的
        # actor 自己必為在職 super_admin（current_user 要求 active=True），故 others>=1；
        # 而 actor == target 早已被自我守門 400 攔下。刻意保留，避免未來若重構自我守門
        # 時「最後一位 super_admin」的保護被悄悄拿掉而無人察覺。
        others = User.query.filter(
            User.role == "super_admin",
            User.active.is_(True),
            User.id != target.id,
        ).count()
        if others == 0:
            return jsonify(status="error", message="cannot deactivate last super_admin"), 400
    target.active = active
    db.session.commit()
    return jsonify(status="ok")


@admin_bp.post("/users/<int:user_id>/store")
@role_required("manager", "super_admin")
def set_user_store(user_id):
    """改帳號店別：經理可改任何人；主管僅本店員工（沿用 _manages）。目標店可為任一有效店或 null。"""
    data = request.get_json(silent=True) or {}
    store_id = data.get("store_id")
    target = db.session.get(User, user_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404
    actor = current_user()
    # 經理可改任何人；主管可改本店員工，也可改自己的店別
    if not (_manages(actor, target) or target.id == actor.id):
        return jsonify(status="error", message="forbidden"), 403
    if store_id is not None:
        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            return jsonify(status="error", message="invalid store_id"), 400
        if db.session.get(Store, store_id) is None:
            return jsonify(status="error", message="store not found"), 400
    target.store_id = store_id
    db.session.commit()
    return jsonify(status="ok")


@admin_bp.post("/users/<int:user_id>/role")
@role_required("super_admin")
def set_user_role(user_id):
    """改帳號角色：僅經理(super_admin)。守門：不可改自己、不可把最後一位在職經理降級。"""
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    if role not in ROLES:
        return jsonify(status="error", message="invalid role"), 400
    target = db.session.get(User, user_id)
    if target is None:
        return jsonify(status="error", message="user not found"), 404
    actor = current_user()
    if target.id == actor.id:
        return jsonify(status="error", message="cannot change own role"), 400
    if target.role == "super_admin" and role != "super_admin":
        others = User.query.filter(
            User.role == "super_admin",
            User.active.is_(True),
            User.id != target.id,
        ).count()
        if others == 0:
            return jsonify(status="error", message="cannot demote last super_admin"), 400
    target.role = role
    db.session.commit()
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
    if not is_valid_pin(new_password):
        return jsonify(status="error", message="pin must be 4 digits"), 400
    actor.set_password(new_password); db.session.commit()
    return jsonify(status="ok")


def _visible_device_query(actor, store_id_filter=None):
    if actor.role == "manager":
        return (
            Device.query.outerjoin(User, Device.bound_user_id == User.id)
            .filter(
                or_(
                    Device.store_id == actor.store_id,
                    and_(Device.store_id.is_(None), Device.is_approved.is_(False)),
                    User.store_id == actor.store_id,
                )
            )
        )
    # super_admin
    q = Device.query
    if store_id_filter is not None:
        q = q.filter(Device.store_id == store_id_filter)
    return q


def _manages_device(actor, device):
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return (
            (device.store_id is None and not device.is_approved)
            or device.store_id == actor.store_id
            or (device.bound_user is not None and device.bound_user.store_id == actor.store_id)
        )
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

    # Validate new_user: if provided, must be a dict
    if new_user is not None and not isinstance(new_user, dict):
        return jsonify(status="error", message="invalid new_user"), 400

    resolved_store_id = None

    if new_user:
        name = (new_user.get("name") or "").strip()
        password = str(new_user.get("password") or "")
        role = new_user.get("role") or "employee"
        if not name or not password:
            return jsonify(status="error", message="name/password required"), 400
        if role not in ROLES:
            return jsonify(status="error", message="invalid role"), 400
        if actor.role == "manager":
            if role != "employee":
                return jsonify(status="error", message="forbidden"), 403
            resolved_store_id = actor.store_id
        else:  # super_admin
            try:
                resolved_store_id = int(new_user.get("store_id"))
            except (TypeError, ValueError):
                return jsonify(status="error", message="invalid store_id"), 400
            if db.session.get(Store, resolved_store_id) is None:
                return jsonify(status="error", message="store not found"), 400
        if not is_valid_pin(password):
            return jsonify(status="error", message="pin must be 4 digits"), 400
        u = User(name=name, role=role, store_id=resolved_store_id)
        u.set_password(password)
        db.session.add(u); db.session.flush()
        bound_user_id = u.id

    elif bound_user_id is not None:
        try:
            bound_user_id = int(bound_user_id)
        except (TypeError, ValueError):
            return jsonify(status="error", message="invalid bound_user_id"), 400
        target = db.session.get(User, bound_user_id)
        if target is None:
            return jsonify(status="error", message="user not found"), 404
        if not _manages(actor, target):
            return jsonify(status="error", message="forbidden"), 403
        resolved_store_id = target.store_id

    else:
        # 裸核准（不換新機也不換帳號）：裝置歸屬需明確指派
        if actor.role == "manager":
            resolved_store_id = actor.store_id
        else:  # super_admin
            try:
                resolved_store_id = int(data.get("store_id"))
            except (TypeError, ValueError):
                return jsonify(status="error", message="store_id required"), 400
            if db.session.get(Store, resolved_store_id) is None:
                return jsonify(status="error", message="store not found"), 400

    if resolved_store_id is None:
        return jsonify(status="error", message="store could not be resolved"), 400

    if bound_user_id is not None:
        # 換機：撤該 user 其他已核准裝置（撤舊發新）
        for old in Device.query.filter(
            Device.bound_user_id == bound_user_id,
            Device.id != device.id,
            Device.is_approved.is_(True),
        ).all():
            old.is_revoked = True
        device.bound_user_id = bound_user_id

    device.store_id = resolved_store_id
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
