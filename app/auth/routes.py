from flask import Blueprint, request, session, jsonify
from app.extensions import db
from app.models.user import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(name=data.get("name"), active=True).first()
    if user is None or not user.check_password(data.get("password", "")):
        return jsonify(error="invalid credentials"), 401
    session["user_id"] = user.id
    return jsonify(id=user.id, name=user.name, role=user.role)


@auth_bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify(status="ok")
