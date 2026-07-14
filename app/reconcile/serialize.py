"""會計端序列化：白名單。務必不含 note（門市內部備註，會計看不到）。"""
from flask import current_app
from app.expenses.logic import audit_light, format_doc_no


def serialize_reconcile_item(e, storage, store_name_by_id, cat_name_by_id, user_name_by_id):
    return {
        "id": e.id,
        "doc_no": format_doc_no(e.business_date, e.day_seq),
        "business_date": e.business_date.isoformat() if e.business_date else None,
        "store_id": e.store_id,
        "store_name": store_name_by_id.get(e.store_id),
        "light": audit_light(
            e.amount_parse_ok, e.is_modified_by_user, e.is_no_receipt,
            e.ocr_is_handwritten, e.ocr_confidence,
            green_threshold=current_app.config.get("GREEN_THRESHOLD", 0.85),
        ),
        "summary": e.summary,
        "category_id": e.category_id,
        "category_name": cat_name_by_id.get(e.category_id),
        "amount": float(e.amount) if e.amount is not None else None,
        "thumb_url": storage.presigned_url(e.thumb_key) if e.thumb_key else None,
        "image_url": storage.presigned_url(e.image_key) if e.image_key else None,
        "status": e.status,
        "reject_reason": e.reject_reason,
        "is_no_receipt": e.is_no_receipt,
        "created_by_name": user_name_by_id.get(e.created_by),
    }
