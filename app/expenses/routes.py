import base64
import uuid
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from app.extensions import db
from app.models import Expense
from app.auth.decorators import current_user
from app.images.image_utils import process_upload_image_async
from app.storage.r2 import get_storage
from app.expenses import expense_bp
from app.expenses.tasks import schedule_ocr, reconcile_stale
from app.expenses.serialize import serialize_expense


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
