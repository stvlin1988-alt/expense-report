from flask import Blueprint

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

from app.audit import routes  # noqa: E402,F401
