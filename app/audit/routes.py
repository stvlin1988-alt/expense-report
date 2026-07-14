from datetime import datetime, timezone, timedelta
from flask import request, jsonify
from app.extensions import db
from app.models import Expense, Store, Handover, User, Category, AuditLog
from app.auth.decorators import current_user, role_required
from app.expenses.tasks import _valid_category_id
from app.expenses.logic import iso_utc, format_doc_no
from app.expenses.amount import parse_amount
from app.expenses.note import validate_note
from app.storage.r2 import get_storage
from app.audit import audit_bp
from app.audit.log import snapshot, log_edit_if_changed, record_check
from app.audit.service import compute_summary
from app.audit.serialize import serialize_audit_item

_TW = timezone(timedelta(hours=8))


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
            .filter(Expense.store_id == store_id, Expense.status.in_(["submitted", "rejected"]))
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
        names, cats, log_ids = _audit_maps(items)
        out.append({
            "business_date": bd, "subtotal": subtotal,
            "items": [serialize_audit_item(x, storage, names, cats, log_ids) for x in items],
        })
    return jsonify(status="ok", groups=out)


@audit_bp.get("/overdue")
@role_required("manager", "super_admin")
def overdue():
    from app.expenses.logic import compute_business_date
    store_id, err = _scope_store_id()
    if err:
        return err
    today_bd = compute_business_date(datetime.now(timezone.utc))
    rows = (Expense.query
            .filter(Expense.store_id == store_id,
                    Expense.status == "submitted",
                    Expense.business_date < today_bd)
            .order_by(Expense.business_date.asc()).all())
    oldest = rows[0].business_date.isoformat() if rows else None
    return jsonify(status="ok", count=len(rows), oldest_business_date=oldest)


