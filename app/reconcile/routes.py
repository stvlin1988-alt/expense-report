from datetime import date, datetime, timezone

from flask import request, jsonify

from app.extensions import db
from app.models import Expense, Store, Category, User
from app.auth.decorators import role_required, current_user
from app.audit.log import record_reconcile, record_reject, snapshot, log_edit_if_changed
from app.storage.r2 import get_storage
from app.reconcile import reconcile_bp
from app.reconcile.serialize import serialize_reconcile_item
from app.expenses.amount import parse_amount
from app.expenses.tasks import _valid_category_id
from app.expenses.logic import next_day_seq

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


@reconcile_bp.get("/stores")
@role_required("accountant")
def stores():
    """會計端店別下拉：只回 id/name（不含 code/secret 等欄位），不走 admin 藍圖
    （admin 的 /admin/stores 是 manager/super_admin 專用，會計不應被放進 admin 權限範圍）。"""
    rows = Store.query.order_by(Store.name.asc()).all()
    return jsonify(status="ok", stores=[{"id": s.id, "name": s.name} for s in rows])


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


@reconcile_bp.patch("/<int:eid>")
@role_required("accountant")
def edit(eid):
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if e.status not in ("audited", "reconciled"):
        return jsonify(status="error", message="not_editable"), 409
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "amount" in data:
        amount, err = parse_amount(data["amount"])
        if err:
            return jsonify(status="error", message=err), 400
        e.amount = amount
        e.amount_parse_ok = amount is not None
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
    # 會計改動只留軌跡，不碰 is_modified_by_user / is_modified_by_manager —— 燈號語意不變
    log_edit_if_changed(e, current_user().id, before)
    db.session.commit()
    return jsonify(status="ok")


@reconcile_bp.post("/<int:eid>/reject")
@role_required("accountant")
def reject(eid):
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    raw_reason = (request.get_json(silent=True) or {}).get("reason")
    if raw_reason is not None and not isinstance(raw_reason, str):
        # 非字串（如 int/list/dict）不可直接 .strip() → AttributeError → 500，
        # 一律當成「沒給合法原因」回 400，不新增錯誤碼。
        return jsonify(status="error", message="reason_required"), 400
    reason = (raw_reason or "").strip()
    if not reason:
        return jsonify(status="error", message="reason_required"), 400
    if len(reason) > 200:
        return jsonify(status="error", message="reason_too_long"), 400
    if e.status not in ("audited", "reconciled"):
        return jsonify(status="error", message="not_rejectable"), 409
    record_reject(e, current_user().id, reason)   # 改 status 之前呼叫，記得到原狀態
    e.status = "rejected"
    e.reject_reason = reason
    e.reconciled_by = None            # 退回即撤銷核銷
    e.reconciled_at = None
    db.session.commit()
    return jsonify(status="ok")


@reconcile_bp.post("/manual")
@role_required("accountant")
def manual():
    """會計自己新增一筆單據（例如上期主管沒打勾、沒進帳的單，這期會計要認就自己補一筆）。
    建出來直接就是已核銷、無單據、可負數，不回頭走主管打勾。"""
    data = request.get_json(silent=True) or {}
    sid = _coerce_id(data.get("store_id"))
    store = db.session.get(Store, sid) if sid is not None else None
    if store is None:
        return jsonify(status="error", message="store required"), 400
    bd = _parse_date(data.get("business_date"))
    if bd is None:
        return jsonify(status="error", message="business_date required"), 400
    raw_summary = data.get("summary")
    if raw_summary is not None and not isinstance(raw_summary, str):
        # 非字串（如 int/list/dict）不可直接 .strip() → AttributeError → 500，
        # 一律當成「沒給合法摘要」回 400。
        return jsonify(status="error", message="summary_invalid"), 400
    amount, err = parse_amount(data.get("amount"))
    if err or amount is None:
        return jsonify(status="error", message=err or "amount required"), 400

    actor = current_user()
    now = datetime.now(timezone.utc)
    e = Expense(
        store_id=store.id, created_by=actor.id, status="reconciled",
        created_at=now, submitted_at=now, business_date=bd,
        day_seq=next_day_seq(store.id, bd),
        summary=(raw_summary or "").strip() or None,
        category_id=_valid_category_id(data.get("category_id")),
        amount=amount, amount_parse_ok=True,
        is_no_receipt=True, is_modified_by_user=True,
        audited_by=actor.id, audited_at=now,      # 不回頭走主管打勾
        reconciled_by=actor.id, reconciled_at=now,
    )
    db.session.add(e)
    db.session.flush()
    record_reconcile(e, actor.id)
    db.session.commit()
    return jsonify(status="ok", id=e.id)
