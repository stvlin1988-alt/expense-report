"""會計端序列化：白名單。務必不含 note（門市內部備註，會計看不到）。"""
from flask import current_app
from app.expenses.logic import audit_light, format_doc_no, iso_utc


def serialize_reconcile_item(e, storage, store_name_by_id, cat_name_by_id, user_name_by_id,
                             period_label_by_id=None):
    period_label_by_id = period_label_by_id or {}
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
        "period_id": e.period_id,
        "period_label": period_label_by_id.get(e.period_id),
        "reject_reason": e.reject_reason,
        # 主管被退回後重送的時間戳（Addendum 10.1）；讓會計端一眼認出重送過的單。
        # 白名單絕對不能加 note——tests/test_reconcile_list.py::test_note_never_leaks_to_accountant 守著。
        "resubmitted_at": iso_utc(e.resubmitted_at),
        "is_no_receipt": e.is_no_receipt,
        "created_by_name": user_name_by_id.get(e.created_by),
    }
