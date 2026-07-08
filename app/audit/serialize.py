from app.expenses.serialize import serialize_expense


def serialize_audit_item(e, storage, actor_name_by_id, cat_name_by_id):
    d = serialize_expense(e, storage, with_main=True)
    d["audited_by"] = e.audited_by
    d["audited_by_name"] = actor_name_by_id.get(e.audited_by)
    d["audited_at"] = e.audited_at.isoformat() if e.audited_at else None
    d["is_modified_by_manager"] = e.is_modified_by_manager
    d["business_date"] = e.business_date.isoformat() if e.business_date else None
    d["category_name"] = cat_name_by_id.get(e.category_id)
    return d