def _audit_maps(expenses):
    uids = {e.audited_by for e in expenses if e.audited_by}
    uids |= {e.created_by for e in expenses}
    uids |= {e.last_modified_by for e in expenses if e.last_modified_by}
    cids = {e.category_id for e in expenses if e.category_id}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    cats = {c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()} if cids else {}
    # 哪些單有 AuditLog（含純改備註那種不會動 last_modified_at 的）——軌跡按鈕要不要顯示靠這個判斷
    eids = [e.id for e in expenses]
    log_ids = ({r[0] for r in db.session.query(AuditLog.expense_id)
               .filter(AuditLog.expense_id.in_(eids)).distinct().all()}
               if eids else set())
    return names, cats, log_ids


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
    if e.status not in ("submitted", "rejected"):
        return jsonify(status="error", message="not editable"), 409
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
    if "amount" in data:
        new_amount, err = parse_amount(data["amount"])
        if err:
            return jsonify(status="error", message=err), 400
        e.amount = new_amount
        e.amount_parse_ok = new_amount is not None
    if "note" in data:
        # 主管/經理改備註（留軌跡）；規則同員工端（Task 3）：>200 拒絕、空白/空字串存 NULL
        note, err = validate_note(data["note"])
        if err:
            return jsonify(status="error", message=err), 400
        e.note = note
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
    if e.status not in ("submitted", "rejected"):
        return jsonify(status="error", message="not checkable"), 409
    e.status = "audited"
    e.reject_reason = None          # 重送後清掉退回原因
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
    # 「主管已打勾」現在對應 CHECKED_STATUSES（audited/reconciled/rejected），不只 audited——
    # 會計可能在主管結班前就先核銷/退回，那筆單這時已經不是 audited 了，但仍要被這次交班掃到。
    # 但要排除會計自建的 manual 單（/reconcile/manual）：它從沒被主管打勾過，handover_id
    # 該永遠是 NULL。manual 單的判別依據：audited_by 指向的是一個 accountant 角色的使用者——
    # 這在正常流程下不可能發生（/audit/<id>/check 只有 manager/super_admin 打得到，
    # 所以 audited_by 正常只會是這兩種角色），manual() 是唯一會讓 audited_by 指向
    # accountant 自己的入口。
    manual_entry_ids = (db.session.query(Expense.id)
                        .join(User, Expense.audited_by == User.id)
                        .filter(User.role == "accountant"))
    count = (Expense.query
             .filter(Expense.store_id == store_id,
                     Expense.status.in_(Expense.CHECKED_STATUSES),
                     Expense.handover_id.is_(None),
                     ~Expense.id.in_(manual_entry_ids))
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


@audit_bp.get("/summary")
@role_required("manager", "super_admin")
def summary():
    store_id, err = _scope_store_id()
    if err:
        return err
    before_id = request.args.get("before", type=int)
    if before_id is not None:
        end = db.session.get(Handover, before_id)
        if end is None:
            return jsonify(status="error", message="not found"), 404
        if end.store_id != store_id:
            return jsonify(status="error", message="forbidden"), 403
        if end.type != "day":
            return jsonify(status="error", message="before must be a day-close"), 400
    data = compute_summary(store_id, before_id)
    return jsonify(status="ok", **data)


@audit_bp.get("/handover/<int:hid>/items")
@role_required("manager", "super_admin")
def handover_items(hid):
    store_id, err = _scope_store_id()
    if err:
        return err
    h = db.session.get(Handover, hid)
    if h is None:
        return jsonify(status="error", message="not found"), 404
    if h.store_id != store_id:
        return jsonify(status="error", message="forbidden"), 403
    rows = (Expense.query
            .filter_by(store_id=store_id, handover_id=hid)
            .order_by(Expense.submitted_at.asc(), Expense.created_at.asc()).all())
    storage = get_storage()
    names, cats, log_ids = _audit_maps(rows)
    return jsonify(status="ok",
                   items=[serialize_audit_item(e, storage, names, cats, log_ids) for e in rows])


@audit_bp.get("/open-items")
@role_required("manager", "super_admin")
def open_items():
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (Expense.query
            .filter(Expense.store_id == store_id,
                    Expense.status.in_(Expense.CHECKED_STATUSES),
                    Expense.handover_id.is_(None))
            .order_by(Expense.audited_at.asc()).all())
    storage = get_storage()
    names, cats, log_ids = _audit_maps(rows)
    return jsonify(status="ok",
                   items=[serialize_audit_item(e, storage, names, cats, log_ids) for e in rows])


@audit_bp.get("/summary-dates")
@role_required("manager", "super_admin")
def summary_dates():
    """總表查詢用：有單據的營業日清單（by business_date，由新到舊，含今日）。"""
    from app.expenses.logic import compute_business_date
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (db.session.query(Expense.business_date)
            .filter(Expense.store_id == store_id,
                    Expense.status.in_(("submitted",) + Expense.CHECKED_STATUSES),
                    Expense.business_date.isnot(None))
            .distinct().all())
    dates = sorted({r[0] for r in rows}, reverse=True)
    out = [d.isoformat() for d in dates]
    today = compute_business_date(datetime.now(timezone.utc)).isoformat()
    if today not in out:
        out.insert(0, today)
    return jsonify(status="ok", dates=out)


@audit_bp.get("/by-date")
@role_required("manager", "super_admin")
def by_date():
    """總表查詢：某營業日的單據，依班別（handover）分組 + 各班小計 + 當日總額。
    未歸班（handover_id=None）另成一組「當前未歸班」。"""
    from datetime import date as _date
    store_id, err = _scope_store_id()
    if err:
        return err
    try:
        d = _date.fromisoformat(request.args.get("date", ""))
    except (TypeError, ValueError):
        return jsonify(status="error", message="bad date"), 400
    rows = (Expense.query
            .filter(Expense.store_id == store_id,
                    Expense.status.in_(("submitted",) + Expense.CHECKED_STATUSES),
                    Expense.business_date == d)
            .order_by(Expense.submitted_at.asc(), Expense.created_at.asc()).all())
    storage = get_storage()
    names, cats, log_ids = _audit_maps(rows)

    groups = {}
    for e in rows:
        groups.setdefault(e.handover_id, []).append(e)
    hids = [hid for hid in groups if hid is not None]
    handovers = ({h.id: h for h in Handover.query.filter(Handover.id.in_(hids)).all()}
                 if hids else {})
    ordered = sorted(hids, key=lambda x: (handovers[x].closed_at, x))

    def _grp(hid, seq):
        items = groups[hid]
        h = handovers.get(hid)
        return {
            "handover_id": hid,
            "type": h.type if h else "open",
            "seq": seq,
            "closed_at": iso_utc(h.closed_at) if h else None,
            "subtotal": sum(float(x.amount) for x in items if x.amount is not None),
            "count": len(items),
            "items": [serialize_audit_item(e, storage, names, cats, log_ids) for e in items],
        }

    shifts = [_grp(hid, i) for i, hid in enumerate(ordered, start=1)]
    if None in groups:
        shifts.append(_grp(None, None))   # 當前未歸班

    total = sum(float(x.amount) for x in rows if x.amount is not None)
    return jsonify(status="ok", date=d.isoformat(), total=total, count=len(rows),
                   shifts=shifts)


@audit_bp.get("/days")
@role_required("manager", "super_admin")
def days():
    store_id, err = _scope_store_id()
    if err:
        return err
    rows = (Handover.query
            .filter_by(store_id=store_id, type="day")
            .order_by(Handover.closed_at.desc(), Handover.id.desc()).all())
    return jsonify(status="ok",
                   days=[{"handover_id": h.id, "closed_at": iso_utc(h.closed_at)} for h in rows])


@audit_bp.get("/logs")
@role_required("manager", "super_admin")
def audit_logs():
    from datetime import date as _date
    store_id, err = _scope_store_id()
    if err:
        return err
    try:
        d = _date.fromisoformat(request.args.get("date", ""))
    except (TypeError, ValueError):
        return jsonify(status="error", message="bad date"), 400
    start = datetime(d.year, d.month, d.day, tzinfo=_TW).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    q = (db.session.query(AuditLog, Expense)
         .join(Expense, AuditLog.expense_id == Expense.id)
         .filter(Expense.store_id == store_id,
                 AuditLog.ts >= start, AuditLog.ts < end))
    actor_id = request.args.get("actor_id", type=int)
    if actor_id is not None:
        q = q.filter(AuditLog.actor_user_id == actor_id)
    rows = q.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).all()
    uids = {lg.actor_user_id for lg, _ in rows}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    items = [{"expense_id": lg.expense_id, "summary": exp.summary,
              "doc_no": format_doc_no(exp.business_date, exp.day_seq),
              "actor_name": names.get(lg.actor_user_id),
              "ts": iso_utc(lg.ts), "action": lg.action}
             for lg, exp in rows]
    actors = [{"id": u.id, "name": u.name}
              for u in User.query.filter_by(store_id=store_id, active=True)
              .order_by(User.name).all()]
    return jsonify(status="ok", items=items, actors=actors)
