from flask import Blueprint

period_bp = Blueprint("periods", __name__, url_prefix="/periods")

from app.periods import routes  # noqa: E402,F401
