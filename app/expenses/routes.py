import base64
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request, jsonify, current_app
from app.extensions import db
from app.models import Expense, Category, User, AuditLog
from app.auth.decorators import current_user
from app.audit.log import snapshot, log_edit_if_changed
from app.images.image_utils import process_upload_image_async
from app.storage.r2 import get_storage
from app.expenses import expense_bp
from app.expenses.tasks import schedule_ocr, reconcile_stale, _valid_category_id
from app.expenses.serialize import serialize_expense
from app.expenses.logic import compute_business_date, iso_utc


def _make_key(store_id):
    yyyymm = datetime.now(timezone.utc).strftime("%Y%m")
    return f"expenses/{store_id}/{yyyymm}/{uuid.uuid4().hex}.jpg"


@expense_bp.post("")
def capture():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    if user.store_id is None:
        return jsonify(status="error", message="no store"), 400
    data = request.get_json(silent=True) or {}
    image = data.get("image")
    if not image:
        return jsonify(status="error", message="no image"), 400
    try:
        raw = base64.b64decode(str(image).split(",")[-1])
    except Exception:
        return jsonify(status="error", message="bad image"), 400
    content_type = data.get("content_type", "image/jpeg")

    main_bytes, thumb_bytes = process_upload_image_async(raw, content_type)
    storage = get_storage()
    key = _make_key(user.store_id)
    thumb_key = key[:-4] + "_thumb.jpg" if thumb_bytes else None
    storage.put(key, main_bytes, "image/jpeg")
    if thumb_bytes:
        storage.put(thumb_key, thumb_bytes, "image/jpeg")

    now = datetime.now(timezone.utc)
    e = Expense(store_id=user.store_id, created_by=user.id, status="pending_ocr",
                image_key=key, thumb_key=thumb_key,
                created_at=now, ocr_scheduled_at=now)
    db.session.add(e); db.session.commit()
    schedule_ocr(e.id, main_bytes, "image/jpeg")
    return jsonify(status="ok", id=e.id), 202


def _load_owned(eid, user):
    e = db.session.get(Expense, eid)
    if e is None:
        return None, (jsonify(status="error", message="not found"), 404)
    if e.created_by != user.id:
        return None, (jsonify(status="error", message="forbidden"), 403)
    return e, None


@expense_bp.get("/pending")
def pending():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    reconcile_stale(user.id)
    rows = (Expense.query
            .filter(Expense.created_by == user.id,
                    Expense.status.in_(["pending_ocr", "draft"]))
            .order_by(Expense.created_at.desc()).all())
    storage = get_storage()
    uids = {e.created_by for e in rows} | {e.last_modified_by for e in rows if e.last_modified_by}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    return jsonify(status="ok",
                    expenses=[serialize_expense(e, storage, with_main=True, name_by_id=names) for e in rows])


