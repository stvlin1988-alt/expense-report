from flask import current_app
from app.expenses.logic import traffic_light


def serialize_expense(e, storage, with_main=False):
    light = traffic_light(
        e.ocr_is_handwritten, e.ocr_confidence, e.amount_parse_ok,
        e.is_modified_by_user,
        green_threshold=current_app.config.get("GREEN_THRESHOLD", 0.85),
    )
    d = {
        "id": e.id, "status": e.status,
        "summary": e.summary, "category_id": e.category_id,
        "amount": float(e.amount) if e.amount is not None else None,
        "light": light,
        "is_modified_by_user": e.is_modified_by_user,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "thumb_url": storage.presigned_url(e.thumb_key) if e.thumb_key else None,
    }
    if with_main:
        d["image_url"] = storage.presigned_url(e.image_key) if e.image_key else None
    return d
