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
# is_period_closed 用 local import（見各端點內），避免 app.periods.service 頂層
# import app.expenses.logic 觸發的循環引用（app.expenses → app.audit → app.periods）。

VISIBLE = ("audited", "reconciled", "rejected")   # 會計看得到的狀態（submitted 不給看）
MAX_BATCH_IDS = 500   # approve-batch 一次帶的 ids 上限，避免無界輸入


def _maps(rows):
    sids = {e.store_id for e in rows}
    cids = {e.category_id for e in rows if e.category_id}
    uids = {e.created_by for e in rows}
    # 店別顯示一律用英文代號（code），全系統不露店名（user 決策：全部用代號）
    stores = {s.id: s.code for s in Store.query.filter(Store.id.in_(sids)).all()} if sids else {}
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
    """會計端店別下拉：回 id + name，但 name 值一律填店的英文代號（code）——
    全系統以代號識別、不露店名（user 決策）。維持 {id,name} 欄位形狀（白名單不含 code/secret 鍵）。
    不走 admin 藍圖（admin 的 /admin/stores 是 manager/super_admin 專用，會計不應被放進 admin 權限範圍）。"""
    # 只回「可檢視」的店（viewable）——不勾的店從選店選單隱藏
    rows = Store.query.filter(Store.viewable.is_(True)).order_by(Store.code.asc()).all()
    return jsonify(status="ok", stores=[{"id": s.id, "name": s.code} for s in rows])


@reconcile_bp.get("/pending")
@role_required("accountant")
def pending():
    from app.periods.service import get_or_create_period, effective_status, maybe_autoclose
    from app.expenses.logic import compute_business_date
    from app.models import AccountingPeriod

    now = datetime.now(timezone.utc)
    pid = _parse_int(request.args.get("period_id"))
    if pid is not None:
        period = db.session.get(AccountingPeriod, pid)
    else:
        period = get_or_create_period(compute_business_date(now))
    # 碰到就檢查是否該自動封月（涵蓋剛好進入鎖定時刻的期）
    if period is not None:
        maybe_autoclose(period, now)
    db.session.commit()

    q = Expense.query.filter(Expense.status.in_(VISIBLE))

    if period is not None:
        q = q.filter(Expense.period_id == period.id)

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

    period_ids = {e.period_id for e in rows if e.period_id is not None}
    period_label_by_id = ({p.id: p.label for p in
                           AccountingPeriod.query.filter(AccountingPeriod.id.in_(period_ids)).all()}
                          if period_ids else {})

    groups, by_date = [], {}
    for e in rows:
        key = e.business_date.isoformat() if e.business_date else "none"
        by_date.setdefault(key, []).append(e)
    # 營業日新到舊排（最新在最上面，月底不用往下拉）；未歸日的 "none" 一律殿後
    for bd in sorted(by_date, key=lambda k: (k != "none", k), reverse=True):
        items = by_date[bd]
        groups.append({
            "business_date": bd,
            "subtotal": sum(float(x.amount) for x in items if x.amount is not None),
            "items": [serialize_reconcile_item(x, storage, stores, cats, users, period_label_by_id)
                     for x in items],
        })

    total = {
        "reconciled": sum(float(e.amount) for e in rows
                          if e.status == "reconciled" and e.amount is not None),
        "pending": sum(float(e.amount) for e in rows
                       if e.status in ("audited", "rejected") and e.amount is not None),
        "count": len(rows),
    }
    period_out = ({"id": period.id, "label": period.label,
                  "status": effective_status(period, now),
                  "end_date": period.end_date.isoformat()} if period else None)
    return jsonify(status="ok", groups=groups, total=total, period=period_out)


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
    from app.periods.service import is_period_closed
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if is_period_closed(e.period_id, datetime.now(timezone.utc)):
        return jsonify(status="error", message="period_closed"), 409
    if not _approve_one(e, current_user().id):
        db.session.rollback()
        return jsonify(status="error", message="not_reconcilable"), 409
    db.session.commit()
    return jsonify(status="ok")


@reconcile_bp.post("/approve-batch")
@role_required("accountant")
def approve_batch():
    from app.periods.service import is_period_closed
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    if not isinstance(ids, list):
        return jsonify(status="error", message="ids required"), 400
    if len(ids) > MAX_BATCH_IDS:
        return jsonify(status="error", message="too_many_ids"), 400
    actor_id = current_user().id
    approved, skipped = [], []
    now = datetime.now(timezone.utc)
    for raw in ids:
        eid = _coerce_id(raw)
        e = db.session.get(Expense, eid) if eid is not None else None
        if (e is not None and not is_period_closed(e.period_id, now)
                and _approve_one(e, actor_id)):
            approved.append(eid)
        else:
            skipped.append(raw)           # 原始元素回填，錯誤不能悄悄消失
    db.session.commit()
    return jsonify(status="ok", approved=approved, skipped=skipped)


