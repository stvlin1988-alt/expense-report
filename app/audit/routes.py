from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from flask import request, jsonify
from app.extensions import db
from app.models import Expense, Store, Handover
from app.auth.decorators import current_user, role_required
from app.expenses.serialize import serialize_expense
from app.expenses.tasks import _valid_category_id
from app.storage.r2 import get_storage
from app.audit import audit_bp
from app.audit.log import snapshot, log_edit_if_changed, record_check


def _scope_store_id(from_body=False):
    """回 (store_id, error)。manager→本店；super_admin→需帶 store_id（GET 讀 query、POST 讀 body）。"""
    actor = current_user()
    if actor.role == "manager":
        return actor.store_id, None
    # super_admin
    if from_body:
        raw = (request.get_json(silent=True) or {}).get("store_id")
    else:
        raw = request.args.get("store_id")
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return None, (jsonify(status="error", message="store_id required"), 400)
    if db.session.get(Store, sid) is None:
        return None, (jsonify(status="error", message="store not found"), 400)
    return sid, None


@audit_bp.get("/pending")
@role_required("manager", "super_admin")
def pending():
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (Expense.query
            .filter(Expense.store_id == store_id, Expense.status == "submitted")
            .order_by(Expense.business_date.asc(), Expense.submitted_at.asc())
            .all())
    storage = get_storage()
    groups = {}
    for e in rows:
        key = e.business_date.isoformat() if e.business_date else "none"
        groups.setdefault(key, []).append(e)
    out = []
    for bd in sorted(groups):
        items = groups[bd]
        subtotal = sum(float(x.amount) for x in items if x.amount is not None)
        out.append({
            "business_date": bd, "subtotal": subtotal,
            "items": [serialize_expense(x, storage) for x in items],
        })
    return jsonify(status="ok", groups=out)


def _load_in_scope(eid, store_id):
    e = db.session.get(Expense, eid)
    if e is None:
        return None, (jsonify(status="error", message="not found"), 404)
    if e.store_id != store_id:
        return None, (jsonify(status="error", message="forbidden"), 403)
    return e, None


@audit_bp.patch("/<int:eid>")
@role_required("manager", "super_admin")
def edit(eid):
    store_id, err = _scope_store_id()
    if err:
        return err
    e, err = _load_in_scope(eid, store_id)
    if err:
        return err
    if e.status != "submitted":
        return jsonify(status="error", message="not editable"), 409
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
    if "amount" in data:
        try:
            e.amount = None if data["amount"] is None else Decimal(str(data["amount"]))
            e.amount_parse_ok = e.amount is not None
        except (InvalidOperation, ValueError):
            e.amount = None; e.amount_parse_ok = False
    if log_edit_if_changed(e, current_user().id, before):
        e.is_modified_by_manager = True
    db.session.commit()
    return jsonify(status="ok")


@audit_bp.post("/<int:eid>/check")
@role_required("manager", "super_admin")
def check(eid):
    store_id, err = _scope_store_id()
    if err:
        return err
    e, err = _load_in_scope(eid, store_id)
    if err:
        return err
    if e.status != "submitted":
        return jsonify(status="error", message="not checkable"), 409
    e.status = "audited"
    e.audited_by = current_user().id
    e.audited_at = datetime.now(timezone.utc)
    record_check(e, current_user().id)
    db.session.commit()
    return jsonify(status="ok")


@audit_bp.post("/handover")
@role_required("manager", "super_admin")
def handover():
    data = request.get_json(silent=True) or {}
    htype = data.get("type")
    if htype not in ("shift", "day"):
        return jsonify(status="error", message="bad type"), 400
    store_id, err = _scope_store_id(from_body=True)
    if err:
        return err
    h = Handover(store_id=store_id, closed_at=datetime.now(timezone.utc),
                 closed_by=current_user().id, type=htype)
    db.session.add(h); db.session.flush()
    count = (Expense.query
             .filter(Expense.store_id == store_id, Expense.status == "audited",
                     Expense.handover_id.is_(None))
             .update({Expense.handover_id: h.id}, synchronize_session=False))
    if count == 0:
        db.session.rollback()
        return jsonify(status="error", message="no audited entries to close"), 400
    db.session.commit()
    return jsonify(status="ok", handover_id=h.id, type=htype, count=count)


@audit_bp.post("/handover/undo")
@role_required("manager", "super_admin")
def handover_undo():
    store_id, err = _scope_store_id(from_body=True)
    if err:
        return err
    last = (Handover.query.filter_by(store_id=store_id)
            .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
    if last is None:
        return jsonify(status="error", message="no handover"), 400
    reopened = (Expense.query.filter_by(handover_id=last.id)
                .update({Expense.handover_id: None}, synchronize_session=False))
    db.session.delete(last)
    db.session.commit()
    return jsonify(status="ok", reopened=reopened)
