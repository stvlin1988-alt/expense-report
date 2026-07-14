import base64
import uuid
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from app.extensions import db
from app.models import Expense, Category, User, AuditLog, Handover
from app.auth.decorators import current_user
from app.audit.log import snapshot, log_edit_if_changed
from app.images.image_utils import process_upload_image_async
from app.storage.r2 import get_storage
from app.expenses import expense_bp
from app.expenses.tasks import schedule_ocr, reconcile_stale, _valid_category_id
from app.expenses.serialize import serialize_expense
from app.expenses.logic import compute_business_date, iso_utc, next_day_seq
from app.expenses.amount import parse_amount
from app.expenses.note import validate_note


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
    if before.get("note") != after.get("note"):
        out.append({"field": "備註", "from": before.get("note"), "to": after.get("note")})
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
        new_amount, err = parse_amount(data["amount"])
        if err:
            return jsonify(status="error", message=err), 400
        new_parse_ok = new_amount is not None
        if new_amount != e.amount or new_parse_ok != e.amount_parse_ok:
            e.amount = new_amount
            e.amount_parse_ok = new_parse_ok
            e.is_modified_by_user = True
    if "note" in data:
        # note 只在 draft 可寫；送出後鎖（不能事後改說法），主管/經理才能改（Task 4）
        # draft 鎖已由上方 handler 頂層的 status!=draft 409 guard 擋下，這裡不重複判斷
        note, err = validate_note(data["note"])
        if err:
            return jsonify(status="error", message=err), 400
        e.note = note
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
    e.day_seq = next_day_seq(e.store_id, e.business_date)
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
    amount, err = parse_amount(data.get("amount"))
    if err or amount is None:
        return jsonify(status="error", message=err or "amount required"), 400
    # 跟 PATCH 共用同一套驗證：不擋長度的話 >200 字直接打到 String(200) 欄位，在 Postgres 會炸 500
    note, err = validate_note(data.get("note"))
    if err:
        return jsonify(status="error", message=err), 400

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
        note=note,
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


@expense_bp.get("/submitted")
def submitted():
    """員工唯讀複查區：本人這一班已送出、主管尚未交/結班的單。
    界定＝本人 + submitted/audited + handover_id 空 + submitted_at 晚於本店最近一次 handover。
    交班與結班都建 Handover，故兩者一致地以時間界清空複查區（含主管沒核到的 submitted）。"""
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    last = (Handover.query.filter_by(store_id=user.store_id)
            .order_by(Handover.closed_at.desc(), Handover.id.desc()).first())
    q = (Expense.query
         .filter(Expense.created_by == user.id,
                 Expense.store_id == user.store_id,
                 Expense.status.in_(["submitted", "audited"]),
                 Expense.handover_id.is_(None)))
    if last is not None:
        q = q.filter(Expense.submitted_at > last.closed_at)
    rows = q.order_by(Expense.day_seq.asc(), Expense.submitted_at.asc()).all()
    storage = get_storage()
    cids = {e.category_id for e in rows if e.category_id}
    cat_names = ({c.id: c.name for c in Category.query.filter(Category.id.in_(cids)).all()}
                 if cids else {})
    out = []
    keep = ("id", "doc_no", "summary", "amount", "thumb_url", "image_url", "note")
    for e in rows:
        d = serialize_expense(e, storage, with_main=True)
        row = {k: d[k] for k in keep if k in d}
        row["category_name"] = cat_names.get(e.category_id)
        out.append(row)
    return jsonify(status="ok", expenses=out)
