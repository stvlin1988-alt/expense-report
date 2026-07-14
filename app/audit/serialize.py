from flask import current_app
from app.expenses.serialize import serialize_expense
from app.expenses.logic import audit_light, iso_utc


def serialize_audit_item(e, storage, actor_name_by_id, cat_name_by_id, log_expense_ids=None):
    d = serialize_expense(e, storage, with_main=True, name_by_id=actor_name_by_id)
    # 主管稽核端燈號語意與員工端不同（員工改過→紅、無單據→黃）
    d["light"] = audit_light(
        e.amount_parse_ok, e.is_modified_by_user, e.is_no_receipt,
        e.ocr_is_handwritten, e.ocr_confidence,
        green_threshold=current_app.config.get("GREEN_THRESHOLD", 0.85),
    )
    d["is_no_receipt"] = e.is_no_receipt
    d["audited_by"] = e.audited_by
    d["audited_by_name"] = actor_name_by_id.get(e.audited_by)
    d["audited_at"] = iso_utc(e.audited_at)
    d["is_modified_by_manager"] = e.is_modified_by_manager
    d["business_date"] = e.business_date.isoformat() if e.business_date else None
    d["category_name"] = cat_name_by_id.get(e.category_id)
    # 有沒有任何 AuditLog（含純改備註那種不會動 last_modified_at 的）——
    # 前端軌跡按鈕靠這個判斷是否可點，不能只看 last_modified_at（Task 4 review finding 3）
    d["has_audit_log"] = e.id in log_expense_ids if log_expense_ids else False
    d["is_rejected"] = (e.status == "rejected")
    d["reject_reason"] = e.reject_reason
    return d
