from datetime import datetime, timezone
from app.extensions import db
from app.models import AuditLog


def _amt_cat(expense):
    return {
        "amount": float(expense.amount) if expense.amount is not None else None,
        "category_id": expense.category_id,
    }


def snapshot(expense):
    """在改動前呼叫，取金額/分類快照。"""
    return _amt_cat(expense)


def log_edit_if_changed(expense, actor_user_id, before):
    """before 為改動前 snapshot；與現值不同才寫一筆 edit。回是否有寫。"""
    after = _amt_cat(expense)
    if after == before:
        return False
    ts = datetime.now(timezone.utc)
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="edit",
        before_json=before, after_json=after, ts=ts,
    ))
    changed = []
    if after["amount"] != before["amount"]:
        changed.append("amount")
    if after["category_id"] != before["category_id"]:
        changed.append("category")
    # 累積「曾被改過的欄位」聯集：分類/金額常分兩次 PATCH 送出，
    # 只記最後一次會漏標先改的欄位。順序保留 amount 在前。
    existing = expense.last_modified_fields.split(",") if expense.last_modified_fields else []
    merged = [f for f in ("amount", "category") if f in existing or f in changed]
    expense.last_modified_by = actor_user_id
    expense.last_modified_at = ts
    expense.last_modified_fields = ",".join(merged) if merged else None
    return True


def record_check(expense, actor_user_id):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="check",
        before_json=None, after_json={"status": "audited"},
        ts=datetime.now(timezone.utc),
    ))
