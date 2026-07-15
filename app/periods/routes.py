from datetime import date, timedelta
from flask import request, jsonify
from app.extensions import db
from app.models import AccountingPeriod
from app.auth.decorators import role_required
from app.periods import period_bp
from app.periods.settings import get_close_day, get_lock_offset_hours, set_setting
from app.periods.service import lock_at_for, successor_bounds


@period_bp.get("/settings")
@role_required("accountant", "super_admin")   # 會計可改、經理唯讀 → 兩者皆可觀看
def get_settings():
    return jsonify(status="ok",
                    period_close_day=get_close_day(),
                    period_lock_offset_hours=get_lock_offset_hours())


@period_bp.patch("/settings")
@role_required("accountant")                  # 僅會計可編輯（經理唯讀）
def patch_settings():
    data = request.get_json(silent=True) or {}
    if "period_close_day" in data:
        try:
            d = int(data["period_close_day"])
        except (TypeError, ValueError):
            return jsonify(status="error", message="bad_close_day"), 400
        if not (1 <= d <= 28):
            return jsonify(status="error", message="bad_close_day"), 400
        set_setting("period_close_day", d)
    if "period_lock_offset_hours" in data:
        try:
            h = int(data["period_lock_offset_hours"])
        except (TypeError, ValueError):
            return jsonify(status="error", message="bad_offset"), 400
        if not (0 <= h <= 168):
            return jsonify(status="error", message="bad_offset"), 400
        set_setting("period_lock_offset_hours", h)
    db.session.commit()
    return jsonify(status="ok")


@period_bp.patch("/<int:pid>/end-date")
@role_required("accountant")                  # 農曆年調整：僅會計（經理唯讀）
def edit_end_date(pid):
    p = db.session.get(AccountingPeriod, pid)
    if p is None:
        return jsonify(status="error", message="not found"), 404
    if p.status == "closed":
        return jsonify(status="error", message="period_closed"), 409
    try:
        new_end = date.fromisoformat((request.get_json(silent=True) or {}).get("end_date", ""))
    except (TypeError, ValueError):
        return jsonify(status="error", message="bad_date"), 400
    if new_end < p.start_date:
        return jsonify(status="error", message="end_before_start"), 400

    offset = get_lock_offset_hours()
    close_day = get_close_day()
    p.end_date = new_end
    # 本期 lock_at 依新 end_date 重算（換期日=new_end+1 起算 offset）
    p.lock_at = lock_at_for(new_end + timedelta(days=1), offset)

    # 明確維護「下一期」，保證首尾相接、不留孤兒日、不與 canonical 重疊。
    nxt = (AccountingPeriod.query
           .filter(AccountingPeriod.start_date > p.start_date)
           .order_by(AccountingPeriod.start_date.asc()).first())
    if nxt is not None:
        if nxt.status == "closed":
            db.session.rollback()
            return jsonify(status="error", message="next_period_closed"), 409
        nxt.start_date = new_end + timedelta(days=1)
        nxt.lock_at = lock_at_for(nxt.end_date + timedelta(days=1), offset)
        if nxt.start_date > nxt.end_date:
            db.session.rollback()
            return jsonify(status="error", message="would_invert_next"), 400
    else:
        # 下一期還沒被建過 → 現在就建，讓 new_end 之後的日子有歸屬
        s, e, label = successor_bounds(p, close_day)
        db.session.add(AccountingPeriod(
            label=label, start_date=s, end_date=e,
            lock_at=lock_at_for(e + timedelta(days=1), offset), status="open"))
    db.session.commit()
    return jsonify(status="ok")
