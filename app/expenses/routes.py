import base64
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request, jsonify, current_app
from app.extensions import db
from app.models import Expense
from app.auth.decorators import current_user
from app.images.image_utils import process_upload_image_async
from app.storage.r2 import get_storage
from app.expenses import expense_bp
from app.expenses.tasks import schedule_ocr, reconcile_stale, _valid_category_id
from app.expenses.serialize import serialize_expense
from app.expenses.logic import compute_business_date


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

    e = Expense(store_id=user.store_id, created_by=user.id, status="pending_ocr",
                image_key=key, thumb_key=thumb_key,
                created_at=datetime.now(timezone.utc))
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
    return jsonify(status="ok",
                    expenses=[serialize_expense(e, storage) for e in rows])


@expense_bp.get("/<int:eid>")
def detail(eid):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    e, err = _load_owned(eid, user)
    if err:
        return err
    return jsonify(status="ok", expense=serialize_expense(e, get_storage(), with_main=True))


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
    if "summary" in data:
        e.summary = data["summary"]
    if "category_id" in data:
        e.category_id = _valid_category_id(data["category_id"])
        e.is_modified_by_user = True
    if "amount" in data:
        try:
            e.amount = None if data["amount"] is None else Decimal(str(data["amount"]))
            e.amount_parse_ok = e.amount is not None
        except (InvalidOperation, ValueError):
            e.amount = None; e.amount_parse_ok = False
        e.is_modified_by_user = True
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


@expense_bp.post("/no-receipt")
def no_receipt():
    user = current_user()
    if user is None:
        return jsonify(status="error", message="unauthenticated"), 401
    if user.store_id is None:
        return jsonify(status="error", message="no store"), 400
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify(status="error", message="reason required"), 400
    amount, ok = None, False
    if data.get("amount") is not None:
        try:
            amount = Decimal(str(data["amount"])); ok = True
        except (InvalidOperation, ValueError):
            ok = False
    if not ok:
        return jsonify(status="error", message="amount required"), 400
    now = datetime.now(timezone.utc)
    e = Expense(
        store_id=user.store_id, created_by=user.id, status="submitted",
        created_at=now, submitted_at=now, business_date=compute_business_date(now),
        summary=data.get("summary"), category_id=_valid_category_id(data.get("category_id")),
        amount=amount, amount_parse_ok=True, is_modified_by_user=True,
        no_receipt_reason=reason,
    )
    db.session.add(e); db.session.commit()
    return jsonify(status="ok", id=e.id)
