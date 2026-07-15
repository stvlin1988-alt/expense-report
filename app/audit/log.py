from datetime import datetime, timezone
from app.extensions import db
from app.models import AuditLog


def _amt_cat(expense):
    return {
        "amount": float(expense.amount) if expense.amount is not None else None,
        "category_id": expense.category_id,
        "note": expense.note,
    }


def snapshot(expense):
    """在改動前呼叫，取金額/分類/備註快照。"""
    return _amt_cat(expense)


def log_edit_if_changed(expense, actor_user_id, before):
    """before 為改動前 snapshot；與現值不同（含備註）才寫一筆 edit，軌跡完整看得到。
    回傳值＝金額/分類是否有變動——只有這個才算「主管改過金額/分類」，
    單純改備註不算，不能牽動 last_modified_fields／is_modified_by_manager，
    不然主管稽核清單的「主管改」標籤/燈號會被備註改動誤觸發。"""
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
    if changed:
        # 累積「曾被改過的欄位」聯集：分類/金額常分兩次 PATCH 送出，
        # 只記最後一次會漏標先改的欄位。順序保留 amount 在前。
        existing = expense.last_modified_fields.split(",") if expense.last_modified_fields else []
        merged = [f for f in ("amount", "category") if f in existing or f in changed]
        expense.last_modified_by = actor_user_id
        expense.last_modified_at = ts
        expense.last_modified_fields = ",".join(merged)
    return bool(changed)


def record_check(expense, actor_user_id):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="check",
        before_json=None, after_json={"status": "audited"},
        ts=datetime.now(timezone.utc),
    ))


def record_reconcile(expense, actor_user_id):
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="reconcile",
        before_json=None, after_json={"status": "reconciled"},
        ts=datetime.now(timezone.utc),
    ))


def record_reject(expense, actor_user_id, reason):
    """要在改 status 之前呼叫，before_json 才記得到原狀態（audited 或 reconciled）。"""
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="reject",
        before_json={"status": expense.status},
        after_json={"status": "rejected", "reason": reason},
        ts=datetime.now(timezone.utc),
    ))


def record_move_period(expense, actor_user_id, from_pid, to_pid):
    """會計手動把單挪到下一期的軌跡（跟 maybe_autoclose 的系統自動挪期區分開）。"""
    db.session.add(AuditLog(
        expense_id=expense.id, actor_user_id=actor_user_id, action="move_period",
        before_json={"period_id": from_pid}, after_json={"period_id": to_pid},
        ts=datetime.now(timezone.utc),
    ))
