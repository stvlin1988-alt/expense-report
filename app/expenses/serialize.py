from flask import current_app
from app.expenses.logic import traffic_light, iso_utc, format_doc_no


def serialize_expense(e, storage, with_main=False, name_by_id=None):
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
        "created_at": iso_utc(e.created_at),
        "doc_no": format_doc_no(e.business_date, e.day_seq),
        "created_by_name": name_by_id.get(e.created_by) if name_by_id else None,
        "last_modified_by_name": name_by_id.get(e.last_modified_by) if name_by_id else None,
        "last_modified_at": iso_utc(e.last_modified_at),
        "thumb_url": storage.presigned_url(e.thumb_key) if e.thumb_key else None,
        "ocr_failed": e.ocr_failed,
        "ocr_last_error": e.ocr_last_error,
    }
    if with_main:
        d["image_url"] = storage.presigned_url(e.image_key) if e.image_key else None
    return d
