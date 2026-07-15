from datetime import datetime, timezone

from flask import request, jsonify

from app.extensions import db
from app.models import Expense, Category, Store, AccountingPeriod
from app.auth.decorators import role_required
from app.reports import report_bp
from app.reports.service import build_cross_table
from app.periods.service import (get_or_create_period, effective_status,
                                 maybe_autoclose)
from app.expenses.logic import compute_business_date


@report_bp.get("/monthly")
@role_required("accountant", "super_admin")
def monthly():
    now = datetime.now(timezone.utc)
    pid = request.args.get("period_id", type=int)
    if pid is not None:
        period = db.session.get(AccountingPeriod, pid)
    else:
        period = get_or_create_period(compute_business_date(now))
    if period is None:
        return jsonify(status="error", message="not found"), 404
    maybe_autoclose(period, now)
    db.session.commit()

    rows = Expense.query.filter(
        Expense.period_id == period.id,
        Expense.status.in_(Expense.CHECKED_STATUSES)).all()
    cats = {c.id: {"level": c.level, "parent_id": c.parent_id, "name": c.name}
            for c in Category.query.all()}
    # 店別顯示一律用英文代號（code），欄名帶 code 值（全系統不露店名，user 決策）
    stores = [{"id": s.id, "name": s.code}
              for s in Store.query.order_by(Store.code.asc()).all()]
    table = build_cross_table(rows, cats, stores, now, period)
    table["period"] = {"id": period.id, "label": period.label,
                       "status": effective_status(period, now)}
    table["status"] = "ok"
    return jsonify(**table)
