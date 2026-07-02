from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.user import User
from app.models.store import Store
from app.auth.decorators import current_user, role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLES = ("employee", "manager", "accountant", "super_admin")


def _manages(actor, target):
    if actor is None:
        return False
    if actor.role == "super_admin":
        return True
    if actor.role == "manager":
        return target.store_id is not None and target.store_id == actor.store_id
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
    if actor.role == "manager" and store_id != actor.store_id:
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
