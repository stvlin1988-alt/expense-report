from datetime import date

from flask import request, jsonify

from app.models import Expense, Store, Category, User
from app.auth.decorators import role_required
from app.storage.r2 import get_storage
from app.reconcile import reconcile_bp
from app.reconcile.serialize import serialize_reconcile_item

VISIBLE = ("audited", "reconciled", "rejected")   # 會計看得到的狀態（submitted 不給看）


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