@reconcile_bp.patch("/<int:eid>")
@role_required("accountant")
def edit(eid):
    from app.periods.service import is_period_closed
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if e.status not in ("audited", "reconciled"):
        return jsonify(status="error", message="not_editable"), 409
    if is_period_closed(e.period_id, datetime.now(timezone.utc)):
        return jsonify(status="error", message="period_closed"), 409
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
    from app.periods.service import is_period_closed
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
    if is_period_closed(e.period_id, datetime.now(timezone.utc)):
        return jsonify(status="error", message="period_closed"), 409
    record_reject(e, current_user().id, reason)   # 改 status 之前呼叫，記得到原狀態
    e.status = "rejected"
    e.reject_reason = reason
    e.reconciled_by = None            # 退回即撤銷核銷
    e.reconciled_at = None
    db.session.commit()
    return jsonify(status="ok")


@reconcile_bp.post("/<int:eid>/move-next")
@role_required("accountant")
def move_next(eid):
    from datetime import timedelta
    from app.periods.service import get_or_create_period, is_period_closed
    from app.audit.log import record_move_period
    from app.models import AccountingPeriod

    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    if e.period_id is None:
        return jsonify(status="error", message="no_period"), 409
    now = datetime.now(timezone.utc)
    if is_period_closed(e.period_id, now):
        return jsonify(status="error", message="period_closed"), 409
    cur = db.session.get(AccountingPeriod, e.period_id)
    nxt = get_or_create_period(cur.end_date + timedelta(days=1))
    if is_period_closed(nxt.id, now):
        db.session.rollback()
        return jsonify(status="error", message="next_period_closed"), 409
    from_pid = e.period_id
    e.period_id = nxt.id
    record_move_period(e, current_user().id, from_pid, nxt.id)
    db.session.commit()
    return jsonify(status="ok", period_id=nxt.id, period_label=nxt.label)


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
        # audited_by / audited_at 一律留 NULL：這筆從沒被主管打勾過（也不回頭走主管打勾）。
        # audited_at IS NULL 就是主管端各查詢（交班掃描 / 未歸班清單 / 班別小計）用來
        # 排除 manual 單的判別依據——不可在這裡蓋時間戳，否則它會被掃進某個班別的小計。
        reconciled_by=actor.id, reconciled_at=now,
    )
    db.session.add(e)
    db.session.flush()
    from app.periods.service import get_or_create_period, is_period_closed
    period = get_or_create_period(bd)
    if is_period_closed(period.id, datetime.now(timezone.utc)):
        db.session.rollback()
        return jsonify(status="error", message="period_closed"), 409
    e.period_id = period.id
    record_reconcile(e, actor.id)
    db.session.commit()
    return jsonify(status="ok", id=e.id)


@reconcile_bp.get("/unprocessed")
@role_required("accountant")
def unprocessed():
    """上期未處理單：主管交接班沒打勾、封月後留原期沒進帳的 submitted 單（spec §5.4）。
    只回白名單欄位，絕不可含 note（會計端鐵律）。"""
    from app.models import AccountingPeriod
    closed_ids = [p.id for p in AccountingPeriod.query
                  .filter(AccountingPeriod.status == "closed").all()]
    if not closed_ids:
        return jsonify(status="ok", items=[])
    rows = (Expense.query
            .filter(Expense.period_id.in_(closed_ids), Expense.status == "submitted")
            .order_by(Expense.business_date.asc(), Expense.store_id.asc(),
                      Expense.day_seq.asc()).all())
    storage = get_storage()
    stores, cats, users = _maps(rows)
    items = [{
        "id": e.id,
        "business_date": e.business_date.isoformat() if e.business_date else None,
        "store_id": e.store_id,
        "store_name": stores.get(e.store_id),
        "summary": e.summary,
        "amount": float(e.amount) if e.amount is not None else None,
        "image_url": storage.presigned_url(e.image_key) if e.image_key else None,
    } for e in rows]
    return jsonify(status="ok", items=items)


@reconcile_bp.get("/period/<int:pid>/close-preview")
@role_required("accountant")
def close_preview(pid):
    """提前封月二次確認視窗用：回該期還有幾筆 submitted（沒打勾）單，供會計確認。"""
    from app.models import AccountingPeriod
    p = db.session.get(AccountingPeriod, pid)
    if p is None:
        return jsonify(status="error", message="not found"), 404
    n = Expense.query.filter(Expense.period_id == pid,
                             Expense.status == "submitted").count()
    return jsonify(status="ok", unaudited_count=n, label=p.label)


@reconcile_bp.post("/period/<int:pid>/close")
@role_required("accountant")
def close_period(pid):
    """會計提前手動封月：限期間已結束（寬限期 closing）才可封。
    open（進行中）→ 409 period_not_ended（先調 end_date 讓它進寬限期，見 Task 15）；
    closed（已封）→ 409 already_closed。"""
    from app.periods.service import close_period_now, effective_status
    from app.models import AccountingPeriod
    p = db.session.get(AccountingPeriod, pid)
    if p is None:
        return jsonify(status="error", message="not found"), 404
    now = datetime.now(timezone.utc)
    st = effective_status(p, now)
    if st == "closed":
        return jsonify(status="error", message="already_closed"), 409
    if st != "closing":
        # open：期間還在進行中，不可提前封（先調 end_date 讓它進寬限期）
        return jsonify(status="error", message="period_not_ended"), 409
    if not close_period_now(p, now, current_user().id):
        db.session.rollback()
        return jsonify(status="error", message="already_closed"), 409
    db.session.commit()
    return jsonify(status="ok")
