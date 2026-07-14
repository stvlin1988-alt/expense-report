from datetime import date, datetime, timezone

from flask import request, jsonify

from app.extensions import db
from app.models import Expense, Store, Category, User
from app.auth.decorators import role_required, current_user
from app.audit.log import record_reconcile
from app.storage.r2 import get_storage
from app.reconcile import reconcile_bp
from app.reconcile.serialize import serialize_reconcile_item

VISIBLE = ("audited", "reconciled", "rejected")   # 會計看得到的狀態（submitted 不給看）
MAX_BATCH_IDS = 500   # approve-batch 一次帶的 ids 上限，避免無界輸入


def _maps(rows):
    sids = {e.store_id for e in rows}
    cids = {e.category_id for e in rows if e.category_id}
    uids = {e.created_by for e in rows}
    stores = {s.id: s.name for s in Store.query.filter(Store.id.in_(sids)).all()} if sids else {}
    cats = {c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()} if cids else {}
    users = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    return stores, cats, users


def _parse_date(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _parse_int(raw):
    """query param 轉 int；非數字（如 store_id=abc）回 None 代表不套用該篩選，
    不可讓 int() 直接炸 ValueError → 500（brief 原碼的坑，這裡修掉）。"""
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@reconcile_bp.get("/pending")
@role_required("accountant")
def pending():
    q = Expense.query.filter(Expense.status.in_(VISIBLE))

    st = request.args.get("status")
    if st in VISIBLE:
        q = q.filter(Expense.status == st)

    sid = _parse_int(request.args.get("store_id"))
    if sid is not None:
        q = q.filter(Expense.store_id == sid)

    cid = _parse_int(request.args.get("category_id"))
    if cid is not None:
        q = q.filter(Expense.category_id == cid)

    d_from = _parse_date(request.args.get("date_from"))
    if d_from:
        q = q.filter(Expense.business_date >= d_from)
    d_to = _parse_date(request.args.get("date_to"))
    if d_to:
        q = q.filter(Expense.business_date <= d_to)

    rows = q.order_by(Expense.business_date.asc(), Expense.store_id.asc(),
                      Expense.day_seq.asc()).all()

    storage = get_storage()
    stores, cats, users = _maps(rows)

    groups, by_date = [], {}
    for e in rows:
        key = e.business_date.isoformat() if e.business_date else "none"
        by_date.setdefault(key, []).append(e)
    for bd in sorted(by_date):
        items = by_date[bd]
        groups.append({
            "business_date": bd,
            "subtotal": sum(float(x.amount) for x in items if x.amount is not None),
            "items": [serialize_reconcile_item(x, storage, stores, cats, users) for x in items],
        })

    total = {
        "reconciled": sum(float(e.amount) for e in rows
                          if e.status == "reconciled" and e.amount is not None),
        "pending": sum(float(e.amount) for e in rows
                       if e.status in ("audited", "rejected") and e.amount is not None),
        "count": len(rows),
    }
    return jsonify(status="ok", groups=groups, total=total)


def _coerce_id(raw):
    """batch ids 陣列元素轉 int；非數字（如 "abc"/null）回 None 代表跳過該筆，
    不可讓 int() 直接炸 TypeError/ValueError → db.session.get 在 Postgres 上
    對非法型別會炸 DataError → 500（brief 原碼的坑，這裡修掉）。"""
    if isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _approve_one(e, actor_id):
    """狀態必須是 audited。回 True 表示這次真的核銷成功。"""
    updated = (Expense.query
               .filter(Expense.id == e.id, Expense.status == "audited")
               .update({"status": "reconciled",
                        "reconciled_by": actor_id,
                        "reconciled_at": datetime.now(timezone.utc)},
                       synchronize_session=False))
    if not updated:
        return False                      # 併發：別人先核掉了
    db.session.refresh(e)
    record_reconcile(e, actor_id)
    return True


@reconcile_bp.post("/<int:eid>/approve")
@role_required("accountant")
def approve(eid):
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if not _approve_one(e, current_user().id):
        db.session.rollback()
        return jsonify(status="error", message="not_reconcilable"), 409
    db.session.commit()
    return jsonify(status="ok")


@reconcile_bp.post("/approve-batch")
@role_required("accountant")
def approve_batch():
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    if not isinstance(ids, list):
        return jsonify(status="error", message="ids required"), 400
    if len(ids) > MAX_BATCH_IDS:
        return jsonify(status="error", message="too_many_ids"), 400
    actor_id = current_user().id
    approved, skipped = [], []
    for raw in ids:
        eid = _coerce_id(raw)
        e = db.session.get(Expense, eid) if eid is not None else None
        if e is not None and _approve_one(e, actor_id):
            approved.append(eid)
        else:
            skipped.append(raw)           # 原始元素回填，錯誤不能悄悄消失
    db.session.commit()
    return jsonify(status="ok", approved=approved, skipped=skipped)
