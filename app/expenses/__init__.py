from flask import Blueprint

expense_bp = Blueprint("expenses", __name__, url_prefix="/expenses")

from app.expenses import routes  # noqa: E402,F401  綁定路由