@expense_bp.get("/<int:eid>")
def detail(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    uids = {e.created_by} | ({e.last_modified_by} if e.last_modified_by else set())
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    return jsonify(status="ok", expense=serialize_expense(e, get_storage(), with_main=True, name_by_id=names))


def _log_changes(before, after, cat_names):
    """比對一筆 edit 的 before/after，回改動內容 [{field, from, to}]（供軌跡顯示 A→B）。
    分類轉名稱；check 動作 before=None → 回空。"""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    out = []
    if before.get("amount") != after.get("amount"):
        out.append({"field": "金額", "from": before.get("amount"), "to": after.get("amount")})
    if before.get("category_id") != after.get("category_id"):
        out.append({"field": "分類",
                    "from": cat_names.get(before.get("category_id")),
                    "to": cat_names.get(after.get("category_id"))})
    return out


@expense_bp.get("/<int:eid>/logs")
def logs(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e = db.session.get(Expense, eid)
    if e is None:
        return jsonify(status="error", message="not found"), 404
    allowed = (e.created_by == user.id
               or user.role == "super_admin"
               or (user.role == "manager" and e.store_id == user.store_id))
    if not allowed:
        return jsonify(status="error", message="forbidden"), 403
    rows = (AuditLog.query.filter_by(expense_id=eid)
            .order_by(AuditLog.ts.asc(), AuditLog.id.asc()).all())
    uids = {r.actor_user_id for r in rows}
    names = {u.id: u.name for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    # 解析軌跡涉及的分類 id→名稱（before/after 存的是 category_id）
    cids = set()
    for r in rows:
        for j in (r.before_json, r.after_json):
            if isinstance(j, dict) and j.get("category_id") is not None:
                cids.add(j["category_id"])
    cat_names = ({c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()}
                 if cids else {})
    return jsonify(status="ok", logs=[
        {"actor_name": names.get(r.actor_user_id), "ts": iso_utc(r.ts), "action": r.action,
         "changes": _log_changes(r.before_json, r.after_json, cat_names)}
        for r in rows
    ])


@expense_bp.patch("/<int:eid>")
def edit(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft":
        return jsonify(status="error", message="not editable"), 409
    data = request.get_json(silent=True) or {}
    before = snapshot(e)
    if "summary" in data:
        e.summary = data["summary"]
    # 送出前前端會無條件帶 amount/category_id；只有「值真的變了」才算員工改過（Decimal 比較忽略 1290 vs 1290.00）
    if "category_id" in data:
        new_cat = _valid_category_id(data["category_id"])
        if new_cat != e.category_id:
            e.category_id = new_cat
            e.is_modified_by_user = True
    if "amount" in data:
        try:
            new_amount = None if data["amount"] is None else Decimal(str(data["amount"]))
            new_parse_ok = new_amount is not None
        except (InvalidOperation, ValueError):
            new_amount, new_parse_ok = None, False
        if new_amount != e.amount or new_parse_ok != e.amount_parse_ok:
            e.amount = new_amount
            e.amount_parse_ok = new_parse_ok
            e.is_modified_by_user = True
    log_edit_if_changed(e, user.id, before)
    db.session.commit()
    return jsonify(status="ok", expense=serialize_expense(e, get_storage()))


@expense_bp.post("/<int:eid>/submit")
def submit(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft":
        return jsonify(status="error", message="not submittable"), 409
    if e.amount is None or e.amount_parse_ok is not True:
        return jsonify(status="error", message="amount required"), 400
    e.status = "submitted"
    e.business_date = compute_business_date(e.created_at)
    # 當日店內序號（單號 MMDD-NN）：同店同營業日 max+1。低量門市 max+1 足夠；
    # 多 worker 併發送出理論上可能撞號（follow-up：需唯一約束/重試），實務機率低。
    from sqlalchemy import func
    maxseq = (db.session.query(func.max(Expense.day_seq))
              .filter(Expense.store_id == e.store_id,
                      Expense.business_date == e.business_date).scalar()) or 0
    e.day_seq = maxseq + 1
    e.submitted_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(status="ok")


@expense_bp.delete("/<int:eid>")
def discard(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft":
        return jsonify(status="error", message="not deletable"), 409
    storage = get_storage()
    for k in (e.image_key, e.thumb_key):
        if k:
            try:
                storage.delete(k)
            except Exception:
                pass
    db.session.delete(e); db.session.commit()
    return jsonify(status="ok")


@expense_bp.post("/<int:eid>/reocr")
def reocr(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    if e.status != "draft" or not e.ocr_failed:
        return jsonify(status="error", message="not re-ocr-able"), 409
    if not e.image_key:
        return jsonify(status="error", message="no image"), 400
    try:
        image_bytes = get_storage().get(e.image_key)
    except Exception:
        image_bytes = None
    if not image_bytes:
        return jsonify(status="error", message="image unavailable"), 400
    e.status = "pending_ocr"
    e.ocr_failed = False
    e.ocr_attempts = 0
    e.ocr_last_error = None
    e.ocr_scheduled_at = datetime.now(timezone.utc)
    db.session.commit()
    schedule_ocr(e.id, image_bytes, "image/jpeg")
    return jsonify(status="ok"), 202


@expense_bp.post("/no-receipt")
def no_receipt():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    if user.store_id is None:
        return jsonify(status="error", message="no store"), 400
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()  # 原因（備註）非必填
    amount, ok = None, False
    if data.get("amount") is not None:
        try:
            amount = Decimal(str(data["amount"])); ok = True
        except (InvalidOperation, ValueError):
            ok = False
    if not ok:
        return jsonify(status="error", message="amount required"), 400

    # 可選附一張佐證照：壓縮存 R2，但不跑 OCR（純佐證，非收據）
    image_key = thumb_key = None
    image = data.get("image")
    if image:
        try:
            raw = base64.b64decode(str(image).split(",")[-1])
        except Exception:
            return jsonify(status="error", message="bad image"), 400
        main_bytes, thumb_bytes = process_upload_image_async(
            raw, data.get("content_type", "image/jpeg"))
        storage = get_storage()
        image_key = _make_key(user.store_id)
        storage.put(image_key, main_bytes, "image/jpeg")
        if thumb_bytes:
            thumb_key = image_key[:-4] + "_thumb.jpg"
            storage.put(thumb_key, thumb_bytes, "image/jpeg")

    now = datetime.now(timezone.utc)
    # 進暫存區 draft，讓員工確認正確再送出；business_date/submitted_at 由 submit 時設
    e = Expense(
        store_id=user.store_id, created_by=user.id, status="draft",
        created_at=now, is_no_receipt=True,
        image_key=image_key, thumb_key=thumb_key,
        summary=data.get("summary"), category_id=_valid_category_id(data.get("category_id")),
        amount=amount, amount_parse_ok=True, is_modified_by_user=True,
        no_receipt_reason=(reason or None),
    )
    db.session.add(e); db.session.commit()
    return jsonify(status="ok", id=e.id)


@expense_bp.get("/categories")
def categories():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    rows = Category.query.filter_by(active=True).order_by(Category.sort).all()
    children = {}
    for r in rows:
        if r.level == 2:
            children.setdefault(r.parent_id, []).append(r)
    tree = [
        {"id": p.id, "name": p.name,
         "items": [{"id": c.id, "name": c.name} for c in children.get(p.id, [])]}
        for p in rows if p.level == 1
    ]
    return jsonify(status="ok", categories=tree)
