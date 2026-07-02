from functools import wraps
from flask import session, jsonify
from app.models.user import User


def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None


def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return jsonify(error="unauthenticated"), 401
            if roles and user.role not in roles:
                return jsonify(error="forbidden"), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco
